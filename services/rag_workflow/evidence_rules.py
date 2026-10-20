"""Bounded source-evidence checks, without external ranges or medical-class lookups.

Supported assertions are parsed completely. Negative statements must cover all
alternatives, qualifiers and the requested time window. Unknown scopes stay unknown.
"""

import math
import re

from .data import event_date, label, parse_date, patient_facts
from .rules import assessment, numeric_rule, shift_back, unknown
from .schemas import Decision


def clean(text):
    text = (
        text.lower().replace("gastro-intestinal", "gastrointestinal").replace("alcool", "alcohol")
    )
    text = re.sub(r"\b(ulcers|diseases)\b", lambda m: m[0][:-1], text)
    return re.sub(r"\s+", " ", text).strip(" .;")


def source_statement(fact):
    value = fact.get("value") or {}
    data = value.get("data")
    return (
        clean(data) if value.get("type", "").lower() == "string" and isinstance(data, str) else ""
    )


def unresolved(criterion, reason, issue, refs=()):
    result = unknown(criterion, reason)
    result.evidence_fact_ids = list(refs)
    result.validation_warnings.append(issue)
    return result


def remove_window(text):
    match = re.search(
        r"(?:\s+(?:within |in )?(?:the )?(?:last|past) (\d+|one|a|an) (days?|weeks?|months?|years?))$",
        text,
    )
    if not match:
        return text, None
    count = 1 if match[1] in {"one", "a", "an"} else int(match[1])
    return text[: match.start()].strip(), (count, match[2])


def history_terms(text):
    """Expand shared suffixes, not disease ontologies: gastric or duodenal ulcer."""
    pieces = [p.strip() for p in re.split(r",?\s+(?:or|and)\s+|,\s*", text) if p.strip()]
    if not pieces:
        return set()
    suffix = next(
        (suffix for suffix in ("surgery", "ulcer", "disease") if pieces[-1].endswith(" " + suffix)),
        None,
    )
    if suffix:
        pieces = [p if p.endswith(" " + suffix) else p + " " + suffix for p in pieces]
    return set(pieces)


