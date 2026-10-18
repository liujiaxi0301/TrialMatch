"""Preserve model responses and derive separate A/B tables; never score them."""
import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, STATUSES, csv_bytes, fact_ids, json_bytes, normalize_text, parse_response, sha256

RUN_FIELDS = ["run_id", "pair_id", "mode", "patient_id", "trial_id", "model_name", "model_version",
              "interface", "search_enabled", "settings_provenance", "input_provenance", "original_run_timestamp",
              "reconstructed_upload_sha256", "original_upload_sha256",
              "recorded_at_utc", "raw_response_path", "response_sha256", "parse_status", "criterion_count",
              "aligned_criterion_count", "validation_warnings", "context_limitations"]
RESULT_FIELDS = ["run_id", "pair_id", "mode", "trial_id", "model_criterion_id", "source_criterion_id",
                 "alignment_state", "criterion_type", "criterion_text", "model_status", "evidence_fact_ids",
                 "reasoning", "missing_information", "review_error_types", "review_notes"]


def analyze_response(data, input_a, pair):
    warnings, rows = [], []
    try:
        obj, preamble = parse_response(data)
    except (ValueError, UnicodeError) as exc:
        return {"parse_status": "INVALID_JSON", "validation_warnings": [str(exc)],
                "context_limitations": [], "criteria": [], "criterion_count": 0, "aligned_criterion_count": 0}
    trial_id = input_a["trial_record"]["trial_id"]
    if obj.get("pair_id") != pair or obj.get("trial_id") != trial_id:
        warnings.append("RESPONSE_IDENTITY_MISMATCH")
    if preamble:
        warnings.append("TEXT_OUTSIDE_JSON")
    source = input_a["parsed_criteria"]
    bytext = {}
    for criterion in source:
        key = criterion["criterion_type"], normalize_text(criterion["criterion_text"])
        bytext.setdefault(key, []).append(criterion["criterion_id"])
    available_facts = fact_ids(input_a["patient"])
    seen_ids, seen_source = set(), set()
    criteria = obj.get("criteria")
    if not isinstance(criteria, list):
        criteria = []
        warnings.append("CRITERIA_NOT_ARRAY")
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            warnings.append(f"CRITERION_NOT_OBJECT:{index}")
            continue
        cid = str(criterion.get("criterion_id", ""))
        if not cid or cid in seen_ids:
            warnings.append(f"MISSING_OR_DUPLICATE_CRITERION_ID:{index}")
        seen_ids.add(cid)
        text = criterion.get("criterion_text", "")
        ctype = criterion.get("criterion_type", "")
        status = criterion.get("status", "")
        if not isinstance(text, str) or not isinstance(ctype, str) or ctype not in {"inclusion", "exclusion", "unknown"}:
            warnings.append(f"INVALID_CRITERION_TEXT_OR_TYPE:{cid}")
        text = text if isinstance(text, str) else json.dumps(text)
        if not isinstance(status, str) or status not in STATUSES:
            warnings.append(f"INVALID_STATUS:{cid}")
        matches = bytext.get((str(ctype), normalize_text(text)), [])
        source_id = matches[0] if len(matches) == 1 else ""
        if source_id:
            if source_id in seen_source:
                warnings.append(f"DUPLICATE_SOURCE_CLAUSE:{source_id}")
            seen_source.add(source_id)
        else:
            warnings.append(f"UNALIGNED_MODEL_CLAUSE:{cid}")
        evidence = criterion.get("evidence_fact_ids")
        if not isinstance(evidence, list) or not all(isinstance(x, str) for x in evidence):
            warnings.append(f"INVALID_EVIDENCE_ARRAY:{cid}")
        elif not set(evidence) <= available_facts:
            warnings.append(f"UNKNOWN_FACT_IDS:{cid}")
        for field in ("reasoning", "missing_information"):
            if field not in criterion:
                warnings.append(f"MISSING_{field.upper()}:{cid}")
        rows.append({"model_criterion_id": cid, "source_criterion_id": source_id,
                     "alignment_state": "NORMALIZED_TEXT_MATCH" if source_id else "NEEDS_MANUAL_ALIGNMENT",
                     "criterion_type": ctype, "criterion_text": text, "model_status": status,
                     "evidence_fact_ids": json.dumps(evidence, ensure_ascii=False),
                     "reasoning": criterion.get("reasoning", ""),
                     "missing_information": json.dumps(criterion.get("missing_information"), ensure_ascii=False),
                     "review_error_types": "", "review_notes": ""})
    missing = [c["criterion_id"] for c in source if c["criterion_id"] not in seen_source]
    if missing:
        warnings.append("UNMATCHED_SOURCE_CRITERIA:" + ",".join(missing))
    if len(criteria) != len(source):
        warnings.append("CRITERION_COUNT_MISMATCH")
    issues = obj.get("source_criterion_issues", [])
    issues = issues if isinstance(issues, list) else [issues]
    context = [str(issue) for issue in issues if "memory" in str(issue).lower()]
    return {"parse_status": "PARSED", "validation_warnings": warnings, "context_limitations": context,
            "source_criterion_issues_model_reported": issues,
            "source_urls_model_reported": obj.get("source_urls", []),
            "source_accessed_at_model_reported": obj.get("source_accessed_at"),
            "criteria": rows, "criterion_count": len(criteria), "aligned_criterion_count": len(seen_source)}


