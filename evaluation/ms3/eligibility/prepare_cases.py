"""Prepare and freeze the MS3 eligibility evaluation cohort.

Selection is based on previously reviewed topical relevance labels.
No eligibility predictions are used.
"""

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore

BASE = Path(__file__).resolve().parent
MS3 = BASE.parent

QUERIES = MS3 / "retrieval_queries.jsonl"
LABELS = MS3 / "retrieval_labels.csv"

# Fixed, purposively selected patient-trial cases.
TRIAL_SELECTION = {
    "Q01": "NCT03264352",
    "Q02": "NCT05028140",
    "Q03": "NCT01945840",
    "Q04": "NCT04802395",
    "Q05": "NCT03827382",
    "Q06": "NCT03883412",
    "Q07": "NCT04687215",
    "Q08": "NCT04783441",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_frozen(path, content):
    """Create once; refuse to silently change an existing cohort."""
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise RuntimeError(
                f"Frozen file differs from regenerated content: {path}"
            )
        print(f"Already frozen and verified: {path.name}")
        return

    with path.open("x", encoding="utf-8") as f:
        f.write(content)
    print(f"Created: {path.name}")


def main():
    store = DataStore(Settings())
    manifest = store.manifest()

    queries = [
        json.loads(line)
        for line in QUERIES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    with LABELS.open(newline="", encoding="utf-8") as f:
        labels = {
            (row["query_id"], row["trial_id"]): int(row["relevance"])
            for row in csv.DictReader(f)
        }

    expected_qids = [f"Q{i:02d}" for i in range(1, 9)]
    assert [q["query_id"] for q in queries] == expected_qids

    cases = []
    total_counts = Counter()

    for query in queries:
        qid = query["query_id"]
        patient_id = query["patient_id"]
        trial_id = TRIAL_SELECTION[qid]

        assert patient_id in manifest["patient_ids"]
        assert trial_id in manifest["trial_ids"]
        assert labels[(qid, trial_id)] == 2, (
            f"{qid}/{trial_id} is not labeled highly relevant"
        )

        patient = store.patient(patient_id)
        trial = store.trials[trial_id]
        criteria = store.criteria[trial_id]

        assert patient["reference_date"] == "2021-11-30"
        assert trial["snapshot_date"] == "2026-10-11"
        assert criteria

        counts = Counter(c["criterion_type"] for c in criteria)
        assert set(counts) <= {"inclusion", "exclusion"}

        total_counts.update(counts)

        cases.append({
            "case_id": f"E{qid[1:]}",
            "source_query_id": qid,
            "split": "all",
            "patient_id": patient_id,
            "trial_id": trial_id,
            "question": query["question"],
            "patient_reference_date": patient["reference_date"],
            "trial_snapshot_date": trial["snapshot_date"],
            "selection_basis": "manual_topical_relevance_2",
            "inclusion_count": counts["inclusion"],
            "exclusion_count": counts["exclusion"],
            "criterion_count": len(criteria),
        })

    assert len(cases) == 8
    assert total_counts["inclusion"] == 32
    assert total_counts["exclusion"] == 83
    assert sum(c["criterion_count"] for c in cases) == 115

    provenance = {
        "benchmark": "TrialMatch MS3 Eligibility Evaluation",
        "selection_type": "purposive_exploratory",
        "selection_basis": "previously reviewed topical relevance grade 2",
        "patient_trial_pairs": len(cases),
        "evaluation_cases": 8,
        "criterion_count": 115,
        "inclusion_count": 32,
        "exclusion_count": 83,
        "source_sha256": store.hashes,
        "retrieval_queries_sha256": sha256(QUERIES),
        "retrieval_labels_sha256": sha256(LABELS),
        "eligibility_predictions_used_for_selection": False,
    }

    cases_text = "".join(
        json.dumps(c, ensure_ascii=False) + "\n"
        for c in cases
    )

    manifest_text = (
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n"
    )

    # Validate both existing outputs before creating either.
    outputs = [
        (BASE / "eligibility_cases.jsonl", cases_text),
        (BASE / "cohort_manifest.json", manifest_text),
    ]

    for path, content in outputs:
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise RuntimeError(f"Frozen output mismatch: {path}")

    for path, content in outputs:
        write_frozen(path, content)

    print("\n=== Eligibility Cohort ===")
    print("Patient-trial pairs: 8")
    print("Dev: 2 | Reporting: 6")
    print("Inclusion criteria: 32")
    print("Exclusion criteria: 83")
    print("Total criteria: 115")
    print("No model predictions used.")


if __name__ == "__main__":
    main()
