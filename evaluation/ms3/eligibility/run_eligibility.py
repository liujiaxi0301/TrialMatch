#!/usr/bin/env python3
"""TrialMatch MS3 fixed-pair eligibility evaluation.

Run the EXISTING evidence_rule -> ContextSelector -> judge_batch/evidence_guard
pipeline on frozen patient/trial pairs, without retrieval or gold-label leakage.

Usage (from the repository root):

  PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
    evaluation/ms3/eligibility/run_eligibility.py run --split dev --provider offline --tag smoke

  PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
    evaluation/ms3/eligibility/run_eligibility.py run --split dev --provider developer --tag baseline

  PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
    evaluation/ms3/eligibility/run_eligibility.py run --split reporting --provider developer --tag baseline

  PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
    evaluation/ms3/eligibility/run_eligibility.py score \
    --predictions evaluation/ms3/eligibility/results/dev_developer_baseline_predictions.jsonl

Predictions are written BEFORE gold labels are read. Never modifies gold labels.
Report-set results should only be evaluated after the dev setup is frozen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

# Permit direct `python evaluation/ms3/eligibility/run_eligibility.py` from repo root.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.rag_workflow.config import MODULE, Settings
from services.rag_workflow.data import DataStore, complexity_flags, patient_facts
from services.rag_workflow.evidence_rules import evidence_rule
from services.rag_workflow.judge import judge_batch
from services.rag_workflow.providers import GeminiProvider
from services.rag_workflow.retrieve import ContextSelector
from services.rag_workflow.rules import unknown

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
DECISIONS = ("MET", "NOT_MET", "UNKNOWN")
EXPECTED_SIZES = (22, 8, 23, 8, 10, 15, 15, 14)
EXPECTED_SPLITS = {"all": tuple(f"E{i:02d}" for i in range(1, 9))}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_info() -> dict:
    def run(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {"branch": run("branch", "--show-current"), "commit": run("rev-parse", "HEAD")}


def code_hashes() -> dict[str, str]:
    paths = [
        "services/rag_workflow/evidence_rules.py",
        "services/rag_workflow/judge.py",
        "services/rag_workflow/rules.py",
        "services/rag_workflow/retrieve.py",
        "services/rag_workflow/data.py",
        "services/rag_workflow/providers.py",
        "services/rag_workflow/prompts/criterion_judge.txt",
        "evaluation/ms3/gemini_developer_provider.py",
        "evaluation/ms3/eligibility/eligibility_protocol.md",
        "evaluation/ms3/eligibility/run_eligibility.py",
    ]
    return {name: sha256_file(ROOT / name) for name in paths if (ROOT / name).is_file()}


def load_cases(store: DataStore) -> list[dict]:
    path = BASE / "eligibility_cases.jsonl"
    cases = read_jsonl(path)
    assert len(cases) == 8, f"Expected exactly 8 frozen cases: {path}"
    assert [c["case_id"] for c in cases] == [f"E{i:02d}" for i in range(1, 9)]
    assert [c["criterion_count"] for c in cases] == list(EXPECTED_SIZES)
    assert [c["split"] for c in cases] == ["all"] * 8
    assert sum(c["criterion_count"] for c in cases) == 115
    assert all(c["patient_reference_date"] == "2021-11-30" for c in cases)
    assert all(c["trial_snapshot_date"] == "2026-10-11" for c in cases)
    provenance = json.loads((BASE / "cohort_manifest.json").read_text(encoding="utf-8"))
    assert provenance["source_sha256"] == store.hashes, (
        "Processed patient/trial/criteria sources changed since the cohort was frozen"
    )
    for case in cases:
        assert case["patient_id"] in store.patients
        assert case["trial_id"] in store.trials
        assert len(store.criteria[case["trial_id"]]) == case["criterion_count"]
        assert store.patient(case["patient_id"])["reference_date"] == case["patient_reference_date"]
        assert store.trials[case["trial_id"]]["snapshot_date"] == case["trial_snapshot_date"]
    return cases


def make_provider(provider_name: str, settings: Settings):
    if provider_name == "offline":
        return None
    if provider_name == "developer":
        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY not set; use --provider offline or set the key privately.")
        # Import lazily: offline evaluation requires no Google SDK credentials.
        from evaluation.ms3.gemini_developer_provider import GeminiDeveloperProvider
        return GeminiDeveloperProvider(settings)
    if provider_name == "vertex":
        if not settings.project:
            raise RuntimeError("GCP_PROJECT is not set; Vertex mode requires GCP_PROJECT.")
        return GeminiProvider(settings)
    raise ValueError(f"Unsupported provider: {provider_name}")


def predict_case(case: dict, store: DataStore, settings: Settings, provider) -> list[dict]:
    """Mirror ScreeningWorkflow's criterion decision path, but bypass Retrieval."""
    patient = store.patient(case["patient_id"])
    trial = store.trials[case["trial_id"]]
    criteria = store.criteria[case["trial_id"]]
    selector = ContextSelector(patient, settings.max_facts_per_criterion)
    flags = complexity_flags(trial, criteria)
    assessments, pending = [], []

    for criterion in criteria:
        if flags:
            assessments.append(unknown(
                criterion,
                "Trial cohort/criterion structure requires review: " + ", ".join(flags),
            ))
            continue
        if len(criterion["criterion_text"]) > settings.max_criterion_chars:
            assessments.append(unknown(
                criterion, "Criterion exceeds supported context budget; not truncated for judgment."
            ))
            continue
        rule = evidence_rule(criterion, patient)
        if rule is not None:
            assessments.append(rule)
            continue
        if provider is None:
            assessments.append(unknown(
                criterion, "Offline baseline: criterion requires LLM interpretation."
            ))
        else:
            pending.append({
                "criterion": {k: criterion[k] for k in ("criterion_id", "criterion_type", "criterion_text")},
                "patient_evidence": selector.select(criterion),
            })

    batches_left = settings.max_llm_batches  # same per-request budget as ScreeningWorkflow
    for start in range(0, len(pending), settings.llm_batch_size):
        batch = pending[start:start + settings.llm_batch_size]
        if batches_left <= 0:
            assessments.extend(unknown(
                item["criterion"], "Per-request inference budget reached.", "INFERENCE_BUDGET"
            ) for item in batch)
            continue
        assessments.extend(judge_batch(provider, patient, case["question"], trial, batch))
        batches_left -= 1

    by_id = {a.criterion_id: a for a in assessments}
    expected = [c["criterion_id"] for c in criteria]
    assert len(assessments) == len(expected), f"Unexpected assessment count for {case['case_id']}"
    assert set(by_id) == set(expected), f"Missing/duplicate criterion IDs for {case['case_id']}"
    fact_ids = set(selector.facts)
    rows = []
    for criterion in criteria:
        a = by_id[criterion["criterion_id"]]
        assert a.criterion_text == criterion["criterion_text"]
        assert a.criterion_type == criterion["criterion_type"]
        assert set(a.evidence_fact_ids) <= fact_ids, "Citation outside the patient's source facts"
        assert set(a.context_fact_ids) <= fact_ids, "Context fact outside the patient"
        row = a.model_dump(mode="json")
        rows.append({
            "case_id": case["case_id"],
            "split": case["split"],
            "patient_id": case["patient_id"],
            "trial_id": case["trial_id"],
            "cohort_flags": list(flags),
            **{("pred_decision" if k == "decision" else k): v for k, v in row.items()},
        })
    return rows


