"""Gemini Developer API adapter for MS3 retrieval evaluation."""

import json
import os

from google import genai
from google.genai import types

from services.rag_workflow.providers import (
    GeminiProvider,
    ProviderError,
    content_hash,
    save_json,
)


class GeminiDeveloperProvider(GeminiProvider):
    def __init__(self, settings):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY")

        self.settings = settings
        self.client = genai.Client(api_key=api_key, vertexai=False)

        self.metrics = {
            "embedding_requests": 0,
            "generation_requests": 0,
            "cache_hits": 0,
            "prompt_tokens": 0,
            "output_tokens": 0,
        }

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        key = content_hash([
            self.settings.embedding_model,
            self.settings.dimension,
            task_type,
            text,
        ])
        path = self.settings.artifacts / "cache/embeddings" / f"{key}.json"

        if path.exists():
            self.metrics["cache_hits"] += 1
            return json.loads(path.read_text())["vector"]

        def request():
            self.metrics["embedding_requests"] += 1
            return self.client.models.embed_content(
                model=self.settings.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.settings.dimension,
                    task_type=task_type,
                ),
            )

        response = self._call(request)
        vector = list(response.embeddings[0].values)

        if len(vector) != self.settings.dimension:
            raise ProviderError(
                "EMBEDDING_DIMENSION_MISMATCH",
                "Unexpected embedding dimension.",
            )

        save_json(path, {
            "model": self.settings.embedding_model,
            "dimension": len(vector),
            "vector": vector,
        })
        return vector


    def generate(self, system: str, payload: dict, schema):
        """Gemini Developer API structured output compatibility."""
        json_schema = schema.model_json_schema()

        key = content_hash([
            "response_json_schema_v1",
            self.settings.generation_model,
            system,
            payload,
            json_schema,
        ])

        path = self.settings.artifacts / "cache/generation" / f"{key}.json"

        if path.exists():
            self.metrics["cache_hits"] += 1
            return schema.model_validate(
                json.loads(path.read_text(encoding="utf-8"))["response"]
            )

        def request():
            self.metrics["generation_requests"] += 1

            return self.client.models.generate_content(
                model=self.settings.generation_model,
                contents=json.dumps(payload, ensure_ascii=False),
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    response_mime_type="application/json",
                    response_json_schema=json_schema,
                    max_output_tokens=8192,
                ),
            )

        response = self._call(request)

        usage = response.usage_metadata
        if usage:
            self.metrics["prompt_tokens"] += usage.prompt_token_count or 0
            self.metrics["output_tokens"] += usage.candidates_token_count or 0

        value = schema.model_validate_json(response.text or "{}")

        save_json(path, {
            "model": self.settings.generation_model,
            "response": value.model_dump(mode="json"),
        })

        return value
