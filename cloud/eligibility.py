"""Run C's frozen eligibility evaluator on a validated release and publish evidence."""

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

from cloud.tasks import ROOT, blob, download_release, log, write_json

DEFAULT_MODEL = "gemini-3.1-flash-lite"
PREFIX = "all_vertex_pipeline"
RESULT_FILES = tuple(f"{PREFIX}_{suffix}" for suffix in (
    "predictions.jsonl", "metadata.json", "metrics.json", "disagreements.csv",
))
CASE_IDS = [f"E{i:02d}" for i in range(1, 9)]
SCOPE = "Fixed-pair eligibility engineering evaluation; no retrieval scoring or clinical validation."


def verify_results(payloads, source_hashes, model):
    """Reject offline, incomplete or failed inference even when the evaluator exits zero."""
    if set(payloads) != set(RESULT_FILES):
        raise RuntimeError("Eligibility result files are missing")
    predictions, metadata, metrics, _ = (payloads[name] for name in RESULT_FILES)
    meta, scores = json.loads(metadata), json.loads(metrics)
    rows = [json.loads(line) for line in predictions.splitlines() if line.strip()]
    expected = {"provider": "vertex", "split": "all", "model": model}
    if any(meta.get(k) != v or scores.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Eligibility provider, split or model does not match this run")
    if (scores.get("official_reporting_ready") is not True
            or scores.get("inference_failures", {}).get("count") != 0
            or meta.get("prediction_errors") != 0
            or any(row.get("error_code") for row in rows)):
        raise RuntimeError("Eligibility inference failed or is not ready for reporting")
    if (len(rows) != 115 or meta.get("prediction_count") != 115
            or meta.get("case_ids") != CASE_IDS
            or set(scores.get("by_case", {})) != set(CASE_IDS)
            or scores.get("criterion_metrics_all_outputs_including_failures", {}).get("n") != 115):
        raise RuntimeError("Eligibility must cover all 8 cases and 115 criteria")
    digest = hashlib.sha256(predictions).hexdigest()
    if (meta.get("source_sha256") != source_hashes
            or meta.get("predictions_sha256") != digest
            or scores.get("prediction_sha256") != digest):
        raise RuntimeError("Eligibility predictions or source hashes do not match")
    return scores


def verify_manifest(manifest, release_uri, report_uri, output_uri, image, model, source_hashes):
    """Bind an output manifest to the exact task whose results the submitter reads."""
    expected = {
        "schema_version": 1, "status": "PASSED", "workflow_type": "fixed-pair-eligibility",
        "source_release_uri": release_uri, "validation_report_uri": report_uri,
        "output_uri": output_uri.rstrip("/"), "image_uri": image, "model": model,
        "provider": "vertex", "source_sha256": source_hashes,
    }
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Eligibility manifest does not match this run")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(RESULT_FILES):
        raise RuntimeError("Eligibility manifest is missing result files")
    for name, item in files.items():
        if (not isinstance(item, dict) or item.get("uri") != f"{output_uri.rstrip('/')}/{name}"
                or not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])):
            raise RuntimeError("Eligibility manifest has invalid output paths or checksums")


def read_verified_results(manifest):
    payloads = {}
    for name, item in manifest["files"].items():
        payload = blob(item["uri"]).download_as_bytes()
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Eligibility output checksum mismatch: {name}")
        payloads[name] = payload
    verify_results(payloads, manifest["source_sha256"], manifest["model"])
    return payloads


def publish_results(directory, output, manifest):
    """Keep partial results for diagnosis; publish the manifest after all available files."""
    manifest["files"] = {}
    for name in RESULT_FILES:
        path = directory / name
        if path.is_file():
            payload = path.read_bytes()
            uri = f"{output}/{name}"
            blob(uri).upload_from_string(payload)
            manifest["files"][name] = {"uri": uri, "sha256": hashlib.sha256(payload).hexdigest()}
    write_json(f"{output}/eligibility_manifest.json", manifest)


def run(source, output, image, model=DEFAULT_MODEL):
    from evaluation.ms3.eligibility import run_eligibility as evaluator

    output = output.rstrip("/")
    report_uri = source.rstrip("/") + "/validation.json"
    manifest = {
        "schema_version": 1, "status": "FAILED", "workflow_type": "fixed-pair-eligibility",
        "validation_report_uri": report_uri, "output_uri": output, "image_uri": image,
        "provider": "vertex", "model": model, "code_commit": os.environ.get("SOURCE_COMMIT"),
        "scope": SCOPE,
    }
    directory = ROOT / "artifacts/eligibility"
    directory.mkdir(parents=True, exist_ok=True)
    # A fresh directory also prevents response-cache reuse across pipeline runs.
    with tempfile.TemporaryDirectory(prefix="run-", dir=directory) as temporary:
        results = Path(temporary)
        previous_results = evaluator.RESULTS
        try:
            report = json.loads(blob(report_uri).download_as_text())
            if report.get("status") != "PASSED" or not str(report.get("release_uri", "")).startswith("gs://"):
                raise ValueError("Eligibility requires a PASSED validation report with a GCS release")
            manifest.update(source_release_uri=report["release_uri"], source_sha256=report["source_sha256"])
            cohort = json.loads((evaluator.BASE / "cohort_manifest.json").read_text())
            if report["source_sha256"] != cohort["source_sha256"]:
                raise ValueError("Validated data does not match C's frozen eligibility cohort")
            download_release(report["release_uri"])
            evaluator.RESULTS = results
            prediction_path = evaluator.run_predictions(SimpleNamespace(
                split="all", provider="vertex", model=model, tag="pipeline", overwrite=False,
            ))
            evaluator.evaluate_predictions(prediction_path)
            payloads = {name: (results / name).read_bytes() for name in RESULT_FILES}
            verify_results(payloads, report["source_sha256"], model)
        except Exception as exc:
            # Record error class only: raw model responses and credential details are not logs.
            manifest["error_type"] = type(exc).__name__
            publish_results(results, output, manifest)
            log("eligibility_failed", output=output, error_type=type(exc).__name__)
            raise
        finally:
            evaluator.RESULTS = previous_results
        manifest["status"] = "PASSED"
        publish_results(results, output, manifest)
    log("eligibility_completed", output=output, cases=8, criteria=115, scope=SCOPE)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Vertex validation report artifact URI")
    parser.add_argument("--output", required=True, help="This task's unique Vertex output artifact URI")
    parser.add_argument("--image-uri", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    if any(not re.fullmatch(r"gs://[^/\s]+/\S+", uri) for uri in (args.source, args.output)):
        parser.error("--source and --output must be GCS artifact URIs")
    if not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", args.image_uri):
        parser.error("--image-uri must be pinned by a full SHA256 digest")
    run(args.source, args.output, args.image_uri, args.model)


if __name__ == "__main__":
    main()