def run_predictions(args: argparse.Namespace) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}", args.tag):
        raise ValueError("--tag must be short and contain only letters, digits, '-' or '_'")
    out = RESULTS / f"{args.split}_{args.provider}_{args.tag}_predictions.jsonl"
    meta = out.with_name(out.stem.replace("_predictions", "") + "_metadata.json")
    metrics = out.with_name(out.stem.replace("_predictions", "") + "_metrics.json")
    errors = out.with_name(out.stem.replace("_predictions", "") + "_disagreements.csv")
    if any(p.exists() for p in (out, meta, metrics, errors)) and not args.overwrite:
        raise FileExistsError(
            f"Output already exists for tag={args.tag}. Choose a NEW --tag or use --overwrite intentionally: {out}"
        )

    base_settings = Settings()
    # Dedicated cache per provider: avoid mixing Vertex and Developer responses.
    settings = replace(
        base_settings,
        mode="offline" if args.provider == "offline" else "live",
        artifacts=RESULTS / "provider_cache" / args.provider,
        generation_model=args.model or base_settings.generation_model,
    )
    settings.validate()
    store = DataStore(settings)
    cases = [c for c in load_cases(store) if c["split"] == args.split]
    assert tuple(c["case_id"] for c in cases) == EXPECTED_SPLITS[args.split]
    provider = make_provider(args.provider, settings)
    rows: list[dict] = []
    try:
        for case in cases:
            per_case = predict_case(case, store, settings, provider)
            rows.extend(per_case)
            methods = Counter(r["method"] for r in per_case)
            errors_here = sum(bool(r["error_code"]) for r in per_case)
            print(f"{case['case_id']}: {len(per_case)} criteria | methods={dict(methods)} | errors={errors_here}")
    finally:
        if provider is not None:
            provider.close()
    assert len(rows) == sum(c["criterion_count"] for c in cases)
    assert len({(r["case_id"], r["criterion_id"]) for r in rows}) == len(rows)

    metadata = {
        "benchmark": "TrialMatch MS3 Eligibility Evaluation",
        "run_phase": "predictions_only_before_gold_comparison",
        "split": args.split,
        "case_ids": [c["case_id"] for c in cases],
        "provider": args.provider,
        "model": settings.generation_model if args.provider != "offline" else None,
        "offline_baseline_not_live_model_evaluation": args.provider == "offline",
        "generation_temperature": 0 if args.provider != "offline" else None,
        "llm_batch_size": settings.llm_batch_size,
        "max_llm_batches_per_case": settings.max_llm_batches,
        "max_facts_per_criterion": settings.max_facts_per_criterion,
        "max_criterion_chars": settings.max_criterion_chars,
        "source_sha256": store.hashes,
        "cases_sha256": sha256_file(BASE / "eligibility_cases.jsonl"),
        "cohort_manifest_sha256": sha256_file(BASE / "cohort_manifest.json"),
        "code_sha256": code_hashes(),
        "git": git_info(),
        "prediction_count": len(rows),
        "prediction_errors": sum(bool(r["error_code"]) for r in rows),
        "model_metrics": dict(provider.metrics) if provider is not None else {},
        "model_response_errors_are_not_valid_unknowns": True,
    }
    # Model predictions are recorded before any gold-label data is read.
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    metadata["predictions_sha256"] = sha256_file(out)
    save_json(meta, metadata)
    print(f"PREDICTIONS SAVED: {out.relative_to(ROOT)}")
    return out


