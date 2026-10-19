"""Evidence checks: boundaries, OR truth tables, explicit negation and missing mappings."""

import copy
import json
import unittest

from services.rag_workflow.data import patient_facts
from services.rag_workflow.evidence_rules import evidence_rule
from services.rag_workflow.judge import evidence_guard
from services.rag_workflow.rules import numeric_rule
from services.rag_workflow.schemas import CriterionAssessment, Decision
from services.rag_workflow.tests.test_workflow import criterion
from services.rag_workflow.verify_grounding import CASE


class EvidenceRuleTests(unittest.TestCase):
    def setUp(self):
        self.patient = json.loads((CASE / "patient.json").read_text())

    def fact(self, key):
        return next(f for f in patient_facts(self.patient) if f.get("source_resource_id") == key)

    def check(self, text, type_="exclusion"):
        return evidence_rule(criterion(text, type_), self.patient)

    def test_bmi_comparisons_boundary_and_wrong_units(self):
        for value, expected in ((37.2, Decision.MET), (35, Decision.MET), (34.9, Decision.NOT_MET)):
            with self.subTest(value=value):
                self.fact("bmi")["value"]["data"]["value"] = value
                result = self.check("BMI ≥ 35", "inclusion")
                self.assertEqual(result.decision, expected)
                self.assertEqual(result.evidence_fact_ids, [self.fact("bmi")["fact_id"]])
        self.fact("bmi")["value"]["data"]["unit"] = "kg"
        self.assertEqual(self.check("BMI ≥ 35").decision, Decision.UNKNOWN)

    def test_or_true_unknown_and_all_false(self):
        text = "HbA1c ≥ 6,5 % or fasting glycemia ≥7mmol/l or non-fasting glycemia ≥11mmol/l"
        self.assertEqual(self.check(text).decision, Decision.MET)
        self.fact("hba1c")["value"]["data"]["value"] = 6
        self.fact("fasting_glucose")["value"]["data"]["value"] = 6
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)  # Third branch is missing.
        nonfasting = copy.deepcopy(self.fact("fasting_glucose"))
        nonfasting["fact_id"] = "fixture#nonfasting"
        nonfasting["code"] = {"text": "Non-fasting glucose"}
        nonfasting["value"]["data"]["value"] = 10
        self.patient["observations"].append(nonfasting)
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)
        nonfasting["value"]["data"]["value"] = 11
        self.assertEqual(self.check(text).decision, Decision.MET)

    def test_numeric_and_and_unsupported_mixed_logic(self):
        self.assertEqual(self.check("BMI >= 35 and HbA1c >= 6.5%").decision, Decision.MET)
        self.fact("bmi")["value"]["data"]["value"] = 30
        self.assertEqual(self.check("BMI >= 35 and HbA1c >= 6.5%").decision, Decision.NOT_MET)
        self.assertIsNone(
            numeric_rule(
                criterion("BMI >= 35 or HbA1c >= 6.5% and fasting glucose > 7mmol/l"), self.patient
            )
        )
        self.assertIsNone(
            numeric_rule(criterion("BMI >= 35 or willing to participate"), self.patient)
        )

    def test_glucose_sample_type_and_units_not_inferred(self):
        f = self.fact("fasting_glucose")
        f["code"] = {"text": "Glucose"}
        self.assertEqual(self.check("fasting glucose >=7mmol/l").decision, Decision.UNKNOWN)
        f["code"] = {"text": "Non-fasting glucose"}
        self.assertEqual(self.check("fasting glucose >=7mmol/l").decision, Decision.UNKNOWN)
        f["code"] = {"text": "Fasting glucose"}
        f["value"]["data"]["unit"] = "mg/dL"
        self.assertEqual(self.check("fasting glucose >=7mmol/l").decision, Decision.UNKNOWN)
        f["code"] = {"text": "Fasting potassium"}
        f["value"]["data"]["unit"] = "mmol/L"
        self.assertEqual(self.check("fasting glucose >=7mmol/l").decision, Decision.UNKNOWN)

    def test_explicit_window_requires_dates_and_rejects_future_or_conflict(self):
        text = "HbA1c >=7% within last 3 months"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f = self.fact("hba1c")
        f["effective_date"] = "2026-10-01"
        f["raw_status"] = "final"
        self.assertEqual(self.check(text).decision, Decision.MET)
        other = copy.deepcopy(f)
        other["fact_id"] = "fixture#conflicting-a1c"
        other["value"]["data"]["value"] = 5.9
        self.patient["observations"].append(other)
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        self.patient["observations"].remove(other)
        f["effective_date"] = "2027-01-01"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_consent_explicit_not_just_alert_and_conflicts(self):
        self.assertEqual(self.check("able to consent", "inclusion").decision, Decision.MET)
        f = self.fact("consent")
        f["value"]["data"] = "The patient is alert and oriented."
        self.assertEqual(self.check("able to consent").decision, Decision.UNKNOWN)
        f["value"]["data"] = "The patient is not able to provide informed consent."
        self.assertEqual(self.check("able to consent").decision, Decision.NOT_MET)
        other = copy.deepcopy(f)
        other["fact_id"] = "fixture#positive-consent"
        other["value"]["data"] = "The patient is able to provide informed consent."
        self.patient["observations"].append(other)
        self.assertEqual(self.check("able to consent").decision, Decision.UNKNOWN)

    def test_negative_pregnancy_text_and_predicate_specific_boolean(self):
        self.assertEqual(self.check("pregnancy").decision, Decision.NOT_MET)
        f = self.fact("pregnancy_test")
        f["value"] = {"type": "Boolean", "data": False}
        self.assertEqual(self.check("pregnancy").decision, Decision.NOT_MET)
        f["code"] = {"text": "A completely unrelated test"}
        self.assertEqual(self.check("pregnancy").decision, Decision.UNKNOWN)

    def test_contradictory_pregnancy_results_do_not_pick_favorable(self):
        f = copy.deepcopy(self.fact("pregnancy_test"))
        f["fact_id"] = "fixture#positive-pregnancy"
        f["value"]["data"] = "Pregnancy test is positive."
        self.patient["observations"].append(f)
        self.assertEqual(self.check("pregnancy").decision, Decision.UNKNOWN)

    def test_known_old_pregnancy_test_cannot_prove_status_at_snapshot(self):
        self.fact("pregnancy_test")["effective_date"] = "2024-10-11"
        self.assertEqual(self.check("pregnancy").decision, Decision.UNKNOWN)
        self.fact("pregnancy_test")["effective_date"] = self.patient["reference_date"]
        self.assertEqual(self.check("pregnancy").decision, Decision.NOT_MET)

    def test_explicit_surgery_history_is_not_missing_documentation(self):
        text = "past esophageal, gastric or bariatric surgery"
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)
        f = self.fact("surgery_history")
        f["value"]["data"] = "No history of gastric surgery."
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f["value"]["data"] = "No information about esophageal, gastric or bariatric surgery."
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_qualified_ulcer_negation_covers_both_alternatives(self):
        text = "history of gastric or duodenal ulcers"
        result = self.check(text)
        self.assertEqual(result.decision, Decision.NOT_MET)
        self.assertIn("SOURCE_SAYS_NO_KNOWN_HISTORY", result.validation_warnings)
        self.assertIn("no known history", result.reason)
        self.fact("ulcer_history")["value"]["data"] = "No known history of gastric ulcer."
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_negative_subtype_does_not_prove_absence_of_broader_disease(self):
        text = "history of gastro-intestinal inflammatory diseases"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        self.fact("ibd_history")["value"]["data"] = (
            "No known history of gastrointestinal inflammatory diseases."
        )
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)

    def test_negative_history_window_coverage(self):
        text = "history of drug use or alcool abuse in the last 12 months"
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)
        f = self.fact("substance_history")
        f["value"]["data"] = "No history of drug use or alcohol abuse within the last 1 month."
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f["value"]["data"] = "No history of drug use or alcohol abuse within the last 24 months."
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)
        f["effective_date"] = "2025-10-11"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_conflicting_positive_history_blocks_negative_result(self):
        f = copy.deepcopy(self.fact("surgery_history"))
        f["fact_id"] = "fixture#positive-surgery"
        f["value"]["data"] = "History of bariatric surgery."
        self.patient["observations"].append(f)
        self.assertEqual(
            self.check("past esophageal, gastric or bariatric surgery").decision, Decision.UNKNOWN
        )

    def test_positive_history_supports_or_but_wide_positive_window_is_not_recent(self):
        self.fact("surgery_history")["value"]["data"] = "History of bariatric surgery."
        self.assertEqual(
            self.check("past esophageal, gastric or bariatric surgery").decision, Decision.MET
        )
        f = self.fact("substance_history")
        f["value"]["data"] = "History of alcohol abuse within the last 24 months."
        text = "history of drug use or alcohol abuse in the last 12 months"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f["value"]["data"] = "History of alcohol abuse within the last 3 months."
        self.assertEqual(self.check(text).decision, Decision.MET)

    def test_boolean_positive_history_conflicts_with_textual_negative(self):
        fact = copy.deepcopy(self.fact("surgery_history"))
        fact["fact_id"] = "fixture#positive-boolean-history"
        fact["code"] = {"text": "History of bariatric surgery"}
        fact["value"] = {"type": "Boolean", "data": True}
        self.patient["observations"].append(fact)
        self.assertEqual(
            self.check("past esophageal, gastric or bariatric surgery").decision, Decision.UNKNOWN
        )

    def test_albumin_requires_supplied_range_and_preoperative_timing(self):
        text = "pre-operatory hypoalbuminemy"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f = self.fact("albumin")
        f["reference_range"] = {"low": 3.2, "high": 5.2, "unit": "g/dL"}  # Test-supplied range.
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f["timing"] = "pre-operative"
        self.assertEqual(self.check(text).decision, Decision.NOT_MET)
        f["value"]["data"]["value"] = 3.0
        self.assertEqual(self.check(text).decision, Decision.MET)
        f["reference_range"]["unit"] = "g/L"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_medication_time_computed_independently_of_class(self):
        text = "taken of corticosteroid in the last month"
        result = self.check(text)
        self.assertEqual(result.decision, Decision.UNKNOWN)
        self.assertIn("2026-09-27", result.reason)
        self.assertIn("Time-window check passed", result.reason)
        self.assertIn("MEDICATION_CLASS_NOT_SUPPLIED", result.validation_warnings)
        f = self.fact("prednisone")
        f["medication_class"] = "corticosteroid"  # Explicit test evidence, not a built-in lookup.
        self.assertEqual(self.check(text).decision, Decision.MET)
        f["value"]["data"] = "The patient took this drug 2 months ago."
        self.assertEqual(
            self.check(text).decision, Decision.UNKNOWN
        )  # Old use is not proof of non-use.

    def test_medication_calendar_boundary_orders_and_negation(self):
        text = "taken of corticosteroid in the last month"
        f = self.fact("prednisone")
        f["medication_class"] = "corticosteroid"
        f["value"]["data"] = "The patient took this drug 1 month ago."
        self.assertEqual(self.check(text).decision, Decision.MET)
        f["resource_type"] = "MedicationRequest"
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)
        f["resource_type"] = "MedicationStatement"
        f["value"]["data"] = "The patient never took this drug 2 weeks ago."
        self.assertEqual(self.check(text).decision, Decision.UNKNOWN)

    def test_guard_rechecks_source_not_proposal_or_keyword(self):
        c = criterion("BMI >= 35", "inclusion")
        f = self.fact("bmi")
        row = CriterionAssessment(
            **{k: c[k] for k in ("criterion_id", "criterion_type", "criterion_text")},
            decision=Decision.MET,
            reason="BMI is high",
            evidence_fact_ids=[f["fact_id"]],
            method="llm",
        )
        self.assertEqual(
            evidence_guard(row, [f], self.patient["reference_date"]).decision, Decision.MET
        )
        f["value"]["data"]["value"] = 30
        row = row.model_copy(update={"decision": Decision.MET, "reason": "BMI is high"})
        checked = evidence_guard(row, [f], self.patient["reference_date"])
        self.assertEqual(checked.decision, Decision.NOT_MET)
        self.assertEqual(checked.model_decision, Decision.MET)


if __name__ == "__main__":
    unittest.main()
