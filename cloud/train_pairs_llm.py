"""Generate retrieval training queries from criteria with the configured LLM.

Complements `cloud.train_pairs`, which templates queries from trial metadata and so
can only pair a criterion with topic words it already contains. Here the model writes
the trial search request a coordinator might type, which gives pairs that are not
built on lexical overlap.

Needs live credentials, so it runs on a workstation that has them, not in CI. The
provider caches every response on disk by content hash, so re-running costs nothing
and produces the same queries.

    uv run --locked --group embeddings --env-file services/rag_workflow/.env \
      python -m cloud.train_pairs_llm --limit 4000
"""

import argparse
import json
import random
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from cloud.train_pairs import (
    GENERIC,
    InvertedBM25,
    normalize,
    split_of,
    tokens,
)
from services.rag_workflow.config import Settings
from services.rag_workflow.providers import GeminiProvider, ProviderError

ROOT = Path(__file__).resolve().parents[1]

SYSTEM = """You write search requests for a clinical trial registry.

For each numbered eligibility criterion you are given, write the one-sentence request
a trial coordinator might type that this criterion helps answer. Describe the kind of
study and population being looked for. Do not restate or paraphrase the criterion, do
not quote its numbers or thresholds, and do not mention eligibility, inclusion or
exclusion. If a criterion is purely administrative, such as consent or an age range,
return an empty string for it.

Return one entry per input index, in the same order."""


class Query(BaseModel):
    index: int
    query: str = Field(default="")


class Queries(BaseModel):
    queries: list[Query]


def overlap(query: str, criterion: str) -> float:
    """Share of query content words that the criterion already contains."""
    q, c = set(tokens(query)), set(tokens(criterion))
    q -= {"find", "trials", "trial", "studies", "study", "clinical", "looking", "patients"}
    return len(q & c) / len(q) if q else 1.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--criteria", type=Path,
                        default=ROOT / "services/trial_ingestion/data/processed/criteria.jsonl")
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "services/rag_workflow/examples/demo_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/training/pairs_llm.jsonl")
    parser.add_argument("--limit", type=int, default=2000, help="Criteria to send; bounds cost")
    parser.add_argument("--batch", type=int, default=20, help="Criteria per request")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--negatives", type=int, default=4)
    parser.add_argument("--max-overlap", type=float, default=0.6,
                        help="Reject a query that mostly repeats its criterion")
    parser.add_argument("--validation-share", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    held_out = set(json.loads(args.manifest.read_text())["trial_ids"])
    rows = [json.loads(line) for line in args.criteria.read_text().splitlines()]
    pool_rows = [
        r for r in rows
        if r["trial_id"] not in held_out
        and r.get("criterion_text")
        and not GENERIC.search(r["criterion_text"].lower())
        and len(r["criterion_text"].split()) >= 5
    ]
    assert not ({r["trial_id"] for r in pool_rows} & held_out), "benchmark trials leaked"
    random.Random(args.seed).shuffle(pool_rows)
    selected = pool_rows[: args.limit]
    print(f"{len(rows)} criteria -> {len(pool_rows)} eligible -> {len(selected)} sent "
          f"in {-(-len(selected) // args.batch)} requests")

    provider = GeminiProvider(Settings())
    batches = [selected[i : i + args.batch] for i in range(0, len(selected), args.batch)]

    def ask(batch):
        payload = {"criteria": [{"index": i, "text": r["criterion_text"]}
                                for i, r in enumerate(batch)]}
        try:
            answer = provider.generate(SYSTEM, payload, Queries)
        except (ProviderError, ValueError) as exc:
            # One bad batch must not lose the rest of the run; malformed JSON is a ValueError.
            print(f"  batch failed: {type(exc).__name__}")
            return []
        by_index = {q.index: q.query.strip() for q in answer.queries}
        return [(r, by_index.get(i, "")) for i, r in enumerate(batch)]

    generated = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for done, result in enumerate(pool.map(ask, batches), 1):
            generated.extend(result)
            if done % 10 == 0:
                print(f"  {done}/{len(batches)} batches")

    kept, dropped_empty, dropped_overlap = [], 0, 0
    for row, query in generated:
        if not query or len(query.split()) < 4:
            dropped_empty += 1
        elif overlap(query, row["criterion_text"]) > args.max_overlap:
            dropped_overlap += 1  # The model echoed the criterion; it teaches copying.
        else:
            kept.append((row, query))

    # Hard negatives come from other trials, as in cloud.train_pairs.
    index = {r["criterion_id"]: r for r in pool_rows}
    bm25 = InvertedBM25({k: r["criterion_text"] for k, r in index.items()})
    by_trial = defaultdict(set)
    for r in pool_rows:
        by_trial[r["trial_id"]].add(normalize(r["criterion_text"]))

    pairs = []
    for row, query in kept:
        own = by_trial[row["trial_id"]]
        negatives = [
            index[k]["criterion_text"] for k in bm25.top(query, 40)
            if index[k]["trial_id"] != row["trial_id"]
            and normalize(index[k]["criterion_text"]) not in own
        ][: args.negatives]
        if not negatives:
            continue
        pairs.append({
            "query": query,
            "positive": row["criterion_text"],
            "negatives": negatives,
            "trial_id": row["trial_id"],
            "criterion_id": row["criterion_id"],
            "criterion_type": row.get("criterion_type"),
            "split": split_of(row["trial_id"], args.validation_share),
            "query_source": "llm",
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for pair in pairs:
            handle.write(json.dumps(pair, sort_keys=True) + "\n")
    summary = {
        "criteria_sent": len(selected),
        "requests": len(batches),
        "queries_returned": len(generated),
        "dropped_empty_or_administrative": dropped_empty,
        "dropped_for_repeating_the_criterion": dropped_overlap,
        "max_overlap": args.max_overlap,
        "pairs": len(pairs),
        "pairs_by_split": {
            s: sum(1 for p in pairs if p["split"] == s) for s in ("train", "validation")
        },
        "generation_model": Settings().generation_model,
        "held_out_trials": len(held_out),
        "provider_metrics": provider.metrics,
        "seed": args.seed,
    }
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
