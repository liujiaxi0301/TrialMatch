"""Real embedded Chroma round trips; test vectors only, no model/network calls."""

import copy
import io
import json
import random
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from services.rag_workflow.cli import main
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_versions import (
    load_snapshot,
    matching_record,
    read_records,
    records_hash,
)
from services.rag_workflow.providers import ProviderError, content_hash, save_json


class TestEmbeddings:
    calls = 0

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        self.calls += 1
        rng = random.Random(content_hash([text, task_type]))
        return [rng.random() for _ in range(256)]


class IndexVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = DataStore(Settings(mode="offline"))
        cls.manifest = copy.deepcopy(cls.store.manifest())
        cls.manifest["trial_ids"] = cls.manifest["trial_ids"][:2]

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = Settings(mode="offline", artifacts=self.root / "original", chroma_host="")
        self.provider = TestEmbeddings()
        self.index = VectorIndex(self.settings, self.store, self.manifest, self.provider)
        with redirect_stderr(io.StringIO()):
            self.index.build()
        self.snapshot = self.root / "snapshot.json"
        self.index.export(self.snapshot)

    def fresh(self, name="restored", **kwargs):
        return VectorIndex(
            replace(self.settings, artifacts=self.root / name, **kwargs),
            self.store,
            self.manifest,
            TestEmbeddings(),
        )

    def test_vector_restore_query_and_deterministic_export(self):
        second_export = self.root / "again.json"
        self.index.export(second_export)
        self.assertEqual(self.snapshot.read_bytes(), second_export.read_bytes())
        restored = self.fresh()
        result = restored.restore(self.snapshot)
        self.assertEqual(result["status"], "RESTORED")
        self.assertEqual(restored.provider.calls, 0)
        self.assertTrue(
            all(
                matching_record(a, b)
                for a, b in zip(
                    read_records(self.index._collection()),
                    read_records(restored._collection()),
                    strict=True,
                )
            )
        )
        self.assertEqual(self.index.query("Type 2 diabetes"), restored.query("Type 2 diabetes"))
        self.assertEqual(restored.status()["status"], "VERIFIED")
        self.assertEqual(
            restored.restore(self.snapshot)["records_sha256"], result["records_sha256"]
        )

    def test_repeated_build_is_immutable_and_needs_no_provider(self):
        before = self.index.status()
        self.index.provider = None
        self.assertEqual(self.index.build()["records_sha256"], before["records_sha256"])

    def test_wrong_distance_collection_is_rejected_before_build_or_restore(self):
        target = self.fresh()
        target.client.create_collection(
            name=target.name, metadata={"hnsw:space": "l2"}, embedding_function=None
        )
        for action in (target.build, lambda: target.restore(self.snapshot)):
            with self.assertRaises(ProviderError) as caught:
                action()
            self.assertEqual(caught.exception.code, "INDEX_CONFIG_MISMATCH")
        self.assertEqual(target.provider.calls, 0)
        self.assertEqual(target.client.get_collection(target.name).count(), 0)

    def test_same_count_vector_tampering_is_detected_and_not_overwritten(self):
        collection = self.index._collection()
        row = read_records(collection)[0]
        collection.update(ids=[row["id"]], embeddings=[[0.5] * 256])
        count = collection.count()
        for operation in (self.index.status, self.index.build, lambda: self.index.query("T2D")):
            with self.assertRaises(ProviderError) as caught:
                operation()
            self.assertEqual(caught.exception.code, "INDEX_CONTENT_MISMATCH")
        with self.assertRaises(ProviderError) as caught:
            self.index.restore(self.snapshot)
        self.assertEqual(caught.exception.code, "INDEX_RESTORE_CONFLICT")
        self.assertEqual(collection.count(), count)
        self.assertEqual(read_records(collection)[0]["embedding"], [0.5] * 256)

    def test_same_count_source_tampering_is_detected(self):
        collection = self.index._collection()
        row = read_records(collection)[0]
        collection.update(
            ids=[row["id"]], documents=["A different criterion"], embeddings=[row["embedding"]]
        )
        with self.assertRaises(ProviderError) as caught:
            self.index.status()
        self.assertEqual(caught.exception.code, "INDEX_SOURCE_MISMATCH")

    def test_corrupt_snapshot_is_rejected_before_collection_creation(self):
        value = json.loads(self.snapshot.read_text())
        value["records"][0]["embedding"][0] = 0.25
        save_json(self.snapshot, value)
        restored = self.fresh()
        with self.assertRaises(ProviderError) as caught:
            restored.restore(self.snapshot)
        self.assertEqual(caught.exception.code, "SNAPSHOT_CORRUPT")
        self.assertEqual(restored.client.list_collections(), [])

    def test_matching_checksum_does_not_allow_duplicate_ids_or_foreign_source(self):
        value = json.loads(self.snapshot.read_text())
        value["records"][0] = value["records"][1]
        value["records_sha256"] = records_hash(value["records"])
        save_json(self.snapshot, value)
        restored = self.fresh()
        with self.assertRaises(ProviderError) as caught:
            restored.restore(self.snapshot)
        self.assertEqual(caught.exception.code, "INDEX_INCOMPLETE")
        self.assertEqual(restored.client.list_collections(), [])

    def test_incompatible_source_model_dimension_subset_and_chunker_rejected(self):
        for field, changed in (
            ("model", "different-model"),
            ("dimension", 768),
            ("criteria_sha256", "0" * 64),
            ("trial_ids", self.manifest["trial_ids"][:1]),
            ("chunker", "another-chunker"),
        ):
            with self.subTest(field=field):
                value = json.loads(self.snapshot.read_text())
                value["identity"][field] = changed
                path = self.root / f"{field}.json"
                save_json(path, value)
                restored = self.fresh(field)
                with self.assertRaises(ProviderError) as caught:
                    restored.restore(path)
                self.assertEqual(caught.exception.code, "SNAPSHOT_VERSION_MISMATCH")
                self.assertEqual(restored.client.list_collections(), [])

    def test_invalid_dimensions_and_nonfinite_vectors_rejected(self):
        value = json.loads(self.snapshot.read_text())
        value["records"][0]["embedding"] = [0.1]
        value["records_sha256"] = records_hash(value["records"])
        save_json(self.snapshot, value)
        restored = self.fresh()
        with self.assertRaises(ProviderError) as caught:
            restored.restore(self.snapshot)
        self.assertEqual(caught.exception.code, "EMBEDDING_DIMENSION_MISMATCH")
        value["records"][0]["embedding"] = [float("nan")]
        save_json(self.snapshot, value)
        with self.assertRaises(ValueError):
            load_snapshot(self.snapshot)
        self.assertEqual(restored.client.list_collections(), [])

    def test_interrupted_restore_can_resume_matching_partial_records(self):
        restored = self.fresh()
        collection = restored.client.create_collection(
            name=restored.name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )
        row = read_records(self.index._collection())[0]
        collection.add(
            ids=[row["id"]],
            documents=[row["document"]],
            metadatas=[row["metadata"]],
            embeddings=[row["embedding"]],
        )
        self.assertEqual(restored.restore(self.snapshot)["status"], "RESTORED")
        self.assertEqual(restored.provider.calls, 0)

    def test_legacy_manifest_upgrades_without_reembedding(self):
        saved = json.loads(self.index.manifest_path.read_text())
        for key in ("schema_version", "records_sha256", "chroma_version"):
            saved.pop(key)
        save_json(self.index.manifest_path, saved)
        with self.assertRaises(ProviderError) as caught:
            self.index.status()
        self.assertEqual(caught.exception.code, "INDEX_MANIFEST_UPGRADE_REQUIRED")
        self.index.provider = None
        self.index.build()
        self.assertEqual(self.index.status()["status"], "VERIFIED")

    def test_ready_manifest_alone_does_not_populate_new_backend(self):
        restored = self.fresh()
        save_json(restored.manifest_path, json.loads(self.index.manifest_path.read_text()))
        with self.assertRaises(ProviderError) as caught:
            restored.query("T2D")
        self.assertEqual(caught.exception.code, "INDEX_NOT_READY")
        with redirect_stderr(io.StringIO()):
            restored.build()
        self.assertEqual(restored.status()["status"], "VERIFIED")

    def test_http_readiness_manifest_is_separate_from_embedded_manifest(self):
        original = self.index.manifest_path.read_bytes()
        with patch("chromadb.HttpClient", return_value=self.index.client):
            http_index = VectorIndex(
                replace(self.settings, chroma_host="chroma-test", chroma_port=8000),
                self.store,
                self.manifest,
            )
        self.assertNotEqual(http_index.manifest_path, self.index.manifest_path)
        http_index.restore(self.snapshot)
        self.assertEqual(http_index.status()["status"], "VERIFIED")
        self.assertEqual(self.index.manifest_path.read_bytes(), original)
        self.assertEqual(self.index.status()["status"], "VERIFIED")

    def test_two_versions_coexist_and_old_snapshot_can_be_restored_again(self):
        newer = VectorIndex(
            replace(self.settings, embedding_model="different-model"),
            self.store,
            self.manifest,
            TestEmbeddings(),
        )
        with redirect_stderr(io.StringIO()):
            newer.build()
        other_snapshot = self.root / "newer.json"
        newer.export(other_snapshot)
        old = self.fresh()
        old.restore(self.snapshot)
        new = self.fresh(embedding_model="different-model")
        new.restore(other_snapshot)
        self.assertNotEqual(old.name, new.name)
        self.assertEqual(len(old.client.list_collections()), 2)
        old.restore(self.snapshot)
        self.assertEqual(old.status()["status"], "VERIFIED")
        self.assertEqual(new.status()["status"], "VERIFIED")

    def test_cli_restore_status_export_require_no_cloud_credentials(self):
        config = replace(self.settings, artifacts=self.root / "cli", project="")
        manifest_path = self.root / "subset.json"
        # CLI uses DataStore.manifest; keep the test's two-trial selection explicit.
        config = replace(config, manifest_path=manifest_path)
        save_json(manifest_path, self.manifest)
        output = self.root / "cli-export.json"
        with (
            patch("services.rag_workflow.cli.Settings", return_value=config),
            patch("services.rag_workflow.cli.GeminiProvider", side_effect=AssertionError("No GCP")),
            redirect_stdout(io.StringIO()),
        ):
            for args in (
                ["restore-index", "--input", str(self.snapshot)],
                ["index-status"],
                ["export-index", "--output", str(output)],
                ["build-index"],
            ):
                self.assertEqual(main(args), 0)
        original = load_snapshot(self.snapshot)
        exported = load_snapshot(output)
        self.assertEqual(exported.identity, original.identity)
        self.assertTrue(
            all(
                matching_record(a.model_dump(), b.model_dump())
                for a, b in zip(exported.records, original.records, strict=True)
            )
        )


if __name__ == "__main__":
    unittest.main()
