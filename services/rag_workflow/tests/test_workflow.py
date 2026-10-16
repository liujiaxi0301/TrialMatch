import copy
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from services.rag_workflow.api import create_app
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore, complexity_flags, validate_patient
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.judge import judge_batch, validate_judgments
from services.rag_workflow.providers import ProviderError, content_hash
from services.rag_workflow.rules import numeric_rule, unknown
from services.rag_workflow.schemas import (
    Decision,
    LLMJudgments,
    ScreeningStatus,
    ScreenRequest,
    ScreenResponse,
)
from services.rag_workflow.workflow import ScreeningWorkflow, aggregate


def patient_fixture():
    """Handwritten SYNTHETIC TEST FIXTURE, not an official Synthea record."""
    return {
        "schema_version": "0.3",
        "patient_id": "fixture",
        "reference_date": "2021-11-30",
        "demographics": {
            "fact_id": "fixture#Patient/fixture",
            "age_years_at_reference": 45,
            "resource_type": "Patient",
        },
        "conditions": [],
        "observations": [],
        "procedures": [],
        "medications": {},
        "warnings": [],
    }


def criterion(text="Age 18-65", type_="inclusion", id_="T_inc_001"):
    return {
        "criterion_id": id_,
        "trial_id": "T",
        "criterion_type": type_,
        "criterion_text": text,
        "parse_status": "parsed",
        "parse_method": "deterministic",
    }


class RuleTests(unittest.TestCase):
    def test_age_and_exclusion_direction(self):
        p = patient_fixture()
        inc, exc = criterion(), criterion("Age >= 40", "exclusion", "T_exc_001")
        results = [numeric_rule(c, p) for c in (inc, exc)]
        status, score, coverage, _ = aggregate([inc, exc], results)
        self.assertEqual(status, ScreeningStatus.BARRIER)
        self.assertEqual(score, 50)
        self.assertEqual(coverage.screening_barriers, 1)

    def test_missing_age_is_unknown(self):
        p = patient_fixture()
        p["demographics"]["age_years_at_reference"] = None
        self.assertEqual(numeric_rule(criterion(), p).decision, Decision.UNKNOWN)

    def test_compound_numeric_text_not_partially_evaluated(self):
        self.assertIsNone(numeric_rule(criterion("Age 18-65 and HbA1c > 7%"), patient_fixture()))

    def test_unknown_never_averaged_away(self):
        p, inc, missing = (
            patient_fixture(),
            criterion(),
            criterion("No heart disease", "exclusion", "T_exc_001"),
        )
        status, score, coverage, _ = aggregate(
            [inc, missing], [numeric_rule(inc, p), unknown(missing, "Missing")]
        )
        self.assertEqual(status, ScreeningStatus.NEEDS_INFO)
        self.assertEqual(score, 50)
        self.assertEqual(coverage.unknown, 1)

    def test_missing_duplicate_and_foreign_criterion_rejected(self):
        c = criterion()
        value = numeric_rule(c, patient_fixture())
        for rows in ([], [value, value]):
            with self.assertRaises(ValueError):
                aggregate([c], rows)

    def test_complete_no_barrier_is_potential_only(self):
        c = criterion()
        status, score, *_ = aggregate([c], [numeric_rule(c, patient_fixture())])
        self.assertEqual(status, ScreeningStatus.POTENTIAL)
        self.assertEqual(score, 100)

    def test_hba1c_units_dates_ties(self):
        p = patient_fixture()
        c = criterion("HbA1c >= 7% within last 3 months")
        fact = {
            "fact_id": "fixture#Observation/lab",
            "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
            "effective_date": "2021-11-01",
            "raw_status": "final",
            "value": {"type": "Quantity", "data": {"value": 8.1, "unit": "%"}},
        }
        p["observations"] = [fact]
        self.assertEqual(numeric_rule(c, p).decision, Decision.MET)
        for key, value in (
            ("effective_date", None),
            ("effective_date", "2022-01-01"),
            ("effective_date", "2020-01-01"),
            ("raw_status", "preliminary"),
        ):
            changed = copy.deepcopy(p)
            changed["observations"][0][key] = value
            self.assertEqual(numeric_rule(c, changed).decision, Decision.UNKNOWN)
        wrong_unit = copy.deepcopy(p)
        wrong_unit["observations"][0]["value"]["data"]["unit"] = "mmol/mol"
        self.assertEqual(numeric_rule(c, wrong_unit).decision, Decision.UNKNOWN)
        other = copy.deepcopy(fact)
        other["fact_id"] = "fixture#Observation/conflict"
        other["value"]["data"]["value"] = 6
        p["observations"].append(other)
        self.assertEqual(numeric_rule(c, p).decision, Decision.UNKNOWN)

    def test_wrong_patient_reference_rejected(self):
        p = patient_fixture()
        p["conditions"] = [
            {"fact_id": "fixture#Condition/a", "subject_reference": "Patient/another"}
        ]
        with self.assertRaises(ValueError):
            validate_patient(p)

    def test_cohort_flag_prevents_flattening(self):
        flags = complexity_flags(
            {"eligibility_text": "BMI normal weight group; obesity group"}, [criterion()]
        )
        self.assertIn("COHORT_LOGIC_REQUIRES_REVIEW", flags)

    def test_bare_range_is_not_assumed_to_be_age(self):
        self.assertIsNone(numeric_rule(criterion("18-65"), patient_fixture()))

    def test_future_inline_fact_rejected(self):
        p = patient_fixture()
        p["conditions"] = [{"fact_id": "fixture#Condition/future", "onset_date": "2025-01-01"}]
        with self.assertRaises(ValueError):
            validate_patient(p)


