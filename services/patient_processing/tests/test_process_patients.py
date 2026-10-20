"""Tests use official sample Bundles and clearly synthetic edge-case fixtures."""

import json
import unittest
from datetime import date
from pathlib import Path

from services.patient_processing.scripts.process_patients import process_bundle, coverage_report

RAW = Path(__file__).resolve().parents[1] / "data/raw"
REFERENCE_DATE = date(2021, 11, 30)


class PatientProcessingTests(unittest.TestCase):
    def test_official_samples_keep_patient_links_provenance_and_medication_references(self):
        records = []
        for path in sorted(RAW.glob("*.json")):
            bundle = json.loads(path.read_text())
            record = process_bundle(bundle, str(path), REFERENCE_DATE)
            records.append(record)
            self.assertEqual(record["patient_id"], record["demographics"]["source_resource_id"])
            self.assertFalse(record["unresolved_medication_references"])
            facts = record["conditions"] + record["observations"] + record["procedures"] + [
                fact for group in record["medications"].values() for fact in group
            ]
            for item in facts:
                self.assertEqual(item["source_file"], str(path))
                self.assertEqual(item["fact_id"], f"{path}#{item['resource_type']}/{item['source_resource_id']}")
                if "subject_reference" in item:
                    self.assertEqual(item["subject_reference"], "urn:uuid:" + record["patient_id"])
            medication_ids = {item["source_resource_id"] for item in record["medications"]["definitions"]}
            for kind in ("requests", "administrations", "dispenses", "statements"):
                for item in record["medications"][kind]:
                    if item["medication_reference"]:
                        self.assertIn(item["resolved_medication_id"], medication_ids)
        self.assertEqual(len(records), 4)
        self.assertEqual(sum(len(r["medications"]["requests"]) for r in records), 18)
        self.assertEqual(sum(len(r["medications"]["administrations"]) for r in records), 2)
        self.assertEqual(sum(len(r["procedures"]) for r in records), 112)
        self.assertEqual(coverage_report(records)["adult_t2d_patients"], 3)

    def test_official_procedure_and_medication_definition_are_separate_evidence(self):
        path = next(RAW.glob("Shakira*.json"))
        bundle = json.loads(path.read_text())
        record = process_bundle(bundle, str(path), REFERENCE_DATE)
        by_id = {entry["resource"]["id"]: entry["resource"] for entry in bundle["entry"]
                 if entry.get("resource", {}).get("id")}
        procedure = record["procedures"][0]
        original = by_id[procedure["source_resource_id"]]
        self.assertEqual(procedure["code"], original["code"])
        self.assertEqual(procedure["raw_status"], original["status"])
        self.assertEqual(procedure["performed_period"], original["performedPeriod"])
        self.assertEqual(procedure["status_at_reference_date"], "undetermined")
        self.assertEqual(len(record["medications"]["definitions"]), 2)
        self.assertEqual(len(record["medications"]["administrations"]), 2)
        self.assertEqual(len(record["medications"]["requests"]), 8)
        self.assertTrue(all(item["status_at_reference_date"] == "undetermined"
                            for item in record["medications"]["definitions"]))
        for kind, fact in (("Condition", record["conditions"][0]),
                           ("Observation", record["observations"][0]),
                           ("MedicationRequest", next(x for x in record["medications"]["requests"]
                                                      if x["medication_reference"])),
                           ("MedicationAdministration", record["medications"]["administrations"][0])):
            source = by_id[fact["source_resource_id"]]
            self.assertEqual(fact["resource_type"], kind)
            self.assertEqual(source["subject"]["reference"], fact["subject_reference"])
            self.assertEqual(fact["raw_status"], source.get("clinicalStatus", source.get("status")))
            self.assertEqual(fact["status_at_reference_date"], "undetermined")
        definition_ids = {item["source_resource_id"] for item in record["medications"]["definitions"]}
        for request in record["medications"]["requests"]:
            if request["medication_reference"]:
                self.assertIn(request["resolved_medication_id"], definition_ids)
                self.assertEqual(request["resource_type"], "MedicationRequest")

    def test_synthetic_fixture_exact_date_boundary_and_period(self):
        # Handwritten boundary fixture, not an official Synthea patient.
        patient = {"resourceType": "Patient", "id": "p", "birthDate": "2003-11-30"}
        def fact(kind, identifier, field, value):
            return {"resourceType": kind, "id": identifier, "subject": {"reference": "Patient/p"},
                    "code": {"coding": [{"system": "test", "code": identifier}]}, field: value}
        items = [patient,
                 fact("Observation", "on", "effectiveDateTime", "2021-11-30T23:59:59-05:00"),
                 fact("Observation", "after", "effectiveDateTime", "2021-12-01T00:00:00-05:00"),
                 fact("Procedure", "period-on", "performedPeriod", {"start": "2021-11-30", "end": "2021-12-01"}),
                 fact("Procedure", "period-after", "performedPeriod", {"start": "2021-12-01"})]
        bundle = {"resourceType": "Bundle", "entry": [{"resource": item} for item in items]}
        record = process_bundle(bundle, "TEST_FIXTURE.json", REFERENCE_DATE)
        self.assertEqual(record["demographics"]["age_years_at_reference"], 18)
        self.assertEqual([r["source_resource_id"] for r in record["observations"]], ["on"])
        self.assertEqual([r["source_resource_id"] for r in record["procedures"]], ["period-on"])
        self.assertEqual(record["procedures"][0]["performed_period"]["end"], "2021-12-01")

    def test_synthetic_fixture_cutoff_missing_data_and_wrong_patient(self):
        # Handwritten fixture for behavior testing; it is not a Synthea sample.
        patient = {"resourceType": "Patient", "id": "p1", "birthDate": "2000-12-01"}
        undated = {"resourceType": "Condition", "id": "c1", "subject": {"reference": "Patient/p1"}}
        future = {"resourceType": "Observation", "id": "o1", "subject": {"reference": "Patient/p1"},
                  "issued": "2022-01-01", "valueQuantity": {"value": 7, "unit": "mg/dL"}}
        bundle = {"resourceType": "Bundle", "entry": [{"resource": x} for x in (patient, undated, future)]}
        record = process_bundle(bundle, "TEST_FIXTURE.json", REFERENCE_DATE)
        self.assertEqual(record["observations"], [])
        self.assertEqual(record["demographics"]["age_years_at_reference"], 20)
        self.assertIsNone(record["conditions"][0]["code"])
        self.assertTrue(any(w["reason"].startswith("missing_event_date") for w in record["warnings"]))
        self.assertEqual(record["conditions"][0]["event_time_certainty"], "undated")
        self.assertEqual(record["conditions"][0]["status_at_reference_date"], "undetermined")
        self.assertTrue(any(w["reason"].startswith("missing_code") for w in record["warnings"]))
        future["subject"]["reference"] = "Patient/other"
        with self.assertRaisesRegex(ValueError, "invalid patient reference"):
            process_bundle(bundle, "TEST_FIXTURE.json", date(2022, 1, 1))

    def test_synthetic_fixture_unresolved_medication_reference_warns(self):
        # Handwritten fixture for behavior testing; it is not a Synthea sample.
        bundle = {"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Patient", "id": "p1"}},
            {"resource": {"resourceType": "MedicationRequest", "id": "m1", "status": "active",
                          "subject": {"reference": "Patient/p1"}, "authoredOn": "2021-01-01",
                          "medicationReference": {"reference": "Medication/missing"}}},
        ]}
        record = process_bundle(bundle, "TEST_FIXTURE.json", REFERENCE_DATE)
        self.assertEqual(record["unresolved_medication_references"], ["Medication/missing"])
        self.assertIsNone(record["medications"]["requests"][0]["code"])
        self.assertEqual(record["medications"]["administrations"], [])

    def test_synthetic_fixture_missing_birth_and_observation_value(self):
        # Handwritten missing-data fixture, not an official Synthea patient.
        bundle = {"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Patient", "id": "p"}},
            {"resource": {"resourceType": "Observation", "id": "o", "status": "final",
                          "subject": {"reference": "Patient/p"}, "effectiveDateTime": "2021-11-30",
                          "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4"}]}}},
        ]}
        record = process_bundle(bundle, "TEST_FIXTURE.json", REFERENCE_DATE)
        self.assertIsNone(record["demographics"]["age_years_at_reference"])
        self.assertIsNone(record["observations"][0]["value"])
        self.assertEqual(record["observations"][0]["event_time_certainty"], "dated")
        self.assertEqual(record["observations"][0]["raw_status"], "final")
        self.assertEqual(record["observations"][0]["status_at_reference_date"], "undetermined")


if __name__ == "__main__":
    unittest.main()
