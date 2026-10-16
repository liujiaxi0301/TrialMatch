"""Versioned criterion vectors; same code supports embedded Chroma or a Compose server."""

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from .providers import ProviderError, content_hash, save_json


class VectorIndex:
    def __init__(self, settings, store, manifest, provider):
        self.settings, self.store, self.manifest, self.provider = (
            settings,
            store,
            manifest,
            provider,
        )
        self.identity = {
            "trials_sha256": store.hashes["trials"],
            "criteria_sha256": store.hashes["criteria"],
            "trial_ids": manifest["trial_ids"],
            "model": settings.embedding_model,
            "dimension": settings.dimension,
            "chunker": "criterion-char3000-overlap200-v1",
        }
        self.version = content_hash(self.identity)[:20]
        self.name = f"trialmatch-{self.version}"
        self.manifest_path = settings.artifacts / "indexes" / f"{self.version}.json"
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        config = ChromaSettings(anonymized_telemetry=False)
        if settings.chroma_host:
            self.client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port, settings=config
            )
        else:
            self.client = chromadb.PersistentClient(
                path=str(settings.artifacts / "chroma"), settings=config
            )

    def build(self) -> dict:
        collection = self.client.get_or_create_collection(
            name=self.name, metadata={"hnsw:space": "cosine"}
        )
        fragments = []
        for trial_id in self.manifest["trial_ids"]:
            for criterion in self.store.criteria[trial_id]:
                if criterion["parse_status"] != "parsed":
                    continue
                text = criterion["criterion_text"]
                # Retrieval fragments ONLY. Screening always uses the complete original criterion.
                pieces = [text[start : start + 3000] for start in range(0, len(text), 2800)]
                for position, piece in enumerate(pieces):
                    key = f"{criterion['criterion_id']}__{position}"
                    fragments.append(
                        (
                            key,
                            piece,
                            {
                                "trial_id": trial_id,
                                "criterion_id": criterion["criterion_id"],
                                "criterion_type": criterion["criterion_type"],
                                "parse_status": "parsed",
                                "snapshot_date": self.store.trials[trial_id]["snapshot_date"],
                            },
                        )
                    )
        count = 0
        # Small windows bound outstanding requests if credentials fail. Existing text caches resume runs.
        with ThreadPoolExecutor(max_workers=4) as pool:
            for start in range(0, len(fragments), 8):
                batch = fragments[start : start + 8]
                embeddings = list(pool.map(lambda item: self.provider.embed(item[1]), batch))
                collection.upsert(
                    ids=[x[0] for x in batch],
                    documents=[x[1] for x in batch],
                    embeddings=embeddings,
                    metadatas=[x[2] for x in batch],
                )
                count += len(batch)
                if count % 40 == 0 or count == len(fragments):
                    print(f"Indexed {count}/{len(fragments)} criterion fragments", file=sys.stderr)
        if count == 0:
            raise ProviderError("EMPTY_INDEX", "No parsed criteria were available to index.")
        manifest = {**self.identity, "collection": self.name, "vector_count": count, "ready": True}
        save_json(self.manifest_path, manifest)
        return manifest

    def query(self, text: str) -> list[dict]:
        if not self.manifest_path.exists():
            raise ProviderError(
                "INDEX_NOT_READY",
                "Run build-index for this data/model/subset before live screening.",
            )
        saved = json.loads(self.manifest_path.read_text())
        collection = self.client.get_collection(name=self.name)
        count = collection.count()
        if count != saved["vector_count"]:
            raise ProviderError(
                "INDEX_INCOMPLETE", "Index count changed; rebuild the matching version."
            )
        result = collection.query(
            query_embeddings=[self.provider.embed(text, "RETRIEVAL_QUERY")],
            n_results=count,
            include=["metadatas", "distances"],
        )
        seen, hits = set(), []
        # Best criterion distance per trial, never sum over its number of criteria.
        for meta, distance in zip(result["metadatas"][0], result["distances"][0], strict=True):
            if meta["trial_id"] not in seen:
                seen.add(meta["trial_id"])
                hits.append(
                    {
                        "trial_id": meta["trial_id"],
                        "criterion_id": meta["criterion_id"],
                        "cosine_distance": round(float(distance), 6),
                    }
                )
        return hits