def negative_history_rule(criterion, facts, reference_date):
    text, target_window = remove_window(clean(criterion["criterion_text"]))
    match = re.fullmatch(r"(?:history of|past) (.+)", text)
    if not match or re.search(r"\b(if|unless|including|severe)\b", match[1]):
        return None
    required = history_terms(match[1])
    covered, refs, qualified = set(), [], False
    positive, conflicting_positive = set(), []
    anchor = parse_date(reference_date)
    for fact in facts:
        source = source_statement(fact)
        source, window = remove_window(source)
        negative = re.fullmatch(
            r"(?:(?:the )?patient (?:has|reports) )?no (?P<known>known )?history of (?P<terms>.+)",
            source,
        )
        # A Boolean false only supports the predicate named by THIS fact.
        value = fact.get("value") or {}
        if value.get("type", "").lower() == "boolean" and value.get("data") is True:
            descriptor, positive_window = remove_window(clean(label(fact)))
            named = re.fullmatch(r"(?:known )?history of (.+)", descriptor)
            candidate = history_terms(named[1]) & required if named else set()
            if target_window and (
                anchor is None
                or positive_window is None
                or shift_back(anchor, *positive_window) < shift_back(anchor, *target_window)
            ):
                candidate = set()
            positive |= candidate
            if candidate:
                conflicting_positive.append(fact["fact_id"])
            continue
        boolean_negative = value.get("type", "").lower() == "boolean" and value.get("data") is False
        if boolean_negative:
            descriptor, window = remove_window(clean(label(fact)))
            descriptor = re.sub(r"^(?:known )?history of ", "", descriptor)
            terms = history_terms(descriptor)
        elif negative:
            terms = history_terms(negative["terms"])
        else:
            # Detect explicit positive history that contradicts a negative statement.
            stated_positive = re.fullmatch(
                r"(?:(?:the )?patient (?:has|reports) (?:a )?)?(?:history of|past) (.+)", source
            )
            if stated_positive:
                candidate = history_terms(stated_positive[1]) & required
                # Existence somewhere in a larger interval does not prove recent use.
                if target_window and (
                    anchor is None
                    or window is None
                    or shift_back(anchor, *window) < shift_back(anchor, *target_window)
                ):
                    candidate = set()
                positive |= candidate
                if candidate:
                    conflicting_positive.append(fact["fact_id"])
            continue
        if not (terms & required):
            continue
        recorded = parse_date(event_date(fact) or fact.get("event_date"))
        if recorded and anchor and recorded != anchor:
            continue  # Do not move an old negative assertion forward to the patient snapshot.
        if window:
            if not target_window or anchor is None:
                continue  # A bounded absence cannot establish a lifetime absence.
            # Use an explicit statement date when available, rather than moving history forward.
            source_anchor = parse_date(event_date(fact) or fact.get("event_date")) or anchor
            if source_anchor < anchor or shift_back(source_anchor, *window) > shift_back(
                anchor, *target_window
            ):
                continue
        covered |= terms & required
        refs.append(fact["fact_id"])
        qualified |= bool(negative and negative["known"])
    if positive & covered:
        return unresolved(
            criterion,
            "A positive history conflicts with or requires review alongside negative history.",
            "CONFLICTING_HISTORY_REQUIRES_REVIEW",
            [*refs, *conflicting_positive],
        )
    if positive:
        return assessment(
            criterion,
            Decision.MET,
            "An explicit positive history supports at least one alternative within the required scope/window.",
            conflicting_positive,
        )
    if covered != required:
        return unresolved(
            criterion,
            "Explicit negative history does not cover every required condition and time window; missing: "
            + ", ".join(sorted(required - covered)),
            "NEGATIVE_SCOPE_OR_WINDOW_INCOMPLETE",
            refs,
        )
    result = assessment(
        criterion,
        Decision.NOT_MET,
        "Source explicitly denies all required histories"
        + (" within the requested window." if target_window else ".")
        + (" The source says 'no known history'; that qualifier is retained." if qualified else ""),
        refs,
    )
    if qualified:
        result.validation_warnings.append("SOURCE_SAYS_NO_KNOWN_HISTORY")
    return result


def consent_rule(criterion, facts):
    text = clean(criterion["criterion_text"])
    if not re.fullmatch(
        r"(?:able|ability|capacity) to (?:provide |give )?(?:informed )?consent", text
    ):
        return None
    positive, negative = [], []
    for fact in facts:
        source = source_statement(fact)
        if re.search(r"\b(if|unless|possibly|may be)\b", source):
            continue
        if re.search(
            r"\b(?:unable|not able|lacks capacity) to (?:provide |give )?(?:informed )?consent\b",
            source,
        ):
            negative.append(fact["fact_id"])
        elif re.search(
            r"\b(?:able|has capacity) to (?:provide |give )?(?:informed )?consent\b", source
        ):
            positive.append(fact["fact_id"])
    if positive and negative:
        return unresolved(
            criterion,
            "Conflicting consent-capacity statements require review.",
            "CONFLICTING_CONSENT_EVIDENCE",
            [*positive, *negative],
        )
    if positive or negative:
        return assessment(
            criterion,
            Decision.MET if positive else Decision.NOT_MET,
            "An explicit source statement documents consent capacity; alertness alone was not used.",
            positive or negative,
        )
    return unresolved(
        criterion,
        "No explicit statement establishes ability or inability to consent; alertness alone is insufficient.",
        "CONSENT_CAPACITY_NOT_EXPLICIT",
    )


