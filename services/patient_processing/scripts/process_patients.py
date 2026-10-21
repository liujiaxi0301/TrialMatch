"""Normalize a small set of Synthea FHIR R4 patient Bundles."""

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path


T2D_SNOMED = ("http://snomed.info/sct", "44054006")
RELEVANT_LOINC = {"4548-4": "HbA1c", "2339-0": "glucose"}


def reference_target(reference, entries):
    if not reference:
        return None
    if reference in entries:
        return entries[reference]
    if reference.startswith("urn:uuid:"):
        return entries.get(reference.removeprefix("urn:uuid:"))
    return entries.get(reference)


def resource_index(bundle):
    index = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        resource_id = resource.get("id")
        if not resource_id:
            continue
        for key in (resource_id, f"{resource.get('resourceType')}/{resource_id}", entry.get("fullUrl")):
            if key:
                if key in index and index[key] is not resource:
                    raise ValueError(f"duplicate FHIR reference: {key}")
                index[key] = resource
    return index


def as_of(value, reference_date):
    """Unknown dates stay visible; known future events are excluded."""
    if not value:
        return True
    try:
        return date.fromisoformat(value[:10]) <= reference_date
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid FHIR date: {value!r}") from exc


def known_event_dates(resource):
    """Dates that must all be on/before the cutoff to avoid future evidence."""
    kind = resource["resourceType"]
    fields = {
        "Condition": ("recordedDate", "onsetDateTime"),
        "Observation": ("issued", "effectiveDateTime"),
        "Procedure": ("performedDateTime",),
        "MedicationRequest": ("authoredOn",),
        "MedicationAdministration": ("effectiveDateTime",),
        "MedicationDispense": ("whenHandedOver", "whenPrepared"),
        "MedicationStatement": ("dateAsserted", "effectiveDateTime"),
    }.get(kind, ())
    values = [resource[field] for field in fields if resource.get(field)]
    period_field = {"Condition": "onsetPeriod", "Observation": "effectivePeriod",
                    "Procedure": "performedPeriod", "MedicationAdministration": "effectivePeriod",
                    "MedicationStatement": "effectivePeriod"}.get(kind)
    if period_field and resource.get(period_field, {}).get("start"):
        values.append(resource[period_field]["start"])
    return values


def provenance(resource, source_file):
    return {
        "fact_id": f"{source_file}#{resource['resourceType']}/{resource['id']}",
        "resource_type": resource["resourceType"],
        "source_resource_id": resource["id"],
        "source_file": source_file,
    }


def value_of(resource):
    for key, value in resource.items():
        if key.startswith("value") and key != "value":
            return {"type": key.removeprefix("value"), "data": value}
    return None


def normalize_resource(resource, source_file, index):
    kind = resource["resourceType"]
    record = provenance(resource, source_file)
    if kind == "Medication":
        record.update(code=resource.get("code"), raw_status=resource.get("status"),
                      event_time_certainty="undated", status_at_reference_date="undetermined")
        return record

    record["subject_reference"] = resource.get("subject", {}).get("reference")
    record["event_time_certainty"] = "dated" if known_event_dates(resource) else "undated"
    record["status_at_reference_date"] = "undetermined"
    if kind == "Condition":
        record.update(
            code=resource.get("code"),
            raw_status=resource.get("clinicalStatus"),
            raw_clinical_status=resource.get("clinicalStatus"),
            raw_verification_status=resource.get("verificationStatus"),
            onset_date=resource.get("onsetDateTime") or resource.get("onsetPeriod", {}).get("start"),
            onset_period=resource.get("onsetPeriod"),
            abatement_date=resource.get("abatementDateTime") or resource.get("abatementPeriod", {}).get("end"),
            abatement_period=resource.get("abatementPeriod"),
            recorded_date=resource.get("recordedDate"),
        )
    elif kind == "Observation":
        record.update(
            code=resource.get("code"), raw_status=resource.get("status"),
            effective_date=resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start"),
            effective_period=resource.get("effectivePeriod"),
            issued_date=resource.get("issued"), value=value_of(resource),
            components=[{"code": item.get("code"), "value": value_of(item)} for item in resource.get("component", [])],
        )
    elif kind == "Procedure":
        record.update(
            code=resource.get("code"), raw_status=resource.get("status"),
            performed_date=resource.get("performedDateTime"),
            performed_period=resource.get("performedPeriod"),
        )
    elif kind in ("MedicationRequest", "MedicationAdministration", "MedicationDispense", "MedicationStatement"):
        medication_reference = resource.get("medicationReference", {}).get("reference")
        target = reference_target(medication_reference, index)
        if target is not None and target.get("resourceType") != "Medication":
            raise ValueError(f"medication reference points to {target.get('resourceType')}: {medication_reference}")
        record.update(
            code=resource.get("medicationCodeableConcept") or (target.get("code") if target else None),
            medication_reference=medication_reference,
            resolved_medication_id=target.get("id") if target else None,
            raw_status=resource.get("status"),
        )
        if kind == "MedicationRequest":
            record.update(
                intent=resource.get("intent"), authored_on=resource.get("authoredOn"),
                dosage_instruction=resource.get("dosageInstruction", []),
            )
        elif kind == "MedicationAdministration":
            record.update(
                effective_date=resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start"),
                effective_period=resource.get("effectivePeriod"),
                dosage=resource.get("dosage"),
            )
        elif kind == "MedicationDispense":
            record.update(when_handed_over=resource.get("whenHandedOver"),
                          when_prepared=resource.get("whenPrepared"), quantity=resource.get("quantity"))
        else:
            record.update(effective_date=resource.get("effectiveDateTime") or resource.get("effectivePeriod", {}).get("start"),
                          effective_period=resource.get("effectivePeriod"), date_asserted=resource.get("dateAsserted"))
    return record


