"""Ranked trial IDs for the fixed MS3 retrieval benchmark (retrieval_protocol.md).

Runs the production retrieval components over the fixed manifest trial universe
for Q01-Q08 and writes `retrieval_runs.jsonl` plus a configuration record.
Relevance labelling and scoring belong to the evaluation owner; this script only
produces rankings.
"""

import argparse
import hashlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from evaluation.retrieval.benchmark import BIO_MODEL, BIO_REVISION, rrf, unique
from services.rag_workflow.config import Settings
from services.rag_workflow.data import DataStore, read_jsonl
from services.rag_workflow.embedding_providers import create_embedding_provider
from services.rag_workflow.index import VectorIndex
from services.rag_workflow.providers import ProviderError
from services.rag_workflow.retrieve import Retriever, patient_query

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STORES = Path(os.environ.get("MS3_STORES", ROOT / "artifacts/embedding_eval"))
SNAPSHOTS = {"bioclinical": ROOT / "artifacts/embedding_eval/bioclinical.snapshot.json"}


def build_finetuned_index(store, manifest, checkpoint, sha256):
    """Embed the 50-trial universe with a fine-tuned checkpoint into its own store.

    The checkpoint digest is part of the encoder identity, so this collection has a
    different name from the frozen one and the two sets of vectors cannot be mixed.
    """
    settings = replace(
        Settings(), artifacts=STORES / f"finetuned-{sha256[:12]}", chroma_host="", mode="live",
        embedding_provider="bioclinical", embedding_model=BIO_MODEL,
        embedding_revision=BIO_REVISION, dimension=768,
        embedding_checkpoint=checkpoint, embedding_checkpoint_sha256=sha256,
        embedding_device=os.environ.get("EMBEDDING_DEVICE", "auto"),
    )
    index = VectorIndex(settings, store, manifest, create_embedding_provider(settings))
    try:
        index.verify()
    except ProviderError:
        index.build()  # No snapshot exists for a new checkpoint; documents are encoded once.
    return settings, index


def build_index(encoder, store, manifest):
    """Reuse the existing experiment store; never re-embed or write to the shared index."""
    settings = replace(
        Settings(), artifacts=STORES / encoder, chroma_host="", mode="live",
        **({"embedding_provider": "bioclinical", "embedding_model": BIO_MODEL,
            "embedding_revision": BIO_REVISION, "dimension": 768}
           if encoder == "bioclinical" else
           {"embedding_provider": "gemini", "embedding_model": "gemini-embedding-001",
            "embedding_revision": "", "dimension": 256}),
    )
    index = VectorIndex(settings, store, manifest, create_embedding_provider(settings))
    source = (ROOT / "services/rag_workflow/index_snapshots/current.json"
              if encoder == "gemini" else SNAPSHOTS[encoder])
    if not source.exists():
        raise SystemExit(f"Missing {encoder} snapshot: {source}")
    try:
        index.verify()
    except ProviderError:
        # Restore validates source IDs, hashes, model and dimension before writing,
        # and makes no document API calls. Nothing is re-encoded here.
        index.restore(source)
    return settings, index


