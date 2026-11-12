"""Run Jenny's ranking entry point against this pipeline's trained checkpoint."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from cloud.tasks import ROOT, blob, download_release, log, write_json
from cloud.training_inputs import verify_training_manifest

FILES = ("retrieval_runs.jsonl", "retrieval_runs.config.json")
MANIFEST = "finetuned_retrieval_manifest.json"
BENCHMARK = "services/rag_workflow/examples/demo_manifest.json"
QUERIES = "evaluation/ms3/retrieval_queries.jsonl"
METHODS = {f"{method}_{mode}" for method in ("bm25", "finetuned_dense", "finetuned_hybrid")
           for mode in ("question", "patient")}
SCOPE = "Rankings from this run's trained encoder; human relevance scoring remains separate."


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def benchmark_contract(release_uri):
    """Read the universe bound to the release; query bytes are fixed in source/image."""
    release = json.loads(blob(release_uri).download_as_text())
    item = release["files"][BENCHMARK]
    content = blob(item["uri"]).download_as_bytes()
    if sha256(content) != item["sha256"]:
        raise ValueError("Retrieval benchmark checksum mismatch")
    trial_ids = json.loads(content)["trial_ids"]
    queries = (ROOT / QUERIES).read_bytes()
    query_ids = [json.loads(line)["query_id"] for line in queries.splitlines() if line.strip()]
    if len(trial_ids) != 50 or len(set(trial_ids)) != 50:
        raise ValueError("Retrieval requires the fixed 50-trial universe")
    if len(query_ids) != 8 or set(query_ids) != {f"Q{i:02d}" for i in range(1, 9)}:
        raise ValueError("Retrieval requires the fixed eight query IDs")
    return {"benchmark_sha256": item["sha256"], "queries_sha256": sha256(queries),
            "trial_ids": sorted(trial_ids), "query_ids": sorted(query_ids), "top_k": 5}


def expected_manifest(report_uri, report, training_uri, training_bytes, image, contract):
    training = json.loads(training_bytes)
    return {
        "schema_version": 1, "status": "PASSED", "workflow_type": "finetuned-retrieval",
        "validation_report_uri": report_uri, "source_release_uri": report["release_uri"],
        "source_sha256": report["source_sha256"],
        "training_manifest_uri": training_uri.rstrip("/") + "/training_manifest.json",
        "training_manifest_sha256": sha256(training_bytes),
        "checkpoint_uri": training["artifact_uri"], "checkpoint_sha256": training["artifact_sha256"],
        "training_image_uri": training["image_uri"], "image_uri": image,
        **contract,
    }


def verify_results(payloads, expected):
    if set(payloads) != set(FILES):
        raise RuntimeError("Fine-tuned retrieval outputs are missing")
    config = json.loads(payloads[FILES[1]])
    if (config.get("source_sha256") != expected["source_sha256"]
            or config.get("queries_sha256") != expected["queries_sha256"]
            or config.get("query_count") != 8 or config.get("trial_universe") != 50
            or config.get("top_k") != 5 or set(config.get("methods", {})) != METHODS):
        raise RuntimeError("Fine-tuned retrieval configuration does not match its inputs")
    for method, settings in config["methods"].items():
        if method.startswith("finetuned_") and (
            settings.get("checkpoint_sha256") != expected["checkpoint_sha256"]
            or settings.get("checkpoint_uri") != expected["checkpoint_uri"]
        ):
            raise RuntimeError("Rankings used a different training checkpoint")
    rows = [json.loads(line) for line in payloads[FILES[0]].splitlines() if line.strip()]
    keys = {(row.get("query_id"), row.get("method")) for row in rows}
    if len(rows) != 48 or keys != {(q, m) for q in expected["query_ids"] for m in METHODS}:
        raise RuntimeError("Rankings must cover all eight queries and six methods exactly once")
    universe = set(expected["trial_ids"])
    for row in rows:
        ranking = row.get("ranked_trial_ids")
        if (not isinstance(ranking, list) or len(ranking) > 5
                or any(not isinstance(item, str) for item in ranking)
                or len(set(ranking)) != len(ranking) or not set(ranking) <= universe):
            raise RuntimeError("Rankings contain invalid, duplicate or out-of-universe trial IDs")


def read_verified_results(manifest, expected, output):
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Fine-tuned retrieval manifest does not match this run")
    if manifest.get("output_uri") != output.rstrip("/") or set(manifest.get("files", {})) != set(FILES):
        raise RuntimeError("Fine-tuned retrieval manifest has foreign or missing outputs")
    payloads = {}
    for name, item in manifest["files"].items():
        if item.get("uri") != f"{output.rstrip('/')}/{name}":
            raise RuntimeError("Fine-tuned retrieval result URI does not match this task")
        payload = blob(item["uri"]).download_as_bytes()
        if sha256(payload) != item.get("sha256"):
            raise RuntimeError(f"Fine-tuned retrieval output checksum mismatch: {name}")
        payloads[name] = payload
    verify_results(payloads, expected)
    return payloads


def run(source, training_uri, output, image, trainer_image, batch_size=8, expected_pairs=None):
    # Importing this module in the submitter requires no PyTorch/transformers.
    from services.rag_workflow.config import Settings
    from services.rag_workflow.data import DataStore
    from services.rag_workflow.embedding_providers import resolve_checkpoint

    report_uri = source.rstrip("/") + "/validation.json"
    output, training_uri = output.rstrip("/"), training_uri.rstrip("/")
    report = json.loads(blob(report_uri).download_as_text())
    if report.get("status") != "PASSED" or not str(report.get("release_uri", "")).startswith("gs://"):
        raise ValueError("Fine-tuned retrieval requires a PASSED data report")
    training_bytes = blob(training_uri + "/training_manifest.json").download_as_bytes()
    training = json.loads(training_bytes)
    verify_training_manifest(training, report["release_uri"], training_uri, trainer_image,
                             batch_size, expected_pairs if expected_pairs is not None else {})
    download_release(report["release_uri"])
    if DataStore(Settings()).hashes != report["source_sha256"]:
        raise ValueError("Retrieval data does not match the validation report")
    contract = benchmark_contract(report["release_uri"])
    expected = expected_manifest(report_uri, report, training_uri, training_bytes, image, contract)
    directory = ROOT / "artifacts/finetuned_retrieval"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="run-", dir=directory) as temporary:
        work = Path(temporary)
        # Use the existing content verifier before starting Jenny's ranking process.
        # A fresh cache prevents an older model/index from satisfying this run.
        settings = replace(Settings(), artifacts=work, embedding_checkpoint=training["artifact_uri"],
                           embedding_checkpoint_sha256=training["artifact_sha256"])
        checkpoint = resolve_checkpoint(settings)
        local_manifest = work / "training_manifest.json"
        local_manifest.write_bytes(training_bytes)
        destination = work / FILES[0]
        env = dict(os.environ, MS3_STORES=str(work / "indices"), EMBEDDING_DEVICE="cpu",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", ANONYMIZED_TELEMETRY="False",
                   TOKENIZERS_PARALLELISM="false", OMP_NUM_THREADS="4", MKL_NUM_THREADS="4")
        subprocess.run(
            [sys.executable, "-m", "evaluation.ms3.run_retrieval", "--encoders",
             "--finetuned-manifest", str(local_manifest), "--finetuned-checkpoint", str(checkpoint),
             "--queries", str(ROOT / QUERIES), "--top-k", "5", "--output", str(destination)],
            cwd=ROOT, env=env, check=True,
        )
        payloads = {name: (work / name).read_bytes() for name in FILES}
        verify_results(payloads, expected)
        manifest = dict(expected, output_uri=output, code_commit=os.environ.get("SOURCE_COMMIT"),
                        scope=SCOPE, files={})
        for name, payload in payloads.items():
            uri = f"{output}/{name}"
            blob(uri).upload_from_string(payload)
            manifest["files"][name] = {"uri": uri, "sha256": sha256(payload)}
        # Success is published only after both complete, checked outputs exist.
        write_json(f"{output}/{MANIFEST}", manifest)
    log("finetuned_rankings_saved", output=output, queries=8, methods=6, rows=48, scope=SCOPE)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--training", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--image-uri", required=True)
    parser.add_argument("--trainer-image", required=True)
    parser.add_argument("--trainer-batch-size", type=int, default=8)
    parser.add_argument("--expected-pairs", default="{}", help="JSON URI -> SHA256 map submitted for training")
    args = parser.parse_args()
    if any(not re.fullmatch(r"gs://[^/\s]+/\S+", uri) for uri in (args.source, args.training, args.output)):
        parser.error("Source, training and output must be GCS artifact URIs")
    if any(not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", uri)
           for uri in (args.image_uri, args.trainer_image)):
        parser.error("Retrieval and trainer images must be pinned by full SHA256 digests")
    expected_pairs = json.loads(args.expected_pairs)
    if not isinstance(expected_pairs, dict) or any(
        not re.fullmatch(r"gs://[^/\s]+/\S+", uri)
        or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)
        for uri, sha in expected_pairs.items()
    ):
        parser.error("Expected pairs must map GCS URIs to SHA256 values")
    run(args.source, args.training, args.output, args.image_uri, args.trainer_image,
        args.trainer_batch_size, expected_pairs)


if __name__ == "__main__":
    main()
