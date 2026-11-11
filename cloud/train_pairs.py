"""Build retrieval training pairs from the trial corpus alone.

The 50 trials of the evaluation manifest are excluded entirely, so no criterion
that the fixed retrieval benchmark can return is ever seen in training. Queries
are derived from trial metadata, never from benchmark questions or relevance
labels, so this file depends on no human judgement.
"""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = (
    "Find clinical trials investigating {topic} in {condition}.",
    "Which studies enrol participants with {condition} for {topic}?",
    "Trials of {topic} among adults with {condition}.",
)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


class InvertedBM25:
    """BM25 restricted to documents sharing a query token, for negative mining."""

    def __init__(self, documents: dict[str, str]):
        self.tf = {key: Counter(tokens(value)) for key, value in documents.items()}
        self.length = {key: sum(c.values()) for key, c in self.tf.items()}
        self.average = sum(self.length.values()) / max(1, len(self.tf))
        self.postings = defaultdict(list)
        for key, counts in self.tf.items():
            for token, freq in counts.items():
                self.postings[token].append((key, freq))
        self.total = len(self.tf)

    def top(self, query: str, limit: int) -> list[str]:
        scores = Counter()
        # Sorted, so the float sums and therefore near-ties do not depend on hash order.
        for token in sorted(set(tokens(query))):
            posting = self.postings.get(token)
            if not posting or len(posting) > self.total * 0.3:
                continue  # Skip absent and near-universal tokens.
            idf = (self.total - len(posting) + 0.5) / (len(posting) + 0.5)
            idf = max(0.0, idf) ** 0.5
            for key, freq in posting:
                norm = 0.25 + 0.75 * self.length[key] / self.average
                scores[key] += idf * freq * 2.5 / (freq + 1.5 * norm)
        return sorted(scores, key=lambda key: (-scores[key], key))[:limit]


GENERIC = re.compile(
    r"\b(informed consent|able to (?:understand|read|provide)|willing(?:ness)? to|"
    r"aged? \d+|years of age|between the ages|male or female|any (?:sex|gender)|"
    r"signed consent|able to comply|life expectancy|investigator(?:'s)? (?:opinion|discretion))\b"
)


def content_terms(text: str) -> set[str]:
    """Topic words of a metadata term, ignoring the disease anchor every trial shares."""
    stop = {"of", "the", "and", "in", "with", "for", "to", "a", "an", "or", "type",
            "mellitus", "diabetes", "diabetic", "study", "studies", "trial", "trials",
            "patients", "patient", "adults", "adult", "disease", "2", "ii"}
    return {t for t in tokens(text) if t not in stop and len(t) > 3}


def topical(criterion: str, topic_terms: set[str]) -> bool:
    """A positive must carry the query's topic, not just belong to the same trial."""
    if not topic_terms or GENERIC.search(criterion.lower()):
        return False
    return bool(topic_terms & content_terms(criterion))


def split_of(trial_id: str, validation_share: float) -> str:
    # Hash the trial, never the criterion: a trial's criteria stay in one split.
    digest = hashlib.sha256(trial_id.encode()).hexdigest()
    return "validation" if int(digest[:8], 16) / 0xFFFFFFFF < validation_share else "train"


