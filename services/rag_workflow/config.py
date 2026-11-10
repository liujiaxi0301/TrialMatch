"""Environment-driven configuration; no embedded project IDs or credentials."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = Path(__file__).resolve().parent


def env_path(name: str, default: Path) -> Path:
    value = Path(os.environ.get(name, str(default))).expanduser()
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class Settings:
    trials_path: Path = field(
        default_factory=lambda: env_path(
            "TRIALMATCH_TRIALS", ROOT / "services/trial_ingestion/data/processed/trials.jsonl"
        )
    )
    criteria_path: Path = field(
        default_factory=lambda: env_path(
            "TRIALMATCH_CRITERIA", ROOT / "services/trial_ingestion/data/processed/criteria.jsonl"
        )
    )
    patients_path: Path = field(
        default_factory=lambda: env_path(
            "TRIALMATCH_PATIENTS",
            ROOT / "services/patient_processing/data/processed/batch25_patients.jsonl",
        )
    )
    artifacts: Path = field(
        default_factory=lambda: env_path("TRIALMATCH_ARTIFACTS", ROOT / "artifacts/rag_workflow")
    )
    manifest_path: Path = field(
        default_factory=lambda: env_path(
            "TRIALMATCH_MANIFEST", MODULE / "examples/demo_manifest.json"
        )
    )
    mode: str = field(default_factory=lambda: os.environ.get("TRIALMATCH_MODE", "offline"))
    project: str = field(default_factory=lambda: os.environ.get("GCP_PROJECT", ""))
    location: str = field(default_factory=lambda: os.environ.get("GCP_LOCATION", "global"))
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "gemini-embedding-001")
    )
    generation_model: str = field(
        default_factory=lambda: os.environ.get("GENERATIVE_MODEL", "gemini-3.1-flash-lite")
    )
    dimension: int = field(
        default_factory=lambda: int(os.environ.get("EMBEDDING_DIMENSION", "256"))
    )
    embedding_provider: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_PROVIDER", "gemini")
    )
    embedding_revision: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_REVISION", "")
    )
    embedding_max_tokens: int = field(
        default_factory=lambda: int(os.environ.get("EMBEDDING_MAX_TOKENS", "2048"))
    )
    embedding_device: str = field(default_factory=lambda: os.environ.get("EMBEDDING_DEVICE", "cpu"))
    chroma_host: str = field(default_factory=lambda: os.environ.get("CHROMADB_HOST", ""))
    chroma_port: int = field(default_factory=lambda: int(os.environ.get("CHROMADB_PORT", "8000")))
    max_facts_per_criterion: int = 12
    llm_batch_size: int = 6
    max_llm_batches: int = 12
    max_criterion_chars: int = 6000

    def validate(self) -> None:
        if self.mode not in {"offline", "live"}:
            raise ValueError("TRIALMATCH_MODE must be offline or live")
        if not 1 <= self.dimension <= 3072:
            raise ValueError("EMBEDDING_DIMENSION must be between 1 and 3072")
        if self.embedding_provider not in {"gemini", "bioclinical"}:
            raise ValueError("EMBEDDING_PROVIDER must be gemini or bioclinical")
        if self.embedding_provider == "bioclinical":
            import re

            if not re.fullmatch(r"[0-9a-f]{40}", self.embedding_revision):
                raise ValueError("BioClinical requires an exact 40-character EMBEDDING_REVISION")
            if self.dimension != 768:
                raise ValueError("BioClinical base mean pooling requires EMBEDDING_DIMENSION=768")
            if not 1 <= self.embedding_max_tokens <= 8192:
                raise ValueError("EMBEDDING_MAX_TOKENS must be between 1 and 8192")
