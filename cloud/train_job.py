"""Submit one `cloud.train` run to Vertex AI as a CustomJob and wait for it.

    python -m cloud.train_job \
      --image us-east1-docker.pkg.dev/<project>/trialmatch/trainer@sha256:<digest> \
      --pairs gs://<bucket>/training/pairs/<sha>/pairs.jsonl \
      --evidence docs/ms3/evidence/module-b/<date>

The image must be pinned by digest. The W&B key is never passed here: the job reads it
from Secret Manager at run time with its own service account, so it appears in neither
the job spec nor the logs. Exits non-zero unless the job reaches JOB_STATE_SUCCEEDED.

Without GPU quota the same job runs on CPU: pass `--accelerator-count 0` with a larger
`--machine-type` and `--max-run-seconds`, and usually a smaller configuration, e.g.

      --accelerator-count 0 --machine-type n1-standard-16 --max-run-seconds 21600 \
      --epochs 1 --batch-size 8 --max-negatives 2 --max-length 128
"""

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from cloud.train import code_commit, gcs_blob

ROOT = Path(__file__).resolve().parents[1]
DIGEST = re.compile(r"^[a-z0-9./_-]+@sha256:[0-9a-f]{64}$")
RUN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")


def config_env() -> dict:
    lines = (ROOT / "cloud/config.env").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))


def worker_pool(args, output: str, commit: str) -> list[dict]:
    command_args = ["--pairs", *args.pairs, "--output", output,
                    "--epochs", str(args.epochs), "--batch-size", str(args.batch_size),
                    "--lr", str(args.lr), "--temperature", str(args.temperature),
                    "--max-length", str(args.max_length),
                    "--max-negatives", str(args.max_negatives), "--seed", str(args.seed),
                    "--wandb-project", args.wandb_project, "--run-name", args.run_id,
                    "--image-uri", args.image]
    if args.wandb_entity:
        command_args += ["--wandb-entity", args.wandb_entity]
    if args.wandb_secret:
        command_args += ["--wandb-secret",
                         f"projects/{args.project}/secrets/{args.wandb_secret}/versions/latest"]
    if args.source_release:
        command_args += ["--source-release", args.source_release]
    if args.no_amp:
        command_args.append("--no-amp")
    machine = {"machine_type": args.machine_type}
    if args.accelerator_count:  # Vertex rejects an accelerator type with a count of zero.
        machine.update(accelerator_type=args.accelerator_type,
                       accelerator_count=args.accelerator_count)
    return [{
        "machine_spec": machine,
        "replica_count": 1,
        "container_spec": {"image_uri": args.image, "command": ["python", "-m", "cloud.train"],
                           "args": command_args,
                           "env": [{"name": "CODE_COMMIT", "value": commit}]},
    }]


def remote_sha256(uri: str) -> str:
    digest = hashlib.sha256()
    with gcs_blob(uri).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checkpoint(manifest: dict) -> dict:
    """Recompute every checkpoint file's SHA256 from GCS against the manifest."""
    actual = {name: remote_sha256(f"{manifest['artifact_uri']}/{name}")
              for name in manifest["artifact_files"]}
    combined = hashlib.sha256(json.dumps(actual, sort_keys=True).encode()).hexdigest()
    return {"artifact_uri": manifest["artifact_uri"], "files": actual,
            "artifact_sha256": combined,
            "matches_manifest": actual == manifest["artifact_files"]
            and combined == manifest["artifact_sha256"]}


def job_logs(project: str, job_id: str) -> list[str]:
    """Every Cloud Logging line of the job, oldest first."""
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    body = {"resourceNames": [f"projects/{project}"], "orderBy": "timestamp asc",
            "pageSize": 1000,
            "filter": f'resource.type="ml_job" AND resource.labels.job_id="{job_id}"'}
    lines = []
    while True:
        response = session.post("https://logging.googleapis.com/v2/entries:list", json=body,
                                timeout=60)
        response.raise_for_status()
        page = response.json()
        for entry in page.get("entries", []):
            text = entry.get("textPayload") or json.dumps(entry.get("jsonPayload", {}))
            lines.append(f"{entry.get('timestamp', '')} {entry.get('severity', '')} {text}".rstrip())
        if not page.get("nextPageToken"):
            return lines
        body["pageToken"] = page["nextPageToken"]


