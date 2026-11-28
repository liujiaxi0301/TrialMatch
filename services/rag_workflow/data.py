"""Read Part 1/2 artifacts without modifying their schemas or source facts."""

import hashlib
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from .config import Settings


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def parse_date(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def label(fact: dict) -> str:
    code = fact.get("code") or {}
    names = [code.get("text", "")] + [c.get("display", "") for c in code.get("coding", [])]
    return " / ".join(dict.fromkeys(n for n in names if n))


def event_date(fact: dict) -> str | None:
    for key in (
        "effective_date",
        "performed_date",
        "authored_on",
        "when_handed_over",
        "date_asserted",
        "onset_date",
        "recorded_date",
        "issued_date",
    ):
        if fact.get(key):
            return fact[key]
    for key in ("effective_period", "performed_period", "onset_period"):
        if (fact.get(key) or {}).get("start"):
            return fact[key]["start"]
    return None


def patient_facts(patient: dict) -> list[dict]:
    facts = [patient["demographics"]]
    for key in ("conditions", "observations", "procedures"):
        facts.extend(patient.get(key, []))
    for key in ("requests", "definitions", "dispenses", "administrations", "statements"):
        facts.extend(patient.get("medications", {}).get(key, []))
    return facts


def validate_patient(patient: dict) -> dict:
    if patient.get("schema_version") != "0.3":
        raise ValueError("Expected normalized patient schema_version 0.3 from Part 2")
    if not patient.get("patient_id") or not parse_date(patient.get("reference_date")):
        raise ValueError("patient_id and a valid reference_date are required")
    if not isinstance(patient.get("demographics"), dict):
        raise TypeError("Invalid demographics: expected a Part 2 object")
    if not isinstance(patient.get("medications", {}), dict):
        raise TypeError("Invalid medications: expected the separate Part 2 evidence arrays")
    for key in ("conditions", "observations", "procedures"):
        if not isinstance(patient.get(key, []), list):
            raise TypeError(f"Invalid {key}: expected an array")
    for key in ("requests", "definitions", "dispenses", "administrations", "statements"):
        if not isinstance(patient.get("medications", {}).get(key, []), list):
            raise TypeError(f"Invalid medications.{key}: expected an array")
    age = patient["demographics"].get("age_years_at_reference")
    if age is not None and (
        isinstance(age, bool) or not isinstance(age, int) or not 0 <= age <= 150
    ):
        raise ValueError("Invalid age_years_at_reference")
    ids = set()
    reference = parse_date(patient["reference_date"])
    for fact in patient_facts(patient):
        if not isinstance(fact, dict) or not fact.get("fact_id"):
            raise ValueError("Every patient fact must preserve its source fact_id")
        if fact["fact_id"] in ids:
            raise ValueError("Duplicate patient fact_id")
        ids.add(fact["fact_id"])
        code = fact.get("code")
        if code is not None and (
            not isinstance(code, dict) or not isinstance(code.get("coding", []), list)
        ):
            raise ValueError("Invalid fact code; preserve the Part 2 CodeableConcept shape")
        if fact.get("resource_type") != "Patient":
            for date_key in (
                "effective_date",
                "performed_date",
                "authored_on",
                "when_handed_over",
                "when_prepared",
                "date_asserted",
                "onset_date",
                "recorded_date",
                "issued_date",
            ):
                when = parse_date(fact.get(date_key))
                if when and when > reference:
                    raise ValueError(
                        "Patient contains a future event; reprocess it with Part 2 reference-date filtering"
                    )
        subject = fact.get("subject_reference")
        if subject and subject.split("/")[-1].removeprefix("urn:uuid:") != patient["patient_id"]:
            raise ValueError("Fact subject_reference does not match patient_id")
    return patient


def complexity_flags(trial: dict, criteria: list[dict]) -> list[str]:
    flags = []
    text = trial.get("eligibility_text") or ""
    if any(c.get("parse_status") != "parsed" for c in criteria):
        flags.append("AMBIGUOUS_CRITERIA")
    # Deliberately conservative: do not turn mutually exclusive groups into an AND.
    if re.search(
        r"\b(cohorts?|control\s+(?:group|subjects?|participants?)|groups?|arms?)\b",
        text,
        re.IGNORECASE,
    ):
        flags.append("COHORT_LOGIC_REQUIRES_REVIEW")
    if not criteria or not text.strip():
        flags.append("MISSING_ELIGIBILITY")
    return flags


class DataStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        trial_rows = read_jsonl(settings.trials_path)
        criteria_rows = read_jsonl(settings.criteria_path)
        patient_rows = read_jsonl(settings.patients_path)
        self.trials = {t["trial_id"]: t for t in trial_rows}
        self.patients = {p["patient_id"]: validate_patient(p) for p in patient_rows}
        self.criteria = defaultdict(list)
        ids = set()
        for criterion in criteria_rows:
            if criterion["trial_id"] not in self.trials:
                raise ValueError("Orphan criterion in trial input")
            if criterion["criterion_id"] in ids:
                raise ValueError("Duplicate criterion_id in trial input")
            ids.add(criterion["criterion_id"])
            self.criteria[criterion["trial_id"]].append(criterion)
        if len(self.trials) != len(trial_rows) or len(self.patients) != len(patient_rows):
            raise ValueError("Duplicate trial_id or patient_id")
        self.hashes = {
            "trials": digest(settings.trials_path),
            "criteria": digest(settings.criteria_path),
            "patients": digest(settings.patients_path),
        }

    def patient(self, patient_id: str) -> dict:
        if patient_id not in self.patients:
            raise KeyError(f"Patient not found: {patient_id}")
        return self.patients[patient_id]

    def manifest(self) -> dict:
        data = json.loads(self.settings.manifest_path.read_text())
        for key in ("trials", "criteria", "patients"):
            if data["source_sha256"][key] != self.hashes[key]:
                raise ValueError(
                    f"Demo manifest is stale: {key} input changed; regenerate explicitly"
                )
        if not data.get("trial_ids") or any(t not in self.trials for t in data["trial_ids"]):
            raise ValueError("Invalid or empty trial subset in manifest")
        return data

    def create_manifest(self, count: int = 50) -> dict:
        eligible = [
            t
            for t in self.trials.values()
            if not complexity_flags(t, self.criteria[t["trial_id"]])
            and 3 <= len(self.criteria[t["trial_id"]]) <= 25
            and t.get("overall_status") == "RECRUITING"
        ]
        trial_ids = [t["trial_id"] for t in sorted(eligible, key=lambda t: t["trial_id"])[:count]]
        if len(trial_ids) < count:
            raise ValueError(f"Only {len(trial_ids)} trials satisfy the demo selection rule")
        demo_patients = sorted(
            p["patient_id"]
            for p in self.patients.values()
            if not p["demographics"].get("deceased_date")
        )[:3]
        manifest = {
            "manifest_version": "0.1",
            "source_sha256": self.hashes,
            "selection_rule": "RECRUITING; 3..25 criteria; no ambiguity or detected cohort/group/arm markers; sort trial_id; first N. Heuristic subset, not clinical validation.",
            "trial_ids": trial_ids,
            "patient_ids": sorted(self.patients),
            "demo_patient_ids": demo_patients,
            "patient_reference_dates": sorted(
                {p["reference_date"] for p in self.patients.values()}
            ),
            "trial_snapshot_dates": sorted({t["snapshot_date"] for t in self.trials.values()}),
        }
        self.settings.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        return manifest
