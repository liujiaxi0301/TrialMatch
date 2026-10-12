import json
import re
from pathlib import Path


PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
TRIALS_PATH = PROCESSED_DIR / "trials.jsonl"
CRITERIA_PATH = PROCESSED_DIR / "criteria.jsonl"


# ---------------------------------------------------------------------
# Section parsing
# ---------------------------------------------------------------------

INCLUSION_PATTERN = re.compile(
    r"(?im)^\s*(?:Main\s+)?Inclusion Criteria\s*:?\s*$"
)

EXCLUSION_PATTERN = re.compile(
    r"(?im)^\s*(?:Main\s+)?(?:"
    r"Exclusion Criteria|"
    r"No Inclusion Criteria|"
    r"Non[- ]Inclusion Criteria"
    r")\s*:?\s*$"
)


def split_sections(eligibility_text: str):
    """
    Identify inclusion and/or exclusion sections.

    Returns:
        {
            "inclusion": str | None,
            "exclusion": str | None,
        }

    Returns None when section structure cannot be interpreted safely.
    """

    inclusion_match = INCLUSION_PATTERN.search(eligibility_text)
    exclusion_match = EXCLUSION_PATTERN.search(eligibility_text)

    # Neither section header can be identified.
    if not inclusion_match and not exclusion_match:
        return None

    # Both sections are present.
    if inclusion_match and exclusion_match:
        # Unexpected ordering is treated as ambiguous.
        if inclusion_match.start() > exclusion_match.start():
            return None

        inclusion_text = eligibility_text[
            inclusion_match.end():exclusion_match.start()
        ].strip()

        exclusion_text = eligibility_text[
            exclusion_match.end():
        ].strip()

        return {
            "inclusion": inclusion_text,
            "exclusion": exclusion_text,
        }

    # Inclusion section only.
    if inclusion_match:
        inclusion_text = eligibility_text[
            inclusion_match.end():
        ].strip()

        return {
            "inclusion": inclusion_text,
            "exclusion": None,
        }

    # Exclusion section only.
    exclusion_text = eligibility_text[
        exclusion_match.end():
    ].strip()

    return {
        "inclusion": None,
        "exclusion": exclusion_text,
    }


# ---------------------------------------------------------------------
# Criterion parsing
# ---------------------------------------------------------------------

def is_empty_placeholder(text: str):
    """
    ClinicalTrials.gov sometimes uses '-' or '\\-' to indicate
    that a section contains no criteria.
    """

    if text is None:
        return True

    return text.strip() in {
        "",
        "-",
        "\\-",
    }


def looks_like_single_criterion(text: str):
    """
    Conservative heuristic for a section containing one criterion
    without a bullet or number marker.

    Short, simple single-line statements such as:
        "Type 2 diabetes"
        "patients with T2D and obesity"

    can be safely treated as one criterion.

    Longer prose containing multiple sentences remains ambiguous.
    """

    text = text.strip()

    if not text:
        return False

    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    if len(lines) != 1:
        return False

    sentence_boundaries = re.findall(
        r"[.!?](?:\s|$)",
        text,
    )

    if len(sentence_boundaries) > 1:
        return False

    return True


def split_criteria(section_text: str):
    """
    Split a known inclusion or exclusion section into individual
    criteria when explicit structure is available.

    Returns:
        list[str] when parsing is reliable
        None when criterion boundaries remain ambiguous
    """

    if is_empty_placeholder(section_text):
        return []

    section_text = section_text.strip()

    # -------------------------------------------------------------
    # Fix rare inline numbered formatting:
    #
    # "... signing. 3. Body weight ..."
    #
    # becomes:
    #
    # "... signing.
    # 3. Body weight ..."
    # -------------------------------------------------------------

    section_text = re.sub(
        r"(?<=\.)[ \t]+(?=\d+\\?\.\s+[A-Z])",
        "\n",
        section_text,
    )

    # -------------------------------------------------------------
    # Numbered lists:
    #
    # 1. criterion
    # 2. criterion
    #
    # or escaped:
    #
    # 1\. criterion
    # -------------------------------------------------------------

    numbered_pattern = re.compile(
        r"(?m)^\s*(?:\*\s*)?\d+\\?\.\s+"
    )

    numbered_matches = list(
        numbered_pattern.finditer(section_text)
    )

    if numbered_matches:
        criteria = []

        for i, match in enumerate(numbered_matches):
            start = match.end()

            if i + 1 < len(numbered_matches):
                end = numbered_matches[i + 1].start()
            else:
                end = len(section_text)

            criterion = section_text[start:end].strip()

            if criterion:
                criteria.append(criterion)

        if criteria:
            return criteria

    # -------------------------------------------------------------
    # Bullet lists:
    #
    # * criterion
    # - criterion
    # \- criterion
    # -------------------------------------------------------------

    bullet_pattern = re.compile(
        r"^\s*(?:\*|\\?-)\s+(.+?)\s*$"
    )

    bullet_criteria = []

    for line in section_text.splitlines():
        match = bullet_pattern.match(line)

        if match:
            criterion = match.group(1).strip()

            if criterion:
                bullet_criteria.append(criterion)

    if bullet_criteria:
        return bullet_criteria

    # -------------------------------------------------------------
    # One clearly identifiable criterion without list formatting.
    # -------------------------------------------------------------

    if looks_like_single_criterion(section_text):
        return [section_text]

    # Anything more complicated is intentionally left ambiguous.
    return None