def parse_args(argv=None):
    env = config_env()
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=env.get("GCP_PROJECT"))
    parser.add_argument("--region", default=env.get("GCP_REGION", "us-east1"))
    parser.add_argument("--bucket", default=env.get("GCS_BUCKET"))
    parser.add_argument("--image", required=True, help="Trainer image pinned by digest")
    parser.add_argument("--pairs", nargs="+", required=True, help="gs:// pair files")
    parser.add_argument("--run-id", default=time.strftime("train-%Y%m%d-%H%M%S", time.gmtime()))
    parser.add_argument("--service-account", default="")
    parser.add_argument("--machine-type", default="n1-standard-4")
    parser.add_argument("--accelerator-type", default="NVIDIA_TESLA_T4")
    parser.add_argument("--accelerator-count", type=int, default=1,
                        help="0 runs the job on CPU only, for projects without GPU quota")
    parser.add_argument("--max-run-seconds", type=int, default=5400,
                        help="Vertex cancels the job after this long; bounds the GPU spend")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--temperature", type=float, default=0.05)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--max-negatives", type=int, default=4)
    parser.add_argument("--no-amp", action="store_true", help="Disable CUDA mixed precision")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--wandb-project", default="trialmatch-ms3")
    parser.add_argument("--wandb-entity", default="")
    parser.add_argument("--wandb-secret", default="wandb-api-key",
                        help="Secret Manager secret name; empty to track offline")
    parser.add_argument("--source-release", default="")
    parser.add_argument("--evidence", type=Path, help="Directory for the run's evidence files")
    parser.add_argument("--dry-run", action="store_true", help="Print the job spec and stop")
    args = parser.parse_args(argv)
    if not DIGEST.fullmatch(args.image):
        parser.error("--image must be pinned by digest: <registry>/trainer@sha256:<64 hex>")
    if not RUN_ID.fullmatch(args.run_id):
        parser.error("--run-id must be lowercase letters, digits and dashes")
    if not all(uri.startswith("gs://") for uri in args.pairs):
        parser.error("--pairs must be gs:// URIs; the job cannot read this workstation")
    if args.accelerator_count < 0:
        parser.error("--accelerator-count cannot be negative")
    if not args.project or not args.bucket:
        parser.error("--project and --bucket are required")
    args.service_account = (args.service_account
                            or f"trialmatch-pipeline@{args.project}.iam.gserviceaccount.com")
    return args


def main(argv=None):
    args = parse_args(argv)
    commit = code_commit()
    output = f"gs://{args.bucket}/training/{args.run_id}"
    pools = worker_pool(args, output, commit)
    spec = {"display_name": f"trialmatch-{args.run_id}", "project": args.project,
            "region": args.region, "service_account": args.service_account,
            "max_run_seconds": args.max_run_seconds, "output": output, "code_commit": commit,
            "worker_pool_specs": pools}
    print(json.dumps(spec, indent=2))
    if args.dry_run:
        return 0

    from google.cloud import aiplatform

    aiplatform.init(project=args.project, location=args.region,
                    staging_bucket=f"gs://{args.bucket}/training/staging")
    job = aiplatform.CustomJob(display_name=spec["display_name"], worker_pool_specs=pools)
    job.submit(service_account=args.service_account, timeout=args.max_run_seconds)
    print(job.resource_name, flush=True)
    record = {**spec, "resource_name": job.resource_name}
    evidence = args.evidence
    if evidence:
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "job.json").write_text(json.dumps(record, indent=2) + "\n")
    try:
        job.wait()
    except Exception as exc:  # noqa: BLE001 - the state below decides the exit code
        print(f"Waiting ended with {type(exc).__name__}: {exc}")
    job = aiplatform.CustomJob.get(job.resource_name)
    state = job.state.name
    record.update(state=state, create_time=str(job.create_time), end_time=str(job.end_time),
                  console=f"https://console.cloud.google.com/vertex-ai/locations/{args.region}"
                          f"/training/{job.name}?project={args.project}")
    succeeded = state == "JOB_STATE_SUCCEEDED"
    if succeeded:
        manifest = json.loads(gcs_blob(f"{output}/training_manifest.json").download_as_text())
        record["checkpoint"] = verify_checkpoint(manifest)
        record["wandb"] = manifest["experiment"]
        succeeded = record["checkpoint"]["matches_manifest"]
        if evidence:
            (evidence / "training_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if evidence:
        (evidence / "job.json").write_text(json.dumps(record, indent=2) + "\n")
        try:
            (evidence / "job.log").write_text("\n".join(job_logs(args.project, job.name)) + "\n")
        except Exception as exc:  # noqa: BLE001 - missing log access must not hide the state
            print(f"Could not export the job log: {type(exc).__name__}: {exc}")
    print(json.dumps({k: v for k, v in record.items() if k != "worker_pool_specs"}, indent=2))
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
