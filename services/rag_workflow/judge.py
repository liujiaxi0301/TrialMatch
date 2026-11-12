"""Bounded criterion judgments; validate identifiers and abstain on persistent failure."""

import re

from .config import MODULE
from .evidence_rules import context_patient, evidence_rule
from .providers import ProviderError
from .rules import unknown
from .schemas import CriterionAssessment, Decision, LLMExplanation, LLMJudgments

JUDGE_PROMPT = (MODULE / "prompts/criterion_judge.txt").read_text()
EXPLAIN_PROMPT = (MODULE / "prompts/trial_explanation.txt").read_text()


def evidence_guard(assessment: CriterionAssessment, facts: list[dict], reference_date=None):
    """Check cited evidence, not keywords in a model's explanation alone."""
    if assessment.decision == Decision.UNKNOWN:
        return assessment
    cited = [fact for fact in facts if fact["fact_id"] in assessment.evidence_fact_ids]
    text, reason = assessment.criterion_text.lower(), assessment.reason.lower()
    negative_reason = bool(
        re.search(r"no (?:evidence|record|history)|absence of|not provided", reason)
    )
    verified = evidence_rule(
        {
            key: getattr(assessment, key)
            for key in ("criterion_id", "criterion_type", "criterion_text")
        },
        context_patient(cited, reference_date),
    )
    if verified is not None:
        proposal = assessment.decision
        assessment.decision = verified.decision
        assessment.reason = verified.reason
        assessment.evidence_fact_ids = verified.evidence_fact_ids
        assessment.missing_information = verified.missing_information
        assessment.validation_warnings.extend(verified.validation_warnings)
        if verified.decision != proposal:
            assessment.model_decision = proposal
            assessment.method = "llm_abstain" if verified.decision == Decision.UNKNOWN else "rule"
        if verified.decision == Decision.UNKNOWN and negative_reason:
            assessment.validation_warnings.append("ABSENCE_IS_NOT_NEGATIVE_EVIDENCE")
        return assessment
    issue = None
    if any(fact.get("resource_type") in {"MedicationRequest", "Medication"} for fact in cited):
        issue = "ORDER_OR_DEFINITION_DOES_NOT_ESTABLISH_ACTUAL_DRUG_USE"
    elif negative_reason:
        issue = "ABSENCE_IS_NOT_NEGATIVE_EVIDENCE"
    elif re.search(
        r"[<>≥≤]|\bbetween\b|\bmonths?\b|\bweeks?\b|\byears?\b|\bcurrent\b|\bactive\b|\bstable\b|\bsevere\b|\buncontrolled\b|\bscreening\b",
        text,
    ):
        issue = "UNSUPPORTED_NUMERIC_TEMPORAL_OR_SEVERITY_EXPRESSION"
    elif re.search(r"\band\b|\bor\b|including|unless|consent|willing|competent|investigator", text):
        issue = "UNSUPPORTED_COMPOSITE_OR_SUBJECTIVE_EXPRESSION"
    elif assessment.criterion_type == "exclusion" and assessment.decision == Decision.NOT_MET:
        issue = "EXPLICIT_NEGATIVE_SCOPE_NOT_VERIFIED"
    elif not cited or all(fact.get("resource_type") == "Patient" for fact in cited):
        issue = "DEMOGRAPHICS_DO_NOT_ESTABLISH_CLINICAL_CRITERION"
    if issue:
        assessment.model_decision = assessment.decision
        assessment.decision = Decision.UNKNOWN
        assessment.reason = (
            "The supplied evidence does not verify the complete criterion: " + issue + "."
        )
        assessment.missing_information = [issue]
        assessment.validation_warnings.append(issue)
        assessment.method = "llm_abstain"
    return assessment


def validate_judgments(response: LLMJudgments, items: list[dict]) -> list[CriterionAssessment]:
    expected = {item["criterion"]["criterion_id"]: item for item in items}
    received = [row.criterion_id for row in response.assessments]
    if len(received) != len(set(received)) or set(received) != set(expected):
        raise ValueError("Every requested criterion must appear exactly once, with no extra IDs")
    output = []
    for row in response.assessments:
        item = expected[row.criterion_id]
        offered = {f["fact_id"] for f in item["patient_evidence"]}
        if not set(row.evidence_fact_ids) <= offered:
            raise ValueError("Evidence IDs must belong to this criterion's patient context")
        if row.decision != Decision.UNKNOWN and not row.evidence_fact_ids:
            raise ValueError("Definite judgments must cite supporting patient evidence")
        if row.decision == Decision.UNKNOWN and not row.missing_information:
            raise ValueError("UNKNOWN must identify missing or ambiguous information")
        output.append(
            CriterionAssessment(
                **item["criterion"],
                **row.model_dump(exclude={"criterion_id"}),
                method="llm",
                context_fact_ids=sorted(offered),
            )
        )
    return output