class JudgeTests(unittest.TestCase):
    def setUp(self):
        c = criterion()
        self.items = [
            {
                "criterion": {
                    k: c[k] for k in ("criterion_id", "criterion_type", "criterion_text")
                },
                "patient_evidence": [{"fact_id": "fixture#Patient/fixture"}],
            }
        ]

    def test_hallucinated_patient_fact_rejected(self):
        result = LLMJudgments(
            assessments=[
                {
                    "criterion_id": "T_inc_001",
                    "decision": "MET",
                    "reason": "Matched",
                    "evidence_fact_ids": ["other-patient"],
                    "missing_information": [],
                }
            ]
        )
        with self.assertRaises(ValueError):
            validate_judgments(result, self.items)

    def test_invalid_output_gets_only_one_repair(self):
        class InvalidProvider:
            calls = 0

            def generate(self, *args):
                self.calls += 1
                return LLMJudgments(assessments=[])

        provider = InvalidProvider()
        result = judge_batch(provider, patient_fixture(), "Why?", {"trial_id": "T"}, self.items)
        self.assertEqual(provider.calls, 2)
        self.assertEqual(result[0].decision, Decision.UNKNOWN)
        self.assertEqual(result[0].error_code, "INVALID_LLM_OUTPUT")

    def test_403_does_not_retry_or_become_mock(self):
        class DeniedProvider:
            calls = 0

            def generate(self, *args):
                self.calls += 1
                raise ProviderError("GCP_403", "Denied")

        provider = DeniedProvider()
        result = judge_batch(provider, patient_fixture(), "Why?", {"trial_id": "T"}, self.items)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result[0].error_code, "GCP_403")


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings(mode="offline")
        cls.workflow = ScreeningWorkflow(cls.settings)
        cls.patient_id = cls.workflow.manifest["demo_patient_ids"][0]

    def test_actual_25_cohort_50_trials_and_source_ledger(self):
        self.assertEqual(len(self.workflow.store.patients), 25)
        self.assertEqual(len(self.workflow.manifest["trial_ids"]), 50)
        result = self.workflow.screen(
            ScreenRequest(
                patient_id=self.patient_id,
                question="Which trials may suit this patient, and what concerns need review?",
                top_k=3,
            )
        )
        self.assertEqual(result.result_status, "OK")
        self.assertEqual(result.mode, "offline")
        self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in result.answer))
        self.assertEqual(len(result.candidate_trials), 3)
        for trial in result.candidate_trials:
            self.assertIsNone(trial.eligibility_probability)
            self.assertEqual(len(trial.criteria_assessments), trial.assessment_coverage.total)
            self.assertEqual(
                len({a.criterion_id for a in trial.criteria_assessments}),
                trial.assessment_coverage.total,
            )
            self.assertTrue(
                all(
                    set(a.evidence_fact_ids) <= set(trial.evidence)
                    for a in trial.criteria_assessments
                )
            )
        ScreenResponse.model_validate_json(result.model_dump_json())

    def test_inline_patient_and_id_contract(self):
        p = self.workflow.store.patient(self.patient_id)
        request = ScreenRequest(patient=p, question="Which trials?", top_k=1)
        self.assertEqual(self.workflow.screen(request).patient_id, self.patient_id)
        with self.assertRaises(ValueError):
            ScreenRequest(patient=p, patient_id=self.patient_id, question="Why?")

    def test_changed_source_invalidates_manifest(self):
        store = DataStore(self.settings)
        store.hashes["criteria"] = "changed"
        with self.assertRaises(ValueError):
            store.manifest()

    def test_live_provider_failure_structured(self):
        live = ScreeningWorkflow(replace(self.settings, mode="live"))
        with patch(
            "services.rag_workflow.workflow.GeminiProvider",
            side_effect=ProviderError("GCP_403", "Denied"),
        ):
            result = live.screen(ScreenRequest(patient_id=self.patient_id, question="Why?"))
        self.assertEqual(result.mode, "live")
        self.assertEqual(result.result_status, "ERROR")
        self.assertEqual(result.errors[0].code, "GCP_403")
        self.assertEqual(result.candidate_trials, [])

    def test_http_contract(self):
        client = TestClient(create_app(self.settings))
        self.assertEqual(client.get("/health").json()["patients"], 25)
        self.assertEqual(len(client.get("/patients").json()["patients"]), 25)
        self.assertEqual(
            client.post("/screen", json={"patient_id": self.patient_id}).status_code, 422
        )
        self.assertEqual(
            client.post("/screen", json={"patient_id": "missing", "question": "Why?"}).status_code,
            404,
        )
        result = client.post(
            "/screen",
            json={
                "patient_id": self.patient_id,
                "question": "Which clinical trial and why?",
                "top_k": 1,
            },
        )
        self.assertEqual(result.status_code, 200)
        ScreenResponse.model_validate(result.json())
        bad = patient_fixture()
        bad["observations"] = "not an array"
        self.assertEqual(
            client.post("/screen", json={"patient": bad, "question": "Why?"}).status_code, 422
        )

    def test_index_version_does_not_mix_models(self):
        a = content_hash([self.settings.embedding_model, 256, self.workflow.store.hashes])
        b = content_hash([self.settings.embedding_model, 768, self.workflow.store.hashes])
        self.assertNotEqual(a, b)

    def test_real_chroma_persistence_upsert_and_model_version(self):
        class FakeEmbeddings:
            """Deterministic test vectors only, never an online embedding model."""

            def embed(self, text, task_type="RETRIEVAL_DOCUMENT"):
                rng = random.Random(content_hash(text))
                return [rng.random() for _ in range(256)]

        with tempfile.TemporaryDirectory() as temporary:
            config = replace(self.settings, artifacts=Path(temporary), chroma_host="")
            manifest = dict(self.workflow.manifest)
            manifest["trial_ids"] = manifest["trial_ids"][:2]
            first = VectorIndex(config, self.workflow.store, manifest, FakeEmbeddings())
            initial = first.build()
            self.assertEqual(first.build()["vector_count"], initial["vector_count"])
            second = VectorIndex(config, self.workflow.store, manifest, FakeEmbeddings())
            hits = second.query("Type 2 diabetes")
            self.assertEqual({hit["trial_id"] for hit in hits}, set(manifest["trial_ids"]))
            changed = VectorIndex(
                replace(config, embedding_model="another-model"),
                self.workflow.store,
                manifest,
                FakeEmbeddings(),
            )
            with self.assertRaises(ProviderError):
                changed.query("Type 2 diabetes")


if __name__ == "__main__":
    unittest.main()
