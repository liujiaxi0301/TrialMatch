"""Fine-tuned retrieval encoder catalog and the per-backend active-encoder record.

The catalog is code, not JSON/YAML: the rag-api image copies only
services/rag_workflow/*.py, so a data file here would be missing on Cloud Run.

The active-encoder record is runtime state under settings.artifacts (Compose mounts
services/rag_workflow read-only). It is kept beside the backend's index readiness
manifests, because an index verified on embedded Chroma is not ready on HTTP Chroma.
Without a record the declared default is used, which matches the MS3 configuration.
"""

import json
import os
import re
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from .index_versions import index_directory
from .providers import ProviderError

BIOCLINICAL_BASE = "thomas-sounack/BioClinical-ModernBERT-base"
BIOCLINICAL_REVISION = "c3648aa87af95837c809e6f0c5f85d08160db437"
SELECTION_FILE = "active-finetuned.json"
SELECTION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EncoderVersion:
    name: str
    checkpoint: str
    checkpoint_sha256: str
    base_model: str
    revision: str
    dimension: int
    max_tokens: int
    evaluated: bool
    note: str


ENCODERS = MappingProxyType(
    {
        entry.name: entry
        for entry in (
            EncoderVersion(
                name="train-20261110-t4-r3",
                checkpoint="gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model",
                checkpoint_sha256="7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c",
                base_model=BIOCLINICAL_BASE,
                revision=BIOCLINICAL_REVISION,
                dimension=768,
                max_tokens=2048,
                evaluated=True,
                note="MS3 submitted checkpoint, scored in the MS3 retrieval benchmark; default.",
            ),
            EncoderVersion(
                name="pipeline-20261112",
                checkpoint=(
                    "gs://trialmatch-ac215-yixiao-ms3/pipelines/15733748057/"
                    "trialmatch-data-pipeline-20261112172151/"
                    "train-encoder_-554883867400470528/training/model"
                ),
                checkpoint_sha256="7dd900ba458da9156de2fdac75e9bce934839e7169d81135f4225cc4aae18f98",
                base_model=BIOCLINICAL_BASE,
                revision=BIOCLINICAL_REVISION,
                dimension=768,
                max_tokens=2048,
                evaluated=False,
                note=(
                    "November 12 pipeline output. Not scored in the retrieval benchmark; "
                    "a switch demonstration target only, never the default."
                ),
            ),
        )
    }
)
DEFAULT_FINETUNED = "train-20261110-t4-r3"


def encoder(name: str) -> EncoderVersion:
    if name not in ENCODERS:
        raise ProviderError(
            "ENCODER_UNKNOWN",
            f"Unknown fine-tuned encoder {name!r}; choose one of {sorted(ENCODERS)}.",
        )
    return ENCODERS[name]


def apply_encoder(settings, entry: EncoderVersion):
    """Retrieval settings for one catalog entry; generation settings are unchanged."""
    return replace(
        settings,
        embedding_provider="bioclinical",
        embedding_model=entry.base_model,
        dimension=entry.dimension,
        embedding_revision=entry.revision,
        embedding_checkpoint=entry.checkpoint,
        embedding_checkpoint_sha256=entry.checkpoint_sha256,
        embedding_max_tokens=entry.max_tokens,
        embedding_device="cpu",
    )


def selection_path(settings) -> Path:
    return index_directory(settings) / SELECTION_FILE


def _invalid(path: Path, reason: str) -> ProviderError:
    return ProviderError(
        "ENCODER_SELECTION_INVALID",
        f"{path} is invalid ({reason}). It is not repaired or ignored automatically; "
        "inspect it, then move it aside to return to the declared default.",
    )


def load_selection(settings) -> dict | None:
    """The validated record, or None when this backend has never switched encoders."""
    path = selection_path(settings)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _invalid(path, f"unreadable: {type(exc).__name__}") from exc
    try:
        record = json.loads(text)
    except ValueError as exc:
        raise _invalid(path, "not JSON") from exc
    if not isinstance(record, dict):
        raise _invalid(path, "not an object")
    if record.get("schema_version") != SELECTION_SCHEMA_VERSION:
        raise _invalid(path, "unsupported schema_version")
    if record.get("retrieval_model") != "finetuned":
        raise _invalid(path, "retrieval_model is not finetuned")
    if record.get("active") not in ENCODERS:
        raise _invalid(path, "active is not in the encoder catalog")
    if record.get("previous") is not None and record["previous"] not in ENCODERS:
        raise _invalid(path, "previous is not in the encoder catalog")
    if record.get("previous") == record["active"]:
        raise _invalid(path, "previous equals active")
    for key in ("index_version", "previous_index_version"):
        value = record.get(key)
        if value is not None and not (
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{20}", value)
        ):
            raise _invalid(path, f"{key} is not an index version")
    if not isinstance(record.get("index_version"), str):
        raise _invalid(path, "index_version is missing")
    if not isinstance(record.get("activated_at"), str) or not isinstance(
        record.get("history"), list
    ):
        raise _invalid(path, "activated_at or history is missing")
    return record


def active_encoder(settings) -> EncoderVersion:
    record = load_selection(settings)
    return ENCODERS[record["active"] if record else DEFAULT_FINETUNED]


def write_selection(settings, record: dict) -> Path:
    """Atomically replace the record: a failed write leaves the previous record intact."""
    path = selection_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise ProviderError(
            "ENCODER_SELECTION_WRITE_FAILED",
            f"Could not write {path}; the previous selection is unchanged.",
        ) from exc
    return path


def next_selection(
    current: dict | None, *, action, active, index_version, previous, previous_index_version
):
    now = datetime.now(UTC).isoformat()
    history = list(current["history"]) if current else []
    history.append(
        {
            "action": action,
            "from": previous,
            "to": active,
            "index_version": index_version,
            "at": now,
        }
    )
    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "retrieval_model": "finetuned",
        "active": active,
        "previous": previous,
        "index_version": index_version,
        "previous_index_version": previous_index_version,
        "activated_at": now,
        "history": history,
    }