def pregnancy_rule(criterion, facts, reference_date=None):
    if clean(criterion["criterion_text"]) != "pregnancy":
        return None
    positives, negatives = [], []
    anchor = parse_date(reference_date)
    for fact in facts:
        when = parse_date(event_date(fact) or fact.get("event_date"))
        if when and anchor and when != anchor:
            continue  # A known old result does not establish status at the snapshot.
        source, descriptor = source_statement(fact), clean(label(fact))
        if re.fullmatch(
            r"(?:the )?(?:patient(?:'s)? )?pregnancy test (?:is |was )?(negative|positive)", source
        ):
            (negatives if source.endswith("negative") else positives).append(fact["fact_id"])
        value = fact.get("value") or {}
        if (
            descriptor in {"pregnancy", "pregnancy test"}
            and value.get("type", "").lower() == "boolean"
        ):
            if value.get("data") is False:
                negatives.append(fact["fact_id"])
            elif value.get("data") is True:
                positives.append(fact["fact_id"])
    if positives and negatives:
        return unresolved(
            criterion,
            "Conflicting pregnancy-test results require timing and review.",
            "CONFLICTING_PREGNANCY_EVIDENCE",
            [*positives, *negatives],
        )
    if positives or negatives:
        result = assessment(
            criterion,
            Decision.MET if positives else Decision.NOT_MET,
            "The source explicitly reports a "
            + ("positive" if positives else "negative")
            + " pregnancy test; this describes the supplied record, not a new/current clinical test.",
            list(dict.fromkeys(positives or negatives)),
        )
        result.validation_warnings.append("PREGNANCY_TEST_TIMING_REQUIRES_CLINICAL_REVIEW")
        return result
    return unresolved(
        criterion,
        "A pregnancy-specific test/result is not supplied; an unrelated Boolean false or missing record is insufficient.",
        "EXPLICIT_NEGATIVE_EVIDENCE_REQUIRED",
    )


def albumin_rule(criterion, facts):
    if clean(criterion["criterion_text"]) not in {
        "pre-operatory hypoalbuminemy",
        "pre-operative hypoalbuminemia",
        "preoperative hypoalbuminemia",
    }:
        return None
    decisions = []
    for fact in facts:
        if "albumin" not in clean(label(fact)):
            continue
        preoperative = fact.get("timing") in ("pre-operative", "preoperative") or bool(
            re.search(r"pre[- ]?operat", clean(label(fact)))
        )
        if not preoperative:
            continue
        value = fact.get("value") or {}
        raw = value.get("data") or {}
        interval = fact.get("reference_range") or {}
        if value.get("type") == "Quantity" and isinstance(raw, dict) and isinstance(interval, dict):
            number, low = raw.get("value"), interval.get("low")
            if (
                type(number) in {int, float}
                and type(low) in {int, float}
                and math.isfinite(number)
                and math.isfinite(low)
                and isinstance(raw.get("unit"), str)
                and bool(raw["unit"])
                and (
                    interval.get("high") is None
                    or (
                        type(interval["high"]) in {int, float}
                        and math.isfinite(interval["high"])
                        and low <= interval["high"]
                    )
                )
                and interval.get("unit") == raw.get("unit")
            ):
                decisions.append((number < low, fact["fact_id"]))
    if decisions and len({decision for decision, _ in decisions}) == 1:
        return assessment(
            criterion,
            Decision.MET if decisions[0][0] else Decision.NOT_MET,
            "Compared documented pre-operative albumin with source-provided lower bounds; no external range used.",
            [key for _, key in decisions],
        )
    return unresolved(
        criterion,
        "Pre-operative albumin interpretation/timing and a source-provided reference range or explicit diagnosis are insufficient. No normal range is invented.",
        "ALBUMIN_RANGE_OR_PREOPERATIVE_TIMING_MISSING",
        [f["fact_id"] for f in facts if "albumin" in clean(label(f))],
    )


def dose_time(fact, anchor):
    """A documented dose within a window can prove use; an old dose cannot prove non-use."""
    when = parse_date(event_date(fact) or fact.get("event_date"))
    source = source_statement(fact)
    match = re.search(r"\b(\d+|one|two|three|four) (days?|weeks?|months?|years?) ago\b", source)
    if match and not re.search(r"more than|at least|about|approximately|not|never", source):
        count = {"one": 1, "two": 2, "three": 3, "four": 4}.get(match[1])
        relative = shift_back(anchor, count if count is not None else int(match[1]), match[2])
        if when and when != relative:
            return None
        return relative
    return when


