#!/usr/bin/env python3
"""One isolated cloud checksum-failure test of the reviewed Nov 10 pipeline.

run: two new GCS test objects and one Vertex PipelineJob; then collect evidence.
collect: read the previously planned job, without uploading or submitting again.
Uses Python's standard library and Cloud Shell's existing gcloud login.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen
import uuid

PROJECT = "trialmatch-ac215-yixiao"
PROJECT_NUMBER = "15733748057"
REGION = "us-east1"
BUCKET = "trialmatch-ac215-yixiao-ms3"
BASELINE_ID = "trialmatch-data-pipeline-20261110055153"
BASELINE_COMMIT = "6cae15b387cb4de2e344b49864b68f7d0b24ab6a"
IMAGE = f"us-east1-docker.pkg.dev/{PROJECT}/trialmatch/workflow@sha256:452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad"
SPEC_SHA = "5ec84318ec05f0f1fb4eef627fe3f8a9937d1b9682c045250a808b42c83a5690"
RELEASE_SHA = "5f1811a9a5f4c1026ab1b9ed84b29d7412e8be183e3070da63b2b96725bac460"
RELEASE_URI = f"gs://{BUCKET}/releases/2c8b5da003025134/452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad/c8627e7addd3d265a61eb137d28691c545b4786b321e9e1981a9035e748e2125/release.json"
SERVICE_ACCOUNT = f"trialmatch-pipeline@{PROJECT}.iam.gserviceaccount.com"
NODES = ("fetch-raw", "process-trials", "validate-data", "retrieve-trials")
FAULT_FILE = "services/trial_ingestion/data/raw.dvc"
EXPECTED_ERROR = "Checksum mismatch: " + FAULT_FILE
JOB_COLLECTION = f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{REGION}/pipelineJobs"
LOGS_URL = "https://logging.googleapis.com/v2/entries:list"
TERMINAL = {"PIPELINE_STATE_FAILED", "PIPELINE_STATE_SUCCEEDED", "PIPELINE_STATE_CANCELLED", "PIPELINE_STATE_PAUSED"}
SCOPE = "Cloud component checksum rejection and blocking three downstream tasks; not Python-runner marker cleanup, deployment, training or evaluation."


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def now():
    return datetime.now(timezone.utc).isoformat()


def normalized_spec(spec):
    spec = copy.deepcopy(spec)
    alias = spec.pop("deploymentConfig", None)
    if alias is not None:
        alias.pop("@type", None)
        if alias != spec["deploymentSpec"]:
            raise ValueError("Conflicting deployment specifications")
    if set(spec["root"]["dag"]["tasks"]) != set(NODES):
        raise ValueError("Expected the reviewed four-node DAG")
    for task in spec["root"]["dag"]["tasks"].values():
        if task.get("cachingOptions", {}).get("enableCache", False):
            raise ValueError("Caching must be disabled")
        task["cachingOptions"] = {}
    return spec


def valid_job_name(name, job_id):
    return name in {f"projects/{p}/locations/{REGION}/pipelineJobs/{job_id}" for p in (PROJECT, PROJECT_NUMBER)}


def verify_baseline(job, manifest_bytes):
    tasks = {t["taskName"]: t for t in job["jobDetail"]["taskDetails"]}
    spec = normalized_spec(job["pipelineSpec"])
    if not (valid_job_name(job["name"], BASELINE_ID)
            and job["state"] == "PIPELINE_STATE_SUCCEEDED"
            and all(tasks[n]["state"] == "SUCCEEDED" for n in NODES)
            and sha(canonical(spec)) == SPEC_SHA
            and job["serviceAccount"] == SERVICE_ACCOUNT
            and job["runtimeConfig"]["parameterValues"]["release"] == RELEASE_URI
            and sha(manifest_bytes) == RELEASE_SHA):
        raise ValueError("Live baseline differs from the reviewed run; no test may be submitted")
    manifest = json.loads(manifest_bytes)
    if manifest["image"] != IMAGE or len(manifest["files"]) != 7:
        raise ValueError("Unexpected baseline manifest")
    return spec, manifest


def locations(job_id):
    if not re.fullmatch(r"xuyang-ms3-hash-\d{8}t\d{6}z-[0-9a-f]{8}", job_id):
        raise ValueError("Invalid isolated test job ID")
    prefix = f"gs://{BUCKET}/negative-tests/xuyang/{job_id}"
    return {"bad_object": prefix + "/bad-raw.dvc", "bad_release": prefix + "/release.json",
            "pipeline_root": prefix + "/pipeline-output"}


def make_fault(manifest, original, bad_uri):
    if sha(original) != manifest["files"][FAULT_FILE]["sha256"]:
        raise ValueError("Baseline raw.dvc already has a checksum error")
    modified = copy.deepcopy(manifest)
    modified["files"][FAULT_FILE]["uri"] = bad_uri
    # Visit the corrupted file first; retain every original expected hash.
    modified["files"] = {FAULT_FILE: modified["files"][FAULT_FILE],
                         **{k: v for k, v in modified["files"].items() if k != FAULT_FILE}}
    return modified, original + b"\n"


class ApiError(RuntimeError):
    def __init__(self, code, operation):
        self.code = code
        super().__init__(f"HTTP {code}: {operation}")


class Google:
    def __init__(self):
        proc = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True)
        if proc.returncode or not proc.stdout.strip():
            raise RuntimeError("gcloud login is unavailable; use the authenticated Cloud Shell")
        self.token = proc.stdout.strip()

    def request(self, url, data=None, content_type="application/json"):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {
            f"{REGION}-aiplatform.googleapis.com", "storage.googleapis.com", "logging.googleapis.com"
        }:
            raise ValueError("Unexpected API host")
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": content_type}
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=45) as response:
                return response.read()
        except HTTPError as error:
            # Do not expose tokens, headers or authentication output in evidence.
            raise ApiError(error.code, parsed.path) from None

    def json(self, url, body=None):
        return json.loads(self.request(url, None if body is None else json.dumps(body).encode()))

    def job(self, job_id):
        if job_id != BASELINE_ID:
            locations(job_id)
        return self.json(JOB_COLLECTION + "/" + job_id)

    def object(self, uri):
        prefix = f"gs://{BUCKET}/"
        if not uri.startswith(prefix) or len(uri) <= len(prefix):
            raise ValueError("Object outside the selected team bucket")
        url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{quote(uri[len(prefix):], safe='')}"
        metadata = self.json(url)
        raw = self.request(url + "?" + urlencode({"alt": "media", "generation": metadata["generation"],
                                                   "ifGenerationMatch": metadata["generation"]}))
        return raw, {k: metadata.get(k) for k in ("bucket", "name", "generation", "size", "md5Hash")}

    def create_object(self, job_id, uri, payload):
        allowed = locations(job_id)
        if uri not in {allowed["bad_object"], allowed["bad_release"]}:
            raise ValueError("Uploads are restricted to this case's two new test objects")
        key = uri[len(f"gs://{BUCKET}/"):]
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o?" + urlencode({
            "uploadType": "media", "name": key, "ifGenerationMatch": "0"})
        return json.loads(self.request(url, payload, "application/octet-stream"))

    def submit(self, plan):
        validate_plan(plan)
        body = {"displayName": plan["job_id"], "pipelineSpec": plan["pipeline_spec"],
                "runtimeConfig": {"gcsOutputDirectory": plan["uris"]["pipeline_root"],
                                  "parameterValues": {"release": plan["uris"]["bad_release"]}},
                "serviceAccount": SERVICE_ACCOUNT,
                "labels": {"owner": "xuyang", "purpose": "ms3-checksum-failure"}}
        return self.json(JOB_COLLECTION + "?" + urlencode({"pipelineJobId": plan["job_id"]}), body)

    def logs(self, executor):
        match = re.fullmatch(r"projects/(?:" + PROJECT + "|" + PROJECT_NUMBER
                             + r")/locations/" + REGION + r"/customJobs/(\d+)", executor)
        if not match:
            raise ValueError("Unexpected fetch executor resource")
        job_id = match.group(1)
        query = f'resource.type="ml_job" AND resource.labels.job_id="{job_id}"'
        entries, token = [], None
        for _ in range(5):
            request = {"resourceNames": [f"projects/{PROJECT}"], "filter": query,
                       "orderBy": "timestamp asc", "pageSize": 1000}
            if token:
                request["pageToken"] = token
            page = self.json(LOGS_URL, request)
            for entry in page.get("entries", []):
                resource = entry.get("resource", {})
                if not (resource.get("type") == "ml_job"
                        and resource.get("labels", {}).get("job_id") == job_id
                        and resource.get("labels", {}).get("project_id") == PROJECT):
                    raise ValueError("Log entry belongs to a different job/project")
                entries.append(entry)
            token = page.get("nextPageToken")
            if not token:
                break
        return {"filter": query, "entries": entries, "truncated": bool(token)}


def validate_plan(plan):
    if not (plan["schema_version"] == 1 and plan["workflow_image"] == IMAGE
            and plan["baseline_run"] == BASELINE_ID and plan["baseline_commit_recorded"] == BASELINE_COMMIT
            and plan["uris"] == locations(plan["job_id"])
            and sha(canonical(normalized_spec(plan["pipeline_spec"]))) == SPEC_SHA):
        raise ValueError("Plan does not match the isolated reviewed baseline")


def verify_saved_inputs(directory, plan):
    baseline = (directory / "baseline-release.json").read_bytes()
    if sha(baseline) != RELEASE_SHA:
        raise ValueError("Saved baseline release changed")
    expected_manifest, expected_raw = make_fault(
        json.loads(baseline), (directory / "original-raw.dvc").read_bytes(), plan["uris"]["bad_object"])
    actual_manifest = (directory / "bad-release.json").read_bytes()
    actual_raw = (directory / "bad-raw.dvc").read_bytes()
    if not (json.loads(actual_manifest) == expected_manifest and actual_raw == expected_raw
            and plan["test_file_sha256"] == {"bad-release.json": sha(actual_manifest), "bad-raw.dvc": sha(actual_raw)}):
        raise ValueError("Saved fault inputs differ from the one-file checksum experiment")


def executors(task):
    info = task.get("executorDetail", {})
    container, custom = info.get("containerDetail", {}), info.get("customJobDetail", {})
    return list(dict.fromkeys(x for x in [container.get("mainJob"), *container.get("failedMainJobs", []),
                                        custom.get("job"), *custom.get("failedJobs", [])] if x))


def evaluate(plan, job, logs, inputs_verified):
    tasks = {t["taskName"]: t for t in job.get("jobDetail", {}).get("taskDetails", [])}
    try:
        binding = (valid_job_name(job["name"], plan["job_id"])
                   and job["runtimeConfig"]["parameterValues"]["release"] == plan["uris"]["bad_release"]
                   and job["runtimeConfig"]["gcsOutputDirectory"] == plan["uris"]["pipeline_root"]
                   and job["serviceAccount"] == SERVICE_ACCOUNT
                   and sha(canonical(normalized_spec(job["pipelineSpec"]))) == SPEC_SHA)
    except (KeyError, ValueError, TypeError):
        binding = False
    fetch = tasks.get("fetch-raw", {})
    payload = "\n".join(str(e.get("textPayload", "")) + json.dumps(e.get("jsonPayload", {})) for e in logs)
    checksum_confirmed = EXPECTED_ERROR in payload or EXPECTED_ERROR in fetch.get("error", {}).get("message", "")
    downstream = {n: tasks.get(n) for n in NODES[1:]}
    blocked = all(t is not None and t.get("state") in {"SKIPPED", "NOT_TRIGGERED"}
                  and not t.get("startTime") and not executors(t) for t in downstream.values())
    executed = any(t and (t.get("startTime") or executors(t) or t.get("state") in {"RUNNING", "SUCCEEDED"})
                   for t in downstream.values())
    checks = {"job_image_release_dag_and_cache_match": binding, "isolated_inputs_verified": inputs_verified,
              "pipeline_failed": job.get("state") == "PIPELINE_STATE_FAILED",
              "fetch_failed": fetch.get("state") == "FAILED", "specific_checksum_error": checksum_confirmed,
              "all_three_downstream_tasks_not_executed": blocked}
    # An unrelated failure or missing evidence is never a pass.
    verdict = "PASSED" if all(checks.values()) else (
        "FAILED" if binding and (job.get("state") == "PIPELINE_STATE_SUCCEEDED" or executed) else "INCONCLUSIVE")
    return {"status": verdict, "checks": checks, "pipeline_state": job.get("state"),
            "task_states": {n: tasks.get(n, {}).get("state", "MISSING") for n in NODES},
            "scope": SCOPE, "reviewed_utc": now()}


def mark_inconclusive(directory, reason):
    current = directory / "result.json"
    if current.exists():
        current.rename(directory / ("previous-result-" + uuid.uuid4().hex[:12] + ".json"))
    save(current, {"status": "INCONCLUSIVE", "reason": reason, "recorded_utc": now()})


def collect(api, directory, wait_seconds):
    # An interrupted/rejected re-collection must not present an older PASS as current.
    mark_inconclusive(directory, "Collection started; checks have not completed")
    plan = json.loads((directory / "plan.json").read_text())
    validate_plan(plan)
    verify_saved_inputs(directory, plan)
    deadline = time.monotonic() + wait_seconds
    previous = None
    while True:
        job = api.job(plan["job_id"])
        save(directory / "vertex-job.json", job)
        state = job.get("state", "UNKNOWN")
        if state != previous:
            print("Vertex:", state, flush=True)
            previous = state
        if state in TERMINAL or time.monotonic() >= deadline:
            break
        time.sleep(min(15, max(0, deadline - time.monotonic())))
    inputs_verified, errors = True, []
    for name, uri in [("bad-raw.dvc", plan["uris"]["bad_object"]), ("bad-release.json", plan["uris"]["bad_release"])]:
        try:
            raw, metadata = api.object(uri)
            same = sha(raw) == plan["test_file_sha256"][name] == sha((directory / name).read_bytes())
            inputs_verified = inputs_verified and same
            save(directory / (name + ".cloud.json"), {"uri": uri, "sha256": sha(raw), "matches_plan": same, **metadata})
        except Exception as error:
            inputs_verified = False
            errors.append(str(error))
    fetch = next((t for t in job.get("jobDetail", {}).get("taskDetails", []) if t["taskName"] == "fetch-raw"), {})
    # Allow a short delay for Cloud Logging ingestion; never resubmit on missing logs.
    for attempt in range(3):
        logs, log_errors = [], []
        for index, executor in enumerate(executors(fetch)):
            try:
                record = api.logs(executor)
                save(directory / f"fetch-logs-{index}.json", record)
                logs.extend(record["entries"])
                if record["truncated"]:
                    log_errors.append("Log export truncated after 5000 entries")
            except Exception as error:
                log_errors.append(str(error))
        result = evaluate(plan, job, logs, inputs_verified)
        if result["status"] != "INCONCLUSIVE" or state not in TERMINAL or attempt == 2:
            break
        print("Waiting briefly for checksum log evidence...", flush=True)
        time.sleep(10)
    result.update({"pipeline_job": job.get("name"), "case_id": plan["job_id"],
                   "workflow_image": IMAGE, "baseline_commit_recorded": BASELINE_COMMIT,
                   "collection_errors": errors + log_errors})
    save(directory / "result.json", result)
    print(json.dumps(result, indent=2), flush=True)
    print("Vertex FAILED is expected; result.json PASSED means the negative test passed.", flush=True)
    return {"PASSED": 0, "INCONCLUSIVE": 2, "FAILED": 3}[result["status"]]


def run(api, directory, wait_seconds):
    # A fixed local case directory prevents accidental repeat submissions.
    directory.mkdir(parents=False, exist_ok=False)
    job_id = "xuyang-ms3-hash-" + datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz") + "-" + uuid.uuid4().hex[:8]
    print("Reading and checking the fixed successful baseline...", flush=True)
    baseline = api.job(BASELINE_ID)
    manifest_bytes, manifest_meta = api.object(RELEASE_URI)
    spec, manifest = verify_baseline(baseline, manifest_bytes)
    original, raw_meta = api.object(manifest["files"][FAULT_FILE]["uri"])
    uris = locations(job_id)
    fault, damaged = make_fault(manifest, original, uris["bad_object"])
    # Explicit false is preserved in the request; Vertex may omit false in its response.
    for task in spec["root"]["dag"]["tasks"].values():
        task["cachingOptions"] = {"enableCache": False}
    bad_manifest_bytes = (json.dumps(fault, indent=2) + "\n").encode()
    plan = {"schema_version": 1, "created_utc": now(), "job_id": job_id, "baseline_run": BASELINE_ID,
            "baseline_commit_recorded": BASELINE_COMMIT, "workflow_image": IMAGE,
            "uris": uris, "pipeline_spec": spec, "scope": SCOPE,
            "expected_error": EXPECTED_ERROR,
            "test_file_sha256": {"bad-raw.dvc": sha(damaged), "bad-release.json": sha(bad_manifest_bytes)},
            "original_expected_raw_sha256": manifest["files"][FAULT_FILE]["sha256"]}
    validate_plan(plan)
    save(directory / "baseline-job.json", baseline)
    (directory / "baseline-release.json").write_bytes(manifest_bytes)
    (directory / "original-raw.dvc").write_bytes(original)
    (directory / "bad-raw.dvc").write_bytes(damaged)
    (directory / "bad-release.json").write_bytes(bad_manifest_bytes)
    save(directory / "baseline-gcs-objects.json", {"release": manifest_meta, "raw.dvc": raw_meta})
    save(directory / "plan.json", plan)  # Save deterministic job ID before any cloud writes.
    shutil.copyfile(__file__, directory / "runner.py")
    print("Creating two NEW objects under:", uris["bad_release"].rsplit("/", 1)[0], flush=True)
    uploads = []
    for uri, content in [(uris["bad_object"], damaged), (uris["bad_release"], bad_manifest_bytes)]:
        uploads.append(api.create_object(job_id, uri, content))
        save(directory / "uploaded-objects.json", uploads)
    # Read back before submitting; failure here never counts as the cloud component test.
    for uri, content in [(uris["bad_object"], damaged), (uris["bad_release"], bad_manifest_bytes)]:
        if api.object(uri)[0] != content:
            raise ValueError("Uploaded test bytes differ; refusing to submit")
    save(directory / "submission-attempt.json", {"job_id": job_id, "attempted_utc": now()})
    print("Submitting ONE isolated pipeline:", job_id, flush=True)
    print(f"https://console.cloud.google.com/vertex-ai/locations/{REGION}/pipelines/runs/{job_id}?project={PROJECT}", flush=True)
    submitted = api.submit(plan)
    save(directory / "submission-response.json", submitted)
    if not valid_job_name(submitted.get("name"), job_id):
        raise ValueError("Unexpected submission response; collect the planned ID, do not resubmit")
    return collect(api, directory, wait_seconds)


def archive(directory):
    inventory = {str(p.relative_to(directory)): sha(p.read_bytes()) for p in sorted(directory.rglob("*"))
                 if p.is_file() and p.name != "inventory.json"}
    save(directory / "inventory.json", inventory)
    target = directory.with_name(directory.name + ".tar.gz")
    with tarfile.open(target, "w:gz") as bundle:
        bundle.add(directory, arcname="evidence")
    print("Evidence archive:", target, flush=True)
    print("Download with: cloudshell download " + str(target), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "collect"))
    parser.add_argument("--case-dir", type=Path, default=Path.home() / "ms3-negative-20261110")
    parser.add_argument("--wait-seconds", type=int, default=1200)
    args = parser.parse_args()
    directory = args.case_dir.expanduser().resolve()
    if args.wait_seconds < 0 or args.wait_seconds > 1800:
        parser.error("--wait-seconds must be between 0 and 1800")
    # Never overwrite another case or package an unrelated directory on errors.
    if args.action == "run" and directory.exists():
        parser.error("Case directory already exists. Use collect for that case; do not repeat run.")
    if args.action == "collect" and not (directory / "plan.json").is_file():
        parser.error("No saved plan found; inspect the previous error before starting a new case.")
    code = 2
    try:
        api = Google()
        code = run(api, directory, args.wait_seconds) if args.action == "run" else collect(api, directory, args.wait_seconds)
    except (Exception, KeyboardInterrupt) as error:
        message = type(error).__name__ + ": " + str(error)
        print("INCONCLUSIVE:", message, flush=True)
        if directory.is_dir():
            save(directory / "collection-error.json", {"status": "INCONCLUSIVE", "error": message, "recorded_utc": now()})
            mark_inconclusive(directory, message)
        print("Do not repeat run. If a plan exists, use collect to inspect the same job.", flush=True)
    finally:
        if directory.is_dir() and (directory / "plan.json").is_file():
            archive(directory)
    return code


if __name__ == "__main__":
    sys.exit(main())
