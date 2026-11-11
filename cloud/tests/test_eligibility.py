"""Real eligibility judgments/scoring with simulated Gemini and cloud storage."""

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cloud import eligibility
from cloud.tests.eligibility_fixtures import HASHES, valid_payloads
from evaluation.ms3.eligibility import run_eligibility as evaluator
from services.rag_workflow.providers import ProviderError


class FakeProvider:
    def __init__(self):
        self.metrics = {"generation_requests": 0}
        self.fail = False
        self.closed = False

    def generate(self, prompt, payload, schema):
        self.metrics["generation_requests"] += 1
        if self.fail:
            raise ProviderError("GCP_429", "Simulated quota failure")
        return schema.model_validate({"assessments": [{
            "criterion_id": item["criterion"]["criterion_id"], "decision": "UNKNOWN",
            "reason": "Synthetic test response", "evidence_fact_ids": [],
            "missing_information": ["Test-only missing evidence"],
        } for item in payload["items"]]})

    def close(self):
        self.closed = True


class MemoryBlob:
    def __init__(self, objects, uri):
        self.objects, self.uri = objects, uri

    def download_as_text(self):
        return self.objects[self.uri].decode()

    def download_as_bytes(self):
        return self.objects[self.uri]

    def upload_from_string(self, value, **kwargs):
        self.objects[self.uri] = value.encode() if isinstance(value, str) else value


class EligibilityTaskTests(unittest.TestCase):
    IMAGE = "example/workflow@sha256:" + "e" * 64
    SOURCE = "gs://test-run/report"
    OUTPUT = "gs://test-run/evaluation"

    def setUp(self):
        root = eligibility.ROOT / "artifacts"
        root.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix="eligibility-test-", dir=root)
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(eligibility, "ROOT", Path(directory.name)))
        self.enterContext(redirect_stdout(io.StringIO()))
        self.report = {
            "status": "PASSED", "release_uri": "gs://test-run/processed/release.json",
            "source_sha256": json.loads((evaluator.BASE / "cohort_manifest.json").read_text())["source_sha256"],
        }
        self.objects = {}
        self.enterContext(patch.object(eligibility, "blob", side_effect=lambda uri: MemoryBlob(self.objects, uri)))
        self.enterContext(patch.object(eligibility, "write_json", side_effect=lambda uri, value:
                                      self.objects.update({uri: json.dumps(value).encode()})))
        self.download = self.enterContext(patch.object(eligibility, "download_release"))
        self.provider = FakeProvider()
        self.make_provider = self.enterContext(patch.object(evaluator, "make_provider", return_value=self.provider))

    def run_task(self):
        self.objects[self.SOURCE + "/validation.json"] = json.dumps(self.report).encode()
        return eligibility.run(self.SOURCE, self.OUTPUT, self.IMAGE)

    def manifest(self):
        return json.loads(self.objects[self.OUTPUT + "/eligibility_manifest.json"])

    def test_real_evaluator_publishes_complete_bound_outputs_without_touching_baseline(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in evaluator.RESULTS.glob("all_developer_baseline_*")}
        original_results = evaluator.RESULTS
        manifest = self.run_task()
        self.download.assert_called_once_with(self.report["release_uri"])
        self.assertEqual(self.make_provider.call_args.args[0], "vertex")
        self.assertGreater(self.provider.metrics["generation_requests"], 0)
        self.assertTrue(self.provider.closed)
        self.assertEqual(evaluator.RESULTS, original_results)
        eligibility.verify_manifest(manifest, self.report["release_uri"], self.SOURCE + "/validation.json",
                                    self.OUTPUT, self.IMAGE, eligibility.DEFAULT_MODEL, self.report["source_sha256"])
        payloads = eligibility.read_verified_results(manifest)
        self.assertEqual(set(payloads), set(eligibility.RESULT_FILES))
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})

    def test_real_evaluator_model_errors_fail_task_but_preserve_diagnostics(self):
        self.provider.fail = True
        with self.assertRaisesRegex(RuntimeError, "inference failed"):
            self.run_task()
        manifest = self.manifest()
        self.assertEqual(manifest["status"], "FAILED")
        self.assertEqual(set(manifest["files"]), set(eligibility.RESULT_FILES))
        metrics = json.loads(self.objects[self.OUTPUT + "/" + eligibility.RESULT_FILES[2]])
        self.assertFalse(metrics["official_reporting_ready"])
        self.assertGreater(metrics["inference_failures"]["count"], 0)

    def test_failed_or_foreign_data_stops_before_model_calls(self):
        for change in ({"status": "FAILED"}, {"source_sha256": HASHES}):
            with self.subTest(change=change):
                original = dict(self.report)
                self.report.update(change)
                with self.assertRaises(ValueError):
                    self.run_task()
                self.assertEqual(self.manifest()["status"], "FAILED")
                self.assertEqual(self.manifest()["files"], {})
                self.report = original
        self.download.assert_not_called()
        self.make_provider.assert_not_called()

    def test_release_checksum_failure_stops_before_model_calls(self):
        self.download.side_effect = ValueError("Checksum mismatch")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.run_task()
        self.make_provider.assert_not_called()
        self.assertEqual(self.manifest()["status"], "FAILED")

    def test_missing_result_cannot_be_published_as_success(self):
        with patch.object(evaluator, "evaluate_predictions", return_value={}), self.assertRaises(FileNotFoundError):
            self.run_task()
        self.assertEqual(self.manifest()["status"], "FAILED")
        self.assertIn(eligibility.RESULT_FILES[0], self.manifest()["files"])
        self.assertNotIn(eligibility.RESULT_FILES[2], self.manifest()["files"])

    def test_upload_failure_cannot_publish_success_manifest(self):
        with (patch.object(MemoryBlob, "upload_from_string", side_effect=RuntimeError("Upload failed")),
              self.assertRaisesRegex(RuntimeError, "Upload failed")):
            self.run_task()
        self.assertNotIn(self.OUTPUT + "/eligibility_manifest.json", self.objects)


class EligibilityOutputTests(unittest.TestCase):
    def test_unready_offline_incomplete_and_foreign_outputs_are_rejected(self):
        for target, field, value in (
            (2, "official_reporting_ready", False), (2, "provider", "offline"),
            (2, "inference_failures", {"count": 1}), (1, "prediction_errors", 1),
            (1, "prediction_count", 114), (1, "case_ids", ["E01"]),
            (1, "source_sha256", {}), (1, "predictions_sha256", "0" * 64),
            (2, "model", "another-model"),
        ):
            with self.subTest(field=field):
                payloads = valid_payloads()
                name = eligibility.RESULT_FILES[target]
                item = json.loads(payloads[name])
                item[field] = value
                payloads[name] = json.dumps(item).encode()
                with self.assertRaises(RuntimeError):
                    eligibility.verify_results(payloads, HASHES, eligibility.DEFAULT_MODEL)


if __name__ == "__main__":
    unittest.main()
