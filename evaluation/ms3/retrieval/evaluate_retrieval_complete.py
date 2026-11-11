"""Evaluate MS3 retrieval runs against the merged, reviewed gold pool."""

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
QUERY_IDS = [f"Q{i:02d}" for i in range(1, 9)]

SCOPES = {
    "report_Q03_Q08": QUERY_IDS[2:],
    "dev_Q01_Q02": QUERY_IDS[:2],
    "all_Q01_Q08": QUERY_IDS,
}

HANDOFF_METHODS = {
    "bm25_question",
    "bm25_patient",
    "bioclinical_dense_question",
    "bioclinical_dense_patient",
    "bioclinical_hybrid_question",
    "bioclinical_hybrid_patient",
    "finetuned_dense_question",
    "finetuned_dense_patient",
    "finetuned_hybrid_question",
    "finetuned_hybrid_patient",
}

LEGACY = {
    "BM25 Question-only (legacy)": (
        "bm25_question_only_rankings.jsonl",
        "bm25_question_only_v1",
    ),
    "BM25 Patient-aware (legacy)": (
        "bm25_rankings.jsonl",
        "bm25_v1",
    ),
    "BM25 + Gemini/Chroma Hybrid": (
        "hybrid_rankings.jsonl",
        "bm25_gemini_chroma_hybrid",
    ),
    "Hybrid Question-only (legacy)": (
        "hybrid_question_only_rankings.jsonl",
        "hybrid_question_only_v1",
    ),
}

