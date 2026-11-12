"""Offline regression tests for the frozen MS3 eligibility benchmark."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.ms3.eligibility import run_eligibility as ev
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore


class EligibilityEvaluationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.store = DataStore(Settings())
        cls.cases = ev.load_cases(cls.store)
        cls.original = ev.RESULTS / "all_developer_baseline_predictions.jsonl"
        cls.original_meta = ev.RESULTS / "all_developer_baseline_metadata.json"
        cls.original_metrics = ev.RESULTS / "all_developer_baseline_metrics.json"

        for path in (cls.original, cls.original_meta, cls.original_metrics):
            if not path.exists():
                raise AssertionError(f"Missing baseline file: {path}")

    @contextlib.contextmanager
    def copied_run(self, change_rows=None, change_meta=None):
        # Temporary files stay inside repo so existing output paths work.
        # They are automatically removed after each test.
        with tempfile.TemporaryDirectory(
            prefix="_test_", dir=ev.RESULTS
        ) as d:
            folder = Path(d)
            path = folder / "fixture_predictions.jsonl"

            rows = ev.read_jsonl(self.original)
            meta = json.loads(
                self.original_meta.read_text(encoding="utf-8")
            )

            if change_rows:
                change_rows(rows)

            path.write_text(
                "".join(
                    json.dumps(r, ensure_ascii=False) + "\n"
                    for r in rows
                ),
                encoding="utf-8",
            )

            if change_meta:
                change_meta(meta)

            meta["predictions_sha256"] = ev.sha256_file(path)
            ev.save_json(folder / "fixture_metadata.json", meta)

            yield path

    def evaluate(self, path):
        with contextlib.redirect_stdout(io.StringIO()):
            return ev.evaluate_predictions(path)

    def test_frozen_gold_and_case_counts(self):
        from collections import Counter

        gold, hashes = ev.load_gold(self.cases)

        self.assertEqual(len(self.cases), 8)
        self.assertEqual(len(gold), 115)
        self.assertEqual(
            Counter(r["gold_decision"] for r in gold.values()),
            {"MET": 16, "NOT_MET": 17, "UNKNOWN": 82},
        )
        self.assertEqual(len(hashes), 8)

    def test_metrics_on_synthetic_labels(self):
        rows = [
            {"gold_decision": "MET", "pred_decision": "MET"},
            {"gold_decision": "MET", "pred_decision": "UNKNOWN"},
            {"gold_decision": "NOT_MET", "pred_decision": "NOT_MET"},
            {"gold_decision": "NOT_MET", "pred_decision": "MET"},
            {"gold_decision": "UNKNOWN", "pred_decision": "UNKNOWN"},
        ]

        score = ev.score_table(rows)

        self.assertEqual(score["n"], 5)
        self.assertEqual(score["accuracy"], 0.6)
        self.assertEqual(score["macro_f1"], 0.61111)
        self.assertEqual(
            score["per_class"]["MET"]["recall"], 0.5
        )
        self.assertEqual(
            score["confusion_gold_rows_pred_columns"]["NOT_MET"]["MET"],
            1,
        )

    def test_trial_status_rules(self):
        rows = [
            {"criterion_type": "inclusion", "pred_decision": "MET"},
            {"criterion_type": "exclusion", "pred_decision": "NOT_MET"},
        ]

        self.assertEqual(
            ev.trial_status(rows, "pred_decision"),
            "POTENTIAL_MATCH_FOR_REVIEW",
        )

        rows[0]["pred_decision"] = "UNKNOWN"
        self.assertEqual(
            ev.trial_status(rows, "pred_decision"),
            "NEEDS_MORE_INFORMATION",
        )

        rows[0]["pred_decision"] = "NOT_MET"
        self.assertEqual(
            ev.trial_status(rows, "pred_decision"),
            "SCREENING_BARRIER",
        )

        rows[0]["pred_decision"] = "MET"
        rows[1]["pred_decision"] = "MET"
        self.assertEqual(
            ev.trial_status(rows, "pred_decision"),
            "SCREENING_BARRIER",
        )

    def test_offline_inference_does_not_call_gold_loader(self):
        with patch.object(
            ev,
            "load_gold",
            side_effect=AssertionError("Gold accessed during inference"),
        ):
            rows = ev.predict_case(
                self.cases[0], self.store, Settings(), None
            )

        self.assertEqual(len(rows), 22)
        self.assertEqual(
            len({r["criterion_id"] for r in rows}), 22
        )

    def test_frozen_baseline_reproduces_metrics(self):
        original_files = (
            self.original,
            self.original_meta,
            self.original_metrics,
        )
        hashes_before = {
            p: ev.sha256_file(p) for p in original_files
        }

        with self.copied_run() as path:
            report = self.evaluate(path)
            score = report[
                "criterion_metrics_all_outputs_including_failures"
            ]

            self.assertEqual(score["n"], 115)
            self.assertEqual(score["accuracy"], 0.78261)
            self.assertEqual(score["macro_f1"], 0.54956)
            self.assertEqual(
                report["inference_failures"]["count"], 0
            )
            self.assertTrue(report["official_reporting_ready"])
            self.assertEqual(
                report["class_safety"]["gold_definite_predicted_unknown"],
                25,
            )

        self.assertEqual(
            hashes_before,
            {p: ev.sha256_file(p) for p in original_files},
        )

    def test_tampered_prediction_hash_is_rejected(self):
        with self.copied_run() as path:
            with path.open("a", encoding="utf-8") as f:
                f.write("\n")

            with self.assertRaisesRegex(
                AssertionError, "Prediction file changed"
            ):
                self.evaluate(path)

    def test_duplicate_criterion_is_rejected(self):
        def duplicate(rows):
            rows[1] = dict(rows[0])

        with self.copied_run(change_rows=duplicate) as path:
            with self.assertRaisesRegex(
                AssertionError, "Duplicate prediction key"
            ):
                self.evaluate(path)

    def test_inference_error_not_valid_abstention(self):
        def fail_one(rows):
            rows[0]["pred_decision"] = "UNKNOWN"
            rows[0]["error_code"] = "SYNTHETIC_TEST_429"

        def update_meta(meta):
            meta["prediction_errors"] = 1

        with self.copied_run(
            change_rows=fail_one,
            change_meta=update_meta,
        ) as path:
            report = self.evaluate(path)

            self.assertFalse(report["official_reporting_ready"])
            self.assertEqual(
                report["inference_failures"]["count"], 1
            )
            self.assertEqual(
                report["criterion_metrics_successful_outputs_only"]["n"],
                114,
            )
            self.assertEqual(
                report["inference_failures"]["by_error_code"],
                {"SYNTHETIC_TEST_429": 1},
            )


if __name__ == "__main__":
    unittest.main()