def medication_window_rule(criterion, facts, reference_date):
    match = re.fullmatch(
        r"(?:taken of|taken|use of|used) (corticosteroids?) in (?:the )?(?:last|past) (?:one |a |1 )?month",
        clean(criterion["criterion_text"]),
    )
    if not match:
        return None
    anchor = parse_date(reference_date)
    if anchor is None:
        return unresolved(
            criterion,
            "A reference date is needed to evaluate the relative medication window.",
            "MEDICATION_REFERENCE_DATE_MISSING",
        )
    start = shift_back(anchor, 1, "month")
    timed, classified, refs = [], [], []
    for fact in facts:
        if fact.get("resource_type") not in {"MedicationStatement", "MedicationAdministration"}:
            continue  # An order/definition/dispense alone is not proof of consumption.
        if fact.get("raw_status") in {"entered-in-error", "not-done", "intended"}:
            continue
        source = source_statement(fact)
        if re.search(r"\b(not|never|denies)\b|no use", source):
            continue
        if (
            not re.search(r"\b(took|taken|used|received|administered)\b", source)
            and fact.get("resource_type") != "MedicationAdministration"
        ):
            continue
        when = dose_time(fact, anchor)
        if when and start <= when <= anchor:
            timed.append(
                f"Use date derived/recorded as {when}, relative to the supplied reference {anchor}, is inside [{start}, {anchor}]."
            )
            refs.append(fact["fact_id"])
            supplied_class = clean(str(fact.get("medication_class") or ""))
            if supplied_class in {"corticosteroid", "corticosteroids"}:
                classified.append(fact["fact_id"])
    if classified:
        return assessment(
            criterion,
            Decision.MET,
            " ".join(timed)
            + " The supplied medication-class field identifies corticosteroid use; no drug-class inference was added.",
            classified,
        )
    if timed:
        return unresolved(
            criterion,
            " ".join(timed)
            + " Time-window check passed, but a source-provided corticosteroid classification is missing.",
            "MEDICATION_CLASS_NOT_SUPPLIED",
            refs,
        )
    return unresolved(
        criterion,
        "No documented, class-verified dose within the requested window. An older dose or an absent record does not prove non-use.",
        "MEDICATION_CLASS_OR_TIME_NOT_ESTABLISHED",
    )


def evidence_rule(criterion, patient):
    result = numeric_rule(criterion, patient)
    if result is not None:
        return result
    facts = patient_facts(patient)
    for checker in (consent_rule, albumin_rule):
        result = checker(criterion, facts)
        if result is not None:
            return result
    result = pregnancy_rule(criterion, facts, patient.get("reference_date"))
    if result is not None:
        return result
    for checker in (medication_window_rule, negative_history_rule):
        result = checker(criterion, facts, patient.get("reference_date"))
        if result is not None:
            return result
    return None


def context_patient(facts, reference_date):
    """Re-run validators on cited facts only, without reaching outside offered context."""
    demo = next((fact for fact in facts if fact.get("resource_type") == "Patient"), {})
    return {
        "reference_date": reference_date,
        "demographics": demo,
        "observations": [fact for fact in facts if fact.get("resource_type") == "Observation"],
        "conditions": [fact for fact in facts if fact.get("resource_type") == "Condition"],
        "procedures": [fact for fact in facts if fact.get("resource_type") == "Procedure"],
        "medications": {
            "requests": [
                fact for fact in facts if fact.get("resource_type") == "MedicationRequest"
            ],
            "definitions": [fact for fact in facts if fact.get("resource_type") == "Medication"],
            "statements": [
                fact for fact in facts if fact.get("resource_type") == "MedicationStatement"
            ],
            "administrations": [
                fact for fact in facts if fact.get("resource_type") == "MedicationAdministration"
            ],
        },
    }
