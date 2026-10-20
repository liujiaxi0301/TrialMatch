"""Replay the shared Claude failure through guards without calling a model."""

import copy
import json
import unittest

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore, patient_facts, validate_patient
from services.rag_workflow.judge import evidence_guard
from services.rag_workflow.retrieve import BM25, tokens
from services.rag_workflow.schemas import CriterionAssessment, Decision
from services.rag_workflow.verify_grounding import CASE, evaluate_fixed, fixed_trial


class GroundingCaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patient = validate_patient(json.loads((CASE / "patient.json").read_text()))
        cls.source = json.loads((CASE / "source_case.json").read_text())
        cls.baseline = json.loads((CASE / "claude_baseline.json").read_text())
        cls.expectations = json.loads((CASE / "expectations.json").read_text())
        cls.store = DataStore(Settings(mode="offline"))

    def test_english_tokenizer_and_retrieval_work_after_translation_removal(self):
        self.assertIn("diabetes", tokens("Which trials for type 2 diabetes?"))
        rank = BM25({"T2D": "type 2 diabetes", "other": "different disease"}).rank("diabetes")
        self.assertEqual(rank[0][0], "T2D")

    def test_fixture_preserves_missing_ranges_dates_and_qualified_history(self):
        facts = {fact["source_resource_id"]: fact for fact in patient_facts(self.patient)}
        self.assertEqual(len(facts), len(patient_facts(self.patient)))
        self.assertIn("No known history", facts["ibd_history"]["value"]["data"])
        self.assertEqual(facts["ibd_history"]["value"]["type"], "String")
        self.assertEqual(facts["albumin"]["value"]["data"], {"value": 4.0, "unit": "g/dL"})
        for key in ("bmi", "hba1c", "fasting_glucose", "albumin"):
            self.assertNotIn("effective_date", facts[key])
            self.assertNotIn("reference_range", facts[key])
            self.assertNotIn("interpretation", facts[key])
        self.assertNotIn("corticosteroid", json.dumps(facts["prednisone"]).lower())
        self.assertEqual(
            facts["prednisone"]["value"]["data"], self.source["statements"]["prednisone"]
        )

    def test_original_claude_focus_claims_are_rejected_despite_valid_source_ids(self):
        by_id = {row["criterion_id"]: row for row in self.store.criteria["NCT02390973"]}
        facts = {fact["source_resource_id"]: fact for fact in patient_facts(self.patient)}
        mapping = {"exc_005": "albumin", "exc_007": "prednisone", "exc_010": "ibd_history"}
        for suffix, fact_key in mapping.items():
            key = f"NCT02390973_{suffix}"
            with self.subTest(criterion_id=key):
                criterion = by_id[key]
                fact = facts[fact_key]
                row = CriterionAssessment(
                    **{
                        k: criterion[k]
                        for k in ("criterion_id", "criterion_type", "criterion_text")
                    },
                    decision=self.baseline["decisions"][key],
                    reason=self.baseline["focus_reasoning"][key],
                    evidence_fact_ids=[fact["fact_id"]],
                    method="llm",
                )
                checked = evidence_guard(row, [fact])
                self.assertEqual(checked.decision, Decision.UNKNOWN)
                self.assertEqual(checked.model_decision, self.baseline["decisions"][key])
                self.assertTrue(checked.validation_warnings)

    def test_offline_unknowns_are_not_counted_as_live_grounding_success(self):
        fixed, trace = fixed_trial(Settings(mode="offline"), self.store, self.patient)
        evaluation = evaluate_fixed(fixed, self.expectations, self.baseline)
        self.assertEqual(len(fixed["criteria_assessments"]), 14)
        self.assertEqual(trace, [])
        self.assertIsNone(evaluation["grounding_focus_passed"])
        # BMI, OR thresholds and explicit consent are now evidence rules, even offline.
        # The diagnosis is still an LLM judgment; offline execution is not model validation.
        self.assertEqual(evaluation["positive_controls_met"], 3)

    def test_model_failures_are_not_counted_as_grounded_abstention(self):
        fixed, _ = fixed_trial(Settings(mode="offline"), self.store, self.patient)
        failed = copy.deepcopy(fixed)
        failed["mode"] = "live"
        for row in failed["criteria_assessments"]:
            row["error_code"] = "PROVIDER_UNAVAILABLE"
        evaluation = evaluate_fixed(failed, self.expectations, self.baseline)
        self.assertFalse(evaluation["grounding_focus_passed"])
        self.assertTrue(evaluation["error_codes"])
        self.assertTrue(
            all(
                row["raw_model_proposal_before_guard"] is None for row in evaluation["focus_checks"]
            )
        )


if __name__ == "__main__":
    unittest.main()
