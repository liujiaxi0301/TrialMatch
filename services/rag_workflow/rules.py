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

    return measurement_rule(criterion, patient)


def measurement_rule(criterion: dict, patient: dict) -> CriterionAssessment | None:
    """Parse complete supported comparisons before evaluating any numeric branch."""
    text = re.sub(r"(?<=\d),(?=\d)", ".", normalized(criterion["criterion_text"]))
    leaf = parse_measurement(text)
    if leaf is not None:
        return evaluate_measurement(criterion, patient, leaf)
    has_or = bool(re.search(r"\bor\b", text, re.IGNORECASE))
    has_and = bool(re.search(r"\band\b", text, re.IGNORECASE))
    if has_or == has_and or "(" in text or ")" in text:
        return None  # No partial interpretation of mixed/parenthesized/unsupported logic.
    join = "or" if has_or else "and"
    parts = re.split(rf"\s+{join}\s+", text, flags=re.IGNORECASE)
    leaves = [parse_measurement(part) for part in parts]
    if any(item is None for item in leaves):
        return None
    branches = [evaluate_measurement(criterion, patient, item) for item in leaves]
    if join == "or":
        decision = (
            Decision.MET
            if any(row.decision == Decision.MET for row in branches)
            else Decision.NOT_MET
            if all(row.decision == Decision.NOT_MET for row in branches)
            else Decision.UNKNOWN
        )
    else:
        decision = (
            Decision.NOT_MET
            if any(row.decision == Decision.NOT_MET for row in branches)
            else Decision.MET
            if all(row.decision == Decision.MET for row in branches)
            else Decision.UNKNOWN
        )
    refs = list(dict.fromkeys(ref for row in branches for ref in row.evidence_fact_ids))
    result = assessment(
        criterion,
        decision,
        f"{join.upper()} evaluated with three-valued logic: "
        + "; ".join(row.reason for row in branches),
        refs,
        [row.reason for row in branches if row.decision == Decision.UNKNOWN]
        if decision == Decision.UNKNOWN
        else [],
    )
    result.validation_warnings = list(
        dict.fromkeys(w for row in branches for w in row.validation_warnings)
    )
    return result


MEASURE = r"(?P<measure>BMI|body mass index|HbA1c|hemoglobin A1c|fasting (?:glucose|glycemia)|non[- ]?fasting (?:glucose|glycemia))"
NUMBER = r"\d+(?:\.\d+)?"
UNIT = r"(?:%|kg/m(?:²|2|\^2)|mmol/l|mg/dl)"
WINDOW = (
    r"(?:\s+within (?:the )?(?:last |past )?(?P<count>\d+) (?P<unit>days?|weeks?|months?|years?))?"
)


def parse_measurement(text: str) -> dict | None:
    bound = re.fullmatch(
        MEASURE + rf"\s*(?P<op>>=|<=|>|<)\s*(?P<low>{NUMBER})\s*(?P<units>{UNIT})?" + WINDOW,
        text,
        re.IGNORECASE,
    )
    span = re.fullmatch(
        MEASURE
        + rf"\s*(?:between\s+)?(?P<low>{NUMBER})\s*(?:%)?\s*(?:and|to|-)\s*(?P<high>{NUMBER})\s*(?P<units>{UNIT})"
        + WINDOW,
        text,
        re.IGNORECASE,
    )
    match = bound or span
    if not match:
        return None
    parsed = match.groupdict()
    name = parsed["measure"].lower()
    kind = (
        "bmi"
        if name in {"bmi", "body mass index"}
        else "hba1c"
        if "a1c" in name
        else "nonfasting"
        if name.startswith("non")
        else "fasting"
    )
    units = parsed.get("units")
    if kind != "bmi" and units is None:
        return None  # Never supply a missing unit/threshold from medical knowledge.
    parsed.update(kind=kind, units=canonical_unit(units or "kg/m2"))
    return parsed


def canonical_unit(unit: str) -> str:
    return unit.lower().replace(" ", "").replace("²", "2").replace("^2", "2")


def measurement_kind(fact: dict, kind: str) -> bool:
    code = fact.get("code") or {}
    names = " ".join(
        [code.get("text", ""), *[c.get("display", "") for c in code.get("coding", [])]]
    ).lower()
    codes = {c.get("code") for c in code.get("coding", []) if c.get("system") == "http://loinc.org"}
    if kind == "bmi":
        return "39156-5" in codes or bool(re.search(r"\bbmi\b|body mass index", names))
    if kind == "hba1c":
        return "4548-4" in codes or bool(re.search(r"hba1c|hemoglobin a1c", names))
    if not re.search(r"\b(glucose|glycemia)\b", names):
        return False
    nonfasting = bool(re.search(r"non[- ]?fasting", names))
    # Generic glucose is not assumed fasting or non-fasting.
    return (
        nonfasting
        if kind == "nonfasting"
        else bool(re.search(r"\bfasting\b", names)) and not nonfasting
    )


def evaluate_measurement(criterion: dict, patient: dict, spec: dict) -> CriterionAssessment:
    from .data import event_date

    anchor = parse_date(patient.get("reference_date"))
    count, unit = spec.get("count"), spec.get("unit")
    candidates = []
    for fact in patient.get("observations", []):
        if not measurement_kind(fact, spec["kind"]):
            continue
        value = fact.get("value") or {}
        raw = value.get("data")
        if value.get("type") != "Quantity" or not isinstance(raw, dict):
            continue
        number = raw.get("value")
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
            or not isinstance(raw.get("unit"), str)
            or canonical_unit(raw["unit"]) != spec["units"]
        ):
            continue
        if fact.get("raw_status") not in {None, "final", "amended", "corrected"}:
            continue
        when = parse_date(event_date(fact) or fact.get("event_date"))
        if when and (anchor is None or when > anchor):
            continue
        if count and (not anchor or not when or when < shift_back(anchor, int(count), unit)):
            continue
        candidates.append((when, float(number), fact))
    if not candidates:
        return unknown(
            criterion,
            f"No usable {spec['measure']} measurement with matching units"
            + (" and a dated value within the specified window." if count else "."),
        )
    dated = [row for row in candidates if row[0] is not None]
    latest = max((row[0] for row in dated), default=None)
    selected = [row for row in candidates if row[0] is None or row[0] == latest]
    if len({row[1] for row in selected}) != 1:
        return unknown(
            criterion, "Conflicting latest or undated measurements cannot be ordered reliably."
        )
    value = selected[0][1]
    low = float(spec["low"])
    if spec.get("high") is not None:
        passed = low <= value <= float(spec["high"])
    else:
        passed = {">=": value >= low, "<=": value <= low, ">": value > low, "<": value < low}[
            spec["op"]
        ]
    result = assessment(
        criterion,
        Decision.MET if passed else Decision.NOT_MET,
        f"Verified {spec['measure']} {value} {spec['units']} against the supplied threshold; "
        + (
            f"dated {latest}, relative to {anchor}."
            if all(row[0] is not None for row in selected)
            else "source is undated; no recency is asserted or required by this statement."
        ),
        [row[2]["fact_id"] for row in selected],
    )
    if any(row[0] is None for row in selected):
        result.validation_warnings.append("UNDATED_MEASUREMENT_NO_RECENCY_CLAIM")
    return result
