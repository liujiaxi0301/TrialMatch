"""Describe cohort evidence without assigning trial eligibility or gold labels."""
import argparse
import json
import re
from datetime import date

from common import ROOT, REPO, csv_bytes, json_bytes, normalize_text, read_jsonl, sha256

OBSERVATIONS = {
    "hba1c": "4548-4", "bmi": "39156-5", "blood_pressure": "85354-9",
    "egfr": "33914-3", "ast": "1920-8", "alt": "1742-6",
}
MEDICATION_TYPES = ("requests", "definitions", "administrations", "dispenses", "statements")
DRUG_TEXT_PATTERNS = {"sglt2_name_hit": "gliflozin", "insulin_name_hit": "insulin", "metformin_name_hit": "metformin"}


def calendar_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def has_code(fact, system, code):
    return any(c.get("system") == system and c.get("code") == code
               for c in (fact.get("code") or {}).get("coding", []))


def measurement_date(observation):
    # issued is a publication timestamp, not a substitute for measurement time.
    return calendar_date(observation.get("effective_date")) or calendar_date((observation.get("effective_period") or {}).get("start"))


def observation_summary(patient, code, reference):
    facts = [o for o in patient["observations"] if has_code(o, "http://loinc.org", code)]
    dated = [(measurement_date(o), o) for o in facts]
    valid = [(d, o) for d, o in dated if d is not None and d <= reference]
    latest = max((d for d, _ in valid), default=None)
    # Retain all observations on the latest calendar date. No arbitrary tie break.
    selected = sorted((o for d, o in valid if d == latest), key=lambda o: o["fact_id"])
    return {"loinc_code": code, "count": len(facts),
            "all_fact_ids": [o["fact_id"] for o in facts],
            "undated_count": sum(d is None for d, _ in dated),
            "after_reference_count": sum(d is not None and d > reference for d, _ in dated),
            "latest_measurement_date": latest.isoformat() if latest else None,
            "days_before_reference": (reference - latest).days if latest else None,
            "latest_facts": [{k: o.get(k) for k in ("fact_id", "source_file", "raw_status", "status_at_reference_date", "effective_date", "effective_period", "value", "components")} for o in selected]}


def medication_name_text(fact):
    # Only the source display/text; matching codes is deliberately not claimed.
    concept = fact.get("code") or {}
    return " ".join([concept.get("text") or ""] + [c.get("display") or "" for c in concept.get("coding", [])]).lower()


def patient_summary(patient, archive_member=None):
    reference = calendar_date(patient["reference_date"])
    if reference is None:
        raise ValueError("Invalid patient reference_date")
    demographics = patient["demographics"]
    birth = calendar_date(demographics.get("birth_date"))
    age = reference.year - birth.year - ((reference.month, reference.day) < (birth.month, birth.day)) if birth and birth <= reference else None
    if age != demographics["age_years_at_reference"]:
        raise ValueError(f"Age does not reproduce: {patient['patient_id']}")
    death = calendar_date(demographics.get("deceased_date"))
    recorded_deceased = death is not None and death <= reference
    t2d = [f for f in patient["conditions"] if has_code(f, "http://snomed.info/sct", "44054006")]
    medications = patient["medications"]
    counts = {kind: len(medications[kind]) for kind in MEDICATION_TYPES}
    name_hits = {label: {kind: [f["fact_id"] for f in medications[kind] if re.search(pattern, medication_name_text(f))]
                         for kind in MEDICATION_TYPES} for label, pattern in DRUG_TEXT_PATTERNS.items()}
    observations = {name: observation_summary(patient, code, reference) for name, code in OBSERVATIONS.items()}
    return {"patient_id": patient["patient_id"], "reference_date": reference.isoformat(),
            "schema_version": patient["schema_version"], "source_file": patient["source_file"],
            "archive_member": archive_member, "demographics_fact_id": demographics["fact_id"],
            "birth_date": demographics.get("birth_date"), "age_years_at_reference": age,
            "deceased_date_source": demographics.get("deceased_date"),
            "recorded_deceased_on_or_before_reference": recorded_deceased,
            "candidate_gate": "EXCLUDE_RECORDED_DECEASED" if recorded_deceased else "NO_DEATH_ON_OR_BEFORE_REFERENCE_RECORDED_NOT_CONFIRMED_ALIVE",
            "t2d_facts": [{k: f.get(k) for k in ("fact_id", "code", "onset_date", "recorded_date", "raw_clinical_status", "status_at_reference_date")} for f in t2d],
            "observations": observations, "medication_counts": counts,
            "drug_name_hits_not_terminology_classification": name_hits,
            "stable_actual_use_duration": "NOT_ESTABLISHED_BY_THIS_AUDIT",
            "workflow_information": "NOT_NORMALIZED_IN_PATIENT_FACTS_SCHEMA; RAW_COHORT_BUNDLES_NOT_REAUDITED",
            "unprocessed_resource_types": patient["unprocessed_resource_types"]}