def write_record(pair, mode, data, run_id, model, version, interface, search,
                 settings_provenance="USER_SUPPLIED_AT_RECORDING", root=ROOT):
    if not re.fullmatch(r"V0[1-6]", pair) or mode not in {"A", "B"}:
        raise ValueError("Unknown pair or mode")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        raise ValueError("Run ID must contain only letters, digits, underscores and hyphens")
    input_a = json.loads((root / f"uploads/A/{pair}.json").read_text())
    upload_hash = sha256((root / f"uploads/{mode}/{pair}.json").read_bytes())
    record_path = root / "results/records" / f"{run_id}.json"
    raw_path = root / "results/raw" / mode / f"{run_id}.txt"
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        for key, expected in {"response_sha256": sha256(data), "pair_id": pair, "mode": mode,
                              "model_name": model, "model_version": version, "interface": interface,
                              "search_enabled": search, "settings_provenance": settings_provenance,
                              "reconstructed_upload_sha256": upload_hash}.items():
            if previous[key] != expected:
                raise ValueError(f"Run ID already exists with different {key}; use a new ID")
        if raw_path.read_bytes() != data:
            raise ValueError("Recorded raw response was changed")
        return previous
    if raw_path.exists() and raw_path.read_bytes() != data:
        raise ValueError("Refusing to replace existing response")
    analysis = analyze_response(data, input_a, pair)
    record = {"run_id": run_id, "pair_id": pair, "mode": mode,
              "patient_id": input_a["patient"]["patient_id"], "trial_id": input_a["trial_record"]["trial_id"],
              "model_name": model, "model_version": version, "interface": interface,
              "search_enabled": search, "settings_provenance": settings_provenance,
              "input_provenance": "RECONSTRUCTED_INPUTS_ORIGINAL_UPLOAD_HASHES_UNAVAILABLE",
              "reconstructed_upload_sha256": upload_hash,
              "original_upload_sha256": None,
              "original_run_timestamp": None,
              "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
              "raw_response_path": str(raw_path.relative_to(root)), "response_sha256": sha256(data), **analysis}
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)
    record_path.write_bytes(json_bytes(record))
    return record


def export_tables(root=ROOT):
    """Regenerate derived CSVs; review decisions belong in reference_answers.csv."""
    records = [json.loads(p.read_text()) for p in sorted((root / "results/records").glob("*.json"))]
    for mode in ("A", "B"):
        runs, results = [], []
        for record in records:
            if record["mode"] != mode:
                continue
            row = {f: record[f] for f in RUN_FIELDS}
            for field in ("validation_warnings", "context_limitations"):
                row[field] = json.dumps(row[field], ensure_ascii=False)
            runs.append(row)
            for c in record["criteria"]:
                results.append({**{f: record[f] for f in ("run_id", "pair_id", "mode", "trial_id")}, **c})
        (root / f"results/runs_{mode}.csv").write_bytes(csv_bytes(runs, RUN_FIELDS))
        (root / f"results/model_results_{mode}.csv").write_bytes(csv_bytes(results, RESULT_FIELDS))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-recovered", action="store_true")
    parser.add_argument("--mode", choices=["A", "B"])
    parser.add_argument("--pair", choices=[f"V{i:02d}" for i in range(1, 7)])
    parser.add_argument("--response", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--model-version")
    parser.add_argument("--interface")
    parser.add_argument("--search-enabled", choices=["TRUE", "FALSE", "UNKNOWN"], default="UNKNOWN")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.import_recovered:
        manifest = json.loads((ROOT / "recovery_manifest.json").read_text())
        for item in manifest["raw_responses"]:
            data = (ROOT / item["raw_response_path"]).read_bytes()
            if sha256(data) != item["response_sha256"]:
                raise ValueError("Recovered attachment hash changed")
            write_record(item["pair_id"], item["mode"], data,
                         f"recovered_{item['pair_id']}_{item['mode']}", "Claude Opus", "5.5", "Claude web",
                         "TRUE" if item["search_enabled_user_reported"] else "FALSE", "USER_REPORTED_IN_PRIOR_CHAT")
    else:
        if not all((args.mode, args.pair, args.response, args.model, args.model_version, args.interface)):
            parser.error("Supply --mode, --pair, --response, --model, --model-version and --interface")
        run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + f"_{args.pair}_{args.mode}"
        write_record(args.pair, args.mode, args.response.read_bytes(), run_id,
                     args.model, args.model_version, args.interface, args.search_enabled)
    export_tables()
    print("Responses preserved; separate A/B tables exported. No reference labels or scores generated.")


if __name__ == "__main__":
    main()
