"""Local failure injection, plus synthetic vectors for snapshot compatibility checks."""

import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cloud import tasks
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_versions import records_hash
from services.rag_workflow.providers import ProviderError


class ReleaseFailureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.enterContext(patch.object(tasks, "ROOT", Path(directory.name)))
        self.blob = self.enterContext(patch.object(tasks, "blob"))
        self.real_command = tasks.command
        self.command = self.enterContext(patch.object(tasks, "command"))
        self.report = self.enterContext(patch.object(tasks, "write_json"))
        self.manifest = {
            "schema_version": 1,
            "image": "test:fixed",
            "files": {
                name: {
                    "uri": f"gs://test-release/{name}",
                    "sha256": hashlib.sha256(b"ok").hexdigest(),
                }
                for name in tasks.FILES
            },
        }
        self.blob.return_value.download_as_text.side_effect = lambda: json.dumps(self.manifest)

    def test_missing_remote_file_stops_before_dvc(self):
        self.blob.return_value.download_to_filename.side_effect = FileNotFoundError("missing")
        with self.assertRaises(FileNotFoundError):
            tasks.fetch("gs://test/release.json", "gs://test/output")
        self.command.assert_not_called()
        self.report.assert_not_called()

    def test_hash_mismatch_stops_before_dvc(self):
        self.blob.return_value.download_to_filename.side_effect = lambda p: p.write_bytes(b"bad")
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            tasks.fetch("gs://test/release.json", "gs://test/output")
        self.command.assert_not_called()
        self.report.assert_not_called()

    def test_invalid_manifest_schema_stops_before_download(self):
        self.manifest["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "Unexpected release files"):
            tasks.fetch("gs://test/release.json", "gs://test/output")
        self.blob.return_value.download_to_filename.assert_not_called()
        self.command.assert_not_called()

    def test_validation_subprocess_failure_does_not_write_success(self):
        self.command.side_effect = subprocess.CalledProcessError(1, "prepare_data.py")
        with (
            patch.object(tasks, "download_release"),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            tasks.validate("gs://test/processed", "gs://test/report")
        self.report.assert_not_called()

    def test_wrong_raw_file_count_stops_before_publishing(self):
        module = tasks.ROOT / "services/trial_ingestion"
        raw = module / "data/raw"
        raw.mkdir(parents=True)
        (raw / "one.json").write_text("{}")
        (module / "data/raw_metadata.json").write_text('{"raw_file_count":2}')
        with (
            patch.object(tasks, "download_release"),
            self.assertRaisesRegex(ValueError, "Unexpected raw snapshot size"),
        ):
            tasks.fetch("gs://test/release.json", "gs://test/output")
        self.blob.assert_not_called()
        self.report.assert_not_called()

    def test_corrupt_raw_archive_stops_before_rebuild(self):
        self.blob.return_value.download_as_text.side_effect = None
        self.blob.return_value.download_as_text.return_value = json.dumps(
            {
                "release_uri": "gs://test/release.json",
                "archive_sha256": "0" * 64,
            }
        )
        self.blob.return_value.download_to_filename.side_effect = lambda p: p.write_bytes(b"bad")
        with (
            patch.object(tasks, "download_release"),
            patch.object(tasks, "publish") as publish,
            self.assertRaisesRegex(ValueError, "Raw archive checksum mismatch"),
        ):
            tasks.process("gs://test/raw", "gs://test/processed")
        self.command.assert_not_called()
        publish.assert_not_called()

    def test_command_propagates_nonzero_exit(self):
        # Exercise the real subprocess wrapper in a disposable directory.
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            self.real_command(sys.executable, "-c", "raise SystemExit(7)")
        self.assertEqual(caught.exception.returncode, 7)


class SnapshotValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.settings = Settings(mode="offline", chroma_host="", artifacts=Path(cls.directory.name))
        cls.data = DataStore(cls.settings)
        index = VectorIndex(cls.settings, cls.data, cls.data.manifest())
        # These constant vectors are test fixtures, never real Gemini embeddings or MS3 evidence.
        records = [
            {
                "id": key,
                "document": text,
                "metadata": meta,
                "embedding": [0.1] * cls.settings.dimension,
            }
            for key, text, meta in index.fragments()
        ]
        cls.snapshot = {
            "schema_version": 1,
            "identity": index.identity,
            "collection": index.name,
            "distance": "cosine",
            "chroma_version": "1.5.9",
            "vector_count": len(records),
            "records_sha256": records_hash(records),
            "records": records,
        }

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.enterContext(patch.object(tasks, "ROOT", root))
        self.path = root / tasks.FILES[-1]
        self.path.parent.mkdir(parents=True)
        self.value = copy.deepcopy(self.snapshot)
        self.enterContext(patch.object(tasks, "download_release"))
        self.enterContext(patch.object(tasks, "command"))
        self.report = self.enterContext(patch.object(tasks, "write_json"))
        self.settings_factory = self.enterContext(
            patch("services.rag_workflow.config.Settings", return_value=self.settings)
        )
        self.enterContext(
            patch.object(tasks.storage, "Client", side_effect=AssertionError("cloud call"))
        )
        self.enterContext(
            patch(
                "services.rag_workflow.workflow.GeminiProvider",
                side_effect=AssertionError("model call"),
            )
        )
        self.enterContext(redirect_stdout(io.StringIO()))

    def validate(self):
        self.path.write_text(json.dumps(self.value))
        tasks.validate("gs://test/processed", "gs://test/report")

    def test_matching_snapshot_and_offline_screening_pass(self):
        self.validate()
        report = self.report.call_args_list[0].args[1]
        self.assertEqual(report["status"], "PASSED")
        self.assertEqual(report["vectors"], 607)
        self.assertEqual(report["source_sha256"], self.data.hashes)

    def test_foreign_source_snapshot_is_rejected_even_with_valid_internal_checksum(self):
        self.value["identity"]["trials_sha256"] = "0" * 64
        with self.assertRaises(ProviderError):
            self.validate()
        self.report.assert_not_called()

    def test_wrong_vector_dimension_is_rejected_even_with_valid_checksum(self):
        self.value["records"][0]["embedding"] = [0.1]
        self.value["records_sha256"] = records_hash(self.value["records"])
        with self.assertRaises(ProviderError):
            self.validate()
        self.report.assert_not_called()

    def test_corrupt_snapshot_checksum_is_rejected(self):
        self.value["records"][0]["embedding"][0] = 0.9
        with self.assertRaises(ProviderError):
            self.validate()
        self.report.assert_not_called()

    def test_invalid_patient_schema_stops_before_success_report(self):
        patient = copy.deepcopy(next(iter(self.data.patients.values())))
        patient["schema_version"] = "invalid"
        patients = self.path.parent / "patients.jsonl"
        patients.write_text(json.dumps(patient) + "\n")
        self.settings_factory.return_value = replace(self.settings, patients_path=patients)
        with self.assertRaisesRegex(ValueError, "schema_version 0.3"):
            self.validate()
        self.report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
