"""Question-only Gemini/Chroma hybrid retrieval ablation."""

import argparse
import json
from collections import Counter
from pathlib import Path

from evaluation.ms3.gemini_developer_provider import GeminiDeveloperProvider
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.retrieve import Retriever

BASE = Path("evaluation/ms3/retrieval")
METHOD = "hybrid_question_only_v1"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-id")
    args = parser.parse_args()

    queries = [
        json.loads(line)
        for line in (BASE / "retrieval_queries.jsonl").read_text().splitlines()
        if line.strip()
    ]

    if args.query_id:
        queries = [q for q in queries if q["query_id"] == args.query_id]
        if not queries:
            parser.error("Unknown query ID")

    settings = Settings()
    store = DataStore(settings)
    manifest = store.manifest()
    provider = GeminiDeveloperProvider(settings)

    try:
        index = VectorIndex(settings, store, manifest, provider)
        status = index.status()

        retriever = Retriever(store, manifest, vector_index=index)
        rankings = []

        print(f"Chroma verified: {status['vector_count']} vectors")

        for q in queries:
            question = q["question"]

            # Same lexical index as existing baselines.
            lexical = retriever.lexical.rank(question)

            # Same semantic index; question only.
            vector_hits = index.query(question)

            # Same reciprocal rank fusion as MS2 Retriever.
            scores = Counter()

            for rank, (trial_id, _) in enumerate(lexical, 1):
                scores[trial_id] += 1 / (60 + rank)

            for rank, hit in enumerate(vector_hits, 1):
                scores[hit["trial_id"]] += 1 / (60 + rank)

            ranked_ids = [
                tid
                for tid, _ in sorted(
                    scores.items(),
                    key=lambda item: (-item[1], item[0]),
                )[:5]
            ]

            assert len(ranked_ids) == 5
            assert len(set(ranked_ids)) == 5
            assert set(ranked_ids) <= set(manifest["trial_ids"])

            rankings.append({
                "query_id": q["query_id"],
                "method": METHOD,
                "ranked_trial_ids": ranked_ids,
                "index_version": status["index_version"],
            })

            print(f"{q['query_id']}: {', '.join(ranked_ids)}")

        if args.query_id:
            print("Smoke test completed; no ranking file written.")
        else:
            output = BASE / "results/hybrid_question_only_rankings.jsonl"
            with output.open("w", encoding="utf-8") as f:
                for row in rankings:
                    f.write(json.dumps(row) + "\n")
            print(f"Saved: {output}")

        print("Gemini usage:", json.dumps(provider.metrics))

    finally:
        provider.close()


if __name__ == "__main__":
    main()
