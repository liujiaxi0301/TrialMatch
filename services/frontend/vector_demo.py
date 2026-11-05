"""Credential-free vector retrieval baseline, separate from the Gemini index.

Signed token hashing is lexical, not a pretrained semantic embedding model.
It demonstrates actual chunking, persisted Chroma vectors, and query-to-context.
Jenny's screening workflow is unchanged and retains its offline/live modes.
"""

import hashlib
import math
from collections import Counter
from dataclasses import replace

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.retrieve import patient_query, tokens


class TokenHashProvider:
    dimension = 512

    def embed(self, text, task="RETRIEVAL_DOCUMENT"):
        vector = [0.0] * self.dimension
        for word, count in Counter(tokens(text)).items():
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            position = int.from_bytes(digest[:4], "big") % self.dimension
            vector[position] += (1 if digest[4] % 2 else -1) * (1 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            raise ValueError("The query must contain searchable English words or numbers")
        return [value / norm for value in vector]


class LocalVectorDemo:
    def __init__(self, config=None):
        self.config = replace(
            config or Settings(),
            embedding_model="local-signed-tokenhash-sha256-v1",
            dimension=512,
        )
        self.store = DataStore(self.config)
        self.manifest = self.store.manifest()
        self.provider = TokenHashProvider()
        self.index = VectorIndex(self.config, self.store, self.manifest, self.provider)

    def build(self):
        return self.index.build()

    def retrieve(self, patient_id, question, top_k=5):
        # Fail if not prepared: requests never silently initialize an empty DB.
        status = self.index.status()
        patient = self.store.patient(patient_id)
        query = patient_query(patient, question)
        collection = self.index.client.get_collection(
            self.index.name, embedding_function=None
        )
        result = collection.query(
            query_embeddings=[self.provider.embed(query)],
            n_results=min(top_k, status["vector_count"]),
            include=["documents", "metadatas", "distances"],
        )
        chunks = [
            {"chunk_id": key, "text": text, "distance": distance, **metadata}
            for key, text, distance, metadata in zip(
                result["ids"][0], result["documents"][0],
                result["distances"][0], result["metadatas"][0],
            )
        ]
        return {
            "mode": "local_vector_baseline", "patient_id": patient_id,
            "question": question, "retrieval_query": query,
            "embedding_model": self.config.embedding_model,
            "collection": self.index.name, "vector_count": status["vector_count"],
            "source_hashes": self.store.hashes, "chunks": chunks,
            "note": "Real Chroma cosine retrieval using lexical hash vectors. No LLM, no Gemini embeddings, and no eligibility decision.",
        }