OUTPUTS = {
    "per_query": RESULTS / "ms3_retrieval_all14_per_query.csv",
    "summary": RESULTS / "ms3_retrieval_all14_summary.csv",
    "deltas": RESULTS / "ms3_retrieval_finetune_deltas.csv",
    "manifest": RESULTS / "ms3_retrieval_evaluation_manifest.json",
}

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_jsonl(path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

def load_labels():
    path = BASE / "retrieval_labels.csv"
    labels = defaultdict(dict)

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 182, (
        f"Official gold has {len(rows)} rows, expected 182. "
        "Complete the official merge before scoring."
    )

    for row in rows:
        qid, tid = row["query_id"], row["trial_id"]
        assert qid in QUERY_IDS
        assert tid not in labels[qid], (qid, tid)
        assert row["relevance"] in {"0", "1", "2"}
        assert row["reason"].strip()
        assert row["source_reference"].strip()
        labels[qid][tid] = int(row["relevance"])

    assert set(labels) == set(QUERY_IDS)

    reviewed = {}
    for qid in QUERY_IDS:
        path_json = BASE / "reviewed_labels" / f"{qid}.json"
        data = json.loads(path_json.read_text(encoding="utf-8"))
        assert data["query_id"] == qid

        for item in data["labels"]:
            key = (qid, item["trial_id"])
            assert key not in reviewed, key
            assert item["trial_id"] in labels[qid], key
            assert item["relevance"] == labels[qid][item["trial_id"]], key
            reviewed[key] = item

    assert len(reviewed) == 182, (
        "Official reviewed JSON files are not fully merged."
    )

    return labels

def validate_rankings(rows, expected_method, labels):
    rankings = {}

    for row in rows:
        qid = row["query_id"]
        ids = row["ranked_trial_ids"]

        assert row["method"] == expected_method
        assert qid in QUERY_IDS
        assert qid not in rankings, (expected_method, qid)
        assert len(ids) == 5
        assert len(ids) == len(set(ids))

        missing = [tid for tid in ids if tid not in labels[qid]]
        if missing:
            raise ValueError(
                f"Unjudged results: {expected_method}, {qid}: {missing}"
            )

        rankings[qid] = ids

    assert set(rankings) == set(QUERY_IDS), expected_method
    return rankings

def load_all_runs(labels):
    handoff_path = BASE / "retrieval_runs.jsonl"
    handoff = read_jsonl(handoff_path)

    assert len(handoff) == 80
    assert {row["method"] for row in handoff} == HANDOFF_METHODS

    runs = {}
    for method in sorted(HANDOFF_METHODS):
        subset = [row for row in handoff if row["method"] == method]
        runs[("Jenny handoff", method)] = validate_rankings(
            subset, method, labels
        )

    legacy_paths = {}
    for name, (filename, method_id) in LEGACY.items():
        path = RESULTS / filename
        assert path.is_file(), f"Missing legacy ranking: {path}"
        runs[("Legacy baseline", name)] = validate_rankings(
            read_jsonl(path), method_id, labels
        )
        legacy_paths[name] = sha256(path)

    assert len(runs) == 14

    handoff_pool = {
        (qid, tid)
        for (group, _), rankings in runs.items()
        if group == "Jenny handoff"
        for qid, ids in rankings.items()
        for tid in ids
    }

    assert len(handoff_pool) == 166
    assert all(tid in labels[qid] for qid, tid in handoff_pool)

    return runs, handoff_path, legacy_paths

def dcg(grades):
    return sum(
        (2 ** grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(grades[:5], start=1)
    )

def score(qid, ids, labels):
    grades = [labels[qid][tid] for tid in ids]
    ideal = sorted(labels[qid].values(), reverse=True)[:5]
    denominator = dcg(ideal)

    return {
        "p_at_3": sum(g >= 1 for g in grades[:3]) / 3,
        "ndcg_at_5": dcg(grades) / denominator if denominator else 0.0,
        "relevant_top_3": sum(g >= 1 for g in grades[:3]),
        "highly_relevant_top_5": sum(g == 2 for g in grades),
    }

def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

def main():
    parser = argparse.ArgumentParser(
        description="Score TrialMatch MS3 retrieval rankings."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESULTS,
        help="Destination for the four metric artifacts; existing files are protected."
    )
    args = parser.parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    outputs = {
        key: output_dir / path.name
        for key, path in OUTPUTS.items()
    }

    labels = load_labels()
    runs, handoff_path, legacy_paths = load_all_runs(labels)

    for path in outputs.values():
        if path.exists():
            raise FileExistsError(
                f"Refusing to overwrite an existing result: {path}"
            )

    metrics = {}
    per_query = []
    summary = []

    for (group, method), rankings in runs.items():
        for qid in QUERY_IDS:
            values = score(qid, rankings[qid], labels)
            metrics[(group, method, qid)] = values

            per_query.append({
                "source_group": group,
                "method": method,
                "query_id": qid,
                **{
                    k: round(v, 6) if isinstance(v, float) else v
                    for k, v in values.items()
                },
            })

        for scope_name, qids in SCOPES.items():
            subset = [metrics[(group, method, qid)] for qid in qids]

            summary.append({
                "scope": scope_name,
                "source_group": group,
                "method": method,
                "n_queries": len(qids),
                "mean_p_at_3": round(
                    mean(x["p_at_3"] for x in subset), 6
                ),
                "mean_ndcg_at_5": round(
                    mean(x["ndcg_at_5"] for x in subset), 6
                ),
                "queries_with_zero_p3": sum(
                    x["p_at_3"] == 0 for x in subset
                ),
            })

    comparisons = [
        ("bioclinical_dense_question", "finetuned_dense_question"),
        ("bioclinical_dense_patient", "finetuned_dense_patient"),
        ("bioclinical_hybrid_question", "finetuned_hybrid_question"),
        ("bioclinical_hybrid_patient", "finetuned_hybrid_patient"),
    ]

    summary_index = {
        (r["scope"], r["source_group"], r["method"]): r
        for r in summary
    }

    deltas = []

    for frozen, tuned in comparisons:
        a = summary_index[("report_Q03_Q08", "Jenny handoff", frozen)]
        b = summary_index[("report_Q03_Q08", "Jenny handoff", tuned)]

        deltas.append({
            "scope": "report_Q03_Q08",
            "frozen_method": frozen,
            "finetuned_method": tuned,
            "frozen_p_at_3": a["mean_p_at_3"],
            "finetuned_p_at_3": b["mean_p_at_3"],
            "delta_p_at_3": round(
                b["mean_p_at_3"] - a["mean_p_at_3"], 6
            ),
            "frozen_ndcg_at_5": a["mean_ndcg_at_5"],
            "finetuned_ndcg_at_5": b["mean_ndcg_at_5"],
            "delta_ndcg_at_5": round(
                b["mean_ndcg_at_5"] - a["mean_ndcg_at_5"], 6
            ),
        })

    manifest = {
        "evaluation": "TrialMatch MS3 retrieval",
        "reporting_queries": SCOPES["report_Q03_Q08"],
        "development_queries": SCOPES["dev_Q01_Q02"],
        "gold_labels": 182,
        "source_groups": {
            "Jenny handoff": 10,
            "Legacy baseline": 4,
        },
        "relevance_scale": [0, 1, 2],
        "p_at_3_threshold": 1,
        "ndcg_at_5_ideal": "all judged candidates for each query",
        "gold_sha256": sha256(BASE / "retrieval_labels.csv"),
        "handoff_sha256": sha256(handoff_path),
        "legacy_ranking_sha256": legacy_paths,
        "note": (
            "Pooled-candidate evaluation; not full-corpus recall. "
            "Legacy and handoff runs may differ in model or run provenance."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(outputs["per_query"], per_query)
    write_csv(outputs["summary"], summary)
    write_csv(outputs["deltas"], deltas)

    outputs["manifest"].write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    print("\n=== REPORTING SET: Q03-Q08 ===")
    report = [
        r for r in summary if r["scope"] == "report_Q03_Q08"
    ]
    for row in sorted(
        report, key=lambda r: (
            -r["mean_ndcg_at_5"],
            -r["mean_p_at_3"],
            r["method"],
        )
    ):
        print(
            f"{row['source_group']:<16} "
            f"{row['method']:<37} "
            f"P@3={row['mean_p_at_3']:.4f} "
            f"nDCG@5={row['mean_ndcg_at_5']:.4f} "
            f"zero-P@3={row['queries_with_zero_p3']}"
        )

    print("\n=== FINE-TUNING DELTAS ===")
    for row in deltas:
        print(
            f"{row['frozen_method']} -> "
            f"{row['finetuned_method']}: "
            f"dP@3={row['delta_p_at_3']:+.4f}, "
            f"dnDCG@5={row['delta_ndcg_at_5']:+.4f}"
        )

    print("\nSUCCESS")
    print("Methods scored:", len(runs))
    print("Per-query rows:", len(per_query))
    print("Summary rows:", len(summary))
    print("Fine-tuning comparisons:", len(deltas))
    for path in outputs.values():
        print("Saved:", path)

if __name__ == "__main__":
    main()