def load_gold(cases: list[dict]) -> tuple[dict[tuple[str, str, str], dict], dict[str, str]]:
    gold: dict[tuple[str, str, str], dict] = {}
    hashes = {}
    for case in cases:
        file = BASE / "reviewed_labels" / f"{case['case_id']}.json"
        record = json.loads(file.read_text(encoding="utf-8"))
        assert record["case_id"] == case["case_id"]
        assert record["patient_id"] == case["patient_id"]
        assert record["trial_id"] == case["trial_id"]
        assert record["review_status"] == "frozen"
        assert len(record["labels"]) == case["criterion_count"]
        hashes[case["case_id"]] = sha256_file(file)
        for row in record["labels"]:
            assert row["gold_decision"] in DECISIONS
            assert row["criterion_type"] in {"inclusion", "exclusion"}
            key = (case["patient_id"], case["trial_id"], row["criterion_id"])
            assert key not in gold, f"Duplicate gold key: {key}"
            gold[key] = row
    return gold, hashes


def safe_ratio(a: int, b: int) -> float | None:
    return round(a / b, 5) if b else None


def confusion_matrix(rows: list[dict]) -> dict[str, dict[str, int]]:
    counts = {a: {b: 0 for b in DECISIONS} for a in DECISIONS}
    for r in rows:
        counts[r["gold_decision"]][r["pred_decision"]] += 1
    return counts


def score_table(rows: list[dict]) -> dict[str, Any]:
    matrix = confusion_matrix(rows)
    n = len(rows)
    right = sum(matrix[d][d] for d in DECISIONS)
    per_class = {}
    f1_values = []
    for cls in DECISIONS:
        tp = matrix[cls][cls]
        support = sum(matrix[cls].values())
        predicted = sum(matrix[actual][cls] for actual in DECISIONS)
        precision = tp / predicted if predicted else None
        recall = tp / support if support else None
        # A class with zero gold support has undefined recall and is not in macro F1.
        f1 = (2 * tp / (support + predicted)) if support + predicted else None
        if support:
            f1_values.append(f1 if f1 is not None else 0.0)
        per_class[cls] = {
            "support": support, "predicted": predicted, "tp": tp,
            "precision": round(precision, 5) if precision is not None else None,
            "recall": round(recall, 5) if recall is not None else None,
            "f1": round(f1, 5) if f1 is not None else None,
        }
    return {
        "n": n,
        "accuracy": safe_ratio(right, n),
        "correct": right,
        "macro_f1": round(sum(f1_values) / len(f1_values), 5) if f1_values else None,
        "macro_f1_classes_with_gold_support": [d for d in DECISIONS if per_class[d]["support"] > 0],
        "per_class": per_class,
        "confusion_gold_rows_pred_columns": matrix,
    }


