"""Encoder separation, immutable index identity, and pooling correctness without downloads."""

import importlib.util
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from services.rag_workflow.config import Settings
from services.rag_workflow.embedding_providers import (
    BioClinicalProvider,
    create_embedding_provider,
    encoder_identity,
)
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.index_versions import load_snapshot
from services.rag_workflow.providers import ProviderError, save_json


def bio_settings(**kwargs):
    return Settings(
        embedding_provider="bioclinical",
        embedding_model="test-encoder",
        embedding_revision="a" * 40,
        dimension=768,
        **kwargs,
    )


class EncoderIdentityTests(unittest.TestCase):
    def test_gemini_provider_can_be_reused_and_keeps_old_identity(self):
        settings = Settings(embedding_provider="gemini")
        existing = object()
        self.assertIs(create_embedding_provider(settings, existing), existing)
        self.assertEqual(encoder_identity(settings), {})

    def test_revision_and_dimension_are_required(self):
        for changes in (
            {"embedding_revision": "main"},
            {"dimension": 256},
            {"embedding_max_tokens": 9000},
        ):
            with self.assertRaises(ValueError):
                replace(bio_settings(), **changes).validate()

    def test_encoder_config_changes_index_identity_and_snapshot_roundtrip(self):
        from services.rag_workflow.data import DataStore

        with tempfile.TemporaryDirectory() as tmp:
            settings = bio_settings(artifacts=Path(tmp), chroma_host="")
            store = DataStore(settings)
            manifest = store.manifest()
            manifest["trial_ids"] = manifest["trial_ids"][:1]

            class FixedEncoder:
                def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
                    return [1.0] + [0.0] * 767

            index = VectorIndex(settings, store, manifest, FixedEncoder())
            index.build()
            path = Path(tmp) / "export.json"
            index.export(path)
            snapshot = load_snapshot(path)
            self.assertEqual(snapshot.identity.encoder["revision"], "a" * 40)
            target = VectorIndex(
                replace(settings, artifacts=Path(tmp) / "restore"), store, manifest
            )
            self.assertEqual(target.restore(path)["status"], "RESTORED")
            for changes in ({"embedding_revision": "b" * 40}, {"embedding_max_tokens": 4096}):
                different = VectorIndex(replace(settings, **changes), store, manifest)
                self.assertNotEqual(different.name, index.name)
                with self.assertRaises(ProviderError):
                    different.restore(path)


@unittest.skipUnless(importlib.util.find_spec("torch"), "Install the optional embeddings group")
class PoolingTests(unittest.TestCase):
    def test_nonfinite_cached_vector_is_rejected_without_loading_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            encoder = BioClinicalProvider(bio_settings(artifacts=Path(tmp)))
            save_json(
                encoder._path("cached"),
                {
                    "identity": encoder.identity,
                    "vector": [float("nan")] + [0.0] * 767,
                },
            )
            with self.assertRaises(ProviderError) as caught:
                encoder.embed("cached")
            self.assertEqual(caught.exception.code, "EMBEDDING_CACHE_MISMATCH")
            self.assertIsNone(encoder.model)

    def test_masked_pooling_ignores_padding_and_query_document_share_encoding(self):
        import torch

        with tempfile.TemporaryDirectory() as tmp:
            encoder = BioClinicalProvider(bio_settings(artifacts=Path(tmp)))

            class Tokenizer:
                def __call__(self, texts, **kwargs):
                    return {
                        "input_ids": torch.tensor([[1, 2, 0]] * len(texts)),
                        "attention_mask": torch.tensor([[1, 1, 0]] * len(texts)),
                    }

            class Model:
                def __call__(self, **batch):
                    # A huge padding value must not affect the pooled result.
                    hidden = torch.zeros((len(batch["input_ids"]), 3, 768))
                    hidden[:, 0, 0], hidden[:, 1, 1], hidden[:, 2, 2] = 1, 1, 10000
                    return SimpleNamespace(last_hidden_state=hidden)

            encoder.model, encoder.tokenizer, encoder.device = Model(), Tokenizer(), "cpu"
            vector = encoder.embed("same text")
            self.assertAlmostEqual(vector[0], 2**-0.5, places=6)
            self.assertAlmostEqual(vector[1], 2**-0.5, places=6)
            self.assertEqual(vector[2], 0)
            self.assertEqual(vector, encoder.embed("same text", "RETRIEVAL_QUERY"))
            self.assertEqual(encoder.metrics["embedded_texts"], 1)
            encoder.settings = replace(encoder.settings, embedding_max_tokens=2)
            with self.assertRaises(ProviderError) as caught:
                encoder.embed("too long")
            self.assertEqual(caught.exception.code, "EMBEDDING_INPUT_TOO_LONG")


if __name__ == "__main__":
    unittest.main()
