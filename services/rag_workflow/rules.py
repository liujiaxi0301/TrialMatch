"""Narrow, auditable numeric rules; unsupported wording goes to LLM/UNKNOWN."""

import calendar
import math
import re
from datetime import date, timedelta

from .data import parse_date
from .schemas import CriterionAssessment, Decision


def normalized(text: str) -> str:
    return (
        text.replace("\\", "").replace("≥", ">=").replace("≤", "<=").replace("–", "-").strip(" .;")
    )


def assessment(criterion: dict, decision, reason: str, refs=(), missing=()) -> CriterionAssessment:
    return CriterionAssessment(
        **{k: criterion[k] for k in ("criterion_id", "criterion_type", "criterion_text")},
        decision=decision,
        reason=reason,
        evidence_fact_ids=list(refs),
        missing_information=list(missing),
        method="rule",
    )


def unknown(criterion: dict, reason: str, code: str | None = None) -> CriterionAssessment:
    result = assessment(criterion, Decision.UNKNOWN, reason, missing=[reason])
    result.method = "abstain"
    result.error_code = code
    return result


def shift_back(anchor: date, count: int, unit: str) -> date:
    if unit.startswith(("day", "week")):
        return anchor - timedelta(days=count * (7 if unit.startswith("week") else 1))
    months = count * (12 if unit.startswith("year") else 1)
    total = anchor.year * 12 + anchor.month - 1 - months
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, min(anchor.day, calendar.monthrange(year, month0 + 1)[1]))


def numeric_rule(criterion: dict, patient: dict) -> CriterionAssessment | None:
    text = normalized(criterion["criterion_text"])
    demo = patient["demographics"]
    age = demo.get("age_years_at_reference")
    # Full matches only: do not accidentally evaluate one clause of a composite criterion.
    between = re.fullmatch(
        r"(?:age[d]?\s*)?(?:between\s+)?(\d+)\s*(?:-|to|and)\s*(\d+)\s*(?:years(?:\s+old)?(?:\s+of\s+age)?)?",
        text,
        re.IGNORECASE,
    )
    bound = re.fullmatch(
        r"age[d]?\s*(>=|<=|>|<|at least|at most|over|under)\s*(\d+)\s*(?:years(?:\s+old)?)?",
        text,
        re.IGNORECASE,
    )
    plus = re.fullmatch(r"(?:age[d]?\s*)?(\d+)\s*(?:\+|years or older)", text, re.IGNORECASE)
    age_wording = bool(re.search(r"\bage[d]?\b|\byears\b", text, re.IGNORECASE))
    if age_wording and (between or bound or plus):
        if age is None:
            return unknown(criterion, "Age at patient reference_date is unavailable.")
        if between:
            passed = int(between[1]) <= age <= int(between[2])
        elif plus:
            passed = age >= int(plus[1])
        else:
            op, threshold = bound[1].lower(), int(bound[2])
            passed = {
                ">=": age >= threshold,
                "at least": age >= threshold,
                "<=": age <= threshold,
                "at most": age <= threshold,
                ">": age > threshold,
                "<": age < threshold,
                "over": age > threshold,
                "under": age < threshold,
            }[op]
        return assessment(
            criterion,
            Decision.MET if passed else Decision.NOT_MET,
            f"Age is {age} at {patient['reference_date']}; checked against the exact age statement.",
            [demo["fact_id"]],
        )

    hba = re.fullmatch(
        r"(?:HbA1c|hemoglobin A1c)\s*(>=|<=|>|<)\s*(\d+(?:\.\d+)?)\s*%(?:\s+within (?:the )?(?:last |past )?(\d+) (days?|weeks?|months?|years?))?",
        text,
        re.IGNORECASE,
    )
    hba_range = re.fullmatch(
        r"(?:HbA1c|hemoglobin A1c)\s*(?:between\s+)?(\d+(?:\.\d+)?)\s*%?\s*(?:and|to|-)\s*(\d+(?:\.\d+)?)\s*%(?:\s+within (?:the )?(?:last |past )?(\d+) (days?|weeks?|months?|years?))?",
        text,
        re.IGNORECASE,
    )
    if not hba and not hba_range:
        return None
    time_count, time_unit = (hba[3], hba[4]) if hba else (hba_range[3], hba_range[4])
    candidates = []
    anchor = parse_date(patient["reference_date"])
    for fact in patient.get("observations", []):
        codings = (fact.get("code") or {}).get("coding", [])
        if not any(
            c.get("system") == "http://loinc.org" and c.get("code") == "4548-4" for c in codings
        ):
            continue
        when = parse_date(
            fact.get("effective_date") or (fact.get("effective_period") or {}).get("start")
        )
        value = fact.get("value") or {}
        raw = value.get("data") or {}
        if (
            value.get("type") != "Quantity"
            or raw.get("unit") != "%"
            or when is None
            or when > anchor
        ):
            continue
        if fact.get("raw_status") not in {"final", "amended", "corrected"}:
            continue
        number = raw.get("value")
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            continue
        if time_count and when < shift_back(anchor, int(time_count), time_unit):
            continue
        candidates.append((when, float(number), fact["fact_id"]))
    if not candidates:
        return unknown(
            criterion, "No final, dated HbA1c in % satisfies the required measurement window."
        )
    latest = max(c[0] for c in candidates)
    selected = [c for c in candidates if c[0] == latest]
    if len({c[1] for c in selected}) != 1:
        return unknown(
            criterion, "Conflicting HbA1c values on the latest usable date require review."
        )
    value = selected[0][1]
    if hba_range:
        passed = float(hba_range[1]) <= value <= float(hba_range[2])
    else:
        threshold, op = float(hba[2]), hba[1]
        passed = {
            ">=": value >= threshold,
            "<=": value <= threshold,
            ">": value > threshold,
            "<": value < threshold,
        }[op]
    return assessment(
        criterion,
        Decision.MET if passed else Decision.NOT_MET,
        f"HbA1c {value}% on {latest.isoformat()}, relative to {anchor.isoformat()}.",
        [c[2] for c in selected],
    )
