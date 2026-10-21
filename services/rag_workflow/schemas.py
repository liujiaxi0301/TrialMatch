"""Shared API/function/CLI response contract, including explicit unknown/failure states."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Decision(StrEnum):
    MET = "MET"
    NOT_MET = "NOT_MET"
    UNKNOWN = "UNKNOWN"


class ScreeningStatus(StrEnum):
    BARRIER = "SCREENING_BARRIER"
    NEEDS_INFO = "NEEDS_MORE_INFORMATION"
    POTENTIAL = "POTENTIAL_MATCH_FOR_REVIEW"


class ScreenRequest(StrictModel):
    patient_id: str | None = Field(default=None, min_length=1, max_length=250)
    patient: dict[str, Any] | None = None
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def exactly_one_patient(self):
        if (self.patient_id is None) == (self.patient is None):
            raise ValueError("Provide exactly one of patient_id or normalized patient")
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self


class ErrorDetail(StrictModel):
    code: str
    message: str
    criterion_id: str | None = None


class CriterionAssessment(StrictModel):
    criterion_id: str
    criterion_type: str
    criterion_text: str
    decision: Decision
    reason: str
    evidence_fact_ids: list[str] = Field(default_factory=list)
    context_fact_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    method: str = "abstain"
    error_code: str | None = None
    model_decision: Decision | None = None
    validation_warnings: list[str] = Field(default_factory=list)


class Coverage(StrictModel):
    total: int
    completed: int
    known: int
    unknown: int
    screening_barriers: int


class TrialResult(StrictModel):
    trial_id: str
    brief_title: str | None
    recruitment_status: str | None
    screening_status: ScreeningStatus
    match_score: float | None = Field(default=None, ge=0, le=100)
    score_type: str = "criterion_satisfaction_v0"
    eligibility_probability: None = None
    retrieval: dict[str, Any]
    summary: str
    question_response: str
    assessment_coverage: Coverage
    criteria_assessments: list[CriterionAssessment]
    evidence: dict[str, dict[str, Any]]
    missing_information: list[str]
    screening_concerns: list[str]
    review_required: bool = True
    source_url: str
    trial_snapshot_date: str | None
    warnings: list[str] = Field(default_factory=list)


class ScreenResponse(StrictModel):
    schema_version: str = "0.1"
    run_id: str
    patient_id: str
    question: str
    patient_reference_date: str
    mode: str
    result_status: str
    answer: str
    candidate_trials: list[TrialResult]
    warnings: list[str]
    errors: list[ErrorDetail]
    provenance: dict[str, Any]
    metrics: dict[str, Any]


class LLMJudgment(StrictModel):
    criterion_id: str
    decision: Decision
    reason: str = Field(min_length=1, max_length=2000)
    evidence_fact_ids: list[str]
    missing_information: list[str]


class LLMJudgments(StrictModel):
    assessments: list[LLMJudgment]


class LLMExplanation(StrictModel):
    explanation: str = Field(min_length=1, max_length=4000)
    cited_criterion_ids: list[str]
