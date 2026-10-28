"""Container commands for release files, the data pipeline, and app startup."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from google.cloud import storage

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "services/trial_ingestion/data/raw.dvc",
    "services/trial_ingestion/data/raw_metadata.json",
    "services/trial_ingestion/data/processed/trials.jsonl",
    "services/trial_ingestion/data/processed/criteria.jsonl",
    "services/patient_processing/data/processed/batch25_patients.jsonl",
    "services/rag_workflow/examples/demo_manifest.json",
    "services/rag_workflow/index_snapshots/current.json",
]


def blob(uri):
    if not uri.startswith("gs://"):
        raise ValueError("Expected a gs:// URI")
    bucket, name = uri[5:].split("/", 1)
    return storage.Client(project=os.environ.get("GCP_PROJECT")).bucket(bucket).blob(name)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(uri, value):
    blob(uri).upload_from_string(json.dumps(value, indent=2) + "\n", content_type="application/json")


def log(event, **values):
    print(json.dumps({"event": event, **values}), flush=True)


def publish(prefix, image=""):
    """Publish an immutable release. Fail rather than overwrite a different file."""
    manifest = {"schema_version": 1, "image": image, "files": {}}
    for name in FILES:
        source = ROOT / name
        sha = digest(source)
        uri = f"{prefix}/{name}"
        target = blob(uri)
        if target.exists():
            if hashlib.sha256(target.download_as_bytes()).hexdigest() != sha:
                raise ValueError(f"Release already exists with different content: {name}")
        else:
            target.upload_from_filename(source, if_generation_match=0)
        manifest["files"][name] = {"uri": uri, "sha256": sha}
    target = blob(f"{prefix}/release.json")
    if target.exists():
        if json.loads(target.download_as_text()) != manifest:
            raise ValueError("Release manifest already exists with different content")
    else:
        target.upload_from_string(json.dumps(manifest, indent=2), if_generation_match=0)
    log("release_published", uri=f"{prefix}/release.json")


def download_release(uri):
    manifest = json.loads(blob(uri).download_as_text())
    if manifest["schema_version"] != 1 or set(manifest["files"]) != set(FILES):
        raise ValueError("Unexpected release files")
    for name, item in manifest["files"].items():
        path = ROOT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        blob(item["uri"]).download_to_filename(path)
        if digest(path) != item["sha256"]:
            raise ValueError(f"Checksum mismatch: {name}")
    log("release_verified", uri=uri, files=len(FILES))
    return manifest


def command(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def fetch(release, output):
    download_release(release)
    module = ROOT / "services/trial_ingestion"
    (module / ".dvc").mkdir(exist_ok=True)
    (module / ".dvc/config").write_text(
        "[core]\n    no_scm = true\n    remote = team\n"
        "['remote \"team\"']\n    url = gs://trialmatch-ac215-yixiao-dvc/dvc\n"
    )
    command("dvc", "--cd", str(module), "pull", "data/raw.dvc")
    metadata = json.loads((module / "data/raw_metadata.json").read_text())
    sources = sorted((module / "data/raw").glob("*.json"))
    if len(sources) != metadata["raw_file_count"]:
        raise ValueError("Unexpected raw snapshot size")
    archive = ROOT / "artifacts/raw.tar.gz"
    archive.parent.mkdir(exist_ok=True)
    with tarfile.open(archive, "w:gz") as target:
        target.add(module / "data/raw", arcname="raw")
    blob(f"{output}/raw.tar.gz").upload_from_filename(archive)
    write_json(f"{output}/snapshot.json", {
        "release_uri": release, "raw_files": len(sources),
        "archive_sha256": digest(archive),
        "dvc_pointer_sha256": digest(module / "data/raw.dvc"),
    })
    log("raw_snapshot_restored", count=len(sources), output=output)


def process(source, output):
    record = json.loads(blob(f"{source}/snapshot.json").download_as_text())
    manifest = download_release(record["release_uri"])
    archive = ROOT / "artifacts/raw.tar.gz"
    archive.parent.mkdir(exist_ok=True)
    blob(f"{source}/raw.tar.gz").download_to_filename(archive)
    if digest(archive) != record["archive_sha256"]:
        raise ValueError("Raw archive checksum mismatch")
    with tarfile.open(archive) as source_tar:
        source_tar.extractall(ROOT / "services/trial_ingestion/data", filter="data")
    command(sys.executable, "prepare_data.py", "--from-raw")
    publish(output, manifest["image"])
    blob(f"{output}/raw_reproduction.json").upload_from_filename(
        ROOT / "artifacts/infra/raw_reproduction.json"
    )
    log("processed_data_reproduced", output=output)


def validate(source, output):
    download_release(f"{source}/release.json")
    command(sys.executable, "prepare_data.py")
    from services.rag_workflow.config import Settings
    from services.rag_workflow.data import DataStore
    from services.rag_workflow.index_versions import load_snapshot
    from services.rag_workflow.schemas import ScreenRequest
    from services.rag_workflow.workflow import ScreeningWorkflow

    settings = Settings(mode="offline")
    data = DataStore(settings)
    snapshot = load_snapshot(ROOT / FILES[-1])
    # Offline smoke check: this is a functional check, not a clinical accuracy benchmark.
    workflow = ScreeningWorkflow(settings)
    patient_id = data.manifest()["patient_ids"][0]
    started = time.monotonic()
    response = workflow.screen(ScreenRequest(
        patient_id=patient_id, question="Which type 2 diabetes trials may suit this patient?", top_k=3
    ))
    if response.result_status in {"ERROR", "PARTIAL"} or not response.candidate_trials:
        raise ValueError("Offline screening did not complete")
    report = {
        "status": "PASSED", "release_uri": f"{source}/release.json",
        "trials": len(data.trials), "patients": len(data.patients),
        "criteria": sum(len(rows) for rows in data.criteria.values()),
        "vectors": snapshot.vector_count, "source_sha256": data.hashes,
        "offline_screening_status": response.result_status,
        "smoke_seconds": round(time.monotonic() - started, 3),
        "scope": "Data reproduction and functional validation; no training or clinical benchmark.",
    }
    write_json(f"{output}/validation.json", report)
    write_json(f"{output}/offline_screening.json", response.model_dump(mode="json"))
    log("pipeline_validation_passed", **report)


def serve():
    download_release(os.environ["RELEASE_URI"])
    from services.rag_workflow.config import Settings
    from services.rag_workflow.data import DataStore
    from services.rag_workflow.index import VectorIndex

    settings = Settings()
    data = DataStore(settings)
    if settings.mode == "live":
        index = VectorIndex(settings, data, data.manifest())
        status = index.restore(ROOT / FILES[-1])
        log("cloud_index_ready", collection=status["collection"], vectors=status["vector_count"])
    os.execvp(sys.executable, [
        sys.executable, "-m", "uvicorn", "services.frontend.app:app",
        "--host", "0.0.0.0", "--port", os.environ.get("PORT", "8080"),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["publish", "fetch", "process", "validate", "serve"])
    parser.add_argument("--source")
    parser.add_argument("--output")
    parser.add_argument("--image", default="")
    args = parser.parse_args()
    if args.action == "serve":
        serve()
    elif args.action == "publish":
        publish(args.output, args.image)
    else:
        {"fetch": fetch, "process": process, "validate": validate}[args.action](args.source, args.output)


if __name__ == "__main__":
    main()
