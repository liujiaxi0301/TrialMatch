"""Run the shared Claude synthetic case through fixed-trial and normal RAG paths.

Default is offline. --live explicitly enables existing GeminiProvider/GCP calls.
The fixed-trial layer supplies the complete fixture to isolate judgment grounding;
the end-to-end layer uses unchanged production retrieval and context selection.
"""

import argparse
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

from .config import MODULE, ROOT, Settings
from .data import DataStore, patient_facts, validate_patient
from .evidence_rules import evidence_rule
from .judge import judge_batch
from .providers import GeminiProvider, content_hash, save_json
from .retrieve import fact_summary, patient_query
from .rules import unknown
from .schemas import Decision, ScreenRequest
from .workflow import ScreeningWorkflow, aggregate, template_explanation

CASE = MODULE / "examples/grounding_case"
QUESTION = (
    "Which clinical trials may suit this patient? Explain supporting evidence, screening "
    "barriers, and what remains unknown, using only the supplied trial criteria and patient record."
)


class RecordingProvider(GeminiProvider):
    """Real provider with an audit copy taken before aliases/guards modify model output."""

    def __init__(self, settings):
        super().__init__(settings)
        self.trace = []

    def generate(self, system, payload, schema):
        response = super().generate(system, payload, schema)
        self.trace.append(
            {
                "operation": schema.__name__,
                "system_instruction": system,
                "input": json.loads(json.dumps(payload)),
                "raw_model_response": response.model_dump(mode="json"),
            }
        )
        print(f"Fixed-trial model batch completed: {len(self.trace)}", flush=True)
        return response


def fixed_trial(settings, store, patient):
    criteria = store.criteria["NCT02390973"]
    trial = store.trials["NCT02390973"]
    # This is NOT a retrieval test: offer the whole small fixture, like the Claude baseline.
    facts = [fact_summary(fact) for fact in patient_facts(patient)]
    assessments, pending = [], []
    for criterion in criteria:
        rule = evidence_rule(criterion, patient)
        if rule is not None:
            assessments.append(rule)
        elif settings.mode == "offline":
            assessments.append(unknown(criterion, "Offline mode does not run an LLM."))
        else:
            pending.append(
                {
                    "criterion": {
                        key: criterion[key]
                        for key in ("criterion_id", "criterion_type", "criterion_text")
                    },
                    "patient_evidence": facts,
                }
            )
    provider, trace, metrics = None, [], {}
    try:
        if pending:
            provider = RecordingProvider(settings)
            for start in range(0, len(pending), settings.llm_batch_size):
                assessments.extend(
                    judge_batch(
                        provider,
                        patient,
                        QUESTION,
                        trial,
                        pending[start : start + settings.llm_batch_size],
                    )
                )
            trace, metrics = provider.trace, dict(provider.metrics)
    finally:
        if provider is not None:
            provider.close()
    by_id = {row.criterion_id: row for row in assessments}
    rows = [by_id[criterion["criterion_id"]] for criterion in criteria]
    status, score, coverage, _ = aggregate(criteria, rows)
    return {
        "test_layer": "fixed_trial_full_fixture_context_not_retrieval",
        "mode": settings.mode,
        "patient_id": patient["patient_id"],
        "trial_id": trial["trial_id"],
        "screening_status": status.value,
        "match_score": score,
        "assessment_coverage": coverage.model_dump(),
        "criteria_assessments": [row.model_dump(mode="json") for row in rows],
        "evidence": {fact["fact_id"]: fact for fact in facts},
        "answer": template_explanation(trial, status, coverage, rows, QUESTION),
        "metrics": metrics,
    }, trace


