"""Synthetic API integration fixtures; model doubles never call external services.

The HTTP app, data loading, workflow, retrieval, judgments, aggregation and Chroma
remain real. Tiny on-disk inputs keep failure cases independent of the demo cohort.
"""

import hashlib
import json
import random
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.schemas import LLMExplanation, LLMJudgments


class DeterministicProvider:
    """Test vectors and explicit UNKNOWN judgments, not a trained model."""

    def __init__(self, settings):
        self.settings = settings
        self.closed = False
        self.metrics = {
            "embedding_requests": 0,
            "generation_requests": 0,
            "cache_hits": 0,
        }

    def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
        self.metrics["embedding_requests"] += 1
        rng = random.Random(f"{self.settings.embedding_model}:{task_type}:{text}")
        return [rng.random() for _ in range(self.settings.dimension)]

    def generate(self, system, payload, schema):
        self.metrics["generation_requests"] += 1
        if schema is LLMJudgments:
            return schema.model_validate(
                {
                    "assessments": [
                        {
                            "criterion_id": item["criterion"]["criterion_id"],
                            "decision": "UNKNOWN",
                            "reason": "Synthetic test provider has no supporting evidence.",
                            "evidence_fact_ids": [],
                            "missing_information": ["Criterion needs human review."],
                        }
                        for item in payload["items"]
                    ]
                }
            )
        if schema is LLMExplanation:
            criterion_id = payload["assessments"][0]["criterion_id"]
            return schema(
                explanation=f"Synthetic test explanation; review required. [{criterion_id}]",
                cited_criterion_ids=[criterion_id],
            )
        raise AssertionError(f"Unexpected model response schema: {schema}")

    def close(self):
        self.closed = True


class ApiFixture:
    def __init__(self, directory):
        directory = Path(directory)
        self.patient = {
            "schema_version": "0.3",
            "patient_id": "api-fixture",
            "reference_date": "2021-11-30",
            "demographics": {
                "fact_id": "api-fixture#Patient/api-fixture",
                "resource_type": "Patient",
                "age_years_at_reference": 45,
                "gender": "female",
            },
            "conditions": [],
            "observations": [],
            "procedures": [],
            "medications": {},
            "warnings": [],
        }
        self.trial_id = "SYNTHETIC_API_TRIAL"
        trial = {
            "trial_id": self.trial_id,
            "brief_title": "Synthetic diabetes API test",
            "conditions": ["Type 2 diabetes"],
            "brief_summary": "Handwritten test fixture, not a clinical trial record.",
            "overall_status": "RECRUITING",
            "eligibility_text": "Age 18-65. Written consent. Cardiovascular review.",
            "snapshot_date": "2026-10-11",
        }
        self.criteria = [
            {
                "trial_id": self.trial_id,
                "criterion_id": f"{self.trial_id}_{suffix}",
                "criterion_type": type_,
                "criterion_text": text,
                "parse_status": "parsed",
                "parse_method": "synthetic-test-fixture",
            }
            for suffix, type_, text in (
                ("inc_001", "inclusion", "Age 18-65"),
                ("inc_002", "inclusion", "Willing to provide written informed consent"),
                ("exc_001", "exclusion", "Uncontrolled cardiovascular disease"),
            )
        ]
        hashes = {}
        for name, rows in (
            ("trials", [trial]),
            ("criteria", self.criteria),
            ("patients", [self.patient]),
        ):
            data = "".join(json.dumps(row) + "\n" for row in rows).encode()
            (directory / f"{name}.jsonl").write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        manifest = {
            "manifest_version": "0.1",
            "source_sha256": hashes,
            "trial_ids": [self.trial_id],
            "patient_ids": [self.patient["patient_id"]],
            "demo_patient_ids": [self.patient["patient_id"]],
        }
        (directory / "manifest.json").write_text(json.dumps(manifest))
        self.settings = Settings(
            trials_path=directory / "trials.jsonl",
            criteria_path=directory / "criteria.jsonl",
            patients_path=directory / "patients.jsonl",
            manifest_path=directory / "manifest.json",
            artifacts=directory / "artifacts",
            mode="live",
            project="trialmatch-api-test",
            location="global",
            embedding_model="gemini-embedding-001",
            generation_model="fixture-generator",
            dimension=256,
            embedding_provider="gemini",
            embedding_revision="",
            embedding_checkpoint="",
            embedding_checkpoint_sha256="",
            embedding_max_tokens=2048,
            embedding_device="cpu",
            chroma_host="",
            chroma_port=8000,
        )
        self.payload = {
            "patient_id": self.patient["patient_id"],
            "question": "Which diabetes criteria need review?",
            "top_k": 1,
        }

    def build_index(self, model=None):
        settings = self.settings.for_retrieval(model)
        store = DataStore(settings)
        index = VectorIndex(settings, store, store.manifest(), DeterministicProvider(settings))
        index.build()
        return index

    @contextmanager
    def providers(self, provider_type=DeterministicProvider):
        """Replace model adapters only; retain the real embedding-selector factory."""
        instances = []

        def create(settings):
            provider = provider_type(settings)
            instances.append(provider)
            return provider

        with (
            patch("services.rag_workflow.workflow.GeminiProvider", side_effect=create),
            patch(
                "services.rag_workflow.embedding_providers.BioClinicalProvider", side_effect=create
            ),
        ):
            yield instances
