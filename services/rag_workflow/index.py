"""Versioned criterion vectors; same code supports embedded Chroma or a Compose server."""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .index_versions import (
    IndexSnapshot,
    load_snapshot,
    matching_record,
    read_records,
    records_hash,
)
from .providers import ProviderError, content_hash, save_json


class VectorIndex:
    def __init__(self, settings, store, manifest, provider=None):
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
        indexes = settings.artifacts / "indexes"
        if settings.chroma_host:
            backend = content_hash([settings.chroma_host, settings.chroma_port])[:12]
            indexes = indexes / f"http-{backend}"
        # HTTP and embedded stores can share artifacts/caches but need separate readiness/digests.
        self.manifest_path = indexes / f"{self.version}.json"
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

    def fragments(self) -> list[tuple]:
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
        return fragments

    def _validate_records(self, records: list[dict]) -> None:
        expected = {key: (text, meta) for key, text, meta in self.fragments()}
        keys = [row["id"] for row in records]
        if not expected or len(keys) != len(set(keys)) or set(keys) != set(expected):
            raise ProviderError("INDEX_INCOMPLETE", "Index IDs do not match the selected criteria.")
        for row in records:
            text, meta = expected[row["id"]]
            if row["document"] != text or row["metadata"] != meta:
                raise ProviderError(
                    "INDEX_SOURCE_MISMATCH", "Index text or metadata differs from source."
                )
            if len(row["embedding"]) != self.settings.dimension:
                raise ProviderError(
                    "EMBEDDING_DIMENSION_MISMATCH", "Unexpected stored vector dimension."
                )

    def _collection(self):
        from chromadb.errors import NotFoundError

        try:
            collection = self.client.get_collection(name=self.name, embedding_function=None)
        except NotFoundError as exc:
            raise ProviderError(
                "INDEX_NOT_READY",
                "Index is missing in this database; restore-index or build-index.",
            ) from exc
        if (collection.metadata or {}).get("hnsw:space") != "cosine":
            raise ProviderError("INDEX_CONFIG_MISMATCH", "Expected a cosine-distance collection.")
        return collection

    def _manifest(self, records: list[dict]) -> dict:
        import chromadb

        return {
            **self.identity,
            "schema_version": 1,
            "collection": self.name,
            "vector_count": len(records),
            "records_sha256": records_hash(records),
            "chroma_version": chromadb.__version__,
            "ready": True,
        }

    def verify(self, *, upgrade_legacy=False) -> tuple[dict, list[dict]]:
        if not self.manifest_path.exists():
            raise ProviderError(
                "INDEX_NOT_READY", "Run build-index or restore-index for this data/model/subset."
            )
        saved = json.loads(self.manifest_path.read_text())
        if (
            any(saved.get(key) != value for key, value in self.identity.items())
            or saved.get("collection") != self.name
            or saved.get("ready") is not True
            or saved.get("schema_version", 1) != 1
        ):
            raise ProviderError(
                "INDEX_MANIFEST_MISMATCH", "Index manifest does not match configuration."
            )
        records = read_records(self._collection())
        self._validate_records(records)
        if len(records) != saved.get("vector_count"):
            raise ProviderError("INDEX_INCOMPLETE", "Index count differs from its manifest.")
        if "records_sha256" not in saved:
            if not upgrade_legacy:
                raise ProviderError(
                    "INDEX_MANIFEST_UPGRADE_REQUIRED",
                    "Run build-index once to verify the legacy index and add its checksum; no re-embedding.",
                )
            saved = self._manifest(records)
            save_json(self.manifest_path, saved)
        if saved["records_sha256"] != records_hash(records):
            raise ProviderError(
                "INDEX_CONTENT_MISMATCH",
                "Index content changed; restore the matching snapshot into a fresh database.",
            )
        return saved, records

    def build(self) -> dict:
        # A published collection is immutable. Do not silently repair/overwrite corrupt vectors.
        if self.manifest_path.exists():
            try:
                return self.verify(upgrade_legacy=True)[0]
            except ProviderError as exc:
                from chromadb.errors import NotFoundError

                # Artifacts may be shared with another backend that has not been populated yet.
                if exc.code != "INDEX_NOT_READY" or not isinstance(exc.__cause__, NotFoundError):
                    raise
        if self.provider is None:
            raise ProviderError("MISSING_PROVIDER", "A new index requires an embedding provider.")
        collection = self.client.get_or_create_collection(
            name=self.name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )
        if (collection.metadata or {}).get("hnsw:space") != "cosine":
            raise ProviderError("INDEX_CONFIG_MISMATCH", "Expected a cosine-distance collection.")
        fragments = self.fragments()
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
        records = read_records(collection)
        self._validate_records(records)
        manifest = self._manifest(records)
        save_json(self.manifest_path, manifest)
        return manifest

    def status(self) -> dict:
        saved, _ = self.verify()
        return {
            "status": "VERIFIED",
            "backend": "http" if self.settings.chroma_host else "embedded",
            "index_version": self.version,
            **saved,
        }

    def export(self, output: Path) -> dict:
        saved, records = self.verify()
        snapshot = IndexSnapshot(
            schema_version=1,
            identity=self.identity,
            collection=self.name,
            distance="cosine",
            chroma_version=saved["chroma_version"],
            vector_count=len(records),
            records_sha256=saved["records_sha256"],
            records=records,
        )
        # No timestamps/host paths/patient data: repeated exports are byte-identical.
        save_json(output, snapshot.model_dump(), sort_keys=True)
        summary = snapshot.model_dump(exclude={"records"})
        summary["snapshot_file"] = output.name
        summary["snapshot_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
        save_json(output.with_suffix(".manifest.json"), summary, sort_keys=True)
        return {"snapshot": str(output), "index_version": self.version, **saved}

    def restore(self, source: Path) -> dict:
        from chromadb.errors import NotFoundError

        snapshot = load_snapshot(source)
        if snapshot.identity.model_dump() != self.identity or snapshot.collection != self.name:
            raise ProviderError(
                "SNAPSHOT_VERSION_MISMATCH",
                "Snapshot requires matching source files, subset, embedding model and dimension.",
            )
        records = [record.model_dump() for record in snapshot.records]
        self._validate_records(records)
        # Validate everything before writing; never delete an existing collection or volume.
        try:
            collection = self._collection()
        except ProviderError as exc:
            if exc.code != "INDEX_NOT_READY" or not isinstance(exc.__cause__, NotFoundError):
                raise
            collection = self.client.create_collection(
                name=self.name, metadata={"hnsw:space": "cosine"}, embedding_function=None
            )
        existing = read_records(collection)
        expected = {row["id"]: row for row in records}
        if any(not matching_record(row, expected.get(row["id"])) for row in existing):
            raise ProviderError(
                "INDEX_RESTORE_CONFLICT",
                "Target has different records; use a fresh database. Existing records were preserved.",
            )
        if len(existing) != len(records):
            for start in range(0, len(records), 128):
                batch = records[start : start + 128]
                collection.upsert(
                    ids=[row["id"] for row in batch],
                    documents=[row["document"] for row in batch],
                    metadatas=[row["metadata"] for row in batch],
                    embeddings=[row["embedding"] for row in batch],
                )
        restored = read_records(collection)
        if len(restored) != len(records) or any(
            not matching_record(row, expected.get(row["id"])) for row in restored
        ):
            raise ProviderError(
                "INDEX_RESTORE_FAILED", "Restored records do not match the snapshot."
            )
        saved = self._manifest(restored)
        saved["restored_from_records_sha256"] = snapshot.records_sha256
        save_json(self.manifest_path, saved)
        return {"status": "RESTORED", "index_version": self.version, **saved}

    def query(self, text: str) -> list[dict]:
        saved, _ = self.verify()
        collection = self._collection()
        count = saved["vector_count"]
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