def evaluate_fixed(fixed, expectations, baseline):
    rows = {row["criterion_id"]: row for row in fixed["criteria_assessments"]}
    focus = []
    for key, expected in expectations["focus"].items():
        row = rows[key]
        focus.append(
            {
                "criterion_id": key,
                "claude_baseline_decision": baseline["decisions"][key],
                "expected_closed_context_decision": expected["expected"],
                "actual_decision": row["decision"],
                "raw_model_proposal_before_guard": (
                    row["model_decision"] or row["decision"]
                    if row["method"] in {"llm", "llm_abstain"}
                    else None
                ),
                "method": row["method"],
                "validation_warnings": row["validation_warnings"],
                "reason": row["reason"],
                "evidence_fact_ids": row["evidence_fact_ids"],
                "passed": row["decision"] == expected["expected"] and not row["error_code"],
            }
        )
    controls = [
        {"criterion_id": key, "expected": expected, "actual": rows[key]["decision"]}
        for key, expected in expectations["positive_controls"].items()
    ]
    errors = [row["error_code"] for row in rows.values() if row["error_code"]]
    citations_valid = all(
        set(row["evidence_fact_ids"]) <= set(fixed["evidence"])
        and (row["decision"] == Decision.UNKNOWN or bool(row["evidence_fact_ids"]))
        for row in rows.values()
    )
    passed = all(row["passed"] for row in focus) and citations_valid and not errors
    return {
        "focus_checks": focus,
        "citation_ids_valid": citations_valid,
        "error_codes": errors,
        "positive_controls": controls,
        "positive_controls_met": sum(row["actual"] == row["expected"] for row in controls),
        "positive_controls_total": len(controls),
        "decision_counts": dict(Counter(row["decision"] for row in rows.values())),
        "grounding_focus_passed": passed if fixed["mode"] == "live" else None,
        "interpretation": (
            "Evaluate guarded outputs separately from raw model behavior. UNKNOWN-only output "
            "does not establish a useful or accurate model. Positive controls quantify abstention."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Enable real Gemini calls")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/rag_workflow/grounding_case"
    )
    args = parser.parse_args(argv)
    settings = replace(Settings(), mode="live" if args.live else "offline")
    patient = validate_patient(json.loads((CASE / "patient.json").read_text()))
    baseline = json.loads((CASE / "claude_baseline.json").read_text())
    expectations = json.loads((CASE / "expectations.json").read_text())
    store = DataStore(settings)
    print(f"Running fixed-trial {settings.mode} assessment: 14 criteria", flush=True)
    fixed, trace = fixed_trial(settings, store, patient)
    save_json(args.output_dir / "fixed_trial_response.json", fixed)
    save_json(args.output_dir / "fixed_trial_model_trace.json", trace)
    evaluation = evaluate_fixed(fixed, expectations, baseline)
    # Preserve the fixed-trial finding even if the subsequent live retrieval fails.
    save_json(args.output_dir / "fixed_trial_verification.json", evaluation)
    print("Running normal 50-trial RAG retrieval and screening (top_k=3)", flush=True)
    response = ScreeningWorkflow(settings).screen(
        ScreenRequest(patient=patient, question=QUESTION, top_k=3)
    )
    save_json(args.output_dir / "full_rag_response.json", response.model_dump(mode="json"))
    trace_rows = []
    for trial in response.candidate_trials:
        hit = trial.retrieval.get("semantic_hit") or {}
        retrieved = next(
            (
                c
                for c in store.criteria[trial.trial_id]
                if c["criterion_id"] == hit.get("criterion_id")
            ),
            None,
        )
        trace_rows.append(
            {
                "trial_id": trial.trial_id,
                "retrieval": trial.retrieval,
                "retrieved_criterion": retrieved,
                "all_trial_criteria": [
                    row.model_dump(mode="json") for row in trial.criteria_assessments
                ],
                "cited_patient_evidence": trial.evidence,
            }
        )
    save_json(
        args.output_dir / "retrieval_trace.json",
        {"query": patient_query(patient, QUESTION), "results": trace_rows},
    )
    summary = {
        "mode": settings.mode,
        "source_case": str(CASE.relative_to(ROOT)),
        "source_patient_sha256": content_hash(patient),
        "source_data_sha256": store.hashes,
        "embedding_model": settings.embedding_model if args.live else None,
        "generation_model": settings.generation_model if args.live else None,
        "fixed_trial": evaluation,
        "full_rag": {
            "result_status": response.result_status,
            "candidate_trial_ids": [trial.trial_id for trial in response.candidate_trials],
            "target_trial_retrieved": any(
                trial.trial_id == "NCT02390973" for trial in response.candidate_trials
            ),
            "metrics": response.metrics,
            "errors": [error.model_dump() for error in response.errors],
        },
        "limitations": [
            "One synthetic case, not clinical validation or an accuracy benchmark.",
            "Claude and Gemini differ in model, prompt packaging and evidence guards; no isolated causal claim about RAG superiority.",
            "A fixed-trial pass does not establish that full retrieval selected the target trial.",
            "Missing dates, a fixture-assigned reference date, conservative guards and normalized-input adapters affect coverage.",
        ],
    }
    save_json(args.output_dir / "verification_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return int(
        bool(evaluation["error_codes"])
        or (args.live and not evaluation["grounding_focus_passed"])
        or response.result_status in {"ERROR", "PARTIAL"}
    )


if __name__ == "__main__":
    raise SystemExit(main())
