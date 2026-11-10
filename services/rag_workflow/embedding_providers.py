"""Separate retrieval encoders from generation; keep the Gemini default compatible."""

import json
import math
import threading

from .providers import GeminiProvider, ProviderError, content_hash, save_json


def encoder_identity(settings) -> dict:
    if settings.embedding_provider == "gemini":
        return {}  # Preserve existing Gemini snapshots and content-addressed collection IDs.
    settings.validate()
    return {
        "provider": "bioclinical",
        "revision": settings.embedding_revision,
        "pooling": "attention-mask-mean-including-special-tokens-v1",
        "normalization": "l2",
        "max_tokens": settings.embedding_max_tokens,
        "dtype": "float32",
        "attention": "sdpa",
    }


def create_embedding_provider(settings, gemini=None):
    settings.validate()
    if settings.embedding_provider == "gemini":
        return gemini if gemini is not None else GeminiProvider(settings)
    return BioClinicalProvider(settings)


class BioClinicalProvider:
    """Experimental frozen MLM encoder + masked mean pooling, not retrieval fine-tuned.

    Both queries and documents use the same encoder. No invented Gemini task prefixes.
    Oversized inputs raise an error instead of silently dropping clinical information.
    """

    def __init__(self, settings):
        settings.validate()
        self.settings = settings
        self.identity = {"model": settings.embedding_model, **encoder_identity(settings)}
        self.metrics = {"embedding_requests": 0, "embedded_texts": 0, "cache_hits": 0}
        self._lock = threading.RLock()
        self.tokenizer = self.model = None
        self.device = settings.embedding_device

    def _load(self):
        if self.model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        torch.manual_seed(0)
        if self.device == "auto":
            self.device = (
                "cuda"
                if torch.cuda.is_available()
                else "mps"
                if torch.backends.mps.is_available()
                else "cpu"
            )
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.settings.embedding_model,
            revision=self.settings.embedding_revision,
            trust_remote_code=False,
        )
        self.model = (
            AutoModel.from_pretrained(
                self.settings.embedding_model,
                revision=self.settings.embedding_revision,
                trust_remote_code=False,
                attn_implementation="sdpa",
                torch_dtype=torch.float32,
            )
            .to(self.device)
            .eval()
        )
        if self.model.config.hidden_size != self.settings.dimension:
            raise ProviderError("EMBEDDING_DIMENSION_MISMATCH", "Encoder hidden size differs.")

    def _path(self, text):
        key = content_hash([self.identity, text])
        return self.settings.artifacts / "cache/bioclinical" / f"{key}.json"

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        return self.embed_many([text], task_type)[0]

    def embed_many(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        if task_type not in {"RETRIEVAL_QUERY", "RETRIEVAL_DOCUMENT"}:
            raise ValueError("Unsupported retrieval task")
        with self._lock:
            vectors, pending = {}, {}
            for text in texts:
                path = self._path(text)
                if path.exists():
                    row = json.loads(path.read_text())
                    if (
                        row["identity"] != self.identity
                        or len(row["vector"]) != self.settings.dimension
                        or not all(math.isfinite(value) for value in row["vector"])
                        or not math.isclose(
                            sum(value * value for value in row["vector"]), 1, abs_tol=1e-4
                        )
                    ):
                        raise ProviderError("EMBEDDING_CACHE_MISMATCH", "Invalid encoder cache.")
                    vectors[text] = row["vector"]
                    self.metrics["cache_hits"] += 1
                else:
                    pending[text] = path
            if pending:
                import torch

                self._load()
                batch = self.tokenizer(
                    list(pending), padding=True, truncation=False, return_tensors="pt"
                )
                if batch["input_ids"].shape[1] > self.settings.embedding_max_tokens:
                    raise ProviderError(
                        "EMBEDDING_INPUT_TOO_LONG", "Encoder token budget exceeded."
                    )
                batch.pop("token_type_ids", None)
                batch = {key: value.to(self.device) for key, value in batch.items()}
                with torch.inference_mode():
                    hidden = self.model(**batch).last_hidden_state.float()
                    mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                    pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1)
                    result = torch.nn.functional.normalize(pooled, p=2, dim=1)
                    if not torch.isfinite(result).all() or (result.norm(dim=1) < 0.99).any():
                        raise ProviderError(
                            "INVALID_EMBEDDING", "Nonfinite or empty encoder output."
                        )
                    values = result.cpu().tolist()
                self.metrics["embedding_requests"] += 1
                self.metrics["embedded_texts"] += len(pending)
                for (text, path), vector in zip(pending.items(), values, strict=True):
                    vectors[text] = vector
                    save_json(path, {"identity": self.identity, "vector": vector})
            return [vectors[text] for text in texts]

    def close(self):
        self.model = self.tokenizer = None
