"""Scan an official Synthea archive and select a reproducible adult T2D cohort."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from zipfile import ZipFile

from process_patients import T2D_SNOMED, RELEVANT_LOINC, has_code, process_bundle


def count_coverage(records):
    counts = {"patients": len(records),
              "hba1c": {"patients": 0, "facts": 0},
              "glucose": {"patients": 0, "facts": 0},
              "medications": {},
              "procedures": {"patients": 0, "facts": 0}}
    for key in ("requests", "definitions", "dispenses", "administrations", "statements"):
        counts["medications"][key] = {"patients": 0, "facts": 0}
    for record in records:
        for code, name in RELEVANT_LOINC.items():
            n = sum(has_code(fact["code"], "http://loinc.org", code) for fact in record["observations"])
            counts[name.lower()]["patients"] += bool(n)
            counts[name.lower()]["facts"] += n
        for key, slot in counts["medications"].items():
            n = len(record["medications"][key])
            slot["patients"] += bool(n)
            slot["facts"] += n
        n = len(record["procedures"])
        counts["procedures"]["patients"] += bool(n)
        counts["procedures"]["facts"] += n
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--reference-date", required=True, type=date.fromisoformat)
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--selection-manifest", required=True, type=Path)
    args = parser.parse_args()
    if not 20 <= args.count <= 30:
        parser.error("--count must be between 20 and 30")
    digest = hashlib.sha256()
    with args.archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != args.expected_sha256:
        raise ValueError("archive SHA-256 does not match expected value")

    adults = 0
    candidates = []
    type_counts = Counter()
    members = 0
    nonpatient_members = []
    unresolved_references = 0
    warning_counts = Counter()
    with ZipFile(args.archive) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("fhir/") and name.endswith(".json"))
        for name in names:
            raw = archive.read(name)
            bundle = json.loads(raw)
            patient_count = sum(entry.get("resource", {}).get("resourceType") == "Patient"
                                for entry in bundle.get("entry", []))
            if patient_count == 0:
                nonpatient_members.append(name)
                continue
            if patient_count != 1:
                raise ValueError(f"{name}: expected one Patient, found {patient_count}")
            record = process_bundle(bundle, f"{args.archive.name}!{name}", args.reference_date)
            members += 1
            type_counts.update(record["unprocessed_resource_types"])
            unresolved_references += len(record["unresolved_medication_references"])
            warning_counts.update(warning["reason"].split(";")[0] for warning in record["warnings"])
            age = record["demographics"]["age_years_at_reference"]
            if age is not None and age >= 18:
                adults += 1
                if any(has_code(fact["code"], *T2D_SNOMED) for fact in record["conditions"]):
                    candidates.append((record["patient_id"], name, hashlib.sha256(raw).hexdigest(), record))
    candidates.sort(key=lambda item: (item[0], item[1]))
    selected = candidates[:args.count]
    report = {
        "scope": "every fhir/*.json member of the verified official archive",
        "archive": args.archive.name,
        "archive_sha256": digest.hexdigest(),
        "reference_date": args.reference_date.isoformat(),
        "total_json_members": len(names),
        "nonpatient_bundle_members": nonpatient_members,
        "total_patients": members,
        "adult_patients": adults,
        "adult_t2d_patients": len(candidates),
        "t2d_identification": {"resource_type": "Condition", "system": T2D_SNOMED[0],
                               "code": T2D_SNOMED[1], "rule": "exact coding match in retained Condition"},
        "adult_t2d_coverage": count_coverage([item[3] for item in candidates]),
        "unresolved_medication_references": unresolved_references,
        "warning_reasons": dict(sorted(warning_counts.items())),
        "unprocessed_resource_types": dict(sorted(type_counts.items())),
        "selection": {"requested": args.count, "selected": len(selected),
                      "rule": "adult (age >= 18) at reference_date with exact T2D Condition; sort by Patient.id then archive member path; take first N"},
    }
    for path in (args.output, args.report, args.selection_manifest):
        path.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as stream:
        for _, _, _, record in selected:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    manifest = {"archive_sha256": digest.hexdigest(), "reference_date": args.reference_date.isoformat(),
                "selection_rule": report["selection"]["rule"],
                "selected": [{"patient_id": pid, "archive_member": name, "source_sha256": sha}
                             for pid, name, sha, _ in selected]}
    args.selection_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Scanned {members} patients; {adults} adults; {len(candidates)} adult T2D; selected {len(selected)}")
    print(f"Wrote {args.output}, {args.report}, {args.selection_manifest}")


if __name__ == "__main__":
    main()
