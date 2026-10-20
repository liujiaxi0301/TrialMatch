"""Public screening workflow shared by the CLI and HTTP API."""

import time
import uuid
from datetime import UTC, datetime

from .config import Settings
from .data import DataStore, complexity_flags, parse_date, validate_patient
from .evidence_rules import evidence_rule
from .index import VectorIndex
from .judge import explain_trial, judge_batch
from .providers import GeminiProvider, ProviderError
from .retrieve import ContextSelector, Retriever, fact_summary
from .rules import unknown
from .schemas import (
    Coverage,
    Decision,
    ErrorDetail,
    ScreeningStatus,
    ScreenRequest,
    ScreenResponse,
    TrialResult,
)


def aggregate(criteria: list[dict], assessments: list, force_review: bool = False):
    expected = {c["criterion_id"] for c in criteria}
    received = [a.criterion_id for a in assessments]
    if len(received) != len(set(received)) or set(received) != expected:
        raise ValueError("Cannot aggregate missing, duplicate, or unexpected assessments")
    barriers = [
        a
        for a in assessments
        if (a.criterion_type == "inclusion" and a.decision == Decision.NOT_MET)
        or (a.criterion_type == "exclusion" and a.decision == Decision.MET)
    ]
    favorable = sum(
        (a.criterion_type == "inclusion" and a.decision == Decision.MET)
        or (a.criterion_type == "exclusion" and a.decision == Decision.NOT_MET)
        for a in assessments
    )
    unknown_count = sum(a.decision == Decision.UNKNOWN for a in assessments)
    completed = sum(a.method in {"rule", "llm", "llm_abstain"} for a in assessments)
    status = ScreeningStatus.NEEDS_INFO
    if not force_review and barriers:
        status = ScreeningStatus.BARRIER
    elif not force_review and assessments and not unknown_count and completed == len(criteria):
        status = ScreeningStatus.POTENTIAL
    coverage = Coverage(
        total=len(criteria),
        completed=completed,
        known=len(assessments) - unknown_count,
        unknown=unknown_count,
        screening_barriers=len(barriers),
    )
    score = round(100 * favorable / len(criteria), 1) if criteria else None
    return status, score, coverage, barriers


def template_explanation(trial, status, coverage, assessments, question) -> str:
    known = [a for a in assessments if a.decision != Decision.UNKNOWN]
    missing = [a for a in assessments if a.decision == Decision.UNKNOWN]
    parts = [f"{trial['trial_id']}: {status.value}."]
    parts += [f"{a.reason} [{a.criterion_id}]" for a in known[:2]]
    parts += [f"Needs review: {a.reason} [{a.criterion_id}]" for a in missing[:2]]
    parts.append(
        f"{coverage.unknown}/{coverage.total} criteria unknown. Match score is not an enrollment probability. Treatment adverse-event risks are not established by this dataset."
    )
    return " ".join(parts)


