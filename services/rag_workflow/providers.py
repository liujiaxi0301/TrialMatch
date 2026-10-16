"""Lazy Google Gen AI access with bounded retries and content-addressed caches."""

import hashlib
import json
import time
from pathlib import Path

from .config import Settings


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def content_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temporary file also supports concurrent readers/API requests.
    import uuid

    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


class GeminiProvider:
    def __init__(self, settings: Settings):
        if not settings.project:
            raise ProviderError("MISSING_GCP_PROJECT", "Set GCP_PROJECT for live mode.")
        from google import genai
        from google.genai import types

        self.settings = settings
        self.client = genai.Client(
            vertexai=True,
            project=settings.project,
            location=settings.location,
            http_options=types.HttpOptions(
                timeout=45000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        self.metrics = {
            "embedding_requests": 0,
            "generation_requests": 0,
            "cache_hits": 0,
            "prompt_tokens": 0,
            "output_tokens": 0,
        }

    def close(self):
        self.client.close()

    def _call(self, function):
        for attempt in range(3):
            try:
                return function()
            except Exception as exc:
                code = getattr(exc, "code", None)
                if (
                    code is None
                    and type(exc).__name__
                    in {"ConnectError", "ConnectTimeout", "ReadTimeout", "RemoteProtocolError"}
                    and attempt < 1
                ):
                    time.sleep(1)
                    continue
                if code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                # Do not persist service error URLs, tokens, credential material, or raw prompts.
                hints = {
                    400: "Check model, location, input size, and request configuration.",
                    401: "Check application credentials.",
                    403: "Enable aiplatform.googleapis.com and grant the service account roles/aiplatform.user on GCP_PROJECT.",
                    404: "Check model availability in the configured location.",
                    429: "Quota/rate limit reached; retry later or reduce the workload.",
                }
                raise ProviderError(
                    f"GCP_{code}" if code else "PROVIDER_UNAVAILABLE",
                    hints.get(
                        code,
                        f"Provider request failed ({type(exc).__name__}); check network, credentials, and service health.",
                    ),
                ) from exc

    def embed(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
        from google.genai import types

        key = content_hash(
            [self.settings.embedding_model, self.settings.dimension, task_type, text]
        )
        path = self.settings.artifacts / "cache/embeddings" / f"{key}.json"
        if path.exists():
            self.metrics["cache_hits"] += 1
            return json.loads(path.read_text())["vector"]

        def request():
            self.metrics["embedding_requests"] += 1
            # Vertex gemini-embedding-001 accepts ONE input text per request.
            return self.client.models.embed_content(
                model=self.settings.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.settings.dimension,
                    task_type=task_type,
                    auto_truncate=False,
                ),
            )

        response = self._call(request)
        vector = list(response.embeddings[0].values)
        if len(vector) != self.settings.dimension:
            raise ProviderError("EMBEDDING_DIMENSION_MISMATCH", "Unexpected embedding dimension.")
        save_json(
            path,
            {"model": self.settings.embedding_model, "dimension": len(vector), "vector": vector},
        )
        return vector

    def generate(self, system: str, payload: dict, schema):
        from google.genai import types

        key = content_hash(
            [self.settings.generation_model, system, payload, schema.model_json_schema()]
        )
        path = self.settings.artifacts / "cache/generation" / f"{key}.json"
        if path.exists():
            self.metrics["cache_hits"] += 1
            return schema.model_validate(json.loads(path.read_text())["response"])

        def request():
            self.metrics["generation_requests"] += 1
            return self.client.models.generate_content(
                model=self.settings.generation_model,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=schema,
                    max_output_tokens=8192,
                ),
            )

        response = self._call(request)
        usage = response.usage_metadata
        if usage:
            self.metrics["prompt_tokens"] += usage.prompt_token_count or 0
            self.metrics["output_tokens"] += usage.candidates_token_count or 0
        value = schema.model_validate_json(response.text or "{}")
        save_json(
            path,
            {"model": self.settings.generation_model, "response": value.model_dump(mode="json")},
        )
        return value
