"""Real release/checkpoint validation with simulated cloud and ranking execution."""

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cloud import finetuned_retrieval as retrieval
from cloud import release, tasks
from cloud.tests import retrieval_fixtures as fixtures
from services.rag_workflow.providers import ProviderError


class MemoryBlob:
    def __init__(self, objects, uri):
        self.objects, self.uri = objects, uri
        self.name = uri.split("/", 3)[-1]

    def download_as_bytes(self):
        return self.objects[self.uri]

    def download_as_text(self):
        return self.download_as_bytes().decode()

    def download_to_filename(self, path):
        Path(path).write_bytes(self.download_as_bytes())

    def upload_from_string(self, value, **kwargs):
        self.objects[self.uri] = value.encode() if isinstance(value, str) else value


class RetrievalTaskTests(unittest.TestCase):
    IMAGE = "example/retrieval@sha256:" + "a" * 64
    TRAINER = "example/trainer@sha256:" + "d" * 64
    SOURCE = "gs://run/report"
    TRAINING = "gs://run/training"
    OUTPUT = "gs://run/rankings"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(patch.object(retrieval, "ROOT", self.root))
        self.enterContext(patch.object(tasks, "ROOT", self.root))
        self.objects = {}
        self.lookup = lambda uri: MemoryBlob(self.objects, uri)
        self.enterContext(patch.object(retrieval, "blob", side_effect=self.lookup))
        self.enterContext(patch.object(tasks, "blob", side_effect=self.lookup))
        query_path = self.root / retrieval.QUERIES
        query_path.parent.mkdir(parents=True)
        query_path.write_text("".join(json.dumps({"query_id": q, "question": "synthetic query",
                                                "patient_id": "synthetic-patient"}) + "\n"
                                      for q in fixtures.contract()["query_ids"]))
        self.release_uri = "gs://run/processed/release.json"
        data_release = {"schema_version": 1, "files": {}}
        for name in release.FILES:
            uri = "gs://run/processed/" + name
            content = (json.dumps({"trial_ids": fixtures.contract()["trial_ids"]}).encode()
                       if name == retrieval.BENCHMARK else b"synthetic file bytes")
            self.objects[uri] = content
            data_release["files"][name] = {"uri": uri, "sha256": retrieval.sha256(content)}
        self.objects[self.release_uri] = json.dumps(data_release).encode()
        self.hashes = dict.fromkeys(("trials", "criteria", "patients"), "e" * 64)
        self.report = {"status": "PASSED", "release_uri": self.release_uri, "source_sha256": self.hashes}
        self.objects[self.SOURCE + "/validation.json"] = json.dumps(self.report).encode()
        model_files = {"config.json": b"{}", "model.safetensors": b"synthetic weights"}
        for name, content in model_files.items():
            self.objects[f"{self.TRAINING}/model/{name}"] = content
        digests = {name: retrieval.sha256(content) for name, content in model_files.items()}
        self.training = {
            "schema_version": 1, "workflow_type": "contrastive-encoder-finetune",
            "source_release_uri": self.release_uri, "image_uri": self.TRAINER,
            "artifact_uri": self.TRAINING + "/model", "artifact_files": digests,
            "artifact_sha256": retrieval.sha256(json.dumps(digests, sort_keys=True).encode()),
            "config": {"batch_size": 8}, "pair_files": [{"uri": "built-from:" + self.release_uri}],
            "code_commit": "f" * 40, "experiment": {"url": "test-only-run"},
        }
        self.enterContext(patch("services.rag_workflow.data.DataStore",
                                return_value=SimpleNamespace(hashes=self.hashes)))
        self.storage = self.enterContext(patch("google.cloud.storage.Client"))
        self.storage.return_value.list_blobs.side_effect = lambda bucket, prefix: [
            self.lookup(uri) for uri in self.objects if uri.startswith(f"gs://{bucket}/{prefix}")
        ]
        self.runner = self.enterContext(patch.object(retrieval.subprocess, "run", side_effect=self.rank))

    def expected(self):
        return retrieval.expected_manifest(self.SOURCE + "/validation.json", self.report, self.TRAINING,
            json.dumps(self.training).encode(), self.IMAGE, retrieval.benchmark_contract(self.release_uri))

    def rank(self, argv, **kwargs):
        work = Path(argv[argv.index("--output") + 1]).parent
        for name, content in fixtures.payloads(self.expected()).items():
            (work / name).write_bytes(content)

    def run_task(self):
        self.objects[self.TRAINING + "/training_manifest.json"] = json.dumps(self.training).encode()
        return retrieval.run(self.SOURCE, self.TRAINING, self.OUTPUT, self.IMAGE, self.TRAINER)

    def test_success_verifies_checkpoint_and_publishes_bound_rankings(self):
        record = self.run_task()
        retrieval.read_verified_results(record, self.expected(), self.OUTPUT)
        argv = self.runner.call_args.args[0]
        self.assertEqual(argv[argv.index("--encoders") + 1], "--finetuned-manifest")
        self.assertIn("--finetuned-checkpoint", argv)
        env = self.runner.call_args.kwargs["env"]
        self.assertEqual(env["EMBEDDING_DEVICE"], "cpu")
        self.assertEqual(env["HF_HUB_OFFLINE"], "1")
        self.assertIn("/indices", env["MS3_STORES"])
        self.assertIn(self.OUTPUT + "/" + retrieval.MANIFEST, self.objects)

    def test_old_manifest_or_unexpected_pairs_fail_before_ranking(self):
        for key, bad in (("source_release_uri", "gs://old/release.json"),
                         ("image_uri", "example/old"), ("artifact_uri", "gs://old/model"),
                         ("pair_files", []), ("artifact_sha256", "0" * 64)):
            with self.subTest(key=key):
                original = self.training[key]
                self.training[key] = bad
                with self.assertRaises(RuntimeError):
                    self.run_task()
                self.training[key] = original
        self.runner.assert_not_called()
        self.storage.assert_not_called()

    def test_corrupted_data_fails_before_loading_checkpoint(self):
        self.objects["gs://run/processed/" + release.FILES[0]] += b"modified"
        with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
            self.run_task()
        self.storage.assert_not_called()
        self.runner.assert_not_called()

    def test_corrupted_checkpoint_fails_before_ranking(self):
        self.objects[self.TRAINING + "/model/model.safetensors"] += b"modified"
        with self.assertRaises(ProviderError) as error:
            self.run_task()
        self.assertEqual(error.exception.code, "EMBEDDING_CHECKPOINT_MISMATCH")
        self.runner.assert_not_called()
        self.assertNotIn(self.OUTPUT + "/" + retrieval.MANIFEST, self.objects)

    def test_ranking_failure_cannot_publish_success(self):
        self.runner.side_effect = subprocess.CalledProcessError(1, "simulated-ranking-command")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_task()
        self.assertFalse(any(uri.startswith(self.OUTPUT) for uri in self.objects))

    def test_missing_output_cannot_publish_success(self):
        self.runner.side_effect = lambda *a, **k: None
        with self.assertRaises(FileNotFoundError):
            self.run_task()
        self.assertFalse(any(uri.startswith(self.OUTPUT) for uri in self.objects))

    def test_failed_upload_cannot_publish_success_manifest(self):
        with (patch.object(MemoryBlob, "upload_from_string", side_effect=OSError("Upload failed")),
              self.assertRaises(OSError)):
            self.run_task()
        self.assertNotIn(self.OUTPUT + "/" + retrieval.MANIFEST, self.objects)

    def test_result_hash_tampering_is_rejected(self):
        record = self.run_task()
        self.objects[self.OUTPUT + "/" + retrieval.FILES[0]] += b"modified"
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            retrieval.read_verified_results(record, self.expected(), self.OUTPUT)

    def test_rankings_reject_wrong_model_missing_queries_and_foreign_trials(self):
        expected = self.expected()
        for case in ("model", "missing", "duplicate", "foreign"):
            with self.subTest(case=case):
                results = fixtures.payloads(expected)
                if case == "model":
                    config = json.loads(results[retrieval.FILES[1]])
                    config["methods"]["finetuned_dense_question"]["checkpoint_sha256"] = "0" * 64
                    results[retrieval.FILES[1]] = json.dumps(config).encode()
                else:
                    rows = [json.loads(line) for line in results[retrieval.FILES[0]].splitlines()]
                    if case == "missing":
                        rows.pop()
                    elif case == "duplicate":
                        rows[-1] = rows[0]
                    else:
                        rows[0]["ranked_trial_ids"] = ["NCT-foreign"]
                    results[retrieval.FILES[0]] = "".join(json.dumps(r) + "\n" for r in rows).encode()
                with self.assertRaises(RuntimeError):
                    retrieval.verify_results(results, expected)

    def test_real_jenny_entry_accepts_current_manifest_without_frozen_snapshot(self):
        from evaluation.ms3 import run_retrieval as entry

        store = SimpleNamespace(hashes=self.hashes, manifest=lambda: {"trial_ids": fixtures.contract()["trial_ids"]},
                                patient=lambda patient_id: {})
        settings = SimpleNamespace(embedding_model="test-model", embedding_revision="f" * 40, dimension=768)
        index = SimpleNamespace(name="test-new-checkpoint-collection", provider=object())
        lexical = SimpleNamespace(rank=lambda query: [(key, 1) for key in fixtures.contract()["trial_ids"]])

        def real_entry(argv, **kwargs):
            with patch("sys.argv", ["retrieval", *argv[3:]]), patch.dict("os.environ", {"SOURCE_COMMIT": "f" * 40}):
                entry.main()

        self.runner.side_effect = real_entry
        with (patch.object(entry, "ROOT", self.root), patch.object(entry, "DataStore", return_value=store),
              patch.object(entry, "Retriever", return_value=SimpleNamespace(lexical=lexical)),
              patch.object(entry, "patient_query", return_value="synthetic patient query"),
              patch.object(entry, "build_finetuned_index", return_value=(settings, index)) as tuned,
              patch.object(entry, "dense_trials", return_value=fixtures.contract()["trial_ids"]),
              patch.object(entry, "build_index") as frozen):
            record = self.run_task()
        frozen.assert_not_called()
        self.assertEqual(tuned.call_args.args[3], self.training["artifact_sha256"])
        retrieval.read_verified_results(record, self.expected(), self.OUTPUT)


if __name__ == "__main__":
    unittest.main()
