"""Score this run's six retrieval methods using Module C's frozen metric functions."""

import argparse
import csv
import io
import json
import os
import re
from statistics import mean

from cloud import finetuned_retrieval as retrieval
from cloud.tasks import ROOT, blob, log, write_json
from cloud.training_inputs import pair_hashes, verify_training_manifest

CATALOG = "cloud/retrieval_benchmark.json"
BASE = "evaluation/ms3/retrieval/"
MANIFEST = "retrieval_evaluation_manifest.json"
FILES = ("retrieval_per_query.csv", "retrieval_summary.csv")
SCOPE = ("Six current-run retrieval methods; pooled relevance judgments, not clinical validation. "
         "No historical rankings are substituted and no frozen-model delta is computed.")


def load_benchmark(expected_sha=None):
    """Verify the reviewed C bundle before reading labels or using its scorer."""
    raw = (ROOT / CATALOG).read_bytes()
    digest = retrieval.sha256(raw)
    if expected_sha is not None and digest != expected_sha:
        raise ValueError("Evaluation benchmark version differs from the submitted version")
    catalog = json.loads(raw)
    for name, expected in catalog["files"].items():
        if retrieval.sha256((ROOT / name).read_bytes()) != expected:
            raise ValueError(f"Evaluation benchmark checksum mismatch: {name}")
    # Preserve the old runner path as well as C's new location during integration.
    if retrieval.sha256((ROOT / retrieval.QUERIES).read_bytes()) != catalog["queries_sha256"]:
        raise ValueError("Evaluation queries differ from the ranking entry point")
    from evaluation.ms3.retrieval import evaluate_retrieval_complete as scorer

    labels = scorer.load_labels()
    return dict(catalog, catalog_sha256=digest), labels


def expected_manifest(ranking_expected, ranking_uri, ranking_manifest_bytes, image, benchmark):
    for key in ("source_sha256", "queries_sha256", "benchmark_sha256"):
        if ranking_expected[key] != benchmark[key]:
            raise ValueError(f"Rankings and frozen evaluation benchmark differ: {key}")
    return {
        **{k: ranking_expected[k] for k in (
            "validation_report_uri", "source_release_uri", "source_sha256", "queries_sha256",
            "benchmark_sha256", "training_manifest_uri", "training_manifest_sha256",
            "checkpoint_uri", "checkpoint_sha256", "training_image_uri",
        )},
        "schema_version": 1, "status": "PASSED", "workflow_type": "retrieval-evaluation",
        "image_uri": image, "retrieval_image_uri": ranking_expected["image_uri"],
        "retrieval_manifest_uri": ranking_uri.rstrip("/") + "/" + retrieval.MANIFEST,
        "retrieval_manifest_sha256": retrieval.sha256(ranking_manifest_bytes),
        "evaluation_source_commit": benchmark["source_commit"],
        "evaluation_bundle_sha256": benchmark["catalog_sha256"],
        "gold_sha256": benchmark["files"][BASE + "retrieval_labels.csv"],
        "scorer_sha256": benchmark["files"][BASE + "evaluate_retrieval_complete.py"],
        "gold_labels": benchmark["gold_labels"],
        "methods": sorted(retrieval.METHODS), "per_query_rows": 48, "summary_rows": 18,
        "reporting_queries": [f"Q{i:02d}" for i in range(3, 9)],
        "development_queries": ["Q01", "Q02"],
        "p_at_3_threshold": 1, "ndcg_at_5_ideal": "all judged candidates for each query",
        "scope": SCOPE,
    }


class UnjudgedResults(ValueError):
    def __init__(self, pairs):
        self.pairs = [{"query_id": qid, "trial_id": tid} for qid, tid in sorted(pairs)]
        super().__init__(f"Unjudged retrieval results: {len(self.pairs)} query-trial pairs; review required")


def score_outputs(payloads, ranking_expected, labels):
    """Validate current inputs and reuse C's formulas; fewer than five hits are allowed."""
    retrieval.verify_results(payloads, ranking_expected)
    rows = [json.loads(line) for line in payloads[retrieval.FILES[0]].splitlines() if line.strip()]
    missing = {(r["query_id"], tid) for r in rows for tid in r["ranked_trial_ids"]
               if tid not in labels.get(r["query_id"], {})}
    if missing:
        raise UnjudgedResults(missing)
    from evaluation.ms3.retrieval import evaluate_retrieval_complete as scorer

    per_query, summary = [], []
    for method in sorted(retrieval.METHODS):
        values = {r["query_id"]: scorer.score(r["query_id"], r["ranked_trial_ids"], labels)
                  for r in rows if r["method"] == method}
        for qid in scorer.QUERY_IDS:
            per_query.append({"source_group": "Current pipeline run", "method": method, "query_id": qid,
                              **{k: round(v, 6) if isinstance(v, float) else v for k, v in values[qid].items()}})
        for scope, qids in scorer.SCOPES.items():
            selected = [values[qid] for qid in qids]
            summary.append({"scope": scope, "source_group": "Current pipeline run", "method": method,
                            "n_queries": len(qids),
                            "mean_p_at_3": round(mean(v["p_at_3"] for v in selected), 6),
                            "mean_ndcg_at_5": round(mean(v["ndcg_at_5"] for v in selected), 6),
                            "queries_with_zero_p3": sum(v["p_at_3"] == 0 for v in selected)})
    output = {}
    for name, records in zip(FILES, (per_query, summary), strict=True):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        output[name] = stream.getvalue().encode()
    return output


