"""Run from the repository root: python -m evaluation.retrieval.benchmark --help."""

import argparse
import csv
import importlib.metadata
import json
import math
import platform
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore, digest, read_jsonl
from services.rag_workflow.embedding_providers import create_embedding_provider
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.providers import content_hash, save_json
from services.rag_workflow.retrieve import Retriever, patient_query

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "artifacts/embedding_eval"
BIO_MODEL = "thomas-sounack/BioClinical-ModernBERT-base"
BIO_REVISION = "c3648aa87af95837c809e6f0c5f85d08160db437"
# These are transparent SILVER topic labels, not clinical eligibility or human gold labels.
# Lexical definitions can favor lexical retrieval. Keep patterns and every match auditable.
TOPICS = {
    "glycemic": (
        "What restrictions apply to long-term blood sugar control?",
        r"\bhba1c\b|\ba1c\b|glycat(?:ed|ion)|glycosylated|glyc(?:a)?emic|blood sugar|blood glucose|plasma glucose|fasting glucose",
    ),
    "reproductive": (
        "Could reproductive status or nursing a baby prevent participation?",
        r"pregnan|breast.?feed|lactat|contracept|child.?bearing|reproductive|nursing (?:women|mother)",
    ),
    "renal": (
        "What requirements concern kidney function?",
        r"\brenal\b|kidney|\begfr\b|glomerular|creatinine|dialysis|nephro",
    ),
    "body_size": (
        "What body-size requirements would this patient need to meet?",
        r"\bbmi\b|body mass|body.?weight|body weight|obes|overweight|bariatric",
    ),
    "cardiac": (
        "Are there exclusions for heart disease or recent cardiovascular events?",
        r"cardia|heart|coronary|myocard|angina|arrhythm|\bnyha\b|\bqt[c]?\b",
    ),
    "insulin": (
        "Are there restrictions involving insulin treatment?",
        r"\binsulin\b",
    ),
}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def unique(items):
    return list(dict.fromkeys(items))


def rrf(rankings):
    scores = Counter()
    for ranking in rankings:
        for rank, key in enumerate(unique(ranking), 1):
            scores[key] += 1 / (60 + rank)
    return sorted(scores, key=lambda key: (-scores[key], key))


def rank_metrics(ranking, relevance, k):
    """Binary relevance. A missing judgment is not a negative human judgment.

    Silver fixtures label the whole frozen corpus, so their denominator is complete
    under the topic heuristic only. External gold must explicitly declare completeness.
    """
    ranking = unique(ranking)
    relevant = {key for key, grade in relevance.items() if grade > 0}
    if not relevant:
        raise ValueError("Cannot score a query with no relevant documents")
    hits = [int(key in relevant) for key in ranking[:k]]
    dcg = sum(hit / math.log2(rank + 2) for rank, hit in enumerate(hits))
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(k, len(relevant))))
    return {
        f"recall@{k}": sum(hits) / len(relevant),
        f"ndcg@{k}": dcg / ideal,
        f"mrr@{k}": next((1 / i for i, hit in enumerate(hits, 1) if hit), 0.0),
        f"hit@{k}": float(any(hits)),
        f"precision@{k}": sum(hits) / k,
    }


