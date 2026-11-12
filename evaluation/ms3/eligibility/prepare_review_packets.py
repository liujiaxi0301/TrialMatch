"""Prepare prediction-blinded eligibility review materials."""

import json
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore, patient_facts
from services.rag_workflow.retrieve import ContextSelector

BASE = Path(__file__).resolve().parent


def write_frozen(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(
                f"Existing file differs; refusing overwrite: {path}"
            )
        return False

    with path.open("x", encoding="utf-8") as f:
        f.write(content)

    return True


def json_text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def main():
    store = DataStore(Settings())
    cases = [
        json.loads(line)
        for line in (BASE / "eligibility_cases.jsonl")
        .read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) == 8
    total_criteria = 0

    for case in cases:
        case_id = case["case_id"]
        patient = store.patient(case["patient_id"])
        trial = store.trials[case["trial_id"]]
        criteria = store.criteria[case["trial_id"]]

        assert len(criteria) == case["criterion_count"]
        total_criteria += len(criteria)

        # Complete patient evidence: not filtered or truncated.
        facts = patient_facts(patient)
        assert len({f["fact_id"] for f in facts}) == len(facts)

        facts_text = "".join(
            json.dumps(f, ensure_ascii=False) + "\n"
            for f in facts
        )

        trial_text = json_text({
            "trial": trial,
            "criteria": criteria,
        }) + "\n"

        # Source-only evidence previews, not model predictions.
        selector = ContextSelector(patient, limit=5)

        lines = [
            f"# Eligibility Review Packet — {case_id}",
            "",
            f"**Split:** {case['split']}",
            f"**Patient ID:** {case['patient_id']}",
            f"**Trial ID:** {case['trial_id']}",
            f"**Title:** {trial.get('brief_title')}",
            f"**Question:** {case['question']}",
            f"**Patient reference date:** {patient['reference_date']}",
            f"**Trial snapshot date:** {trial.get('snapshot_date')}",
            f"**Criteria:** {len(criteria)}",
            f"**Available patient facts:** {len(facts)}",
            "",
            "## Review instructions",
            "",
            "- Assess criterion satisfaction, NOT topical relevance.",
            "- MET: entire criterion is supported as true.",
            "- NOT_MET: entire criterion is supported as false.",
            "- UNKNOWN: insufficient or ambiguous evidence.",
            "- Inclusion and exclusion criteria use the same truth labels.",
            "- The evidence previews below are NOT exhaustive.",
            "- Check source_facts before finalizing a judgment.",
            "- Never infer absence from a missing record.",
            "- Do not use any model predictions when labeling.",
            "",
            "---",
            "",
        ]

        labels = []

        for index, criterion in enumerate(criteria, 1):
            cid = criterion["criterion_id"]

            lines.extend([
                f"## {index}. {cid}",
                "",
                f"**Type:** {criterion['criterion_type']}",
                "",
                "**Original criterion:**",
                "",
                criterion["criterion_text"],
                "",
                "**Potentially relevant patient facts (navigation preview only):**",
                "",
            ])

            previews = selector.select(criterion)

            if previews:
                for fact in previews:
                    lines.append(
                        "- `" + fact["fact_id"] + "`"
                    )
                    lines.append("")
                    lines.append(
                        "  " + json.dumps(
                            {
                                k: v
                                for k, v in fact.items()
                                if k != "fact_id"
                            },
                            ensure_ascii=False,
                        )
                    )
                    lines.append("")
            else:
                lines.append(
                    "No preview facts selected. Check the complete source."
                )
                lines.append("")

            lines.extend([
                "**Manual review:**",
                "",
                "- Gold decision (MET/NOT_MET/UNKNOWN):",
                "- Reason:",
                "- Supporting fact IDs:",
                "- Missing information:",
                "- Review notes:",
                "",
                "---",
                "",
            ])

            labels.append({
                "criterion_id": cid,
                "criterion_type": criterion["criterion_type"],
                "criterion_text": criterion["criterion_text"],
                "gold_decision": None,
                "reason": "",
                "supporting_fact_ids": [],
                "missing_information": [],
                "review_notes": "",
            })

        review_template = {
            "case_id": case_id,
            "patient_id": case["patient_id"],
            "trial_id": case["trial_id"],
            "split": case["split"],
            "review_status": "pending",
            "reviewer_qualification":
                "Non-clinician evidence-based reference assessment",
            "labels": labels,
        }

        outputs = [
            (
                BASE / "source_facts" / f"{case_id}.jsonl",
                facts_text,
            ),
            (
                BASE / "trial_sources" / f"{case_id}.json",
                trial_text,
            ),
            (
                BASE / "review_packets" / f"{case_id}.md",
                "\n".join(lines) + "\n",
            ),
            (
                BASE / "reviewed_labels" / f"{case_id}.json",
                json_text(review_template) + "\n",
            ),
        ]

        # Check every output before writing this case.
        for path, content in outputs:
            if path.exists():
                if path.read_text(encoding="utf-8") != content:
                    raise RuntimeError(
                        f"Existing file differs: {path}"
                    )

        for path, content in outputs:
            write_frozen(path, content)

        print(
            f"{case_id}: {len(criteria)} criteria, "
            f"{len(facts)} patient facts"
        )

    assert total_criteria == 115

    print("\nReview preparation complete.")
    print("Cases: 8")
    print("Criteria: 115")
    print("Model predictions used: 0")
    print(f"Files saved under: {BASE}")


if __name__ == "__main__":
    main()
