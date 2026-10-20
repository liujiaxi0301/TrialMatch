"""Build v2 offline test materials while preserving editable human-reference rows."""
import argparse
import csv
import io
import json
from datetime import date
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from common import ROOT, REPO, STATUSES, csv_bytes, fact_ids, json_bytes, sha256
from analyze_cohort import audit_trial_text, calendar_date, has_code

V2 = ROOT / "v2"
PAIRS = {"V2P01": "475803f3-ae29-ba8d-bdd1-25145a94eaee", "V2P02": "80534c6c-b12d-caa5-42de-b179fd7f9695"}
REFERENCE_FIELDS = ["pair_id", "patient_id", "trial_id", "criterion_id", "criterion_type", "criterion_text", "reference_precheck_status", "reference_evidence", "reference_reasoning", "needs_review", "reviewer", "review_notes"]


def age_on(birthday, assessment):
    return assessment.year - birthday.year - ((assessment.month, assessment.day) < (birthday.month, birthday.day))


def documented_t2d(patient):
    facts = [f for f in patient["conditions"] if has_code(f, "http://snomed.info/sct", "44054006")]
    dated = [(calendar_date(f.get("recorded_date")) or calendar_date(f.get("onset_date")), f) for f in facts]
    dated = [(d, f) for d, f in dated if d is not None]
    if not dated:
        raise ValueError("Selected case has no documented T2D date")
    return min(dated, key=lambda x: (x[0], x[1]["fact_id"]))


def expected_files():
    policy = json.loads((V2 / "policy.json").read_text())
    assessment = date.fromisoformat(policy["assessment_date"])
    if any(value is not None for value in policy["actual_trial_dates"].values()):
        raise ValueError("Actual trial dates must remain unknown in this protocol")
    trial_path = V2 / "proposals/trials/NCT06774950.json"
    trial = json.loads(trial_path.read_text())
    if not audit_trial_text(trial["trial_record"], trial["parsed_criteria"]):
        raise ValueError("Source trial criteria are incomplete")
    files, references, suggestions, cases = {}, [], [], []
    for pair, patient_id in PAIRS.items():
        patient_path = V2 / f"proposals/patients/{patient_id}.json"
        patient = json.loads(patient_path.read_text())
        if date.fromisoformat(patient["reference_date"]) != assessment:
            raise ValueError("This v2 scenario requires the approved 2021-11-30 cutoff/assessment alignment")
        death = calendar_date(patient["demographics"].get("deceased_date"))
        if death and death <= assessment:
            raise ValueError("Recorded-deceased patient selected for clinical case")
        data = {"pair_id": pair, "policy_version": policy["policy_version"], "assessment_date": assessment.isoformat(),
                "scenario": policy["scenario"], "actual_trial_dates": policy["actual_trial_dates"],
                "diagnosis_duration_rule": policy["diagnosis_duration_rule"],
                "patient": patient, "trial_record": trial["trial_record"], "parsed_criteria": trial["parsed_criteria"]}
        files[f"uploads/A/{pair}.json"] = json_bytes(data)
        birthday = date.fromisoformat(patient["demographics"]["birth_date"])
        age = age_on(birthday, assessment)
        diagnosed, diagnosis = documented_t2d(patient)
        cases.append({"pair_id": pair, "patient_id": patient_id, "trial_id": trial["trial_record"]["trial_id"],
                      "assessment_date": assessment.isoformat(), "trial_snapshot_date": trial["trial_record"]["snapshot_date"],
                      "input_path": f"uploads/A/{pair}.json", "input_sha256": sha256(files[f"uploads/A/{pair}.json"]),
                      "case_state": "READY_FOR_MANUAL_MODE_A_NOT_RUN", "reference_state": "UNREVIEWED_SUGGESTIONS"})
        for criterion in trial["parsed_criteria"]:
            suffix = criterion["criterion_id"].split("NCT06774950_")[1]
            evidence, proposal, reason, category = [], "UNKNOWN", "", ""
            if suffix == "inc_001":
                # These selected cases avoid anniversary boundaries; no fractional-year approximation.
                tenth_anniversary = diagnosed.replace(year=diagnosed.year + 10)
                proposal = "MET" if diagnosed <= assessment < tenth_anniversary else "NOT_MET"
                evidence = [diagnosis["fact_id"]]
                reason = f"Exact-coded T2D is documented on {diagnosed}; at assessment_date {assessment}, documented duration is less than 10 calendar years. This is a documented-history precheck, not proof of the first-ever true diagnosis date or actual enrollment status."
                category = "DOCUMENTED_DIAGNOSIS_DURATION"
            elif suffix == "inc_002":
                if age in (40, 65):
                    raise ValueError("Selected age falls on an unresolved source interval boundary")
                proposal = "MET" if 40 < age < 65 else "NOT_MET"
                evidence = [patient["demographics"]["fact_id"]]
                reason = f"Birth date {birthday} gives age {age} on assessment_date {assessment}; compare with source age range 40–65. This does not substitute for any real trial date."
                category = "AGE_AT_ASSESSMENT"
            elif suffix == "exc_001":
                reason = "The compound clinical exclusion includes severity and attending-physician judgment. Available records do not establish all branches absent or one definitely applicable; no-record is not a negative history."
                category = "CLINICAL_EVIDENCE_AND_INVESTIGATOR_REVIEW"
            elif suffix == "exc_002":
                evidence = [patient["demographics"]["fact_id"]]
                reason = "Source administrative gender is male; that field alone is not a direct pregnancy/breast-feeding assessment. Suggested UNKNOWN requires reviewer judgment about the accepted evidence contract; do not treat it as confirmed gold."
                category = "REPRODUCTIVE_STATUS_REVIEW"
            elif suffix == "exc_003":
                reason = "Consent capacity is not established. Lack of a signed consent document does not prove inability to consent. Requires a capacity assessment, not simply a signature or assumed date."
                category = "CONSENT_CAPACITY_ASSESSMENT"
            key = {k: criterion[k] for k in ("criterion_id", "criterion_type", "criterion_text")}
            row = {f: "" for f in REFERENCE_FIELDS}
            row.update(pair_id=pair, patient_id=patient_id, trial_id=criterion["trial_id"], **key,
                       reference_evidence="[]", needs_review="TRUE",
                       review_notes="V2 precheck only; proposals are in a separate file. No v1 confirmation is automatically transferred.")
            references.append(row)
            suggestions.append({"pair_id": pair, **key, "suggested_precheck_status": proposal,
                                "suggested_evidence": json.dumps(evidence), "suggested_reasoning": reason,
                                "evidence_category": category, "review_state": "UNREVIEWED_ASSISTANT_SUGGESTION"})
    files["cases.csv"] = csv_bytes(cases, list(cases[0]))
    files["templates/reference_suggestions.csv"] = csv_bytes(suggestions, list(suggestions[0]))
    quickstart = (V2 / "RUN_FIRST.md").read_bytes()
    prompt = (V2 / "prompt_A.md").read_bytes()
    package = io.BytesIO()
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in {**{n: d for n, d in files.items() if n.startswith("uploads/A/")}, "prompt_A.md": prompt, "RUN_FIRST.md": quickstart}.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
    files["manual_upload_kit.zip"] = package.getvalue()
    sources = [V2 / "policy.json", V2 / "prompt_A.md", V2 / "RUN_FIRST.md", trial_path, ROOT / "build_v2.py"]
    sources.extend(V2 / f"proposals/patients/{pid}.json" for pid in PAIRS.values())
    files["experiment_manifest.json"] = json_bytes({
        "policy_version": policy["policy_version"], "assessment_date": assessment.isoformat(),
        "actual_trial_dates": policy["actual_trial_dates"], "model_runs": "NOT_ESTABLISHED_BY_BUILDING_INPUTS",
        "sources_sha256": {str(p.relative_to(ROOT)): sha256(p.read_bytes()) for p in sources},
        "fixed_outputs_sha256": {name: sha256(data) for name, data in files.items()},
        "mutable_reference_table": "templates/reference_answers.csv",
        "labels_not_in_uploads": True, "all_reference_suggestions_unreviewed": True})
    return files, references


