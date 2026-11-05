"""Audit edge cases use synthetic fixtures, never model-run result files."""
import copy
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_cohort import audit_trial_text, observation_summary, patient_summary


def fixture_observation(fid, effective=None, issued=None):
    return {"fact_id": fid, "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]},
            "effective_date": effective, "issued_date": issued, "value": {"type": "Quantity", "data": {"value": 7.5, "unit": "%"}}}


class CohortCoverageTests(unittest.TestCase):
    def test_multiline_source_omission_rejects_candidate_trial(self):
        trial = {"eligibility_text": "Inclusion Criteria:\n\n* High risk defined as:\n\nBMI >25\n\n* Age >40\n\nExclusion Criteria:\n\n* Unable to walk"}
        incomplete = [{"criterion_text": t} for t in ("High risk defined as:", "Age >40", "Unable to walk")]
        self.assertFalse(audit_trial_text(trial, incomplete))
        complete = [{"criterion_text": t} for t in ("High risk defined as: BMI >25", "Age >40", "Unable to walk")]
        self.assertTrue(audit_trial_text(trial, complete))

    def test_measurement_ties_preserved_and_issued_not_used_as_measurement(self):
        patient = {"observations": [fixture_observation("first", "2021-11-01T09:00:00Z"),
                                     fixture_observation("second", "2021-11-01T12:00:00Z"),
                                     fixture_observation("issued_only", issued="2021-11-29T09:00:00Z"),
                                     fixture_observation("future", "2021-12-01T09:00:00Z")]}
        result = observation_summary(patient, "4548-4", date(2021, 11, 30))
        self.assertEqual([r["fact_id"] for r in result["latest_facts"]], ["first", "second"])
        self.assertEqual(result["undated_count"], 1)
        self.assertEqual(result["after_reference_count"], 1)
        self.assertEqual(result["days_before_reference"], 29)

    def fixture_patient(self):
        # Explicitly synthetic test-only data.
        return {"patient_id": "fixture", "reference_date": "2021-11-30", "schema_version": "0.3",
                "source_file": "fixture.json", "demographics": {"fact_id": "fixture#Patient/test", "birth_date": "1980-12-01", "age_years_at_reference": 40, "deceased_date": None},
                "conditions": [], "observations": [],
                "medications": {k: [] for k in ("requests", "definitions", "administrations", "dispenses", "statements")},
                "unprocessed_resource_types": {}}

    def test_recorded_death_gate_and_missing_death_not_alive_claim(self):
        patient = self.fixture_patient()
        result = patient_summary(patient)
        self.assertIn("NOT_CONFIRMED_ALIVE", result["candidate_gate"])
        patient["demographics"]["deceased_date"] = "2021-11-30T23:00:00-05:00"
        self.assertEqual(patient_summary(patient)["candidate_gate"], "EXCLUDE_RECORDED_DECEASED")
        patient["demographics"]["deceased_date"] = "2021-12-01T00:00:00Z"
        self.assertFalse(patient_summary(patient)["recorded_deceased_on_or_before_reference"])

    def test_medication_definition_and_order_not_actual_administration(self):
        patient = self.fixture_patient()
        fact = {"fact_id": "fixture#Medication/test", "code": {"text": "insulin example"}}
        patient["medications"]["definitions"] = [fact]
        patient["medications"]["requests"] = [copy.deepcopy(fact)]
        result = patient_summary(patient)
        hits = result["drug_name_hits_not_terminology_classification"]["insulin_name_hit"]
        self.assertEqual(len(hits["definitions"]), 1)
        self.assertEqual(len(hits["requests"]), 1)
        self.assertEqual(hits["administrations"], [])
        self.assertEqual(result["stable_actual_use_duration"], "NOT_ESTABLISHED_BY_THIS_AUDIT")


if __name__ == "__main__":
    unittest.main()