def process_bundle(bundle, source_file, reference_date):
    if bundle.get("resourceType") != "Bundle":
        raise ValueError(f"{source_file}: expected FHIR Bundle")
    index = resource_index(bundle)
    resources = [entry.get("resource", {}) for entry in bundle.get("entry", [])]
    patients = [resource for resource in resources if resource.get("resourceType") == "Patient"]
    if len(patients) != 1 or not patients[0].get("id"):
        raise ValueError(f"{source_file}: expected exactly one Patient with an id")
    patient = patients[0]
    patient_id = patient["id"]
    birth = patient.get("birthDate")
    age = None
    if birth:
        birthday = date.fromisoformat(birth)
        if birthday <= reference_date:
            age = reference_date.year - birthday.year - ((reference_date.month, reference_date.day) < (birthday.month, birthday.day))
    output = {
        "schema_version": "0.3",
        "patient_id": patient_id,
        "reference_date": reference_date.isoformat(),
        "source_file": source_file,
        "demographics": {
            **provenance(patient, source_file),
            "gender": patient.get("gender"),
            "birth_date": birth,
            "deceased_date": patient.get("deceasedDateTime"),
            "age_years_at_reference": age,
        },
        "conditions": [], "observations": [], "procedures": [],
        "medications": {"requests": [], "definitions": [], "administrations": [], "dispenses": [], "statements": []},
        "unresolved_medication_references": [],
        "warnings": [],
        "unprocessed_resource_types": {},
    }
    keys = {
        "Condition": "conditions", "Observation": "observations", "Procedure": "procedures",
        "MedicationRequest": "requests",
        "MedicationAdministration": "administrations",
        "MedicationDispense": "dispenses",
        "MedicationStatement": "statements",
    }
    referenced_medications = set()
    unprocessed = Counter()
    for resource in resources:
        kind = resource.get("resourceType")
        if kind not in keys:
            if kind not in ("Patient", "Medication"):
                unprocessed[kind or "unknown"] += 1
            continue
        if not resource.get("id"):
            raise ValueError(f"{source_file}: {kind} has no id")
        subject_reference = resource.get("subject", {}).get("reference")
        if reference_target(subject_reference, index) is not patient:
            raise ValueError(f"{source_file}: {kind}/{resource['id']} has invalid patient reference {subject_reference!r}")
        if not all(as_of(value, reference_date) for value in known_event_dates(resource)):
            continue
        item = normalize_resource(resource, source_file, index)
        if kind in ("Condition", "Observation", "Procedure"):
            output[keys[kind]].append(item)
        else:
            output["medications"][keys[kind]].append(item)
        if not known_event_dates(resource):
            output["warnings"].append({"source_resource_id": resource["id"], "resource_type": kind,
                                       "reason": "missing_event_date; retained with unknown chronology"})
        if item.get("code") is None:
            output["warnings"].append({"source_resource_id": resource["id"], "resource_type": kind,
                                       "reason": "missing_code; retained without coded interpretation"})
        if item.get("resolved_medication_id"):
            referenced_medications.add(item["resolved_medication_id"])
        elif item.get("medication_reference"):
            output["unresolved_medication_references"].append(item["medication_reference"])
            output["warnings"].append({"source_resource_id": resource["id"], "resource_type": kind,
                                       "reason": "unresolved_medication_reference", "reference": item["medication_reference"]})
    for resource in resources:
        if resource.get("resourceType") == "Medication" and resource.get("id") in referenced_medications:
            output["medications"]["definitions"].append(normalize_resource(resource, source_file, index))
    output["unprocessed_resource_types"] = dict(sorted(unprocessed.items()))
    if unprocessed:
        output["warnings"].append({"reason": "resource_types_outside_first_pass_scope",
                                   "counts": output["unprocessed_resource_types"]})
    return output