def dense_trials(index, query, provider):
    vector = provider.embed(query, "RETRIEVAL_QUERY")
    records = index.verify()[1]
    raw = index._collection().query(
        query_embeddings=[vector], n_results=len(records), include=["metadatas"]
    )
    # One trial keeps only its best criterion hit, matching the production retriever.
    return unique(row["trial_id"] for row in raw["metadatas"][0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--encoders", nargs="*", default=["bioclinical"],
                        choices=["gemini", "bioclinical"])
    parser.add_argument("--queries", type=Path, default=HERE / "retrieval_queries.jsonl")
    parser.add_argument("--output", type=Path, default=HERE / "retrieval_runs.jsonl")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--finetuned-manifest", type=Path,
                        help="training_manifest.json of the checkpoint to add as finetuned_*")
    parser.add_argument("--finetuned-checkpoint",
                        help="Override the manifest's artifact_uri with a local copy")
    args = parser.parse_args()
    args.output, args.queries = args.output.resolve(), args.queries.resolve()
    encoders = list(args.encoders)
    training = None
    if args.finetuned_manifest:
        training = json.loads(args.finetuned_manifest.read_text())
        encoders.append("finetuned")

    store = DataStore(Settings())
    manifest = store.manifest()
    universe = set(manifest["trial_ids"])
    cases = read_jsonl(args.queries)
    commit = os.environ.get("SOURCE_COMMIT", "")
    if not commit:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], check=False, cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()

    def modes(case):
        patient = store.patient(case["patient_id"])
        return {"question": case["question"],
                "patient": patient_query(patient, case["question"])}

    rows, methods = [], {}
    # BM25 does not depend on the encoder, so emit it once.
    lexical_cache = {}
    retriever = Retriever(store, manifest, None)
    for case in cases:
        for mode, query in modes(case).items():
            ranking = [key for key, _ in retriever.lexical.rank(query)]
            lexical_cache[(case["query_id"], mode)] = ranking
            rows.append({"query_id": case["query_id"], "method": f"bm25_{mode}",
                         "ranked_trial_ids": ranking[: args.top_k]})
    for mode in ("question", "patient"):
        methods[f"bm25_{mode}"] = {
            "retrieval": "BM25 over trial title + conditions + brief summary + all criteria",
            "query_construction": mode, "encoder": None, "fusion": None,
        }

    frozen_name = None
    for encoder in encoders:
        if encoder == "finetuned":
            settings, index = build_finetuned_index(
                store, manifest, args.finetuned_checkpoint or training["artifact_uri"],
                training["artifact_sha256"])
            if index.name == frozen_name:
                raise SystemExit("Fine-tuned and frozen encoders resolved to one collection")
        else:
            settings, index = build_index(encoder, store, manifest)
            if encoder == "bioclinical":
                frozen_name = index.name
        provider = index.provider if hasattr(index, "provider") else create_embedding_provider(settings)
        for case in cases:
            for mode, query in modes(case).items():
                dense = dense_trials(index, query, provider)
                hybrid = rrf([lexical_cache[(case["query_id"], mode)], dense])
                rows.append({"query_id": case["query_id"], "method": f"{encoder}_dense_{mode}",
                             "ranked_trial_ids": dense[: args.top_k]})
                rows.append({"query_id": case["query_id"], "method": f"{encoder}_hybrid_{mode}",
                             "ranked_trial_ids": hybrid[: args.top_k]})
        for mode in ("question", "patient"):
            common = {
                "query_construction": mode,
                "encoder": settings.embedding_model,
                "encoder_revision": settings.embedding_revision or "n/a (hosted API)",
                "dimension": settings.dimension,
                "indexed_text": "criterion-level fragments; best criterion hit per trial",
                "similarity": "cosine",
                "collection": index.name,
            }
            if encoder == "finetuned":
                common.update({
                    "checkpoint_sha256": training["artifact_sha256"],
                    "checkpoint_uri": training["artifact_uri"],
                    "training_workflow": training["workflow_type"],
                    "training_code_commit": training["code_commit"],
                    "training_run": training["experiment"].get("url")
                    or training["experiment"].get("path"),
                    "training_data": "corpus-derived and LLM-written query/criterion pairs "
                                     "from trials outside this benchmark universe",
                })
            methods[f"{encoder}_dense_{mode}"] = {**common, "fusion": None}
            methods[f"{encoder}_hybrid_{mode}"] = {
                **common, "fusion": "reciprocal rank fusion, k=60, over [BM25, dense]"}

    unknown = {t for row in rows for t in row["ranked_trial_ids"]} - universe
    if unknown:
        raise SystemExit(f"Rankings left the fixed trial universe: {sorted(unknown)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    config = {
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "code_commit": commit,
        "queries_file": str(args.queries.relative_to(ROOT)),
        "query_count": len(cases),
        "trial_universe": len(universe),
        "manifest": "services/rag_workflow/examples/demo_manifest.json",
        "patients": "services/patient_processing/data/processed/batch25_patients.jsonl",
        "source_sha256": store.hashes,
        "queries_sha256": hashlib.sha256(args.queries.read_bytes()).hexdigest(),
        "top_k": args.top_k,
        "query_construction": {
            "question": "the benchmark question text only",
            "patient": "unmodified production patient_query(patient, question)",
        },
        "cache": "frozen-encoder document vectors reused from the prepared experiment store; "
                 "fine-tuned document vectors are encoded once into a separate store",
        "methods": methods,
    }
    config_path = args.output.with_suffix(".config.json")
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    print(f"{len(rows)} rows -> {args.output}")
    print(f"config    -> {config_path}")


if __name__ == "__main__":
    main()
