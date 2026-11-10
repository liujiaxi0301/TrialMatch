"""One synthetic full-workflow integration check; not a clinical quality benchmark."""

import argparse
import json
import time
from dataclasses import replace

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.providers import save_json
from services.rag_workflow.schemas import ScreenRequest
from services.rag_workflow.workflow import ScreeningWorkflow

from .benchmark import BIO_MODEL, BIO_REVISION, DEFAULT_OUTPUT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoder", choices=["gemini", "bioclinical"], required=True)
    args = parser.parse_args()
    settings = replace(
        Settings(),
        mode="live",
        artifacts=DEFAULT_OUTPUT / args.encoder,
        chroma_host="",
        embedding_provider=args.encoder,
        embedding_model=BIO_MODEL if args.encoder == "bioclinical" else "gemini-embedding-001",
        dimension=768 if args.encoder == "bioclinical" else 256,
        embedding_revision=BIO_REVISION if args.encoder == "bioclinical" else "",
    )
    store = DataStore(settings)
    request = ScreenRequest(
        patient_id=store.manifest()["patient_ids"][0],
        question="What requirements concern kidney function?",
        top_k=1,
    )
    started = time.perf_counter()
    response = ScreeningWorkflow(settings).screen(request)
    path = DEFAULT_OUTPUT / "screening" / f"{args.encoder}.json"
    save_json(path, response.model_dump(mode="json"))
    # Verify every criterion was assessed once and every citation belongs to this synthetic patient.
    for trial in response.candidate_trials:
        expected = {row["criterion_id"] for row in store.criteria[trial.trial_id]}
        actual = [row.criterion_id for row in trial.criteria_assessments]
        assert set(actual) == expected and len(actual) == len(expected)
        assert all(
            set(row.evidence_fact_ids) <= set(trial.evidence) for row in trial.criteria_assessments
        )
    summary = {
        "encoder": args.encoder,
        "result_status": response.result_status,
        "candidate_count": len(response.candidate_trials),
        "trial_ids": [row.trial_id for row in response.candidate_trials],
        "criteria_assessed": sum(
            len(row.criteria_assessments) for row in response.candidate_trials
        ),
        "error_codes": [row.code for row in response.errors],
        "latency_seconds": time.perf_counter() - started,
        "metrics": response.metrics,
        "disclaimer": "Synthetic integration smoke only; no human eligibility labels.",
    }
    save_json(path.with_name(f"{args.encoder}.checks.json"), summary)
    print(json.dumps(summary, indent=2))
    if response.result_status != "OK" or len(response.candidate_trials) != 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
