"""Recovery checks; fabricated cases stay inside temporary test directories."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ROOT, csv_bytes, json_bytes, parse_response, sha256
from build_cases import REFERENCE_FIELDS, check_references, expected_files
from record_run import analyze_response, export_tables, write_record
from unittest.mock import patch


class RecoveryTests(unittest.TestCase):
    def test_recovered_bytes_fact_references_and_source_alignment(self):
        manifest = json.loads((ROOT / "recovery_manifest.json").read_text())
        counts = {}
        for item in manifest["raw_responses"]:
            data = (ROOT / item["raw_response_path"]).read_bytes()
            self.assertEqual(sha256(data), item["response_sha256"])
            source = json.loads((ROOT / f"uploads/A/{item['pair_id']}.json").read_text())
            analyzed = analyze_response(data, source, item["pair_id"])
            self.assertEqual(analyzed["parse_status"], "PARSED")
            self.assertFalse(any("FACT_IDS" in x for x in analyzed["validation_warnings"]))
            counts[item["pair_id"], item["mode"]] = analyzed["aligned_criterion_count"]
            if item["mode"] == "A":
                self.assertTrue(analyzed["context_limitations"])
        self.assertEqual(counts.pop(("V01", "B")), 9)
        self.assertTrue(all(n == 10 for n in counts.values()))

    def test_alignment_uses_text_not_web_id_or_order(self):
        source = json.loads((ROOT / "uploads/A/V02.json").read_text())
        obj, _ = parse_response((ROOT / "results/raw/B/recovered_V02_B.txt").read_bytes())
        obj["criteria"].reverse()
        for i, c in enumerate(obj["criteria"]):
            c["criterion_id"] = f"arbitrary_{i}"
        result = analyze_response(json_bytes(obj), source, "V02")
        self.assertEqual(result["aligned_criterion_count"], 10)
        self.assertFalse(result["validation_warnings"])

    def test_omission_invalid_fact_and_status_remain_visible(self):
        source = json.loads((ROOT / "uploads/A/V01.json").read_text())
        obj, _ = parse_response((ROOT / "results/raw/A/recovered_V01_A.txt").read_bytes())
        obj["criteria"].pop()
        obj["criteria"][0]["evidence_fact_ids"] = ["SYNTHETIC_TEST_ONLY#Condition/nonexistent"]
        obj["criteria"][0]["status"] = "ELIGIBLE"
        warnings = analyze_response(json_bytes(obj), source, "V01")["validation_warnings"]
        self.assertIn("CRITERION_COUNT_MISMATCH", warnings)
        self.assertTrue(any(x.startswith("UNKNOWN_FACT_IDS:") for x in warnings))
        self.assertTrue(any(x.startswith("INVALID_STATUS:") for x in warnings))
        self.assertTrue(any("NCT07156539_exc_006" in x for x in warnings))

    def test_invalid_json_is_preserved_and_run_id_cannot_replace_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "uploads/A").mkdir(parents=True)
            (root / "uploads/A/V01.json").write_bytes((ROOT / "uploads/A/V01.json").read_bytes())
            data = b"SYNTHETIC TEST FIXTURE: request failed, no JSON response"
            record = write_record("V01", "A", data, "fixture", "test", "0", "test fixture", "FALSE", root=root)
            self.assertEqual(record["parse_status"], "INVALID_JSON")
            original_record = (root / "results/records/fixture.json").read_bytes()
            write_record("V01", "A", data, "fixture", "test", "0", "test fixture", "FALSE", root=root)
            self.assertEqual((root / "results/records/fixture.json").read_bytes(), original_record)
            with self.assertRaises(ValueError):
                write_record("V01", "A", b"changed", "fixture", "test", "0", "test fixture", "FALSE", root=root)
            self.assertEqual((root / "results/raw/A/fixture.txt").read_bytes(), data)
            export_tables(root)
            with (root / "results/runs_A.csv").open(newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream))[0]["parse_status"], "INVALID_JSON")
            with (root / "results/model_results_A.csv").open(newline="") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])

    def test_reference_check_accepts_human_edits_and_rejects_false_evidence(self):
        _, expected, patients = expected_files()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "templates").mkdir()
            row = expected[0]
            row.update(reference_status="UNKNOWN", reference_reasoning="Synthetic test-only human review.",
                       reviewer="test fixture", needs_review="FALSE", review_state="CONFIRMED_TEST_FIXTURE")
            path = root / "templates/reference_answers.csv"
            path.write_bytes(csv_bytes(expected, REFERENCE_FIELDS))
            with patch("build_cases.ROOT", root):
                self.assertEqual(check_references(expected, patients)[0]["reviewer"], "test fixture")
                row["reference_evidence"] = '["SYNTHETIC_NONEXISTENT_FACT"]'
                path.write_bytes(csv_bytes(expected, REFERENCE_FIELDS))
                with self.assertRaises(ValueError):
                    check_references(expected, patients)


if __name__ == "__main__":
    unittest.main()