def trial_status(rows: list[dict], column: str) -> str:
    if any(
        (r["criterion_type"] == "inclusion" and r[column] == "NOT_MET")
        or (r["criterion_type"] == "exclusion" and r[column] == "MET")
        for r in rows
    ):
        return "SCREENING_BARRIER"
    if any(r[column] == "UNKNOWN" for r in rows):
        return "NEEDS_MORE_INFORMATION"
    return "POTENTIAL_MATCH_FOR_REVIEW"


def evaluate_predictions(prediction_path: Path) -> dict:
    if not prediction_path.is_file():
        raise FileNotFoundError(prediction_path)
    meta_path = prediction_path.with_name(prediction_path.stem.replace("_predictions", "") + "_metadata.json")
    if not meta_path.is_file():
        raise FileNotFoundError(f"Run metadata missing: {meta_path}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert sha256_file(prediction_path) == meta["predictions_sha256"], "Prediction file changed after run"
    assert meta["split"] in EXPECTED_SPLITS
    store = DataStore(Settings())
    all_cases = load_cases(store)
    cases = [c for c in all_cases if c["split"] == meta["split"]]
    assert [c["case_id"] for c in cases] == meta["case_ids"]
    assert store.hashes == meta["source_sha256"], "Source files changed since prediction"
    assert sha256_file(BASE / "eligibility_cases.jsonl") == meta["cases_sha256"]
    assert sha256_file(BASE / "cohort_manifest.json") == meta["cohort_manifest_sha256"]
    if meta["code_sha256"] != code_hashes():
        raise RuntimeError("Pipeline or protocol changed since prediction; do not score mismatched versions")

    rows = read_jsonl(prediction_path)
    assert len(rows) == sum(c["criterion_count"] for c in cases)
    gold, gold_hashes = load_gold(cases)
    case_map = {c["case_id"]: c for c in cases}
    expected = set(gold)
    seen = set()
    scored = []
    for row in rows:
        case = case_map[row["case_id"]]
        key = (row["patient_id"], row["trial_id"], row["criterion_id"])
        assert key in expected, f"Unexpected prediction key: {key}"
        assert key not in seen, f"Duplicate prediction key: {key}"
        seen.add(key)
        assert row["split"] == case["split"]
        assert row["patient_id"] == case["patient_id"]
        assert row["trial_id"] == case["trial_id"]
        assert row["pred_decision"] in DECISIONS
        original = gold[key]
        assert row["criterion_type"] == original["criterion_type"]
        assert row["criterion_text"] == original["criterion_text"]
        fact_ids = {f["fact_id"] for f in patient_facts(store.patient(case["patient_id"]))}
        assert set(row["evidence_fact_ids"]) <= fact_ids, "Invalid patient evidence citation"
        scored.append({
            **row,
            "gold_decision": original["gold_decision"],
            "correct": row["pred_decision"] == original["gold_decision"],
            "inference_failure": bool(row["error_code"]),
        })
    assert seen == expected, f"Missing predictions: {len(expected - seen)}"

    by_case = defaultdict(list)
    by_type = defaultdict(list)
    by_method = defaultdict(list)
    for row in scored:
        by_case[row["case_id"]].append(row)
        by_type[row["criterion_type"]].append(row)
        by_method[row["method"]].append(row)
    failures = [r for r in scored if r["inference_failure"]]
    valid = [r for r in scored if not r["inference_failure"]]
    status = {}
    for case_id, items in sorted(by_case.items()):
        status[case_id] = {
            "gold": trial_status(items, "gold_decision"),
            "predicted": trial_status(items, "pred_decision"),
            "matches": trial_status(items, "gold_decision") == trial_status(items, "pred_decision"),
            "has_inference_failure": any(r["inference_failure"] for r in items),
        }

    metrics = {
        "benchmark": "TrialMatch MS3 Eligibility Evaluation",
        "split": meta["split"],
        "provider": meta["provider"],
        "model": meta["model"],
        "official_reporting_ready": meta["provider"] != "offline" and not failures and meta["split"] == "all",
        "not_official_reason": (
            "Offline mode is a rule-only baseline" if meta["provider"] == "offline"
            else "Model-call failures occurred; raw UNKNOWNs may reflect errors, not valid abstention" if failures
            else None
        ),
        "gold_sha256_by_case": gold_hashes,
        "prediction_sha256": meta["predictions_sha256"],
        "criterion_metrics_all_outputs_including_failures": score_table(scored),
        "criterion_metrics_successful_outputs_only": score_table(valid),
        "inference_failures": {
            "count": len(failures), "rate": safe_ratio(len(failures), len(scored)),
            "by_error_code": dict(Counter(r["error_code"] for r in failures)),
            "failed_rows_are_in_full_denominator": True,
            "failure_unknowns_must_not_be_counted_as_successful_abstentions": True,
        },
        "class_safety": {
            "gold_unknown_predicted_definite": sum(r["gold_decision"] == "UNKNOWN" and r["pred_decision"] != "UNKNOWN" for r in scored),
            "gold_definite_predicted_unknown": sum(r["gold_decision"] != "UNKNOWN" and r["pred_decision"] == "UNKNOWN" for r in scored),
            "opposite_definite_judgments": sum(r["gold_decision"] == "MET" and r["pred_decision"] == "NOT_MET" or r["gold_decision"] == "NOT_MET" and r["pred_decision"] == "MET" for r in scored),
        },
        "by_case": {key: score_table(value) for key, value in sorted(by_case.items())},
        "by_criterion_type": {key: score_table(value) for key, value in sorted(by_type.items())},
        "by_method": {key: score_table(value) for key, value in sorted(by_method.items())},
        "method_distribution": dict(Counter(r["method"] for r in scored)),
        "trial_status": status,
        "trial_status_agreement": safe_ratio(sum(v["matches"] for v in status.values()), len(status)),
        "trial_false_potential_matches": sum(v["predicted"] == "POTENTIAL_MATCH_FOR_REVIEW" and v["gold"] != v["predicted"] for v in status.values()),
        "citation_identifier_validity": {
            "valid_references": True,
            "clinical_support_not_automatically_verified": True,
        },
        "limitations": [
            "Small purposively selected Synthea patient-trial pairs, not an enrollment study",
            "Reference decisions are evidence-based non-clinician annotations",
            "Criterion judgments within a trial are correlated",
            "Gold UNKNOWN prevalence is high; evaluate definite prediction safety separately",
            "Citation IDs validated against the patient record, not independently clinically adjudicated",
            "Historical patient reference date 2021-11-30; trial snapshot 2026-10-11",
        ],
    }

    prefix = prediction_path.stem.replace("_predictions", "")
    metrics_path = prediction_path.with_name(prefix + "_metrics.json")
    disagreement_path = prediction_path.with_name(prefix + "_disagreements.csv")
    save_json(metrics_path, metrics)
    fields = [
        "case_id", "patient_id", "trial_id", "criterion_id", "criterion_type",
        "criterion_text", "gold_decision", "pred_decision", "method", "model_decision",
        "inference_failure", "error_code", "reason", "missing_information",
        "evidence_fact_ids", "validation_warnings", "cohort_flags",
    ]
    with disagreement_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in scored:
            if r["correct"] and not r["inference_failure"]:
                continue
            writer.writerow({
                field: json.dumps(r[field], ensure_ascii=False) if isinstance(r.get(field), list) else r.get(field)
                for field in fields
            })

    primary = metrics["criterion_metrics_all_outputs_including_failures"]
    print(f"METRICS SAVED: {metrics_path.relative_to(ROOT)}")
    print(f"DISAGREEMENTS SAVED: {disagreement_path.relative_to(ROOT)}")
    print(f"{meta['split']} | n={primary['n']} | accuracy={primary['accuracy']} | macro-F1={primary['macro_f1']}")
    print(f"Inference failures: {len(failures)}; official reporting ready: {metrics['official_reporting_ready']}")
    print("Confusion matrix (gold rows -> predicted MET, NOT_MET, UNKNOWN):")
    for gold_name in DECISIONS:
        print(f"  {gold_name:8s}: {[primary['confusion_gold_rows_pred_columns'][gold_name][p] for p in DECISIONS]}")
    return metrics


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the original rule/LLM pipeline on fixed pairs, then score")
    run.add_argument("--split", choices=tuple(EXPECTED_SPLITS), required=True)
    run.add_argument("--provider", choices=("offline", "developer", "vertex"), required=True)
    run.add_argument("--model", help="Override GENERATIVE_MODEL (optional)")
    run.add_argument("--tag", default="baseline", help="Unique run tag; defaults to baseline")
    run.add_argument("--overwrite", action="store_true", help="Explicitly replace same-tag output files")
    score = sub.add_parser("score", help="Score existing predictions without calling a model")
    score.add_argument("--predictions", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "run":
        out = run_predictions(args)
        evaluate_predictions(out)
    elif args.command == "score":
        evaluate_predictions(args.predictions.resolve())


if __name__ == "__main__":
    main()