def prepare(output):
    settings = Settings()
    store = DataStore(settings)
    manifest = store.manifest()
    # Only enumerate fragments. Never touch the existing Chroma store during preparation.
    fragmenter = object.__new__(VectorIndex)
    fragmenter.store, fragmenter.manifest = store, manifest
    corpus = [
        {"fragment_id": key, "text": text, **meta} for key, text, meta in fragmenter.fragments()
    ]
    indexed_ids = {row["criterion_id"] for row in corpus}
    criteria = {
        row["criterion_id"]: {"text": row["criterion_text"], "trial_id": row["trial_id"]}
        for trial_id in manifest["trial_ids"]
        for row in store.criteria[trial_id]
        if row["criterion_id"] in indexed_ids
    }
    queries, qrels, review = [], [], []
    patient_ids = manifest["patient_ids"][:5]
    for pi, patient_id in enumerate(patient_ids, 1):
        for ti, (topic, (question, pattern)) in enumerate(TOPICS.items(), 1):
            query_id = f"P{pi:02d}_{topic}"
            queries.append(
                {
                    "query_id": query_id,
                    "patient_id": patient_id,
                    "question": question,
                    "topic": topic,
                }
            )
            matches = []
            for criterion_id, row in criteria.items():
                match = re.search(pattern, row["text"], re.IGNORECASE)
                grade = int(match is not None)
                if grade:
                    matches.append(criterion_id)
                review.append(
                    {
                        "query_id": query_id,
                        "criterion_id": criterion_id,
                        "trial_id": row["trial_id"],
                        "silver_label": grade,
                        "matched_text": match.group() if match else "",
                        "criterion_text": row["text"],
                        "human_label": "",
                        "reviewer": "",
                    }
                )
            if not matches:
                raise ValueError(f"No source criteria for topic {topic}")
            qrels.append(
                {
                    "query_id": query_id,
                    "relevant_criterion_ids": matches,
                    "label_source": "regex_silver_not_human_reviewed",
                    "complete_under_topic_rule": True,
                }
            )
    directory = output / "dataset"
    write_jsonl(directory / "corpus.jsonl", corpus)
    write_jsonl(directory / "queries.jsonl", queries)
    write_jsonl(directory / "qrels.silver.jsonl", qrels)
    with (directory / "human_review.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(review[0]))
        writer.writeheader()
        writer.writerows(review)
    save_json(
        directory / "manifest.json",
        {
            "label_source": "regex_silver_not_human_reviewed",
            "warning": "Diagnostic only. Keyword labels can favor BM25; not clinical accuracy or a held-out gold benchmark.",
            "topic_rules": {key: pattern for key, (_, pattern) in TOPICS.items()},
            "source_sha256": store.hashes,
            "trial_ids": manifest["trial_ids"],
            "patients": patient_ids,
            "query_count": len(queries),
            "unique_questions": len(TOPICS),
            "criterion_count": len(criteria),
            "fragment_count": len(corpus),
            "files_sha256": {
                name: digest(directory / name)
                for name in ("corpus.jsonl", "queries.jsonl", "qrels.silver.jsonl")
            },
        },
    )
    print(f"Prepared {len(queries)} cases, {len(criteria)} criteria, {len(corpus)} fragments")


def run(output, encoder, query_mode, query_limit=None):
    import numpy as np

    directory = output / "dataset"
    dataset = json.loads((directory / "manifest.json").read_text())
    for name, expected in dataset["files_sha256"].items():
        if digest(directory / name) != expected:
            raise ValueError(f"Frozen dataset changed: {name}; prepare explicitly")
    settings = Settings()
    store = DataStore(settings)
    manifest = store.manifest()
    if store.hashes != dataset["source_sha256"] or manifest["trial_ids"] != dataset["trial_ids"]:
        raise ValueError("Source changed since dataset preparation")
    settings = replace(settings, artifacts=output / encoder, chroma_host="", mode="live")
    if encoder == "bioclinical":
        settings = replace(
            settings,
            embedding_provider="bioclinical",
            embedding_model=BIO_MODEL,
            embedding_revision=BIO_REVISION,
            dimension=768,
        )
    else:
        settings = replace(
            settings,
            embedding_provider="gemini",
            embedding_model="gemini-embedding-001",
            embedding_revision="",
            dimension=256,
        )
    provider = create_embedding_provider(settings)
    index = VectorIndex(settings, store, manifest, provider)
    started = time.perf_counter()
    if encoder == "gemini":
        source = ROOT / "services/rag_workflow/index_snapshots/current.json"
        index.restore(
            source
        )  # Validates source IDs, hashes, model and dimensions; no cloud writes.
        build_mode = "restored_existing_ms2_snapshot_no_document_api_calls"
    else:
        was_ready = index.manifest_path.exists()
        index.build()
        build_mode = "verified_existing" if was_ready else "encoded_local_documents"
    build_seconds = time.perf_counter() - started
    saved, records = index.verify()
    matrix = np.array([row["embedding"] for row in records], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    queries = read_jsonl(directory / "queries.jsonl")
    if query_limit:
        queries = queries[:query_limit]
    qrels = {row["query_id"]: row for row in read_jsonl(directory / "qrels.silver.jsonl")}
    corpus = read_jsonl(directory / "corpus.jsonl")
    criterion_trial = {row["criterion_id"]: row["trial_id"] for row in corpus}
    retriever = Retriever(store, manifest, index)
    rows = []
    try:
        for qi, case in enumerate(queries, 1):
            patient = store.patient(case["patient_id"])
            query = (
                patient_query(patient, case["question"])
                if query_mode == "patient"
                else case["question"]
            )
            before = dict(provider.metrics)
            begin = time.perf_counter()
            vector = np.array(provider.embed(query, "RETRIEVAL_QUERY"), dtype=np.float32)
            vector /= np.linalg.norm(vector)
            similarities = matrix @ vector
            order = sorted(
                range(len(records)), key=lambda i: (-float(similarities[i]), records[i]["id"])
            )
            # Exhaustive cosine ranking is the controlled embedding comparison (no ANN noise).
            exact_criteria = unique(records[i]["metadata"]["criterion_id"] for i in order)
            # Also run the real Chroma path and preserve its criterion hits and distances.
            raw = index._collection().query(
                query_embeddings=[vector.tolist()],
                n_results=len(records),
                include=["metadatas", "distances"],
            )
            chroma_criteria = unique(row["criterion_id"] for row in raw["metadatas"][0])
            chroma_trials = unique(row["trial_id"] for row in raw["metadatas"][0])
            lexical = [key for key, _ in retriever.lexical.rank(query)]
            hybrid = rrf([lexical, chroma_trials])
            elapsed = time.perf_counter() - begin
            relevance = {key: 1 for key in qrels[case["query_id"]]["relevant_criterion_ids"]}
            trial_relevance = {criterion_trial[key]: 1 for key in relevance}
            metrics = {
                "criterion_exact_dense": rank_metrics(exact_criteria, relevance, 10),
                "criterion_chroma_dense": rank_metrics(chroma_criteria, relevance, 10),
                "trial_dense": rank_metrics(chroma_trials, trial_relevance, 5),
                "trial_hybrid": rank_metrics(hybrid, trial_relevance, 5),
                "trial_bm25": rank_metrics(lexical, trial_relevance, 5),
            }
            # Check evaluator hybrid matches the production Retriever on the actual patient-query path.
            if query_mode == "patient":
                production = retriever.retrieve(patient, case["question"], 5)
                if [row["trial_id"] for row in production] != hybrid[:5]:
                    raise ValueError("Benchmark hybrid differs from production retrieval")
            rows.append(
                {
                    **case,
                    "query": query,
                    "query_sha256": content_hash(query),
                    "metrics": metrics,
                    "seconds": elapsed,
                    "encoder_cache_hits": provider.metrics["cache_hits"] - before["cache_hits"],
                    "relevant_criteria": list(relevance),
                    "relevant_trials": list(trial_relevance),
                    "dense_criterion_ids": chroma_criteria[:10],
                    "dense_trial_ids": chroma_trials[:5],
                    "hybrid_trial_ids": hybrid[:5],
                    "bm25_trial_ids": lexical[:5],
                    "exact_criterion_ids": exact_criteria[:10],
                    "top_criteria": [
                        {
                            "criterion_id": key,
                            "text": next(
                                row["document"]
                                for row in records
                                if row["metadata"]["criterion_id"] == key
                            ),
                            "silver_relevant": key in relevance,
                        }
                        for key in chroma_criteria[:10]
                    ],
                }
            )
            print(
                f"{encoder}/{query_mode}: {qi}/{len(queries)} {case['query_id']} ({elapsed:.2f}s)",
                flush=True,
            )
    finally:
        provider.close()
    averages = {
        section: {
            key: statistics.mean(row["metrics"][section][key] for row in rows)
            for key in rows[0]["metrics"][section]
        }
        for section in rows[0]["metrics"]
    }
    timing = sorted(row["seconds"] for row in rows)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "working_tree_has_changes": bool(
            subprocess.check_output(["git", "diff", "--stat"], cwd=ROOT)
        ),
        "source_code_sha256": {
            str(path.relative_to(ROOT)): digest(path)
            for path in [
                Path(__file__),
                ROOT / "services/rag_workflow/embedding_providers.py",
                ROOT / "services/rag_workflow/retrieve.py",
                ROOT / "uv.lock",
            ]
        },
        "encoder": encoder,
        "query_mode": query_mode,
        "index_identity": index.identity,
        "index_records_sha256": saved["records_sha256"],
        "dataset": dataset,
        "label_source": dataset["label_source"],
        "build_mode": build_mode,
        "index_preparation_seconds": build_seconds,
        "query_count": len(rows),
        "unique_questions": len({row["question"] for row in rows}),
        "query_latency_median_seconds": statistics.median(timing),
        "query_latency_p95_seconds": timing[max(0, math.ceil(len(timing) * 0.95) - 1)],
        "metrics": averages,
        "provider_metrics": provider.metrics,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "device": getattr(provider, "device", "vertex_api"),
            "packages": {
                name: importlib.metadata.version(name)
                for name in ("torch", "transformers", "chromadb", "google-genai", "numpy")
            },
        },
        "cases": rows,
    }
    destination = output / "results" / f"{encoder}_{query_mode}.json"
    save_json(destination, report)
    print(f"Wrote {destination}")


