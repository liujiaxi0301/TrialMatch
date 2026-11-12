"""Synthetic ranking records for interface tests, never benchmark evidence."""

import json

from cloud import finetuned_retrieval as retrieval


def contract():
    return {"benchmark_sha256": "b" * 64, "queries_sha256": "c" * 64,
            "trial_ids": [f"NCT{i:08d}" for i in range(50)],
            "query_ids": [f"Q{i:02d}" for i in range(1, 9)], "top_k": 5}


def payloads(expected):
    rows = [{"query_id": q, "method": m, "ranked_trial_ids": expected["trial_ids"][:5]}
            for q in expected["query_ids"] for m in sorted(retrieval.METHODS)]
    methods = {m: ({"checkpoint_uri": expected["checkpoint_uri"],
                   "checkpoint_sha256": expected["checkpoint_sha256"]}
                  if m.startswith("finetuned_") else {}) for m in retrieval.METHODS}
    config = {"source_sha256": expected["source_sha256"], "queries_sha256": expected["queries_sha256"],
              "query_count": 8, "trial_universe": 50, "top_k": 5, "methods": methods}
    return dict(zip(retrieval.FILES, (
        "".join(json.dumps(row) + "\n" for row in rows).encode(), json.dumps(config).encode(),
    ), strict=True))


def manifest(expected, output, results):
    return dict(expected, output_uri=output, files={
        name: {"uri": f"{output}/{name}", "sha256": retrieval.sha256(value)}
        for name, value in results.items()
    })


def scoring_benchmark(expected):
    from cloud import retrieval_evaluation as evaluation

    benchmark = {key: expected[key] for key in ("source_sha256", "queries_sha256", "benchmark_sha256")}
    benchmark.update(source_commit="f" * 40, catalog_sha256="1" * 64, gold_labels=40,
                     files={evaluation.BASE + "retrieval_labels.csv": "2" * 64,
                            evaluation.BASE + "evaluate_retrieval_complete.py": "3" * 64})
    labels = {qid: {tid: grade for tid, grade in zip(expected["trial_ids"][:5], [2, 1, 0, 0, 0], strict=True)}
              for qid in expected["query_ids"]}
    return benchmark, labels