def check_reference_table(expected):
    with (V2 / "templates/reference_answers.csv").open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != REFERENCE_FIELDS:
            raise ValueError("Reference columns changed")
        rows = list(reader)
    keyed = {(r["pair_id"], r["criterion_id"]): r for r in expected}
    if len(rows) != len(keyed) or {(r["pair_id"], r["criterion_id"]) for r in rows} != set(keyed):
        raise ValueError("Missing or duplicate v2 reference rows")
    available = {pair: fact_ids(json.loads((V2 / f"uploads/A/{pair}.json").read_text())["patient"]) for pair in PAIRS}
    for row in rows:
        source = keyed[row["pair_id"], row["criterion_id"]]
        for field in ("patient_id", "trial_id", "criterion_type", "criterion_text"):
            if row[field] != source[field]:
                raise ValueError("Reference criterion identity changed")
        evidence = json.loads(row["reference_evidence"])
        if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence) or not set(evidence) <= available[row["pair_id"]]:
            raise ValueError("Invalid v2 reference evidence")
        if row["reference_precheck_status"] not in STATUSES | {""} or row["needs_review"] not in {"TRUE", "FALSE"}:
            raise ValueError("Invalid v2 reference label/review state")
        if row["needs_review"] == "FALSE" and not all(row[k] for k in ("reference_precheck_status", "reference_reasoning", "reviewer")):
            raise ValueError("Confirmed reference missing label/reason/reviewer")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, references = expected_files()
    for name, data in files.items():
        path = V2 / name
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                raise ValueError(f"Missing or changed v2 fixed file: {name}")
        else:
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"Refusing to replace changed v2 file: {name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    refpath = V2 / "templates/reference_answers.csv"
    if not args.check and not refpath.exists():
        refpath.write_bytes(csv_bytes(references, REFERENCE_FIELDS))
    rows = check_reference_table(references)
    print(f"V2: 2 full-patient inputs, 5 source clauses each, assessment_date=2021-11-30; {sum(r['needs_review']=='FALSE' for r in rows)}/10 reference clauses human-confirmed.")


if __name__ == "__main__":
    main()