def read_verified_results(manifest, expected, output, expected_payloads):
    """Independently recomputed metric bytes must match the cloud outputs."""
    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError("Retrieval evaluation manifest does not match this run")
    if manifest.get("output_uri") != output or set(manifest.get("files", {})) != set(FILES):
        raise RuntimeError("Retrieval evaluation has foreign or missing outputs")
    for name, item in manifest["files"].items():
        if item.get("uri") != f"{output}/{name}":
            raise RuntimeError("Retrieval evaluation result URI differs from this task")
        payload = blob(item["uri"]).download_as_bytes()
        if retrieval.sha256(payload) != item.get("sha256"):
            raise RuntimeError(f"Retrieval evaluation output checksum mismatch: {name}")
        if payload != expected_payloads[name]:
            raise RuntimeError(f"Retrieval evaluation metrics do not reproduce: {name}")


def run(source, training_uri, ranking_uri, output, image, retrieval_image, trainer_image,
        benchmark_sha, batch_size=8, expected_pairs=None):
    benchmark, labels = load_benchmark(benchmark_sha)
    source, training_uri, ranking_uri, output = (p.rstrip("/") for p in (source, training_uri, ranking_uri, output))
    report_uri = source + "/validation.json"
    report = json.loads(blob(report_uri).download_as_bytes())
    if report.get("status") != "PASSED":
        raise ValueError("Retrieval evaluation requires a PASSED data report")
    training_bytes = blob(training_uri + "/training_manifest.json").download_as_bytes()
    verify_training_manifest(json.loads(training_bytes), report["release_uri"], training_uri,
                             trainer_image, batch_size, expected_pairs if expected_pairs is not None else {})
    contract = retrieval.benchmark_contract(report["release_uri"])
    ranking_expected = retrieval.expected_manifest(report_uri, report, training_uri, training_bytes,
                                                   retrieval_image, contract)
    ranking_bytes = blob(ranking_uri + "/" + retrieval.MANIFEST).download_as_bytes()
    payloads = retrieval.read_verified_results(json.loads(ranking_bytes), ranking_expected, ranking_uri)
    expected = expected_manifest(ranking_expected, ranking_uri, ranking_bytes, image, benchmark)
    try:
        results = score_outputs(payloads, ranking_expected, labels)
    except UnjudgedResults as exc:
        # This diagnostic is not a success marker. No scores are published for an incomplete pool.
        write_json(output + "/unjudged_pairs.json", {
            "status": "BLOCKED_UNJUDGED", "retrieval_manifest_uri": expected["retrieval_manifest_uri"],
            "evaluation_bundle_sha256": benchmark_sha, "pairs": exc.pairs,
        })
        log("retrieval_evaluation_blocked", count=len(exc.pairs), diagnostic=output + "/unjudged_pairs.json")
        raise
    manifest = dict(expected, output_uri=output, code_commit=os.environ.get("SOURCE_COMMIT"), files={})
    for name, payload in results.items():
        uri = output + "/" + name
        blob(uri).upload_from_string(payload)
        manifest["files"][name] = {"uri": uri, "sha256": retrieval.sha256(payload)}
    write_json(output + "/" + MANIFEST, manifest)
    log("retrieval_evaluation_saved", output=output, methods=6, per_query_rows=48, scope=SCOPE)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "training", "rankings", "output", "image-uri", "retrieval-image",
                 "trainer-image", "benchmark-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--trainer-batch-size", type=int, default=8)
    parser.add_argument("--expected-pairs", default="{}")
    args = parser.parse_args()
    if any(not re.fullmatch(r"gs://[^/\s]+/\S+", uri)
           for uri in (args.source, args.training, args.rankings, args.output)):
        parser.error("Artifact inputs and output must be GCS URIs")
    if any(not re.fullmatch(r"[^\s@]+@sha256:[0-9a-f]{64}", uri)
           for uri in (args.image_uri, args.retrieval_image, args.trainer_image)):
        parser.error("All images must use complete SHA256 digests")
    if not re.fullmatch(r"[0-9a-f]{64}", args.benchmark_sha256) or args.trainer_batch_size < 1:
        parser.error("A complete benchmark SHA256 and positive batch size are required")
    try:
        pairs = json.loads(args.expected_pairs)
        if not isinstance(pairs, dict) or any(not re.fullmatch(r"gs://[^/\s]+/\S+", u) for u in pairs):
            raise ValueError("Expected pairs must be a GCS URI-to-SHA256 object")
        pair_hashes(list(pairs), list(pairs.values()))
    except (ValueError, TypeError) as exc:
        parser.error(str(exc))
    run(args.source, args.training, args.rankings, args.output, args.image_uri, args.retrieval_image,
        args.trainer_image, args.benchmark_sha256, args.trainer_batch_size, pairs)


if __name__ == "__main__":
    main()