def csv_row(summary):
    row = {k: summary[k] for k in ("patient_id", "reference_date", "birth_date", "age_years_at_reference", "deceased_date_source", "candidate_gate")}
    row["t2d_fact_count"] = len(summary["t2d_facts"])
    row["source_file"] = summary["source_file"]
    row["demographics_fact_id"] = summary["demographics_fact_id"]
    for name, obs in summary["observations"].items():
        row[f"{name}_count"] = obs["count"]
        row[f"{name}_latest_date"] = obs["latest_measurement_date"]
        row[f"{name}_days_before_reference"] = obs["days_before_reference"]
        row[f"{name}_latest_values"] = json.dumps([o["value"] if o["value"] is not None else o["components"] for o in obs["latest_facts"]], ensure_ascii=False)
        row[f"{name}_latest_fact_ids"] = json.dumps([o["fact_id"] for o in obs["latest_facts"]])
    row.update({f"medication_{k}_count": n for k, n in summary["medication_counts"].items()})
    for label, types in summary["drug_name_hits_not_terminology_classification"].items():
        row.update({f"{label}_{kind}_count": len(ids) for kind, ids in types.items()})
    return row


def audit_trial_text(trial, criteria):
    """Compare ALL source clause text, including non-bulleted continuation lines."""
    raw = []
    for line in trial["eligibility_text"].splitlines():
        if re.fullmatch(r"\s*(Inclusion|Exclusion) Criteria:\s*", line):
            continue
        raw.append(re.sub(r"^\s*(?:\d+\\?\.|\*|\\?-)\s+", "", line))
    return normalize_text(" ".join(raw)) == normalize_text(" ".join(c["criterion_text"] for c in criteria))


def proposal_files(patients):
    """Prepare reviewable cases; no assessment date or gold labels are approved."""
    trial_source = REPO / "services/trial_ingestion/data/processed/trials.jsonl"
    criteria_source = trial_source.with_name("criteria.jsonl")
    trials = {t["trial_id"]: t for t in read_jsonl(trial_source)}
    criteria = read_jsonl(criteria_source)
    trial_id = "NCT06774950"
    selected = [c for c in criteria if c["trial_id"] == trial_id]
    if len(selected) != 5 or not audit_trial_text(trials[trial_id], selected):
        raise ValueError("Proposed trial's source text is incomplete or changed")
    if any(c["parse_status"] != "parsed" for c in selected):
        raise ValueError("Proposed trial has unresolved parser structure")
    trial_input = {"trial_record": trials[trial_id], "parsed_criteria": selected,
                   "audit": {"all_raw_clause_text_preserved": True,
                             "limitations": "Preserves compound clinical exclusions and investigator discretion. Metadata is the repository snapshot, not live recruitment verification."}}
    files = {f"proposals/trials/{trial_id}.json": json_bytes(trial_input)}
    by_id = {p["patient_id"]: p for p in patients}
    candidate_ids = ["475803f3-ae29-ba8d-bdd1-25145a94eaee", "80534c6c-b12d-caa5-42de-b179fd7f9695"]
    rows = []
    for index, pid in enumerate(candidate_ids, 1):
        patient = by_id[pid]
        summary = patient_summary(patient)
        if summary["recorded_deceased_on_or_before_reference"]:
            raise ValueError("A proposed clinical case has a recorded prior death")
        age = summary["age_years_at_reference"]
        rows.append({"proposal_id": f"P{index:02d}", "patient_id": pid, "trial_id": trial_id,
                     "age_years_at_reference": age, "reference_date": patient["reference_date"],
                     "age_comparator_at_reference_not_final_criterion_status": "IN_40_TO_65_RANGE" if 40 < age < 65 else "OUTSIDE_40_TO_65_RANGE",
                     "assessment_date": "", "proposed_assessment_date_for_review": patient["reference_date"],
                     "actual_screening_consent_V1_dates": "UNKNOWN",
                     "purpose": "Supported age component plus T2D evidence and missing-history/workflow handling" if index == 1 else "Clear age conflict in the proposed offline scenario; no missing-record-as-negative shortcut",
                     "full_patient_json_bytes": len(json_bytes(patient)),
                     "review_state": "PROPOSED_CASE_NOT_GOLD_NOT_RUN"})
        files[f"proposals/patients/{pid}.json"] = json_bytes(patient)
    files["proposals/cases.csv"] = csv_bytes(rows, list(rows[0]))
    # Found while selecting cases: explicitly exclude this incomplete candidate.
    rejected_id = "NCT07376655"
    rejected = [c for c in criteria if c["trial_id"] == rejected_id]
    files["proposals/trial_selection_audit.json"] = json_bytes({
        "selected_trial_id": trial_id, "selected_all_raw_text_preserved": True,
        "selected_source_sha256": {str(trial_source.relative_to(REPO)): sha256(trial_source.read_bytes()), str(criteria_source.relative_to(REPO)): sha256(criteria_source.read_bytes())},
        "rejected_candidate": {"trial_id": rejected_id, "all_raw_text_preserved": audit_trial_text(trials[rejected_id], rejected),
                               "reason": "Stored parsed inclusion clause omits BMI continuation lines from source eligibility_text. Not selected; ingestion module not modified."},
        "case_selection_rationale": "Two source patients with manageable full inputs provide opposite age comparisons against one complete trial. This tests preliminary reasoning, not retrieval breadth or real enrollment eligibility.",
        "limitations": ["Age interval inclusivity is not specified in text; chosen ages 43 and 27 avoid boundary ambiguity.", "Assessment date is proposed, not selected; no actual consent/screening/V1 date is substituted.", "Trial snapshot is 2026-10-11 and NOT_YET_RECRUITING; 2021 scenario does not establish historical or current availability.", "Full inputs retain source cohort provenance and all facts; context capacity must be checked before model runs.", "T2D duration and clinical exclusions require further source-linked review, not automatic gold labels."]})
    return files


