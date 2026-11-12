"""Exercise the locked CPU stack with synthetic weights; no model download or scoring."""

import importlib.util
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.embedding_providers import BioClinicalProvider, checkpoint_digest


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("transformers"),
                     "Run in docker/retrieval's locked environment")
class RetrievalRuntimeTests(unittest.TestCase):
    def test_verified_local_modernbert_checkpoint_runs_on_cpu_without_downloads(self):
        import torch
        from tokenizers import Tokenizer
        from tokenizers.models import WordLevel
        from tokenizers.pre_tokenizers import Whitespace
        from transformers import ModernBertConfig, ModernBertModel, PreTrainedTokenizerFast

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_dir = root / "model"
            tok = Tokenizer(WordLevel({"[PAD]": 0, "[UNK]": 1, "hello": 2, "world": 3}, unk_token="[UNK]"))
            tok.pre_tokenizer = Whitespace()
            tokenizer = PreTrainedTokenizerFast(tokenizer_object=tok, unk_token="[UNK]", pad_token="[PAD]")
            tokenizer.save_pretrained(model_dir)
            torch.manual_seed(0)
            config = ModernBertConfig(vocab_size=4, hidden_size=768, intermediate_size=128,
                                     num_hidden_layers=1, num_attention_heads=12, max_position_embeddings=128,
                                     pad_token_id=0, bos_token_id=1, eos_token_id=1)
            ModernBertModel(config).save_pretrained(model_dir)
            digest, _ = checkpoint_digest(model_dir)
            settings = replace(Settings(), artifacts=root / "artifacts", embedding_provider="bioclinical",
                               embedding_revision="a" * 40, embedding_model="synthetic-runtime-probe",
                               dimension=768, embedding_checkpoint=str(model_dir),
                               embedding_checkpoint_sha256=digest, embedding_device="cpu")
            provider = BioClinicalProvider(settings)
            try:
                vectors = provider.embed_many(["hello world", "hello"])
                self.assertEqual(len(vectors), 2)
                for vector in vectors:
                    self.assertEqual(len(vector), 768)
                    self.assertAlmostEqual(sum(value * value for value in vector), 1, places=4)
                self.assertEqual(provider.device, "cpu")
            finally:
                provider.close()


if __name__ == "__main__":
    unittest.main()
