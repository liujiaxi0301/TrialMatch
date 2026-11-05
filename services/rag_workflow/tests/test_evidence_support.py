"""Regression tests for errors seen during the real MS2 model smoke run."""

import json
import unittest

from services.rag_workflow.judge import evidence_guard, explain_trial, judge_batch
from services.rag_workflow.retrieve import ContextSelector
from services.rag_workflow.rules import numeric_rule
from services.rag_workflow.schemas import Decision
from services.rag_workflow.tests.test_workflow import criterion, patient_fixture
from services.rag_workflow.workflow import ScreeningWorkflow


class EvidenceSupportTests(unittest.TestCase):
    def test_grouped_explanation_citations_validate_each_identifier(self):
        row = numeric_rule(criterion(), patient_fixture())
        other = row.model_copy(update={"criterion_id": "T_inc_002"})

        class Provider:
            def generate(self, prompt, payload, schema):
                return schema(
                    explanation="Review these criteria [T_inc_001, T_inc_002].",
                    cited_criterion_ids=["T_inc_001", "T_inc_002"],
                )

        explanation = explain_trial(
            Provider(), "Which trials?", {"trial_id": "T"}, "NEEDS_MORE_INFORMATION", [row, other]
        )
        self.assertIn("[T_inc_001, T_inc_002]", explanation)

    def test_valid_id_does_not_make_absence_supported(self):
        row = numeric_rule(criterion(), patient_fixture())
        row.criterion_type = "exclusion"
        row.criterion_text = "Pregnancy"
        row.decision = Decision.NOT_MET
        row.reason = "There is no evidence of pregnancy."
        checked = evidence_guard(
            row, [{"fact_id": row.evidence_fact_ids[0], "resource_type": "Patient"}]
        )
        self.assertEqual(checked.decision, Decision.UNKNOWN)
        self.assertEqual(checked.model_decision, Decision.NOT_MET)
        self.assertIn("ABSENCE_IS_NOT_NEGATIVE_EVIDENCE", checked.validation_warnings)

    def test_medication_order_is_not_proof_of_use(self):
        row = numeric_rule(criterion(), patient_fixture())
        row.criterion_type = "exclusion"
        row.criterion_text = "Insulin usage for glycemic control"
        row.decision = Decision.MET
        checked = evidence_guard(
            row, [{"fact_id": row.evidence_fact_ids[0], "resource_type": "MedicationRequest"}]
        )
        self.assertEqual(checked.decision, Decision.UNKNOWN)
        self.assertIn(
            "ORDER_OR_DEFINITION_DOES_NOT_ESTABLISH_ACTUAL_DRUG_USE", checked.validation_warnings
        )

    def test_aliases_map_back_to_original_source_ids(self):
        c = criterion("Type 2 diabetes")
        items = [
            {
                "criterion": {
                    k: c[k] for k in ("criterion_id", "criterion_type", "criterion_text")
                },
                "patient_evidence": [
                    {
                        "fact_id": "original/source.json#Condition/diabetes",
                        "resource_type": "Condition",
                    }
                ],
            }
        ]

        class Provider:
            def generate(self, prompt, payload, schema):
                self.payload = payload
                return schema(
                    assessments=[
                        {
                            "criterion_id": "T_inc_001",
                            "decision": "MET",
                            "reason": "Documented diagnosis.",
                            "evidence_fact_ids": ["F0"],
                            "missing_information": [],
                        }
                    ]
                )

        provider = Provider()
        rows = judge_batch(provider, patient_fixture(), "Why?", {"trial_id": "T"}, items)
        self.assertEqual(provider.payload["items"][0]["patient_evidence"][0]["fact_id"], "F0")
        self.assertEqual(provider.payload["response_language"], "English")
        self.assertEqual(rows[0].evidence_fact_ids, ["original/source.json#Condition/diabetes"])
        self.assertEqual(rows[0].decision, Decision.MET)

    def test_real_context_is_bounded_and_t2d_code_is_preserved(self):
        workflow = ScreeningWorkflow()
        patient = workflow.store.patient(workflow.manifest["demo_patient_ids"][0])
        selector = ContextSelector(patient)
        for text in ("HbA1c between 7.5% and 10.5%", "Clinical diagnosis of type 2 diabetes"):
            context = selector.select(criterion(text))
            self.assertLessEqual(len(json.dumps(context, ensure_ascii=False)), 12024)
            expected = "4548-4" if "HbA1c" in text else "44054006"
            self.assertTrue(
                any(
                    c.get("code") == expected
                    for f in context
                    for c in (f.get("code") or {}).get("coding", [])
                )
            )


if __name__ == "__main__":
    unittest.main()
