"""Verify the bytes consumed by training against expectations fixed before download."""

import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud import train


def pair_bytes(query="fixed query"):
    return (json.dumps({"query": query, "positive": "criterion", "negatives": ["other criterion"],
                        "trial_id": "NCT00000000", "split": "train"}) + "\n").encode()


class TrainingInputTests(unittest.TestCase):
    URI = "gs://test/training/pairs_llm.jsonl"

    def test_pipeline_inputs_require_one_valid_hash_per_unique_path(self):
        for extra in (
            ["--pairs", self.URI],
            ["--pairs-sha256", "a" * 64],
            ["--pairs", self.URI, "--pairs-sha256", "invalid"],
            ["--pairs", self.URI, "--pairs-sha256", "a" * 64, "b" * 64],
            ["--pairs", self.URI, self.URI, "--pairs-sha256", "a" * 64, "a" * 64],
        ):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                train.parse_args(["--validated-report", "gs://test/report", "--output", "gs://test/output", *extra])

    def test_legacy_standalone_inputs_remain_supported_without_claiming_verification(self):
        args = train.parse_args(["--pairs", "local.jsonl", "--output", "local-output"])
        self.assertEqual(args.pairs_sha256, [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.jsonl"
            path.write_bytes(pair_bytes())
            _, source = train.load_pair_source(path, str(path))
            self.assertIsNone(source["expected_sha256"])
            self.assertEqual(source["sha256"], hashlib.sha256(pair_bytes()).hexdigest())

    def test_verified_extra_pairs_and_generated_pairs_have_separate_provenance(self):
        content = pair_bytes()
        digest = hashlib.sha256(content).hexdigest()
        args = train.parse_args(["--pairs", self.URI, "--pairs-sha256", digest,
                                 "--validated-report", "gs://test/report", "--output", "gs://test/output"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            built = root / "built.jsonl"
            built.write_bytes(pair_bytes("generated from verified release"))
            remote = SimpleNamespace(download_to_filename=lambda p: Path(p).write_bytes(content))
            with (patch.object(train, "gcs_blob", return_value=remote),
                  patch.object(train, "pairs_from_release", return_value=(built, "gs://test/release.json"))):
                rows, sources = train.prepare_pairs(args, root)
            self.assertEqual(len(rows), 2)
            self.assertEqual(sources[0]["uri"], "built-from:gs://test/release.json")
            self.assertIsNone(sources[0]["expected_sha256"])
            self.assertEqual(sources[1]["uri"], self.URI)
            self.assertEqual(sources[1]["expected_sha256"], digest)
            self.assertEqual(sources[1]["sha256"], digest)
            self.assertEqual(args.source_release, "gs://test/release.json")

    def test_changed_gcs_bytes_stop_main_before_model_import_or_tracking(self):
        expected = hashlib.sha256(pair_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            remote = SimpleNamespace(download_to_filename=lambda p: Path(p).write_bytes(pair_bytes("changed query")))
            with (patch.object(train, "gcs_blob", return_value=remote),
                  patch.object(train.tempfile, "mkdtemp", return_value=str(root / "scratch")),
                  patch.object(train, "pairs_from_release") as build_pairs,
                  patch.object(train, "start_tracking") as tracking,
                  patch.dict(sys.modules, {"torch": None, "transformers": None}),
                  self.assertRaisesRegex(ValueError, "Training pairs checksum mismatch")):
                train.main(["--pairs", self.URI, "--pairs-sha256", expected,
                            "--validated-report", "gs://test/report", "--output", str(output)])
            build_pairs.assert_not_called()
            tracking.assert_not_called()
            self.assertFalse((output / "model").exists())
            self.assertFalse((output / "training_manifest.json").exists())

    def test_hash_verification_precedes_parsing_even_for_malformed_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairs.jsonl"
            path.write_bytes(b"not json")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                train.load_pair_source(path, self.URI, hashlib.sha256(pair_bytes()).hexdigest())

    def test_hashed_and_parsed_bytes_are_identical_if_local_file_changes_after_read(self):
        content = pair_bytes()
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pairs.jsonl"
            path.write_bytes(content)

            def read_then_replace(_):
                path.write_bytes(pair_bytes("changed after read"))
                return content

            with patch.object(Path, "read_bytes", autospec=True, side_effect=read_then_replace) as read:
                rows, source = train.load_pair_source(path, self.URI, digest)
            read.assert_called_once_with(path)
            self.assertEqual(rows[0]["query"], "fixed query")
            self.assertEqual(source["sha256"], digest)
            self.assertEqual(source["expected_sha256"], digest)

    def test_swapped_hashes_cannot_silently_bind_to_the_wrong_file(self):
        a, b = pair_bytes("a"), pair_bytes("b")
        args = train.parse_args(["--pairs", self.URI, "gs://test/second.jsonl", "--pairs-sha256",
                                 hashlib.sha256(b).hexdigest(), hashlib.sha256(a).hexdigest(),
                                 "--validated-report", "gs://test/report", "--output", "gs://test/output"])
        with tempfile.TemporaryDirectory() as directory:
            remote = SimpleNamespace(download_to_filename=lambda p: Path(p).write_bytes(a))
            with (patch.object(train, "gcs_blob", return_value=remote),
                  self.assertRaisesRegex(ValueError, "checksum mismatch")):
                train.prepare_pairs(args, Path(directory))

    def test_generated_pairs_alone_do_not_need_external_hash_arguments(self):
        args = train.parse_args(["--validated-report", "gs://test/report", "--output", "gs://test/output"])
        with tempfile.TemporaryDirectory() as directory:
            built = Path(directory) / "built.jsonl"
            built.write_bytes(pair_bytes())
            with (patch.object(train, "fetch") as fetch,
                  patch.object(train, "pairs_from_release", return_value=(built, "gs://test/release.json"))):
                rows, sources = train.prepare_pairs(args, Path(directory))
            fetch.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["uri"], "built-from:gs://test/release.json")


if __name__ == "__main__":
    unittest.main()
