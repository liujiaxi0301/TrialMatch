"""Current-run scoring boundaries with synthetic rankings and simulated storage."""

import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cloud import finetuned_retrieval as retrieval
from cloud import retrieval_evaluation as evaluation
from cloud import tasks
from cloud.tests import retrieval_fixtures as fixtures
from cloud.tests.test_finetuned_retrieval import MemoryBlob


class ScoringTests(unittest.TestCase):
    SOURCE = "gs://new-run/report"
    TRAINING = "gs://new-run/training"
    RANKINGS = "gs://new-run/rankings"
    OUTPUT = "gs://new-run/evaluation"
    IMAGE = "example/workflow@sha256:" + "a" * 64
    RETRIEVAL_IMAGE = "example/retrieval@sha256:" + "b" * 64
    TRAINER = "example/trainer@sha256:" + "c" * 64

    def setUp(self):
        self.enterContext(redirect_stdout(io.StringIO()))
        self.objects = {}
        self.lookup = lambda uri: MemoryBlob(self.objects, uri)
        for module in (evaluation, retrieval, tasks):
            self.enterContext(patch.object(module, "blob", side_effect=self.lookup))
        self.contract = fixtures.contract()
        self.enterContext(patch.object(retrieval, "benchmark_contract", return_value=self.contract))
        self.report = {"status": "PASSED", "release_uri": "gs://new-run/processed/release.json",
                       "source_sha256": dict.fromkeys(("trials", "criteria", "patients"), "e" * 64)}
        checksums = {"model.safetensors": "d" * 64}
        self.training = {
            "schema_version": 1, "workflow_type": "contrastive-encoder-finetune",
            "source_release_uri": self.report["release_uri"], "image_uri": self.TRAINER,
            "artifact_uri": self.TRAINING + "/model", "artifact_files": checksums,
            "artifact_sha256": retrieval.sha256(json.dumps(checksums, sort_keys=True).encode()),
            "config": {"batch_size": 8}, "pair_files": [{"uri": "built-from:" + self.report["release_uri"]}],
        }
        self.training_bytes = json.dumps(self.training).encode()
        self.objects[self.SOURCE + "/validation.json"] = json.dumps(self.report).encode()
        self.objects[self.TRAINING + "/training_manifest.json"] = self.training_bytes
        self.expected = retrieval.expected_manifest(self.SOURCE + "/validation.json", self.report,
            self.TRAINING, self.training_bytes, self.RETRIEVAL_IMAGE, self.contract)
        self.payloads = fixtures.payloads(self.expected)
        self.refresh_rankings()
        self.benchmark, self.labels = fixtures.scoring_benchmark(self.expected)
        self.enterContext(patch.object(evaluation, "load_benchmark", return_value=(self.benchmark, self.labels)))

    def refresh_rankings(self):
        self.ranking_manifest = fixtures.manifest(self.expected, self.RANKINGS, self.payloads)
        self.ranking_bytes = json.dumps(self.ranking_manifest).encode()
        self.objects[self.RANKINGS + "/" + retrieval.MANIFEST] = self.ranking_bytes
        for name, value in self.payloads.items():
            self.objects[self.RANKINGS + "/" + name] = value

    def run_task(self):
        return evaluation.run(self.SOURCE, self.TRAINING, self.RANKINGS, self.OUTPUT, self.IMAGE,
                              self.RETRIEVAL_IMAGE, self.TRAINER, self.benchmark["catalog_sha256"])

    def test_current_rankings_are_scored_with_c_formulas_and_versioned(self):
        record = self.run_task()
        expected = evaluation.expected_manifest(self.expected, self.RANKINGS, self.ranking_bytes,
                                                 self.IMAGE, self.benchmark)
        results = evaluation.score_outputs(self.payloads, self.expected, self.labels)
        evaluation.read_verified_results(record, expected, self.OUTPUT, results)
        rows = list(csv.DictReader(io.StringIO(results[evaluation.FILES[0]].decode())))
        summary = list(csv.DictReader(io.StringIO(results[evaluation.FILES[1]].decode())))
        self.assertEqual(len(rows), 48)
        self.assertEqual(len(summary), 18)
        self.assertAlmostEqual(float(rows[0]["p_at_3"]), 2 / 3, places=6)
        self.assertEqual(float(rows[0]["ndcg_at_5"]), 1.0)
        self.assertEqual(record["checkpoint_uri"], self.TRAINING + "/model")
        self.assertEqual(record["retrieval_manifest_sha256"], retrieval.sha256(self.ranking_bytes))
        self.assertEqual({r["n_queries"] for r in summary}, {"2", "6", "8"})

    def test_short_and_empty_rankings_use_fixed_precision_denominator(self):
        rows = [json.loads(line) for line in self.payloads[retrieval.FILES[0]].splitlines()]
        rows[0]["ranked_trial_ids"] = self.expected["trial_ids"][:1]
        rows[1]["ranked_trial_ids"] = []
        self.payloads[retrieval.FILES[0]] = "".join(json.dumps(r) + "\n" for r in rows).encode()
        self.refresh_rankings()
        self.run_task()
        scores = list(csv.DictReader(io.StringIO(self.objects[self.OUTPUT + "/" + evaluation.FILES[0]].decode())))
        by_key = {(r["query_id"], r["method"]): r for r in scores}
        self.assertAlmostEqual(float(by_key[(rows[0]["query_id"], rows[0]["method"])]["p_at_3"]), 1 / 3, places=6)
        self.assertEqual(float(by_key[(rows[1]["query_id"], rows[1]["method"])]["p_at_3"]), 0)

    def test_zero_quality_is_a_completed_evaluation(self):
        for grades in self.labels.values():
            for tid in grades:
                grades[tid] = 0
        self.assertEqual(self.run_task()["status"], "PASSED")

    def test_unjudged_pair_gets_diagnostic_and_no_scores_or_success(self):
        del self.labels["Q03"][self.expected["trial_ids"][0]]
        with self.assertRaises(evaluation.UnjudgedResults):
            self.run_task()
        output_keys = {uri.removeprefix(self.OUTPUT + "/") for uri in self.objects if uri.startswith(self.OUTPUT)}
        self.assertEqual(output_keys, {"unjudged_pairs.json"})
        diagnostic = json.loads(self.objects[self.OUTPUT + "/unjudged_pairs.json"])
        self.assertEqual(diagnostic["status"], "BLOCKED_UNJUDGED")
        self.assertEqual(diagnostic["pairs"], [{"query_id": "Q03", "trial_id": self.expected["trial_ids"][0]}])

    def test_foreign_model_manifest_fails_before_scoring(self):
        self.ranking_manifest["checkpoint_uri"] = "gs://old-run/model"
        self.objects[self.RANKINGS + "/" + retrieval.MANIFEST] = json.dumps(self.ranking_manifest).encode()
        with patch.object(evaluation, "score_outputs") as score, self.assertRaises(RuntimeError):
            self.run_task()
        score.assert_not_called()

    def test_changed_ranking_bytes_or_missing_config_cannot_publish_success(self):
        self.objects[self.RANKINGS + "/" + retrieval.FILES[0]] += b"changed"
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            self.run_task()
        self.refresh_rankings()
        del self.objects[self.RANKINGS + "/" + retrieval.FILES[1]]
        with self.assertRaises(KeyError):
            self.run_task()
        self.assertNotIn(self.OUTPUT + "/" + evaluation.MANIFEST, self.objects)

    def test_benchmark_source_and_query_must_match_current_rankings(self):
        for key in ("source_sha256", "queries_sha256", "benchmark_sha256"):
            with self.subTest(key=key):
                original = self.benchmark[key]
                self.benchmark[key] = "different"
                with self.assertRaisesRegex(ValueError, "benchmark differ"):
                    self.run_task()
                self.benchmark[key] = original
        self.assertFalse(any(uri.startswith(self.OUTPUT) for uri in self.objects))

    def test_upload_failure_cannot_publish_success_manifest(self):
        with (patch.object(MemoryBlob, "upload_from_string", side_effect=OSError("upload failure")),
              self.assertRaises(OSError)):
            self.run_task()
        self.assertNotIn(self.OUTPUT + "/" + evaluation.MANIFEST, self.objects)

    def test_wrong_metrics_fail_even_if_their_new_hash_matches(self):
        record = self.run_task()
        expected = evaluation.expected_manifest(self.expected, self.RANKINGS, self.ranking_bytes,
                                                 self.IMAGE, self.benchmark)
        results = evaluation.score_outputs(self.payloads, self.expected, self.labels)
        name = evaluation.FILES[0]
        bad = self.objects[self.OUTPUT + "/" + name].replace(b"0.666667", b"1.000000")
        self.objects[self.OUTPUT + "/" + name] = bad
        record["files"][name]["sha256"] = retrieval.sha256(bad)
        with self.assertRaisesRegex(RuntimeError, "do not reproduce"):
            evaluation.read_verified_results(record, expected, self.OUTPUT, results)