def summarize(output):
    paths = sorted((output / "results").glob("*.json"))
    reports = [json.loads(path.read_text()) for path in paths]
    if not reports:
        raise ValueError("No completed runs")
    lines = [
        "# Embedding retrieval pilot",
        "",
        "**Provisional silver-label diagnostic, not human-validated clinical accuracy.**",
        "",
        "Frozen MS2 corpus; identical chunking, patients, question text and RRF constant (60).",
        "Six unique questions repeat across five synthetic patients. The 30 cases are not 30 independent topics.",
        "Regex-derived topic labels cover the frozen corpus under those rules only and can favor BM25.",
        "",
        "| Encoder | Query | Criterion nDCG@10 | Criterion Recall@10 | Criterion MRR@10 | Trial dense nDCG@5 | Trial hybrid nDCG@5 | Median seconds |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        c = report["metrics"]["criterion_chroma_dense"]
        lines.append(
            f"| {report['encoder']} | {report['query_mode']} | {c['ndcg@10']:.3f} | {c['recall@10']:.3f} | {c['mrr@10']:.3f} | {report['metrics']['trial_dense']['ndcg@5']:.3f} | {report['metrics']['trial_hybrid']['ndcg@5']:.3f} | {report['query_latency_median_seconds']:.3f} |"
        )
    lines += [
        "",
        "## Per-topic diagnostic",
        "",
        "| Encoder | Query | Topic | Criterion nDCG@10 | Trial hybrid nDCG@5 |",
        "|---|---|---|---:|---:|",
    ]
    for report in reports:
        topics = defaultdict(list)
        for row in report["cases"]:
            topics[row["topic"]].append(row)
        for topic, cases in topics.items():
            lines.append(
                f"| {report['encoder']} | {report['query_mode']} | {topic} | {statistics.mean(row['metrics']['criterion_chroma_dense']['ndcg@10'] for row in cases):.3f} | {statistics.mean(row['metrics']['trial_hybrid']['ndcg@5'] for row in cases):.3f} |"
            )
    lines += [
        "",
        "## Interpretation and limits",
        "",
        "- Patient mode is the unmodified production query builder. Question mode is an ablation, not a deployment change.",
        "- Frozen BioClinical MLM uses masked mean pooling and L2 normalization; no retrieval fine-tuning has occurred.",
        "- Raw similarity magnitudes, eligibility match scores, and UNKNOWN counts are not embedding evaluation metrics.",
        "- Gemini document vectors were restored from the verified MS2 snapshot. Restore time is not Gemini encoding time.",
        "- Timing includes cache effects and database/verification overhead. It is not a pure encoder speed comparison.",
        "- No LLM judgments or explanations are generated by this benchmark. Full-pipeline clinical accuracy remains unmeasured.",
        "- Have reviewers complete dataset/human_review.csv before claiming improvement against human reference labels.",
        "- Raw ranks, query hashes, runtime versions, source hashes and encoder settings are in results/*.json.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines))
    print(f"Wrote {output / 'REPORT.md'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare")
    runner = sub.add_parser("run")
    runner.add_argument("--encoder", choices=["gemini", "bioclinical"], required=True)
    runner.add_argument("--query-mode", choices=["patient", "question"], default="patient")
    runner.add_argument("--query-limit", type=int)
    sub.add_parser("report")
    args = parser.parse_args()
    args.output = args.output.resolve()
    if args.command == "prepare":
        prepare(args.output)
    elif args.command == "run":
        run(args.output, args.encoder, args.query_mode, args.query_limit)
    else:
        summarize(args.output)


if __name__ == "__main__":
    main()
