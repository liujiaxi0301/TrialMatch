"""Run the MS3 benchmark using question-only BM25 retrieval."""

import csv
import json
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.retrieve import Retriever

BASE = Path("evaluation/ms3/retrieval")
RESULTS = BASE / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# Load the fixed MS2 data and verify manifest checksums.
store = DataStore(Settings())
manifest = store.manifest()
retriever = Retriever(store, manifest, vector_index=None)

queries = [
    json.loads(line)
    for line in (BASE / "retrieval_queries.jsonl").read_text().splitlines()
    if line.strip()
]

assert len(queries) == 8, "Expected 8 benchmark queries"
assert len(manifest["trial_ids"]) == 50
assert len({q["query_id"] for q in queries}) == 8
assert all(q["patient_id"] in manifest["patient_ids"] for q in queries)

rankings = []
candidate_rows = []

for query in queries:
    query_id = query["query_id"]

    # Direct BM25: no patient-context expansion.
    hits = retriever.lexical.rank(query["question"])[:5]

    trial_ids = [trial_id for trial_id, score in hits]

    assert len(trial_ids) == len(set(trial_ids))
    assert all(t in manifest["trial_ids"] for t in trial_ids)

    rankings.append({
        "query_id": query_id,
        "method": "bm25_question_only_v1",
        "ranked_trial_ids": trial_ids,
    })

    print(f"\n=== {query_id}: Question-only BM25 Top 5 ===")

    for rank, (trial_id, score) in enumerate(hits, start=1):
        title = store.trials[trial_id].get("brief_title", "")

        candidate_rows.append({
            "query_id": query_id,
            "rank": rank,
            "trial_id": trial_id,
            "title": title,
            "bm25_score": round(score, 4),
        })

        print(f"{rank}. {trial_id} | {title}")

# Save rankings using the shared evaluation format.
ranking_path = RESULTS / "bm25_question_only_rankings.jsonl"

with ranking_path.open("w", encoding="utf-8") as f:
    for row in rankings:
        f.write(json.dumps(row) + "\n")

# Save human-readable candidate results.
candidate_path = RESULTS / "bm25_question_only_candidates.csv"

with candidate_path.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "query_id", "rank", "trial_id",
            "title", "bm25_score"
        ],
    )
    writer.writeheader()
    writer.writerows(candidate_rows)

print("\n=== COMPLETED ===")
print(f"Queries evaluated: {len(rankings)}")
print(f"Total returned results: {len(candidate_rows)}")
print(f"Rankings: {ranking_path}")
print(f"Review candidates: {candidate_path}")