class FrozenBenchmarkTests(unittest.TestCase):
    def test_benchmark_bytes_and_compatibility_query_path_are_pinned(self):
        benchmark, labels = evaluation.load_benchmark()
        self.assertEqual(sum(map(len, labels.values())), 182)
        with self.assertRaisesRegex(ValueError, "submitted version"):
            evaluation.load_benchmark("0" * 64)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in [evaluation.CATALOG, retrieval.QUERIES, *benchmark["files"]]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(evaluation.ROOT / name, target)
            (root / evaluation.BASE / "retrieval_labels.csv").write_bytes(b"tampered")
            with patch.object(evaluation, "ROOT", root), self.assertRaisesRegex(ValueError, "checksum mismatch"):
                evaluation.load_benchmark(benchmark["catalog_sha256"])

    def test_original_c_command_reproduces_all_four_outputs_without_model_calls(self):
        # Compare bytes only; do not inspect held-out labels or scores during A integration.
        base = evaluation.ROOT / evaluation.BASE
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([sys.executable, str(base / "evaluate_retrieval_complete.py"),
                                     "--output-dir", tmp], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = list(Path(tmp).iterdir())
            self.assertEqual(len(outputs), 4)
            for output in outputs:
                self.assertEqual(output.read_bytes(), (base / "results" / output.name).read_bytes(), output.name)


if __name__ == "__main__":
    unittest.main()