class ScreeningWorkflow:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.settings.validate()
        self.store = DataStore(self.settings)
        self.manifest = self.store.manifest()

    def screen(self, request: ScreenRequest) -> ScreenResponse:
        patient = (
            validate_patient(request.patient)
            if request.patient is not None
            else self.store.patient(request.patient_id)
        )
        started = time.monotonic()
        errors, warnings, results = [], [], []
        warnings.append(
            "HISTORICAL_SYNTHETIC_DEMO: patient reference date and trial snapshot are separate; this is not current enrollment eligibility."
        )
        if self.settings.mode == "offline":
            warnings.append(
                "OFFLINE_MODE: real BM25 retrieval and deterministic rules; no embeddings or LLM calls; unsupported criteria remain UNKNOWN."
            )
        if parse_date(patient["demographics"].get("deceased_date")) and (
            parse_date(patient["demographics"]["deceased_date"])
            <= parse_date(patient["reference_date"])
        ):
            warnings.append(
                "PATIENT_DECEASED_AT_REFERENCE: historical synthetic record; not a prospective enrollment recommendation."
            )
        if patient.get("warnings"):
            warnings.append(
                f"PATIENT_SOURCE_WARNINGS: {len(patient['warnings'])}; source processing omitted some resource types or retained uncertain facts."
            )
        provider = None
        try:
            vector_index = None
            if self.settings.mode == "live":
                provider = GeminiProvider(self.settings)
                vector_index = VectorIndex(self.settings, self.store, self.manifest, provider)
            hits = Retriever(self.store, self.manifest, vector_index).retrieve(
                patient, request.question, request.top_k
            )
            selector = ContextSelector(patient, self.settings.max_facts_per_criterion)
            batches_left = self.settings.max_llm_batches
            for hit in hits:
                trial = self.store.trials[hit["trial_id"]]
                criteria = self.store.criteria[hit["trial_id"]]
                flags = complexity_flags(trial, criteria)
                assessments, pending = [], []
                for criterion in criteria:
                    if flags:
                        assessments.append(
                            unknown(
                                criterion,
                                "Trial cohort/criterion structure requires review: "
                                + ", ".join(flags),
                            )
                        )
                        continue
                    if len(criterion["criterion_text"]) > self.settings.max_criterion_chars:
                        assessments.append(
                            unknown(
                                criterion,
                                "Criterion exceeds the supported context budget; not truncated for judgment.",
                            )
                        )
                        continue
                    rule = evidence_rule(criterion, patient)
                    if rule is not None:
                        assessments.append(rule)
                        continue
                    if provider is None:
                        assessments.append(
                            unknown(
                                criterion,
                                "This criterion requires interpretation; offline mode does not run an LLM.",
                            )
                        )
                    else:
                        pending.append(
                            {
                                "criterion": {
                                    k: criterion[k]
                                    for k in ("criterion_id", "criterion_type", "criterion_text")
                                },
                                "patient_evidence": selector.select(criterion),
                            }
                        )
                for start in range(0, len(pending), self.settings.llm_batch_size):
                    batch = pending[start : start + self.settings.llm_batch_size]
                    if batches_left <= 0:
                        assessments.extend(
                            unknown(
                                item["criterion"],
                                "Per-request inference budget reached.",
                                "INFERENCE_BUDGET",
                            )
                            for item in batch
                        )
                        continue
                    assessments.extend(
                        judge_batch(provider, patient, request.question, trial, batch)
                    )
                    batches_left -= 1
                by_id = {a.criterion_id: a for a in assessments}
                assessments = [by_id[c["criterion_id"]] for c in criteria]
                # Rules may choose evidence outside the lexical context; validate against full patient.
                for a in assessments:
                    if not set(a.evidence_fact_ids) <= set(selector.facts):
                        raise ValueError("A judgment cited evidence outside this patient")
                    if a.error_code:
                        errors.append(
                            ErrorDetail(
                                code=a.error_code, message=a.reason, criterion_id=a.criterion_id
                            )
                        )
                status, score, coverage, barriers = aggregate(
                    criteria, assessments, force_review=bool(flags)
                )
                explanation = template_explanation(
                    trial, status, coverage, assessments, request.question
                )
                if provider is not None and any(
                    a.method in {"llm", "llm_abstain"} for a in assessments
                ):
                    try:
                        explanation = explain_trial(
                            provider, request.question, trial, status.value, assessments
                        )
                    except (ProviderError, ValueError, TypeError) as exc:
                        errors.append(
                            ErrorDetail(
                                code=getattr(exc, "code", "INVALID_EXPLANATION"),
                                message="LLM explanation unavailable; the labeled assessment template is shown.",
                            )
                        )
                        flags.append("TEMPLATE_EXPLANATION_AFTER_MODEL_ERROR")
                cited = {key for a in assessments for key in a.evidence_fact_ids}
                missing = list(dict.fromkeys(m for a in assessments for m in a.missing_information))
                results.append(
                    TrialResult(
                        trial_id=trial["trial_id"],
                        brief_title=trial.get("brief_title"),
                        recruitment_status=trial.get("overall_status"),
                        screening_status=status,
                        match_score=score,
                        retrieval=hit,
                        summary=f"{coverage.known}/{coverage.total} criteria known; {coverage.screening_barriers} confirmed barriers; {coverage.unknown} unknown.",
                        question_response=explanation,
                        assessment_coverage=coverage,
                        criteria_assessments=assessments,
                        evidence={key: fact_summary(selector.facts[key]) for key in sorted(cited)},
                        missing_information=missing,
                        screening_concerns=[f"{a.criterion_id}: {a.reason}" for a in barriers]
                        + flags,
                        source_url=f"https://clinicaltrials.gov/study/{trial['trial_id']}",
                        trial_snapshot_date=trial.get("snapshot_date"),
                        warnings=flags,
                    )
                )
        except ProviderError as exc:
            errors.append(ErrorDetail(code=exc.code, message=str(exc)))
        finally:
            if provider is not None:
                provider.close()
        # Barrier status is separate from retrieval ranking and cannot be averaged away by score.
        results.sort(
            key=lambda trial: (
                trial.screening_status == ScreeningStatus.BARRIER,
                -trial.retrieval["rank_score"],
                -(trial.match_score or 0),
                trial.trial_id,
            )
        )
        result_status = (
            "PARTIAL"
            if errors and results
            else "ERROR"
            if errors
            else "OK"
            if results
            else "NO_CANDIDATES"
        )
        if results:
            answer = "\n\n".join(r.question_response for r in results)
        elif errors:
            answer = (
                "Screening could not complete. Inspect errors; no eligibility conclusion was made."
            )
        else:
            answer = "No candidates were retrieved from the configured subset. This does not establish ineligibility."
        metrics = {
            "latency_seconds": round(time.monotonic() - started, 3),
            "candidate_count": len(results),
            "corpus_trial_count": len(self.manifest["trial_ids"]),
        }
        if provider:
            metrics.update(provider.metrics)
        return ScreenResponse(
            run_id=uuid.uuid4().hex,
            patient_id=patient["patient_id"],
            question=request.question,
            patient_reference_date=patient["reference_date"],
            mode=self.settings.mode,
            result_status=result_status,
            answer=answer,
            candidate_trials=results,
            warnings=warnings,
            errors=errors,
            provenance={
                "engine_version": "0.1.0",
                "created_at": datetime.now(UTC).isoformat(),
                "source_sha256": self.store.hashes,
                "patient_input": "inline" if request.patient else "cohort",
                "embedding_model": self.settings.embedding_model if provider else None,
                "generation_model": self.settings.generation_model if provider else None,
                "trial_ids": self.manifest["trial_ids"],
                "score_definition": "100 * (inclusion MET + exclusion NOT_MET) / total criteria; UNKNOWN remains in denominator; not probability",
            },
            metrics=metrics,
        )


def screen_patient(
    patient: dict, question: str, top_k: int = 3, settings: Settings | None = None
) -> dict:
    """Oliver can call this with one Part 2 normalized patient object and a question."""
    return (
        ScreeningWorkflow(settings)
        .screen(ScreenRequest(patient=patient, question=question, top_k=top_k))
        .model_dump(mode="json")
    )