def judge_batch(provider, patient: dict, question: str, trial: dict, items: list[dict]):
    # Use short per-criterion evidence aliases in model prompts, then map to ORIGINAL fact IDs.
    # This avoids long file-based IDs being shortened or fabricated by the LLM.
    wire_items, aliases = [], {}
    for item in items:
        criterion_id = item["criterion"]["criterion_id"]
        aliases[criterion_id] = {}
        evidence = []
        for position, fact in enumerate(item["patient_evidence"]):
            alias = f"F{position}"
            aliases[criterion_id][alias] = fact["fact_id"]
            evidence.append(
                {
                    **{
                        k: v
                        for k, v in fact.items()
                        if k not in {"fact_id", "source_file", "source_resource_id"}
                    },
                    "fact_id": alias,
                }
            )
        wire_items.append({"criterion": item["criterion"], "patient_evidence": evidence})
    payload = {
        "patient_reference_date": patient["reference_date"],
        "question": question,
        "trial_id": trial["trial_id"],
        "trial_eligibility_text": trial.get("eligibility_text"),
        "response_language": "English",
        "items": wire_items,
    }
    last_error = "INVALID_LLM_OUTPUT"
    for attempt in range(2):
        try:
            prompt = (
                JUDGE_PROMPT
                + "\nReturn reason/missing_information in "
                + payload["response_language"]
                + "."
            )
            response = provider.generate(prompt, payload, LLMJudgments)
            for row in response.assessments:
                mapping = aliases.get(row.criterion_id, {})
                if not set(row.evidence_fact_ids) <= set(mapping):
                    raise ValueError("Only supplied short evidence aliases are permitted")
                row.evidence_fact_ids = [mapping[key] for key in row.evidence_fact_ids]
            assessments = validate_judgments(response, items)
            contexts = {
                item["criterion"]["criterion_id"]: item["patient_evidence"] for item in items
            }
            return [
                evidence_guard(a, contexts[a.criterion_id], patient["reference_date"])
                for a in assessments
            ]
        except ProviderError as exc:
            last_error = exc.code
            break
        except (ValueError, TypeError, KeyError):
            payload["repair_instruction"] = (
                "Previous response failed schema/ID validation. Return each requested criterion once, use only its F0/F1/... evidence aliases, and state missing information for UNKNOWN."
            )
            if attempt == 1:
                break
    return [
        unknown(
            item["criterion"],
            "Model assessment unavailable or invalid; human review required.",
            last_error,
        )
        for item in items
    ]


def explain_trial(provider, question, trial, result, assessments) -> str:
    payload = {
        "question": question,
        "response_language": "English",
        "trial_id": trial["trial_id"],
        "trial_title": trial.get("brief_title"),
        "screening_status": result,
        "assessments": [
            a.model_dump(
                mode="json", exclude={"context_fact_ids", "evidence_fact_ids", "model_decision"}
            )
            for a in assessments
        ],
    }
    for attempt in range(2):
        try:
            response = provider.generate(
                EXPLAIN_PROMPT + "\nWrite the explanation in " + payload["response_language"] + ".",
                payload,
                LLMExplanation,
            )
            expected = {a.criterion_id for a in assessments}
            citations = set(response.cited_criterion_ids)
            # Accept [ID1, ID2] as well as [ID1] [ID2], while validating every ID.
            in_text = {
                identifier
                for group in re.findall(r"\[([^\[\]]+)\]", response.explanation)
                for identifier in re.split(r"[,;\s]+", group.strip())
                if identifier
            }
            if citations and citations <= expected and in_text == citations:
                return response.explanation
        except (ValueError, TypeError):
            pass
        payload["repair_instruction"] = (
            "Cite supplied criterion IDs in [ID] format and list exactly those IDs."
        )
    raise ProviderError("INVALID_EXPLANATION", "Could not validate explanation citations.")
