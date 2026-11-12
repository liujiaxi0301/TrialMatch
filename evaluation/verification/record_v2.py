"""Record real v2 responses verbatim; validate structure/citations, never assign gold."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, STATUSES, csv_bytes, fact_ids, json_bytes, normalize_text, parse_response, sha256

V2 = ROOT / "v2"
RUN_FIELDS = ["run_id", "pair_id", "trial_id", "assessment_date", "model", "model_version", "interface",
              "search_enabled_user_reported", "context_isolation_user_reported", "recorded_at_utc",
              "raw_response_path", "response_sha256", "upload_sha256", "prompt_sha256", "policy_sha256",
              "parse_status", "criterion_count", "validation_warnings"]
ROW_FIELDS = ["run_id", "pair_id", "criterion_id", "criterion_type", "criterion_text", "precheck_status",
              "evidence_fact_ids", "reasoning", "missing_clinical_information", "required_workflow_followup"]


def validate_response(data, upload):
    try:
        obj, outside = parse_response(data)
    except (ValueError, UnicodeError) as exc:
        return {"parse_status": "INVALID_JSON", "validation_warnings": [str(exc)], "criterion_count": 0,
                "criteria": [], "context_limitations_model_reported": []}
    warnings = ["TEXT_OUTSIDE_JSON"] if outside else []
    if obj.get("pair_id") != upload["pair_id"] or obj.get("trial_id") != upload["trial_record"]["trial_id"]:
        warnings.append("RESPONSE_IDENTITY_MISMATCH")
    if obj.get("assessment_date") != upload["assessment_date"]:
        warnings.append("ASSESSMENT_DATE_MISMATCH")
    if obj.get("actual_trial_dates") != upload["actual_trial_dates"]:
        warnings.append("ACTUAL_TRIAL_DATES_NOT_PRESERVED_AS_UNKNOWN")
    if obj.get("search_status") != "NOT_USED":
        warnings.append("SEARCH_REPORTED_OR_UNCLEAR")
    if "overall_enrollment_decision" not in obj or obj["overall_enrollment_decision"] is not None:
        warnings.append("OVERALL_ENROLLMENT_DECISION_NOT_NULL")
    if any(k in obj for k in ("eligibility_probability", "enrollment_probability")):
        warnings.append("UNREQUESTED_ELIGIBILITY_PROBABILITY")
    source = {c["criterion_id"]: c for c in upload["parsed_criteria"]}
    available = fact_ids(upload["patient"])
    criteria = obj.get("criteria")
    if not isinstance(criteria, list):
        criteria = []
        warnings.append("CRITERIA_NOT_ARRAY")
    seen, rows = set(), []
    expected_summary = {"supported_criterion_ids": [], "conflicting_criterion_ids": [], "unresolved_criterion_ids": []}
    for index, c in enumerate(criteria):
        if not isinstance(c, dict):
            warnings.append(f"CRITERION_NOT_OBJECT:{index}")
            continue
        cid = str(c.get("criterion_id", ""))
        if cid not in source:
            warnings.append(f"UNEXPECTED_CRITERION_ID:{cid}")
        elif cid in seen:
            warnings.append(f"DUPLICATE_CRITERION_ID:{cid}")
        seen.add(cid)
        text, ctype, status = c.get("criterion_text"), c.get("criterion_type"), c.get("precheck_status")
        if cid in source and (not isinstance(text, str) or normalize_text(text) != normalize_text(source[cid]["criterion_text"]) or ctype != source[cid]["criterion_type"]):
            warnings.append(f"SOURCE_TEXT_OR_TYPE_MISMATCH:{cid}")
        if not isinstance(status, str) or status not in STATUSES:
            warnings.append(f"INVALID_PRECHECK_STATUS:{cid}")
        elif cid in source:
            if status == "UNKNOWN":
                group = "unresolved_criterion_ids"
            elif (source[cid]["criterion_type"] == "inclusion" and status == "NOT_MET") or (source[cid]["criterion_type"] == "exclusion" and status == "MET"):
                group = "conflicting_criterion_ids"
            else:
                group = "supported_criterion_ids"
            expected_summary[group].append(cid)
        evidence = c.get("evidence_fact_ids")
        if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence):
            warnings.append(f"INVALID_EVIDENCE_ARRAY:{cid}")
        elif not set(evidence) <= available:
            warnings.append(f"UNKNOWN_FACT_IDS:{cid}")
        if not isinstance(c.get("reasoning"), str) or not c["reasoning"].strip():
            warnings.append(f"MISSING_REASONING:{cid}")
        for field in ("missing_clinical_information", "required_workflow_followup"):
            if not isinstance(c.get(field), list) or not all(isinstance(x, str) for x in c[field]):
                warnings.append(f"INVALID_{field.upper()}:{cid}")
        rows.append({"criterion_id": cid, "criterion_type": ctype, "criterion_text": text,
                     "precheck_status": status, "evidence_fact_ids": evidence,
                     "reasoning": c.get("reasoning"), "missing_clinical_information": c.get("missing_clinical_information"),
                     "required_workflow_followup": c.get("required_workflow_followup")})
    missing = sorted(set(source) - seen)
    if missing:
        warnings.append("MISSING_SOURCE_CRITERIA:" + ",".join(missing))
    if len(criteria) != len(source):
        warnings.append("CRITERION_COUNT_MISMATCH")
    summary = obj.get("summary")
    for field, expected in expected_summary.items():
        value = summary.get(field) if isinstance(summary, dict) else None
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value) or sorted(value) != sorted(expected):
            warnings.append(f"SUMMARY_POLARITY_OR_COVERAGE_MISMATCH:{field}")
    return {"parse_status": "PARSED", "validation_warnings": warnings, "criterion_count": len(criteria),
            "criteria": rows, "context_limitations_model_reported": obj.get("context_limitations", []),
            "source_criterion_issues_model_reported": obj.get("source_criterion_issues", [])}


def record_response(pair, data, run_id, model, version, interface, search, context, root=V2):
    if pair not in {"V2P01", "V2P02"} or not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Unknown pair or unsafe run ID")
    upload_path = root / f"uploads/A/{pair}.json"
    upload_bytes = upload_path.read_bytes()
    manifest = json.loads((root / "experiment_manifest.json").read_text())
    if sha256(upload_bytes) != manifest["fixed_outputs_sha256"][f"uploads/A/{pair}.json"]:
        raise ValueError("Upload differs from fixed experiment manifest")
    upload = json.loads(upload_bytes)
    metadata = {"pair_id": pair, "trial_id": upload["trial_record"]["trial_id"], "assessment_date": upload["assessment_date"],
                "model": model, "model_version": version, "interface": interface,
                "search_enabled_user_reported": search, "context_isolation_user_reported": context,
                "response_sha256": sha256(data), "upload_sha256": sha256(upload_bytes),
                "prompt_sha256": sha256((root / "prompt_A.md").read_bytes()), "policy_sha256": sha256((root / "policy.json").read_bytes())}
    for source in ("prompt_A.md", "policy.json"):
        if sha256((root / source).read_bytes()) != manifest["sources_sha256"][f"v2/{source}"]:
            raise ValueError(f"Protocol differs from fixed manifest: {source}")
    record_path = root / f"results/records/{run_id}.json"
    raw_path = root / f"results/raw/A/{run_id}.txt"
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if any(previous[k] != value for k, value in metadata.items()) or raw_path.read_bytes() != data:
            raise ValueError("Run ID already exists with different response/settings/input; use a new ID")
        return previous
    if raw_path.exists() and raw_path.read_bytes() != data:
        raise ValueError("Refusing to replace existing raw response")
    record = {"run_id": run_id, **metadata, "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "original_model_run_timestamp": None, "raw_response_path": str(raw_path.relative_to(root)),
              **validate_response(data, upload)}
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)
    record_path.write_bytes(json_bytes(record))
    return record


def export_tables(root=V2):
    runs, rows = [], []
    for path in sorted((root / "results/records").glob("*.json")):
        record = json.loads(path.read_text())
        if sha256((root / record["raw_response_path"]).read_bytes()) != record["response_sha256"]:
            raise ValueError("Raw response hash no longer matches its run record")
        run = {f: record[f] for f in RUN_FIELDS}
        run["validation_warnings"] = json.dumps(run["validation_warnings"], ensure_ascii=False)
        runs.append(run)
        for c in record["criteria"]:
            row = {"run_id": record["run_id"], "pair_id": record["pair_id"], **c}
            for field in ("evidence_fact_ids", "missing_clinical_information", "required_workflow_followup"):
                row[field] = json.dumps(row[field], ensure_ascii=False)
            rows.append(row)
    (root / "results").mkdir(parents=True, exist_ok=True)
    (root / "results/runs_A.csv").write_bytes(csv_bytes(runs, RUN_FIELDS))
    (root / "results/precheck_results_A.csv").write_bytes(csv_bytes(rows, ROW_FIELDS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="Create/regenerate derived tables, without a model call")
    parser.add_argument("--pair", choices=["V2P01", "V2P02"])
    parser.add_argument("--response", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--model")
    parser.add_argument("--model-version")
    parser.add_argument("--interface")
    parser.add_argument("--search-enabled", choices=["TRUE", "FALSE", "UNKNOWN"], default="UNKNOWN")
    parser.add_argument("--context-isolation", choices=["CONFIRMED", "NOT_CONFIRMED", "UNKNOWN"], default="UNKNOWN")
    args = parser.parse_args()
    if not args.init:
        if not all((args.pair, args.response, args.model, args.model_version, args.interface)):
            parser.error("Supply --pair, --response, --model, --model-version and --interface")
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + args.pair + "_A"
        record_response(args.pair, args.response.read_bytes(), run_id, args.model, args.model_version,
                        args.interface, args.search_enabled, args.context_isolation)
    export_tables()
    print("V2 response tables exported. No model called; human references and gold labels unchanged.")


if __name__ == "__main__":
    main()
