"""V2 protocol and recorder tests; simulated outputs stay in memory/temp dirs."""
import copy
import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, json_bytes
from build_v2 import PAIRS, V2, age_on
from record_v2 import export_tables, record_response, validate_response


def response_fixture(upload):
    """Fabricated structure for validator tests, not a model assessment."""
    criteria = []
    summary = {"supported_criterion_ids": [], "conflicting_criterion_ids": [], "unresolved_criterion_ids": []}
    for c in upload["parsed_criteria"]:
        status = "MET" if c["criterion_id"].endswith("exc_001") else "UNKNOWN"
        group = "conflicting_criterion_ids" if status == "MET" else "unresolved_criterion_ids"
        summary[group].append(c["criterion_id"])
        criteria.append({**{f: c[f] for f in ("criterion_id", "criterion_type", "criterion_text")},
                         "precheck_status": status, "evidence_fact_ids": [],
                         "reasoning": "Synthetic test-only structural fixture, not clinical reasoning.",
                         "missing_clinical_information": [], "required_workflow_followup": []})
    return {"pair_id": upload["pair_id"], "trial_id": upload["trial_record"]["trial_id"],
            "assessment_date": upload["assessment_date"], "actual_trial_dates": copy.deepcopy(upload["actual_trial_dates"]),
            "search_status": "NOT_USED", "context_limitations": [], "source_criterion_issues": [],
            "criteria": criteria, "summary": summary, "overall_enrollment_decision": None}


class V2Tests(unittest.TestCase):
    def setUp(self):
        self.upload = json.loads((V2 / "uploads/A/V2P01.json").read_text())

    def test_complete_inputs_and_no_reference_leak_in_upload_kit(self):
        for pair, pid in PAIRS.items():
            upload = json.loads((V2 / f"uploads/A/{pair}.json").read_text())
            patient = json.loads((V2 / f"proposals/patients/{pid}.json").read_text())
            self.assertEqual(upload["patient"], patient)
            self.assertEqual(upload["assessment_date"], "2021-11-30")
            self.assertTrue(all(v is None for v in upload["actual_trial_dates"].values()))
            self.assertEqual(len(upload["parsed_criteria"]), 5)
            self.assertNotIn("reference_precheck_status", upload)
            self.assertNotIn("suggested_precheck_status", upload)
        with ZipFile(V2 / "manual_upload_kit.zip") as archive:
            self.assertEqual(set(archive.namelist()), {"uploads/A/V2P01.json", "uploads/A/V2P02.json", "prompt_A.md", "RUN_FIRST.md"})
            self.assertEqual(archive.read("uploads/A/V2P01.json"), (V2 / "uploads/A/V2P01.json").read_bytes())

    def test_age_uses_explicit_assessment_date_and_birthday_boundary(self):
        birthday = date(1977, 12, 5)
        self.assertEqual(age_on(birthday, date(2021, 12, 4)), 43)
        self.assertEqual(age_on(birthday, date(2021, 12, 5)), 44)
        self.assertEqual(age_on(date(1994, 8, 12), date(2021, 11, 30)), 27)

    def test_exclusion_met_is_conflicting_not_supported(self):
        fixture = response_fixture(self.upload)
        self.assertEqual(validate_response(json_bytes(fixture), self.upload)["validation_warnings"], [])
        cid = fixture["summary"]["conflicting_criterion_ids"].pop()
        fixture["summary"]["supported_criterion_ids"].append(cid)
        warnings = validate_response(json_bytes(fixture), self.upload)["validation_warnings"]
        self.assertIn("SUMMARY_POLARITY_OR_COVERAGE_MISMATCH:supported_criterion_ids", warnings)

    def test_invented_trial_date_wrong_citation_and_final_decision_flagged(self):
        fixture = response_fixture(self.upload)
        fixture["actual_trial_dates"]["consent_date"] = "2021-11-30"
        fixture["criteria"][0]["evidence_fact_ids"] = ["fixture#NonexistentFact"]
        fixture["overall_enrollment_decision"] = "eligible"
        warnings = validate_response(json_bytes(fixture), self.upload)["validation_warnings"]
        self.assertIn("ACTUAL_TRIAL_DATES_NOT_PRESERVED_AS_UNKNOWN", warnings)
        self.assertIn("OVERALL_ENROLLMENT_DECISION_NOT_NULL", warnings)
        self.assertTrue(any(w.startswith("UNKNOWN_FACT_IDS:") for w in warnings))

    def test_omitted_clause_is_not_discarded_as_workflow_only(self):
        fixture = response_fixture(self.upload)
        fixture["criteria"].pop()
        warnings = validate_response(json_bytes(fixture), self.upload)["validation_warnings"]
        self.assertIn("CRITERION_COUNT_MISMATCH", warnings)
        self.assertTrue(any(w.startswith("MISSING_SOURCE_CRITERIA:") for w in warnings))

    def test_failed_response_preserved_idempotently_and_not_scored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "uploads/A").mkdir(parents=True)
            for name in ("uploads/A/V2P01.json", "prompt_A.md", "policy.json", "experiment_manifest.json"):
                (root / name).write_bytes((V2 / name).read_bytes())
            raw = b"SYNTHETIC TEST ONLY: upload failed; no assessment returned"
            args = ("V2P01", raw, "fixture_only", "test-model", "0", "test fixture", "FALSE", "UNKNOWN")
            record = record_response(*args, root=root)
            self.assertEqual(record["parse_status"], "INVALID_JSON")
            metadata = (root / "results/records/fixture_only.json").read_bytes()
            record_response(*args, root=root)
            self.assertEqual((root / "results/records/fixture_only.json").read_bytes(), metadata)
            with self.assertRaises(ValueError):
                record_response("V2P01", b"changed", "fixture_only", "test-model", "0", "test fixture", "FALSE", "UNKNOWN", root=root)
            self.assertEqual((root / "results/raw/A/fixture_only.txt").read_bytes(), raw)
            export_tables(root)
            with (root / "results/precheck_results_A.csv").open(newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])
            self.assertFalse((root / "templates/reference_answers.csv").exists())


if __name__ == "__main__":
    unittest.main()
