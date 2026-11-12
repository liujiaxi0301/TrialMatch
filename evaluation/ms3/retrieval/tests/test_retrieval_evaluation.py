"""Offline validation for MS3 retrieval evaluation."""

import csv
import hashlib
import json
import unittest
from pathlib import Path

from evaluation.ms3.retrieval import evaluate_retrieval_complete as scorer

BASE = Path(__file__).resolve().parents[1]
RESULTS = BASE / "results"


def rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RetrievalTests(unittest.TestCase):

    def test_gold_and_reviewed_consistency(self):
        labels = scorer.load_labels()
        self.assertEqual(sum(map(len, labels.values())), 182)

        gold = {
            (r["query_id"], r["trial_id"]): r
            for r in rows(BASE / "retrieval_labels.csv")
        }
        self.assertEqual(len(gold), 182)

        for i in range(1, 9):
            qid = f"Q{i:02d}"
            data = json.loads(
                (BASE / "reviewed_labels" / f"{qid}.json").read_text()
            )
            for item in data["labels"]:
                row = gold[(qid, item["trial_id"])]
                self.assertEqual(str(item["relevance"]), row["relevance"])
                self.assertEqual(item["reason"], row["reason"])
                self.assertEqual(
                    item["source_reference"], row["source_reference"]
                )

    def test_ranking_coverage(self):
        labels = scorer.load_labels()
        runs, _, _ = scorer.load_all_runs(labels)
        self.assertEqual(len(runs), 14)

        for rankings in runs.values():
            self.assertEqual(set(rankings), set(scorer.QUERY_IDS))
            for qid, ids in rankings.items():
                self.assertEqual(len(ids), 5)
                self.assertEqual(len(set(ids)), 5)
                self.assertTrue(all(t in labels[qid] for t in ids))

    def test_scoring_formula(self):
        labels = {
            "Q03": {"a": 2, "b": 1, "c": 0, "d": 2, "e": 0}
        }
        result = scorer.score(
            "Q03", ["a", "b", "c", "d", "e"], labels
        )
        self.assertAlmostEqual(result["p_at_3"], 2 / 3)
        self.assertEqual(result["relevant_top_3"], 2)
        self.assertEqual(result["highly_relevant_top_5"], 2)
        self.assertGreater(result["ndcg_at_5"], 0)
        self.assertLessEqual(result["ndcg_at_5"], 1)

    def test_official_result_counts(self):
        self.assertEqual(len(rows(
            RESULTS / "ms3_retrieval_all14_per_query.csv"
        )), 112)
        self.assertEqual(len(rows(
            RESULTS / "ms3_retrieval_all14_summary.csv"
        )), 42)
        self.assertEqual(len(rows(
            RESULTS / "ms3_retrieval_finetune_deltas.csv"
        )), 4)

    def test_frozen_input_hashes(self):
        manifest = json.loads(
            (RESULTS / "ms3_retrieval_evaluation_manifest.json")
            .read_text()
        )
        self.assertEqual(manifest["gold_labels"], 182)
        self.assertEqual(
            manifest["gold_sha256"],
            digest(BASE / "retrieval_labels.csv")
        )
        self.assertEqual(
            manifest["handoff_sha256"],
            digest(BASE / "retrieval_runs.jsonl")
        )

    def test_legacy_bm25_matches_handoff(self):
        handoff = scorer.read_jsonl(BASE / "retrieval_runs.jsonl")
        pairs = [
            ("bm25_question", "bm25_question_only_rankings.jsonl"),
            ("bm25_patient", "bm25_rankings.jsonl"),
        ]

        for method, filename in pairs:
            current = {
                r["query_id"]: r["ranked_trial_ids"]
                for r in handoff if r["method"] == method
            }
            legacy = {
                r["query_id"]: r["ranked_trial_ids"]
                for r in scorer.read_jsonl(RESULTS / filename)
            }
            self.assertEqual(current, legacy)


if __name__ == "__main__":
    unittest.main()
