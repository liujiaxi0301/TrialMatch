#!/usr/bin/env python3
"""Export an EXISTING Vertex run. Read-only GCP requests; no job submission.

Run in an authenticated Google Cloud Shell with Python 3 and gcloud.
The access token stays in memory and is never written into the evidence.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import uuid

PROJECT = "trialmatch-ac215-yixiao"
REGION = "us-east1"
BUCKET = "trialmatch-ac215-yixiao-ms3"
JOB_ID = "trialmatch-data-pipeline-20261110055153"
JOB_URL = f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/pipelineJobs/{JOB_ID}"
CONSOLE_URL = f"https://console.cloud.google.com/vertex-ai/locations/{REGION}/pipelines/runs/{JOB_ID}?project={PROJECT}"
NODES = ("fetch-raw", "process-trials", "validate-data", "retrieve-trials")
DEMO_FILE = "services/rag_workflow/examples/demo_manifest.json"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def digest(value):
    return hashlib.sha256(value).hexdigest()


class ReadOnlyGoogle:
    def __init__(self, token):
        self.token = token

    def request(self, url, body=None):
        hosts = {f"{REGION}-aiplatform.googleapis.com", "storage.googleapis.com",
                 "cloudbuild.googleapis.com", "logging.googleapis.com"}
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in hosts:
            raise ValueError("Unexpected API host")
        # Logging's entries:list uses POST for a read-only query. No other POST is allowed.
        if body is not None and url != "https://logging.googleapis.com/v2/entries:list":
            raise ValueError("Only the read-only log query may use POST")
        headers = {"Authorization": "Bearer " + self.token}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=45) as response:
                return response.read()
        except HTTPError as error:
            # Do not print headers, tokens, or gcloud authentication output.
            raise RuntimeError(f"HTTP {error.code} reading {parsed.netloc}{parsed.path}") from None

    def json(self, url, body=None):
        return json.loads(self.request(url, body))

    def object(self, uri):
        prefix = f"gs://{BUCKET}/"
        if not isinstance(uri, str) or not uri.startswith(prefix) or len(uri) == len(prefix):
            raise ValueError("Artifact URI is outside the selected TrialMatch bucket")
        key = uri[len(prefix):]
        url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(key, safe='')}"
        metadata = self.json(url)
        # Bind the content download to the exact object generation just described.
        raw = self.request(url + "?" + urlencode({
            "alt": "media", "generation": metadata["generation"],
            "ifGenerationMatch": metadata["generation"],
        }))
        return raw, {key: metadata.get(key) for key in (
            "bucket", "name", "generation", "metageneration", "size", "crc32c",
            "md5Hash", "timeCreated", "updated", "contentType",
        )}


def output_uri(tasks, node, output):
    artifacts = tasks[node]["outputs"][output]["artifacts"]
    if len(artifacts) != 1:
        raise ValueError(f"Expected one {node}/{output} artifact")
    return artifacts[0]["uri"].rstrip("/")


def collect(output, api):
    issues, objects = [], {}

    def attempt(label, action):
        print("Reading:", label, flush=True)
        try:
            return action()
        except Exception as error:
            issues.append({"item": label, "error": f"{type(error).__name__}: {error}"})
            print("  Unavailable; continuing with the remaining evidence.", flush=True)
            return None

    def download(name, uri):
        raw, metadata = api.object(uri)
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        objects[name] = {"uri": uri, "sha256": digest(raw), **metadata}
        if name.endswith(".json"):
            return json.loads(raw)
        return raw

    job = attempt("Vertex job metadata", lambda: api.json(JOB_URL))
    config, validation, images = None, None, []
    task_map = {}
    if job is not None:
        save(output / "vertex-job.json", job)
        if job.get("name", "").split("/")[-1] != JOB_ID:
            raise ValueError("Returned Vertex job does not match the requested run")
        task_map = {t["taskName"]: t for t in job.get("jobDetail", {}).get("taskDetails", [])}
        images = sorted({e["container"]["image"] for e in
                         job.get("pipelineSpec", {}).get("deploymentSpec", {}).get("executors", {}).values()
                         if "container" in e})
        attempt("input release", lambda: download(
            "input-release.json", job["runtimeConfig"]["parameterValues"]["release"]
        ))
        processed = attempt("processed release", lambda: download(
            "output-release.json", output_uri(task_map, "process-trials", "processed") + "/release.json"
        ))
        validation = attempt("data validation report", lambda: download(
            "validation.json", output_uri(task_map, "validate-data", "report") + "/validation.json"
        ))
        attempt("retrieval rankings", lambda: download(
            "retrieval_runs.jsonl", output_uri(task_map, "retrieve-trials", "rankings") + "/retrieval_runs.jsonl"
        ))
        config = attempt("retrieval configuration and source commit", lambda: download(
            "retrieval_runs.config.json", output_uri(task_map, "retrieve-trials", "rankings") + "/retrieval_runs.config.json"
        ))
        if processed is not None:
            attempt("fixed benchmark manifest", lambda: download(
                "demo_manifest.json", processed["files"][DEMO_FILE]["uri"]
            ))

        for node in NODES:
            task = task_map.get(node)
            if task is None:
                issues.append({"item": node, "error": "Node absent from Vertex task metadata"})
                continue
            executor = task.get("executorDetail", {})
            container = executor.get("containerDetail", {})
            custom = executor.get("customJobDetail", {})
            jobs = [container.get("mainJob"), *container.get("failedMainJobs", []),
                    custom.get("job"), *custom.get("failedJobs", [])]
            jobs = list(dict.fromkeys(j for j in jobs if j))
            if not jobs:
                issues.append({"item": node + " logs", "error": "No executor job reference; inspect caching and task status"})
            for index, resource in enumerate(jobs):
                def query_logs(resource=resource, node=node, index=index):
                    match = re.fullmatch(r"projects/[^/]+/locations/[^/]+/customJobs/([0-9]+)", resource)
                    if not match:
                        raise ValueError("Unrecognized CustomJob reference")
                    logs = api.json("https://logging.googleapis.com/v2/entries:list", {
                        "resourceNames": [f"projects/{PROJECT}"],
                        "filter": 'resource.type="aiplatform.googleapis.com/CustomJob" '
                                  f'AND resource.labels.job_id="{match.group(1)}"',
                        "orderBy": "timestamp desc", "pageSize": 1000,
                    })
                    save(output / "logs" / f"{node}-{index}.json", logs)
                    if not logs.get("entries"):
                        issues.append({"item": node + " logs", "error": "No log entries returned"})
                    if logs.get("nextPageToken"):
                        issues.append({"item": node + " logs", "error": "Only latest 1000 entries exported; more exist"})
                attempt(node + " task logs", query_logs)

        def collect_builds():
            data = api.json(f"https://cloudbuild.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/builds?pageSize=100")
            wanted = {image.split("@", 1)[1] for image in images if "@" in image}
            matching = [b for b in data.get("builds", []) if any(
                image.get("digest") in wanted and "/workflow:" in image.get("name", "")
                for image in b.get("results", {}).get("images", [])
            )]
            save(output / "matching-builds.json", {
                "matching_builds": matching, "scanned_count": len(data.get("builds", [])),
                "search_has_more_pages": bool(data.get("nextPageToken")),
                "note": "Digest matches are candidates; confirm commit, timestamps and release before assigning a build ID.",
            })
            if not matching:
                issues.append({"item": "build identity", "error": "No matching build found in this bounded search"})
        attempt("matching Cloud Build records", collect_builds)

    save(output / "gcs-objects.json", objects)
    summary = {
        "collection_status": "COMPLETE" if not issues else "PARTIAL",
        "verification_status": "PENDING_REVIEW",
        "requested_job_id": JOB_ID, "console_url": CONSOLE_URL,
        "pipeline_state": job.get("state") if job else None,
        "task_states": {name: task_map.get(name, {}).get("state") for name in NODES},
        "container_images": images,
        "reported_code_commit": config.get("code_commit") if isinstance(config, dict) else None,
        "validation_status": validation.get("status") if isinstance(validation, dict) else None,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Read-only collection of the existing four-step data/retrieval run; no training, scoring or cloud failure test.",
        "issues": issues,
        "still_needed": ["Independent evidence consistency review", "Vertex graph screenshot showing the four nodes"],
    }
    save(output / "collection-summary.json", summary)
    save(output / "inventory.json", {
        str(path.relative_to(output)): digest(path.read_bytes())
        for path in sorted(output.rglob("*")) if path.is_file() and path.name != "inventory.json"
    })
    archive = output.with_name(output.name + ".tar.gz")
    with tarfile.open(archive, "x:gz") as tar:
        tar.add(output, arcname="evidence")
    print("\nCollection:", summary["collection_status"])
    print("Verification: PENDING_REVIEW")
    print("Archive:", archive)
    print("Download with: cloudshell download", archive)
    print("Upload the archive to this chat. An incomplete archive is still useful for diagnosis.")
    return 0 if not issues else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    output = (args.output_dir or Path.home() / ("ms3-evidence-20261110-" + suffix)).resolve()
    token = subprocess.run(["gcloud", "auth", "print-access-token"],
                           capture_output=True, text=True, timeout=45)
    if token.returncode or not token.stdout.strip():
        raise RuntimeError("No active gcloud login. Use your authenticated Cloud Shell; do not upload credentials.")
    output.mkdir(parents=True, exist_ok=False)
    (output / "collector.py").write_bytes(Path(__file__).read_bytes())
    return collect(output, ReadOnlyGoogle(token.stdout.strip()))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Collection stopped: {type(error).__name__}: {error}")
        raise SystemExit(2)
