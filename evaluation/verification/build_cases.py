"""Reconstruct fixed inputs; --check never writes or overwrites human review."""
import argparse
import csv
import importlib.util
import json
import re

from common import (ROOT, REPO, PATIENT_IDS, TRIAL_IDS, STATUSES, csv_bytes,
                    fact_ids, json_bytes, normalize_text, read_jsonl, sha256)

REFERENCE_FIELDS = ["pair_id", "in_round1", "patient_id", "trial_id", "criterion_id",
                    "criterion_type", "criterion_text", "reference_status", "reference_evidence",
                    "reference_reasoning", "needs_review", "review_state", "reviewer", "review_notes"]


def expected_files():
    patient_path = REPO / "services/patient_processing/data/processed/patients.jsonl"
    trial_path = REPO / "services/trial_ingestion/data/processed/trials.jsonl"
    criteria_path = trial_path.with_name("criteria.jsonl")
    patients = {p["patient_id"]: p for p in read_jsonl(patient_path)}
    trials = {t["trial_id"]: t for t in read_jsonl(trial_path)}
    all_criteria = read_jsonl(criteria_path)
    source_manifest = json.loads((REPO / "services/patient_processing/data/sample_source.json").read_text())
    parser_path = REPO / "services/trial_ingestion/scripts/parse_criteria.py"
    spec = importlib.util.spec_from_file_location("trial_parser", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    files, references, cases, audits = {}, [], [], []
    for patient_id in PATIENT_IDS:
        patient = patients[patient_id]
        raw_path = REPO / patient["source_file"]
        if sha256(raw_path.read_bytes()) != source_manifest["selected_files"][raw_path.name]:
            raise ValueError(f"Official sample hash differs: {patient_id}")
        # Match the processed record against the checked-in raw FHIR and processor.
        processor_path = REPO / "services/patient_processing/scripts/process_patients.py"
        proc_spec = importlib.util.spec_from_file_location("patient_processor", processor_path)
        processor = importlib.util.module_from_spec(proc_spec)
        proc_spec.loader.exec_module(processor)
        from datetime import date
        rebuilt = processor.process_bundle(json.loads((REPO / patient["source_file"]).read_text()),
                                           patient["source_file"], date.fromisoformat(patient["reference_date"]))
        if patient != rebuilt:
            raise ValueError(f"Raw FHIR does not reproduce stored patient: {patient_id}")
        files[f"inputs/patients/{patient_id}.json"] = json_bytes(patient)
    for trial_id in TRIAL_IDS:
        trial = trials[trial_id]
        criteria = [c for c in all_criteria if c["trial_id"] == trial_id]
        if parser.parse_trial_criteria(trial) != criteria:
            raise ValueError(f"Stored parsed criteria differ from source parser: {trial_id}")
        # Independently remove source list markers and compare ALL remaining text.
        # This checks coverage as well as agreement with the original parser.
        raw_clauses = []
        for line in trial["eligibility_text"].splitlines():
            if re.fullmatch(r"\s*(Inclusion|Exclusion) Criteria:\s*", line):
                continue
            raw_clauses.append(re.sub(r"^\s*(?:\d+\\?\.|\*|\\?-)\s+", "", line))
        if normalize_text(" ".join(raw_clauses)) != normalize_text(" ".join(c["criterion_text"] for c in criteria)):
            raise ValueError(f"Eligibility source text coverage differs: {trial_id}")
        if len(criteria) != 10 or any(c["parse_status"] != "parsed" for c in criteria):
            raise ValueError(f"Unexpected source criterion structure: {trial_id}")
        files[f"inputs/trials/{trial_id}.json"] = json_bytes({"trial_record": trial, "parsed_criteria": criteria})
        audits.append({"trial_id": trial_id, "snapshot_date": trial["snapshot_date"],
                       "criterion_count": len(criteria), "ambiguous_count": 0,
                       "all_raw_clause_text_preserved": True,
                       "stored_parser_output_matches": True,
                       "limitation": "Compound clauses remain whole; parsed does not establish clinical clarity. No live website verification."})
    for number in range(1, 7):
        pair = f"V{number:02d}"
        patient_id = PATIENT_IDS[(number - 1) // 3]
        trial_id = TRIAL_IDS[(number - 1) % 3]
        patient = patients[patient_id]
        criteria = [c for c in all_criteria if c["trial_id"] == trial_id]
        trial_input = json.loads(files[f"inputs/trials/{trial_id}.json"])
        a = {"pair_id": pair, "patient": patient, **trial_input}
        b = {"pair_id": pair, "patient": patient, "trial_id": trial_id}
        files[f"uploads/A/{pair}.json"] = json_bytes(a)
        files[f"uploads/B/{pair}.json"] = json_bytes(b)
        cases.append({"pair_id": pair, "patient_id": patient_id, "trial_id": trial_id,
                      "reference_date": patient["reference_date"], "trial_snapshot_date": trials[trial_id]["snapshot_date"],
                      "in_round1": "TRUE" if number <= 3 else "FALSE",
                      "historical_run_state": "A_AND_B_RECOVERED" if number <= 3 else "PREPARED_NOT_RUN",
                      "selection_reason": "Reconstructed historical pair; source clauses cover numeric, time, medication, history and missing evidence.",
                      "input_provenance": "RECONSTRUCTED_FROM_COMMIT_9d6886a_ORIGINAL_UPLOAD_BYTES_UNKNOWN"})
        for c in criteria:
            row = {f: "" for f in REFERENCE_FIELDS}
            row.update(pair_id=pair, in_round1=cases[-1]["in_round1"], patient_id=patient_id,
                       trial_id=trial_id, criterion_id=c["criterion_id"], criterion_type=c["criterion_type"],
                       criterion_text=c["criterion_text"], reference_evidence="[]", needs_review="TRUE",
                       review_state="UNREVIEWED")
            if number > 3:
                row["review_state"] = "OUTSIDE_ROUND1"
            if pair == "V01" and c["criterion_id"] == "NCT07156539_exc_004":
                codes = {"162864005", "237602007"}
                evidence = [f["fact_id"] for f in patient["conditions"]
                            if any(x.get("system") == "http://snomed.info/sct" and x.get("code") in codes
                                   for x in (f.get("code") or {}).get("coding", []))]
                if len(evidence) != 2:
                    raise ValueError("Historical endocrine-exclusion evidence changed")
                row.update(reference_status="UNKNOWN", reference_evidence=json.dumps(evidence),
                           reference_reasoning="User confirmed obesity and metabolic syndrome do not trigger this exclusion. Other relevant endocrine history is not established; missing records do not establish absence.",
                           needs_review="FALSE", review_state="CONFIRMED_BY_USER_HISTORY", reviewer="user (prior chat)",
                           review_notes="Decision carried from prior chat turns 01a140c8-e86d-733f-945e-6c08c6405573 and 01a140ca-3fd9-7067-bdf4-f43f1593b265. Evidence links reconstructed from source conditions; original CSV bytes unavailable.")
            references.append(row)
    files["cases.csv"] = csv_bytes(cases, list(cases[0]))
    files["trial_audit.json"] = json_bytes(audits)
    protocol_paths = [ROOT / "prompts/mode_A.md", ROOT / "prompts/mode_B.md"]
    source_paths = [patient_path, trial_path, criteria_path, parser_path,
                    REPO / "services/patient_processing/scripts/process_patients.py",
                    REPO / "services/patient_processing/data/sample_source.json"]
    source_paths.extend(REPO / patients[p]["source_file"] for p in PATIENT_IDS)
    manifest = {"reconstruction_date": "2026-10-18", "source_commit": "9d6886a7ea925d9068bc38d669987036727873d5",
                "original_upload_hashes": "UNAVAILABLE: reconstructed files do not establish original upload byte identity",
                "sources": {str(p.relative_to(REPO)): sha256(p.read_bytes()) for p in source_paths},
                "reconstructed_protocols": {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in protocol_paths},
                "fixed_files": {p: sha256(data) for p, data in files.items()},
                "mutable_reference_table": "templates/reference_answers.csv",
                "round1_pairs": ["V01", "V02", "V03"], "prepared_only_pairs": ["V04", "V05", "V06"]}
    files["manifest.json"] = json_bytes(manifest)
    return files, references, patients


def check_references(expected, patients):
    path = ROOT / "templates/reference_answers.csv"
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != REFERENCE_FIELDS:
            raise ValueError("Reference table fields changed")
        rows = list(reader)
    expected_map = {(r["pair_id"], r["criterion_id"]): r for r in expected}
    if len(rows) != len(expected_map) or {(r["pair_id"], r["criterion_id"]) for r in rows} != set(expected_map):
        raise ValueError("Missing or duplicate reference rows")
    for row in rows:
        key = row["pair_id"], row["criterion_id"]
        for name in ("patient_id", "trial_id", "criterion_type", "criterion_text", "in_round1"):
            if row[name] != expected_map[key][name]:
                raise ValueError(f"Reference source changed: {key} {name}")
        evidence = json.loads(row["reference_evidence"])
        if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence) or not set(evidence) <= fact_ids(patients[row["patient_id"]]):
            raise ValueError(f"Invalid reference evidence: {key}")
        if row["reference_status"] not in STATUSES | {""} or row["needs_review"] not in {"TRUE", "FALSE"}:
            raise ValueError(f"Invalid reference state: {key}")
        if row["needs_review"] == "FALSE" and (not row["reference_status"] or not row["reviewer"] or not row["reference_reasoning"]):
            raise ValueError(f"Reviewed reference missing decision/reviewer/reasoning: {key}")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, references, patients = expected_files()
    for name, data in files.items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                raise ValueError(f"Fixed input missing or changed: {name}")
        else:
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"Refusing to replace changed fixed input: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    ref_path = ROOT / "templates/reference_answers.csv"
    if not args.check and not ref_path.exists():
        ref_path.parent.mkdir(parents=True, exist_ok=True)
        ref_path.write_bytes(csv_bytes(references, REFERENCE_FIELDS))
    rows = check_references(references, patients)
    reviewed = sum(r["in_round1"] == "TRUE" and r["needs_review"] == "FALSE" for r in rows)
    print(f"{'Checked' if args.check else 'Built'} 6 A/B input pairs; 30 source criteria; 60 reference rows; {reviewed}/30 round-one references confirmed.")


if __name__ == "__main__":
    main()
