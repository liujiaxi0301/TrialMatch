"""MS4 system validation: end-to-end evidence provenance."""

import unittest

from services.rag_workflow.config import Settings
from services.rag_workflow.data import patient_facts
from services.rag_workflow.schemas import ScreenRequest
from services.rag_workflow.workflow import ScreeningWorkflow


class ProvenanceValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = ScreeningWorkflow(Settings(mode="offline"))

    def test_multi_patient_screening_provenance(self):
        workflow = self.workflow

        for patient_id in workflow.manifest["demo_patient_ids"]:
            with self.subTest(patient_id=patient_id):
                patient = workflow.store.patient(patient_id)
                fact_ids = {fact["fact_id"] for fact in patient_facts(patient)}

                result = workflow.screen(
                    ScreenRequest(
                        patient_id=patient_id,
                        question="Which type 2 diabetes trials may suit this patient?",
                        top_k=2,
                    )
                )

                # Patient identity and data provenance
                self.assertEqual(result.result_status, "OK")
                self.assertEqual(result.patient_id, patient_id)
                self.assertEqual(
                    result.patient_reference_date,
                    patient["reference_date"],
                )
                self.assertEqual(
                    result.provenance["source_sha256"],
                    workflow.store.hashes,
                )
                self.assertEqual(len(result.candidate_trials), 2)

                for trial in result.candidate_trials:
                    # Trial belongs to the selected source snapshot
                    self.assertIn(
                        trial.trial_id,
                        workflow.manifest["trial_ids"],
                    )
                    source_trial = workflow.store.trials[trial.trial_id]
                    self.assertEqual(
                        trial.trial_snapshot_date,
                        source_trial["snapshot_date"],
                    )

                    # Returned criteria match source criteria
                    original_criteria = {
                        row["criterion_id"]: row for row in workflow.store.criteria[trial.trial_id]
                    }
                    assessments = trial.criteria_assessments

                    self.assertEqual(
                        len(assessments),
                        len(original_criteria),
                    )
                    self.assertEqual(
                        {a.criterion_id for a in assessments},
                        set(original_criteria),
                    )

                    for assessment in assessments:
                        original = original_criteria[assessment.criterion_id]

                        self.assertEqual(
                            assessment.criterion_text,
                            original["criterion_text"],
                        )
                        self.assertEqual(
                            assessment.criterion_type,
                            original["criterion_type"],
                        )

                        # No cross-patient evidence references
                        self.assertTrue(set(assessment.evidence_fact_ids) <= fact_ids)
                        self.assertTrue(set(assessment.context_fact_ids) <= fact_ids)
                        self.assertTrue(set(assessment.evidence_fact_ids) <= set(trial.evidence))

                    self.assertTrue(set(trial.evidence) <= fact_ids)


if __name__ == "__main__":
    unittest.main()