def queries_for(trial: dict) -> list[str]:
    conditions = trial.get("conditions") or ["type 2 diabetes"]
    condition = conditions[0]
    topics = [t for t in (trial.get("keywords") or []) if len(t.split()) <= 6]
    topics += [t for t in (trial.get("mesh_terms") or []) if t not in conditions]
    if not topics:
        topics = [(trial.get("brief_title") or "").strip()]
    result = []
    for index, topic in enumerate(list(dict.fromkeys(t for t in topics if t))[:3]):
        text = TEMPLATES[index % len(TEMPLATES)].format(topic=topic, condition=condition)
        result.append((text, content_terms(topic) | content_terms(condition)))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=Path,
                        default=ROOT / "services/trial_ingestion/data/processed/trials.jsonl")
    parser.add_argument("--criteria", type=Path,
                        default=ROOT / "services/trial_ingestion/data/processed/criteria.jsonl")
    parser.add_argument("--manifest", type=Path,
                        default=ROOT / "services/rag_workflow/examples/demo_manifest.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/training/pairs.jsonl")
    parser.add_argument("--max-shared", type=int, default=3,
                        help="Drop criterion text reused by more than this many trials")
    parser.add_argument("--positives-per-query", type=int, default=4)
    parser.add_argument("--negatives-per-positive", type=int, default=4)
    parser.add_argument("--validation-share", type=float, default=0.1)
    args = parser.parse_args()

    held_out = set(json.loads(args.manifest.read_text())["trial_ids"])
    trials = {}
    for line in args.trials.read_text().splitlines():
        row = json.loads(line)
        if row["trial_id"] not in held_out:
            trials[row["trial_id"]] = row
    criteria = [json.loads(line) for line in args.criteria.read_text().splitlines()]
    criteria = [c for c in criteria if c["trial_id"] in trials and c.get("criterion_text")]

    # Boilerplate shared across trials carries no topical signal and would teach the
    # encoder to separate identical text by trial. Drop it from positives and negatives.
    owners = defaultdict(set)
    for row in criteria:
        owners[normalize(row["criterion_text"])].add(row["trial_id"])
    distinctive = [c for c in criteria if len(owners[normalize(c["criterion_text"])]) <= args.max_shared]

    by_trial = defaultdict(list)
    for row in distinctive:
        by_trial[row["trial_id"]].append(row)
    pool = {row["criterion_id"]: row for row in distinctive}
    bm25 = InvertedBM25({key: row["criterion_text"] for key, row in pool.items()})

    rows, skipped, skipped_untopical = [], 0, 0
    for trial_id, trial in trials.items():
        positives = by_trial.get(trial_id, [])
        if not positives:
            skipped += 1
            continue
        own_text = {normalize(c["criterion_text"]) for c in positives}
        for query, topic_terms in queries_for(trial):
            # The trial supplies candidates; the topic decides which of them is a positive.
            aligned = [c for c in positives if topical(c["criterion_text"], topic_terms)]
            if not aligned:
                skipped_untopical += 1
                continue
            # Mine once per query, then hand each positive its own disjoint negatives.
            # Drop any mined text that shares the topic more strongly than the positive
            # does: those are unlabelled relevant criteria, not negatives.
            mined = [
                key for key in bm25.top(query, 160)
                if pool[key]["trial_id"] != trial_id
                and normalize(pool[key]["criterion_text"]) not in own_text
                and not topical(pool[key]["criterion_text"], topic_terms)
            ]
            for offset, positive in enumerate(aligned[: args.positives_per_query]):
                start = offset * args.negatives_per_positive
                negatives = mined[start : start + args.negatives_per_positive]
                if not negatives:
                    continue
                rows.append({
                    "query": query,
                    "positive": positive["criterion_text"],
                    "negatives": [pool[key]["criterion_text"] for key in negatives],
                    "trial_id": trial_id,
                    "criterion_id": positive["criterion_id"],
                    "criterion_type": positive.get("criterion_type"),
                    "split": split_of(trial_id, args.validation_share),
                })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = Counter(row["split"] for row in rows)
    summary = {
        "held_out_trials": len(held_out),
        "training_trials": len(trials),
        "criteria_in_scope": len(criteria),
        "criteria_after_boilerplate_filter": len(distinctive),
        "max_trials_sharing_a_criterion": args.max_shared,
        "trials_without_distinctive_criteria": skipped,
        "queries_dropped_no_topical_positive": skipped_untopical,
        "pairs": len(rows),
        "pairs_by_split": dict(counts),
        "query_source": "trial conditions, keywords and MeSH terms; no benchmark text",
        "positives": "criteria of the trial that carry the query topic; generic administrative criteria excluded",
        "negatives": "BM25 over criteria of other trials, excluding text the trial reuses and any criterion that also carries the topic",
    }
    args.output.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
