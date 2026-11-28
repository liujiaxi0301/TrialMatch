"""Encoder switch/rollback on embedded Chroma: fake encoders and local checkpoints only.

No model download, GCS or Gemini access: catalog entries point at temporary local
checkpoint directories and every vector comes from a deterministic fake encoder.
"""

import copy
import io
import json
import random
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from services.rag_workflow import encoders
from services.rag_workflow.cli import main
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.embedding_providers import checkpoint_digest
from services.rag_workflow.encoders import (
    EncoderVersion,
    apply_encoder,
    load_selection,
    selection_path,
)
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_switching import rollback_encoder, switch_encoder
from services.rag_workflow.index_versions import read_records
from services.rag_workflow.providers import ProviderError, content_hash, save_json

# MS3 values of Settings.for_retrieval("finetuned"), copied verbatim from milestone3.
MS3_FINETUNED = {
    "embedding_provider": "bioclinical",
    "embedding_model": "thomas-sounack/BioClinical-ModernBERT-base",
    "dimension": 768,
    "embedding_revision": "c3648aa87af95837c809e6f0c5f85d08160db437",
    "embedding_checkpoint": "gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model",
    "embedding_checkpoint_sha256": "7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c",
    "embedding_max_tokens": 2048,
    "embedding_device": "cpu",
}


class FakeEncoder:
    """Deterministic 768-dimensional vectors that differ per encoder; counts every call."""

    def __init__(self, seed, fail_after=None):
        self.seed, self.fail_after, self.calls = seed, fail_after, 0
        self._lock = threading.Lock()

    def vector(self, text):
        rng = random.Random(content_hash([self.seed, text]))
        return [rng.uniform(-1, 1) for _ in range(768)]

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        with self._lock:
            self.calls += 1
            if self.fail_after is not None and self.calls > self.fail_after:
                raise ProviderError("TEST_ENCODER_FAILURE", "Simulated failure mid-build.")
        return self.vector(text)


class SwitchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = DataStore(Settings(mode="offline"))
        cls.manifest = copy.deepcopy(cls.store.manifest())
        cls.manifest["trial_ids"] = cls.manifest["trial_ids"][:2]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(mode="offline", artifacts=self.root / "artifacts", chroma_host="")
        self.catalog = {
            name: self.entry(name, evaluated)
            for name, evaluated in (("enc-a", True), ("enc-b", False), ("enc-c", True))
        }
        for target, value in (
            ("ENCODERS", MappingProxyType(self.catalog)),
            ("DEFAULT_FINETUNED", "enc-a"),
        ):
            patcher = patch.object(encoders, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.encoders = {name: FakeEncoder(name) for name in self.catalog}
        # The default encoder is already serving, as after make live.
        self.default = self.index("enc-a", self.encoders["enc-a"])
        with redirect_stderr(io.StringIO()):
            self.default.build()

    def entry(self, name, evaluated):
        directory = self.root / "checkpoints" / name
        directory.mkdir(parents=True)
        (directory / "model.safetensors").write_bytes(name.encode())
        digest, _ = checkpoint_digest(directory)
        return EncoderVersion(
            name=name,
            checkpoint=str(directory),
            checkpoint_sha256=digest,
            base_model="test-encoder",
            revision="a" * 40,
            dimension=768,
            max_tokens=2048,
            evaluated=evaluated,
            note="test",
        )

    def index(self, name, provider=None, settings=None):
        return VectorIndex(
            apply_encoder(settings or self.settings, self.catalog[name]),
            self.store,
            self.manifest,
            provider,
        )

    def switch(self, target, provider=None, **kwargs):
        provider = provider or self.encoders[target]
        with redirect_stderr(io.StringIO()):
            return switch_encoder(
                self.settings,
                self.store,
                self.manifest,
                target,
                provider_factory=lambda settings: provider,
                **kwargs,
            )

    def record_bytes(self):
        path = selection_path(self.settings)
        return path.read_bytes() if path.exists() else None

    def assert_code(self, code, action):
        with self.assertRaises(ProviderError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def assert_serving(self, name):
        self.assertEqual(
            self.settings.for_retrieval("finetuned").embedding_checkpoint_sha256,
            self.catalog[name].checkpoint_sha256,
        )
        index = self.index(name, self.encoders[name])
        self.assertEqual(index.status()["status"], "VERIFIED")
        self.assertTrue(index.query("Type 2 diabetes"))

    # T1
    def test_encoder_versions_use_separate_collections_and_never_mix_vectors(self):
        self.switch("enc-c")
        a, c = self.index("enc-a"), self.index("enc-c")
        self.assertNotEqual(a.name, c.name)
        self.assertEqual({col.name for col in a.client.list_collections()}, {a.name, c.name})
        records_a, records_c = read_records(a._collection()), read_records(c._collection())
        self.assertEqual([r["id"] for r in records_a], [r["id"] for r in records_c])
        for row_a, row_c in zip(records_a, records_c, strict=True):
            expected_a = self.encoders["enc-a"].vector(row_a["document"])
            expected_c = self.encoders["enc-c"].vector(row_c["document"])
            self.assertTrue(all(abs(x - y) < 1e-6 for x, y in zip(row_a["embedding"], expected_a)))
            self.assertTrue(all(abs(x - y) < 1e-6 for x, y in zip(row_c["embedding"], expected_c)))
            self.assertFalse(all(abs(x - y) < 1e-6 for x, y in zip(row_a["embedding"], expected_c)))
        # A query vector from encoder C finds its own document at distance ~0 only in C.
        probe = records_c[0]
        nearest_in_a = a._collection().query(
            query_embeddings=[probe["embedding"]], n_results=1, include=["distances"]
        )
        nearest_in_c = c._collection().query(
            query_embeddings=[probe["embedding"]], n_results=1, include=["distances"]
        )
        self.assertLess(nearest_in_c["distances"][0][0], 1e-3)
        self.assertGreater(nearest_in_a["distances"][0][0], 0.1)

    # T2
    def test_unknown_encoder_or_checkpoint_digest_mismatch_is_rejected_before_activation(self):
        self.assert_code("ENCODER_UNKNOWN", lambda: self.switch("enc-unknown", FakeEncoder("x")))
        save_json(
            selection_path(self.settings),
            {
                "schema_version": 1,
                "retrieval_model": "finetuned",
                "active": "retired-encoder",
                "previous": None,
                "index_version": "0" * 20,
                "previous_index_version": None,
                "activated_at": "2026-11-28T00:00:00+00:00",
                "history": [],
            },
        )
        self.assert_code(
            "ENCODER_SELECTION_INVALID", lambda: self.settings.for_retrieval("finetuned")
        )
        selection_path(self.settings).unlink()
        (Path(self.catalog["enc-c"].checkpoint) / "model.safetensors").write_bytes(b"tampered")
        self.assert_code("EMBEDDING_CHECKPOINT_MISMATCH", lambda: self.switch("enc-c"))
        self.assertIsNone(self.record_bytes())
        self.assertEqual(self.encoders["enc-c"].calls, 0)
        self.assertEqual(len(self.default.client.list_collections()), 1)
        self.assert_serving("enc-a")

    # T3
    def test_failed_candidate_build_leaves_selection_and_live_index_untouched(self):
        self.switch("enc-c")
        before = self.record_bytes()
        failing = FakeEncoder("enc-b", fail_after=16)  # Fails during the third batch of 8.
        self.assert_code(
            "TEST_ENCODER_FAILURE",
            lambda: self.switch("enc-b", failing, allow_unevaluated=True),
        )
        self.assertEqual(self.record_bytes(), before)
        candidate = self.index("enc-b")
        self.assertFalse(candidate.manifest_path.exists())
        partial = candidate.client.get_collection(candidate.name).count()
        self.assertEqual(partial, 16)  # Two batches written before the failure.
        self.assertLess(partial, len(candidate.fragments()))
        self.assert_serving("enc-c")
        # The partial candidate collection resumes; it is never served before verification.
        result = self.switch("enc-b", allow_unevaluated=True)
        self.assertEqual(result["status"], "SWITCHED")
        self.assert_serving("enc-b")

    # T4
    def test_successful_switch_records_active_previous_and_history(self):
        result = self.switch("enc-c")
        self.assertEqual(result["status"], "SWITCHED")
        self.assertEqual(result["smoke"]["encoder_query_probe"], "PASS")
        record = load_selection(self.settings)
        self.assertEqual((record["active"], record["previous"]), ("enc-c", "enc-a"))
        self.assertEqual(record["index_version"], self.index("enc-c").version)
        self.assertEqual(record["previous_index_version"], self.default.version)
        self.assertEqual([h["action"] for h in record["history"]], ["switch"])
        self.assert_serving("enc-c")
        self.assertEqual(self.switch("enc-c")["status"], "ALREADY_ACTIVE")
        self.assertEqual(len(load_selection(self.settings)["history"]), 1)

    # T5
    def test_rollback_restores_previous_version_without_encoding(self):
        self.switch("enc-c")
        calls = {name: encoder.calls for name, encoder in self.encoders.items()}
        with (
            patch(
                "services.rag_workflow.index_switching.create_embedding_provider",
                side_effect=AssertionError("Rollback must not create an encoder"),
            ),
            patch(
                "services.rag_workflow.embedding_providers.BioClinicalProvider",
                side_effect=AssertionError("Rollback must not load a model"),
            ),
        ):
            result = rollback_encoder(self.settings, self.store, self.manifest)
        self.assertEqual(result["status"], "ROLLED_BACK")
        self.assertEqual({n: e.calls for n, e in self.encoders.items()}, calls)
        record = load_selection(self.settings)
        self.assertEqual((record["active"], record["previous"]), ("enc-a", "enc-c"))
        self.assertEqual([h["action"] for h in record["history"]], ["switch", "rollback"])
        self.assert_serving("enc-a")
        # Rolling back again returns to enc-c: the two versions alternate.
        rollback_encoder(self.settings, self.store, self.manifest)
        self.assert_serving("enc-c")

    # T6
    def test_rollback_refuses_damaged_or_missing_previous_index(self):
        self.assert_code(
            "ENCODER_ROLLBACK_UNAVAILABLE",
            lambda: rollback_encoder(self.settings, self.store, self.manifest),
        )
        self.switch("enc-c")
        before = self.record_bytes()
        collection = self.default._collection()
        row = read_records(collection)[0]
        collection.update(ids=[row["id"]], embeddings=[[0.5] * 768])
        error = self.assert_code(
            "ROLLBACK_TARGET_NOT_READY",
            lambda: rollback_encoder(self.settings, self.store, self.manifest),
        )
        self.assertIn("INDEX_CONTENT_MISMATCH", str(error))
        self.default.manifest_path.unlink()
        error = self.assert_code(
            "ROLLBACK_TARGET_NOT_READY",
            lambda: rollback_encoder(self.settings, self.store, self.manifest),
        )
        self.assertIn("INDEX_NOT_READY", str(error))
        self.assertEqual(self.record_bytes(), before)
        self.assert_serving("enc-c")

    # T7
    def test_interrupted_record_write_keeps_the_previous_record(self):
        self.switch("enc-c")
        before = self.record_bytes()
        with patch("services.rag_workflow.encoders.os.replace", side_effect=OSError("disk full")):
            self.assert_code(
                "ENCODER_SELECTION_WRITE_FAILED",
                lambda: rollback_encoder(self.settings, self.store, self.manifest),
            )
        self.assertEqual(self.record_bytes(), before)
        self.assertEqual(load_selection(self.settings)["active"], "enc-c")
        self.assertEqual(list(selection_path(self.settings).parent.glob("*.tmp")), [])
        self.assert_serving("enc-c")

    # T8
    def test_damaged_record_is_an_error_not_a_silent_default(self):
        self.switch("enc-c")
        valid = json.loads(self.record_bytes())
        for label, content in (
            ("truncated", self.record_bytes()[:40]),
            ("invalid UTF-8", b"\xff"),
            ("not an object", b"[]"),
            ("active type", json.dumps({**valid, "active": []}).encode()),
            ("previous type", json.dumps({**valid, "previous": {}}).encode()),
            ("schema", json.dumps({**valid, "schema_version": 2}).encode()),
            ("same previous", json.dumps({**valid, "previous": "enc-c"}).encode()),
            ("bad version", json.dumps({**valid, "index_version": "../x"}).encode()),
            ("no history", json.dumps({**valid, "history": None}).encode()),
        ):
            with self.subTest(label):
                selection_path(self.settings).write_bytes(content)
                self.assert_code(
                    "ENCODER_SELECTION_INVALID", lambda: self.settings.for_retrieval("finetuned")
                )
                self.assert_code("ENCODER_SELECTION_INVALID", lambda: self.switch("enc-a"))
                self.assertEqual(selection_path(self.settings).read_bytes(), content)
        # Gemini and the unselected path never read the record.
        self.assertIs(self.settings.for_retrieval(None), self.settings)
        self.assertEqual(self.settings.for_retrieval("gemini").embedding_provider, "gemini")

    # T10
    def test_unevaluated_encoder_needs_explicit_opt_in_for_switch_and_rollback(self):
        error = self.assert_code("ENCODER_NOT_EVALUATED", lambda: self.switch("enc-b"))
        self.assertIn("--allow-unevaluated", str(error))
        self.assertIsNone(self.record_bytes())
        self.assertEqual(self.encoders["enc-b"].calls, 0)
        self.assertEqual(len(self.default.client.list_collections()), 1)
        self.switch("enc-b", allow_unevaluated=True)
        self.switch("enc-c")  # previous is now the unevaluated enc-b.
        self.assert_code(
            "ENCODER_NOT_EVALUATED",
            lambda: rollback_encoder(self.settings, self.store, self.manifest),
        )
        self.assertEqual(load_selection(self.settings)["active"], "enc-c")
        rollback_encoder(self.settings, self.store, self.manifest, allow_unevaluated=True)
        self.assert_serving("enc-b")

    def test_switch_can_restore_candidate_from_snapshot_without_encoding(self):
        source = replace(self.settings, artifacts=self.root / "elsewhere")
        built = self.index("enc-c", FakeEncoder("enc-c"), settings=source)
        with redirect_stderr(io.StringIO()):
            built.build()
        snapshot = self.root / "enc-c.json"
        built.export(snapshot)
        unused = FakeEncoder("enc-c", fail_after=0)
        result = self.switch("enc-c", unused, snapshot=snapshot)
        self.assertEqual(result["status"], "SWITCHED")
        self.assertNotIn("encoder_query_probe", result["smoke"])
        self.assertEqual(unused.calls, 0)
        self.assertEqual(self.index("enc-c").status()["status"], "VERIFIED")

    def test_selection_is_per_backend(self):
        self.switch("enc-c")
        http = replace(self.settings, chroma_host="chroma-test", chroma_port=8000)
        self.assertNotEqual(selection_path(http), selection_path(self.settings))
        self.assertIsNone(load_selection(http))
        self.assertEqual(
            http.for_retrieval("finetuned").embedding_checkpoint_sha256,
            self.catalog["enc-a"].checkpoint_sha256,
        )

    def test_cli_switch_status_and_rollback(self):
        manifest_path = self.root / "subset.json"
        save_json(manifest_path, self.manifest)
        config = replace(self.settings, manifest_path=manifest_path, project="")

        def run(*args):
            out, err = io.StringIO(), io.StringIO()
            with (
                patch("services.rag_workflow.cli.Settings", return_value=config),
                patch(
                    "services.rag_workflow.index_switching.create_embedding_provider",
                    side_effect=lambda settings: FakeEncoder(
                        next(
                            n
                            for n, e in self.catalog.items()
                            if e.checkpoint_sha256 == settings.embedding_checkpoint_sha256
                        )
                    ),
                ),
                redirect_stdout(out),
                redirect_stderr(err),
            ):
                code = main(["--retrieval-model", "finetuned", *args])
            return code, out.getvalue(), err.getvalue()

        code, out, err = run("switch-index", "--to", "enc-b")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "ENCODER_NOT_EVALUATED")
        code, out, _ = run("switch-index", "--to", "enc-c")
        self.assertEqual((code, json.loads(out)["status"]), (0, "SWITCHED"))
        code, out, _ = run("index-status")
        selection = json.loads(out)["encoder_selection"]
        self.assertEqual(code, 0)
        self.assertEqual(selection["source"], "record")
        self.assertEqual(selection["active"]["name"], "enc-c")
        self.assertEqual(selection["previous"]["name"], "enc-a")
        self.assertEqual(selection["previous"]["index_status"], "VERIFIED")
        self.assertTrue(selection["previous"]["evaluated"])
        code, out, _ = run("rollback-index")
        self.assertEqual((code, json.loads(out)["active"]), (0, "enc-a"))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["rollback-index"])  # Switching applies only to the fine-tuned path.


class CatalogTests(unittest.TestCase):
    # T9
    def test_without_a_record_finetuned_settings_equal_ms3_field_by_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            for host in ("", "rag-chromadb"):
                base = Settings(artifacts=Path(tmp), chroma_host=host)
                self.assertIsNone(load_selection(base))
                self.assertEqual(
                    asdict(base.for_retrieval("finetuned")),
                    asdict(replace(base, **MS3_FINETUNED)),
                )

    def test_catalog_declares_evaluated_default_and_flags_unevaluated_pipeline_run(self):
        self.assertEqual(encoders.DEFAULT_FINETUNED, "train-20261110-t4-r3")
        self.assertTrue(encoders.ENCODERS[encoders.DEFAULT_FINETUNED].evaluated)
        self.assertFalse(encoders.ENCODERS["pipeline-20261112"].evaluated)
        for entry in encoders.ENCODERS.values():
            settings = apply_encoder(Settings(), entry)
            settings.validate()
            # cloud/tasks.py derives the remote snapshot folder from the checkpoint URI.
            self.assertTrue(settings.embedding_checkpoint.endswith("/model"))
        with self.assertRaises(TypeError):
            encoders.ENCODERS["new"] = None


if __name__ == "__main__":
    unittest.main()