# ---------------------------------------------------------------------
# Output record construction
# ---------------------------------------------------------------------

def build_parsed_records(
    trial_id: str,
    criterion_type: str,
    criteria: list,
):
    if criterion_type == "inclusion":
        prefix = "inc"
    else:
        prefix = "exc"

    records = []

    for i, criterion in enumerate(criteria, start=1):
        records.append({
            "trial_id": trial_id,
            "criterion_id": f"{trial_id}_{prefix}_{i:03d}",
            "criterion_type": criterion_type,
            "criterion_text": criterion,
            "parse_status": "parsed",
            "parse_method": "deterministic",
        })

    return records


def build_ambiguous_record(
    trial_id: str,
    criterion_text: str,
    criterion_type: str = "unknown",
):
    if criterion_type == "inclusion":
        prefix = "inc"
    elif criterion_type == "exclusion":
        prefix = "exc"
    else:
        prefix = "unk"

    return {
        "trial_id": trial_id,
        "criterion_id": f"{trial_id}_{prefix}_001",
        "criterion_type": criterion_type,
        "criterion_text": criterion_text.strip(),
        "parse_status": "ambiguous",
        "parse_method": "deterministic",
    }


# ---------------------------------------------------------------------
# Trial-level parsing
# ---------------------------------------------------------------------

def parse_known_section(
    trial_id: str,
    criterion_type: str,
    section_text: str | None,
):
    """
    Parse one section when its type is already known.
    """

    if section_text is None:
        return []

    if is_empty_placeholder(section_text):
        return []

    criteria = split_criteria(section_text)

    if criteria is None:
        return [
            build_ambiguous_record(
                trial_id=trial_id,
                criterion_text=section_text,
                criterion_type=criterion_type,
            )
        ]

    return build_parsed_records(
        trial_id=trial_id,
        criterion_type=criterion_type,
        criteria=criteria,
    )


def parse_trial_criteria(trial: dict):
    trial_id = trial["trial_id"]
    eligibility_text = trial.get("eligibility_text")

    # Trial remains in trials.jsonl but produces no criteria.
    if not eligibility_text:
        return []

    sections = split_sections(eligibility_text)

    # Cannot confidently identify inclusion/exclusion structure.
    if sections is None:
        return [
            build_ambiguous_record(
                trial_id=trial_id,
                criterion_text=eligibility_text,
                criterion_type="unknown",
            )
        ]

    records = []

    records.extend(
        parse_known_section(
            trial_id=trial_id,
            criterion_type="inclusion",
            section_text=sections["inclusion"],
        )
    )

    records.extend(
        parse_known_section(
            trial_id=trial_id,
            criterion_type="exclusion",
            section_text=sections["exclusion"],
        )
    )

    return records


# ---------------------------------------------------------------------
# Save output
# ---------------------------------------------------------------------

def save_criteria(records: list):
    PROCESSED_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(CRITERIA_PATH, "w") as f:
        for record in records:
            f.write(
                json.dumps(record)
                + "\n"
            )

    parsed_count = sum(
        record["parse_status"] == "parsed"
        for record in records
    )

    ambiguous_count = sum(
        record["parse_status"] == "ambiguous"
        for record in records
    )

    print(
        f"Saved {len(records)} criteria "
        f"to {CRITERIA_PATH}"
    )

    print(
        f"Parsed: {parsed_count}"
    )

    print(
        f"Ambiguous: {ambiguous_count}"
    )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

if __name__ == "__main__":
    all_records = []

    with open(TRIALS_PATH, "r") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            trial = json.loads(line)

            records = parse_trial_criteria(
                trial
            )

            all_records.extend(
                records
            )

    save_criteria(all_records)