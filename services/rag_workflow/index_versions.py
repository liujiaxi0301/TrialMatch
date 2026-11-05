"""Portable logical snapshots: version vectors, never a live Chroma storage directory."""

import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictInt, StrictStr

from .providers import ProviderError


class VectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    document: str = Field(min_length=1)
    metadata: dict[str, StrictStr | StrictInt | bool | FiniteFloat]
    embedding: list[FiniteFloat] = Field(min_length=1)


class IndexIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    trials_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    criteria_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_ids: list[str] = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(ge=1, le=3072)
    chunker: str = Field(min_length=1)


class IndexSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    identity: IndexIdentity
    collection: str
    distance: Literal["cosine"]
    chroma_version: str
    vector_count: int = Field(gt=0)
    records_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    records: list[VectorRecord]


def records_hash(records: list[dict]) -> str:
    """Canonical digest includes IDs, documents, metadata AND stored float32 vectors."""
    data = json.dumps(
        sorted(records, key=lambda row: row["id"]),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def matching_record(actual: dict, expected: dict | None) -> bool:
    """Allow float32 import rounding, while matching source fields exactly.

    Snapshot files are checksummed exactly. Only import comparison allows atol=1e-7,
    rtol=1e-6; each database gets an exact post-import digest for later checks.
    """
    return (
        expected is not None
        and all(actual[key] == expected[key] for key in ("id", "document", "metadata"))
        and len(actual["embedding"]) == len(expected["embedding"])
        and all(
            math.isclose(a, b, abs_tol=1e-7, rel_tol=1e-6)
            for a, b in zip(actual["embedding"], expected["embedding"], strict=True)
        )
    )


def read_records(collection) -> list[dict]:
    """MS2-sized, bounded API pages; sort IDs for deterministic exports."""
    records = []
    count = collection.count()
    for offset in range(0, count, 128):
        page = collection.get(
            limit=128, offset=offset, include=["documents", "metadatas", "embeddings"]
        )
        if any(page[key] is None for key in ("documents", "metadatas", "embeddings")):
            raise ProviderError("INDEX_INCOMPLETE", "Index records lack required fields.")
        for key, document, metadata, vector in zip(
            page["ids"], page["documents"], page["metadatas"], page["embeddings"], strict=True
        ):
            records.append(
                VectorRecord(
                    id=key,
                    document=document,
                    metadata=metadata,
                    embedding=[float(value) for value in vector],
                ).model_dump()
            )
    if collection.count() != count or len(records) != count:
        raise ProviderError(
            "INDEX_CHANGED", "Index changed during reading; stop writers and retry."
        )
    return sorted(records, key=lambda row: row["id"])


def load_snapshot(path: Path) -> IndexSnapshot:
    snapshot = IndexSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    records = [record.model_dump() for record in snapshot.records]
    if len(records) != snapshot.vector_count or records_hash(records) != snapshot.records_sha256:
        raise ProviderError(
            "SNAPSHOT_CORRUPT", "Snapshot count or SHA-256 checksum does not match."
        )
    return snapshot