def make_outputs(cohort_path, selection_path):
    patients = read_jsonl(cohort_path)
    if len({p["patient_id"] for p in patients}) != len(patients):
        raise ValueError("Duplicate patient IDs")
    selection = json.loads(selection_path.read_text())
    members = {p["patient_id"]: p["archive_member"] for p in selection["selected"]}
    if set(members) != {p["patient_id"] for p in patients}:
        raise ValueError("Selection manifest and processed cohort differ")
    summaries = [patient_summary(p, members[p["patient_id"]]) for p in patients]
    summaries.sort(key=lambda s: s["patient_id"])
    reference_dates = sorted({s["reference_date"] for s in summaries})
    active = [s for s in summaries if not s["recorded_deceased_on_or_before_reference"]]
    aggregate = {
        "patients": len(summaries), "reference_dates": reference_dates,
        "recorded_deceased_on_or_before_reference": len(summaries) - len(active),
        "not_recorded_deceased_not_confirmed_alive": len(active),
        "exact_t2d_code_patients": sum(bool(s["t2d_facts"]) for s in summaries),
        "age_range_at_reference": [min(s["age_years_at_reference"] for s in summaries), max(s["age_years_at_reference"] for s in summaries)],
        "not_recorded_deceased_age_over_75_at_reference": sum(s["age_years_at_reference"] > 75 for s in active),
        "observation_patients": {name: sum(s["observations"][name]["count"] > 0 for s in summaries) for name in OBSERVATIONS},
        "hba1c_within_90_days_before_reference_descriptive_only": sum(s["observations"]["hba1c"]["days_before_reference"] is not None and s["observations"]["hba1c"]["days_before_reference"] <= 90 for s in summaries),
        "medication_patients": {kind: sum(s["medication_counts"][kind] > 0 for s in summaries) for kind in MEDICATION_TYPES},
        "name_hit_patients_not_terminology_classification": {label: {kind: sum(bool(s["drug_name_hits_not_terminology_classification"][label][kind]) for s in summaries) for kind in MEDICATION_TYPES} for label in DRUG_TEXT_PATTERNS},
    }
    rows = [csv_row(s) for s in summaries]
    payload = {"scope": "Descriptive evidence coverage of the checked-in deterministic 25-patient cohort, not eligibility or gold labels.",
               "assessment_date": None, "reference_date_is_not_actual_screening_consent_or_V1_date": True,
               "observation_method": "Exact listed LOINC codes; latest effective calendar date on/before reference_date, retaining ties; issued not substituted for measurement date. Source values/statuses/units unchanged.",
               "medication_method": "Separate evidence types. Source display/text substring matches gliflozin/insulin/metformin, not comprehensive terminology classification or exposure proof.",
               "source_archive_sha256_from_selection_manifest": selection["archive_sha256"],
               "original_archive_members_revalidated_in_this_run": False,
               "source_sha256": {str(cohort_path.relative_to(REPO)): sha256(cohort_path.read_bytes()), str(selection_path.relative_to(REPO)): sha256(selection_path.read_bytes())},
               "aggregate": aggregate, "patients": summaries}
    return payload, csv_bytes(rows, list(rows[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    source = REPO / "services/patient_processing/data/processed"
    payload, table = make_outputs(source / "batch25_patients.jsonl", source / "batch25_selection.json")
    files = {"cohort_evidence_coverage.json": json_bytes(payload), "cohort_evidence_coverage.csv": table}
    files.update(proposal_files(read_jsonl(source / "batch25_patients.jsonl")))
    files["coverage_manifest.json"] = json_bytes({
        "assessment_date": None, "status": "DESCRIPTIVE_AUDIT_AND_UNAPPROVED_CASE_PROPOSALS_NO_NEW_MODEL_RUNS",
        "source_commit": "9d6886a7ea925d9068bc38d669987036727873d5",
        "fixed_outputs_sha256": {name: sha256(data) for name, data in files.items()},
        "source_sha256": payload["source_sha256"],
        "analyzer_sha256": sha256((ROOT / "analyze_cohort.py").read_bytes())})
    for name, data in files.items():
        path = ROOT / "v2" / name
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                raise ValueError(f"Coverage output missing or stale: {name}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    print(json.dumps(payload["aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
