"""Run the fixed MS3 queries through the existing BM25 retriever."""

import csv
import json
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.retrieve import Retriever

BASE = Path("evaluation/ms3/retrieval")
RESULTS = BASE / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# Load the existing MS2 data and verify its manifest checksums.
store = DataStore(Settings())
manifest = store.manifest()

# No vector index: this uses BM25 only, without Gemini.
retriever = Retriever(store, manifest, vector_index=None)

queries = [
    json.loads(line)
    for line in (BASE / "retrieval_queries.jsonl").read_text().splitlines()
    if line.strip()
]

assert len(queries) == 8, "Expected 8 benchmark queries"
assert len(manifest["trial_ids"]) == 50
assert len({q["query_id"] for q in queries}) == 8

rankings = []
candidate_rows = []

for query in queries:
    query_id = query["query_id"]
    patient = store.patient(query["patient_id"])

    hits = retriever.retrieve(
        patient=patient,
        question=query["question"],
        top_k=5,
    )

    trial_ids = [hit["trial_id"] for hit in hits]

    assert len(trial_ids) == len(set(trial_ids))
    assert all(t in manifest["trial_ids"] for t in trial_ids)

    rankings.append({
        "query_id": query_id,
        "method": "bm25_v1",
        "ranked_trial_ids": trial_ids,
    })

    print(f"\n=== {query_id}: BM25 Top 5 ===")

    for rank, hit in enumerate(hits, start=1):
        trial_id = hit["trial_id"]
        title = store.trials[trial_id].get("brief_title", "")

        candidate_rows.append({
            "query_id": query_id,
            "rank": rank,
            "trial_id": trial_id,
            "title": title,
            "bm25_score": hit["bm25_score"],
        })

        print(f"{rank}. {trial_id} | {title}")

# Save rankings in the shared evaluation format.
ranking_path = RESULTS / "bm25_rankings.jsonl"
with ranking_path.open("w", encoding="utf-8") as f:
    for row in rankings:
        f.write(json.dumps(row) + "\n")

# Save human-readable candidates for subsequent manual review.
candidate_path = RESULTS / "bm25_candidates.csv"
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