def has_code(codeable, system, code):
    return any(coding.get("system") == system and coding.get("code") == code
               for coding in (codeable or {}).get("coding", []))


def coverage_report(records):
    """Coverage of the complete supplied input, never of the source archive."""
    adults = [r for r in records if r["demographics"]["age_years_at_reference"] is not None
              and r["demographics"]["age_years_at_reference"] >= 18]
    t2d = [r for r in adults if any(has_code(c["code"], *T2D_SNOMED) for c in r["conditions"])]
    observation_counts = {name: {"patients": 0, "facts": 0} for name in RELEVANT_LOINC.values()}
    for record in records:
        for code, name in RELEVANT_LOINC.items():
            count = sum(has_code(obs["code"], "http://loinc.org", code) for obs in record["observations"])
            observation_counts[name]["facts"] += count
            observation_counts[name]["patients"] += bool(count)
    medication_counts = {}
    for kind in ("requests", "definitions", "dispenses", "administrations", "statements"):
        medication_counts[kind] = {"patients": sum(bool(r["medications"][kind]) for r in records),
                                   "facts": sum(len(r["medications"][kind]) for r in records)}
    return {
        "scope": "all JSON Bundles supplied via --input; selected sample, not the full Synthea archive",
        "reference_date": records[0]["reference_date"],
        "total_patients": len(records), "adult_patients": len(adults),
        "adult_t2d_patients": len(t2d),
        "t2d_identification": {"resource_type": "Condition", "coding_system": T2D_SNOMED[0],
                               "code": T2D_SNOMED[1], "rule": "exact coding match in retained Condition; no medication inference"},
        "relevant_observations": observation_counts,
        "procedure_coverage": {"patients": sum(bool(r["procedures"]) for r in records),
                               "facts": sum(len(r["procedures"]) for r in records)},
        "medication_coverage": medication_counts,
        "unresolved_medication_references": sum(len(r["unresolved_medication_references"]) for r in records),
        "unprocessed_resource_types": dict(sum((Counter(r["unprocessed_resource_types"]) for r in records), Counter())),
        "warnings": sum(len(r["warnings"]) for r in records),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parents[1] / "data/raw",
                        help="directory of Bundle JSON files or one Bundle JSON file")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "data/processed/patients.jsonl")
    parser.add_argument("--coverage-report", type=Path, help="default: coverage_report.json beside --output")
    parser.add_argument("--reference-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    paths = sorted(args.input.glob("*.json")) if args.input.is_dir() else [args.input]
    if not paths:
        parser.error(f"no JSON files in {args.input}")
    records = [process_bundle(json.loads(path.read_text()), str(path), args.reference_date) for path in paths]
    ids = [record["patient_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate patient across input files")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    report_path = args.coverage_report or args.output.with_name("coverage_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(coverage_report(records), indent=2) + "\n")
    print(f"Saved {len(records)} patients to {args.output}")
    print(f"Saved coverage report to {report_path}")
    for key in ("conditions", "observations", "procedures"):
        print(f"{key}: {sum(len(record[key]) for record in records)}")
    for key in ("requests", "definitions", "dispenses", "administrations", "statements"):
        print(f"medication {key}: {sum(len(record['medications'][key]) for record in records)}")


if __name__ == "__main__":
    main()
