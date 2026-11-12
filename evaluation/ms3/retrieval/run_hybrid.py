"""Run the existing MS2 BM25 + Gemini/Chroma hybrid retrieval baseline."""

import argparse
import csv
import json
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from evaluation.ms3.gemini_developer_provider import GeminiDeveloperProvider
from services.rag_workflow.retrieve import Retriever


BASE = Path("evaluation/ms3/retrieval")
METHOD = "bm25_gemini_chroma_hybrid"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--query-id",
        help="Run a single query for a smoke test, e.g. Q01. Omit to run all 8.",
    )
    args = parser.parse_args()

    queries = [
        json.loads(line)
        for line in (BASE / "retrieval_queries.jsonl").read_text().splitlines()
        if line.strip()
    ]

    if args.query_id:
        queries = [q for q in queries if q["query_id"] == args.query_id]
        if not queries:
            parser.error(f"Unknown query ID: {args.query_id}")

    settings = Settings()
    store = DataStore(settings)
    manifest = store.manifest()

    provider = GeminiDeveloperProvider(settings)

    rankings = []
    csv_rows = []

    try:
        index = VectorIndex(settings, store, manifest, provider)
        status = index.status()

        print(
            f"Chroma verified: {status['vector_count']} vectors, "
            f"{len(manifest['trial_ids'])} trials"
        )

        retriever = Retriever(store, manifest, vector_index=index)

        for query in queries:
            hits = retriever.retrieve(
                patient=store.patient(query["patient_id"]),
                question=query["question"],
                top_k=5,
            )

            if not hits or any(h["method"] != "hybrid_rrf" for h in hits):
                raise RuntimeError("Hybrid retrieval did not return valid results")

            if any(h["trial_id"] not in manifest["trial_ids"] for h in hits):
                raise RuntimeError("Retrieved trial outside fixed corpus")

            ids = [h["trial_id"] for h in hits]
            if len(ids) != len(set(ids)):
                raise RuntimeError("Duplicate trial IDs in results")

            rankings.append({
                "query_id": query["query_id"],
                "patient_id": query["patient_id"],
                "method": METHOD,
                "ranked_trial_ids": ids,
                "index_version": status["index_version"],
            })

            for rank, hit in enumerate(hits, 1):
                semantic = hit.get("semantic_hit") or {}

                csv_rows.append({
                    "query_id": query["query_id"],
                    "method": METHOD,
                    "rank": rank,
                    "trial_id": hit["trial_id"],
                    "rank_score": hit["rank_score"],
                    "bm25_score": hit["bm25_score"],
                    "semantic_criterion_id": semantic.get("criterion_id", ""),
                    "semantic_cosine_distance": semantic.get(
                        "cosine_distance", ""
                    ),
                })

            print(f"{query['query_id']}: {', '.join(ids)}")

        if args.query_id:
            print("Smoke test completed; no benchmark files overwritten.")
        else:
            output = BASE / "results"
            output.mkdir(parents=True, exist_ok=True)

            with (output / "hybrid_rankings.jsonl").open("w") as f:
                for row in rankings:
                    f.write(json.dumps(row) + "\n")

            with (output / "hybrid_candidates.csv").open(
                "w", newline=""
            ) as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "query_id", "method", "rank", "trial_id",
                    "rank_score", "bm25_score",
                    "semantic_criterion_id",
                    "semantic_cosine_distance",
                ])
                writer.writeheader()
                writer.writerows(csv_rows)

            print("Saved hybrid_rankings.jsonl and hybrid_candidates.csv")

        print("Gemini usage:", json.dumps(provider.metrics))

    finally:
        provider.close()


if __name__ == "__main__":
    main()
