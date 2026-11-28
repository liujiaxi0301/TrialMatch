# Retrieval provenance

The frozen [rankings](retrieval_runs.jsonl) contain 80 rows: ten methods × eight
queries. [Configuration](retrieval_runs.config.json) records the original code,
encoder revision, query settings, indexing and cache use. Four additional
BM25/Gemini baselines are under `results/`; the [report](RETRIEVAL_EVALUATION_REPORT.md)
compares all 14 methods against 182 reviewed query–trial labels.

## Methods and checkpoint

| Family | Query construction | Retrieval |
| --- | --- | --- |
| `bm25_*` | Question only / production patient-aware query | BM25 over trial title, conditions, summary and criteria |
| `bioclinical_dense_*` | Same pair | Criterion-fragment cosine similarity; best hit per trial |
| `bioclinical_hybrid_*` | Same pair | RRF (k=60) over BM25 and dense retrieval |
| `finetuned_dense_*`, `finetuned_hybrid_*` | Same pair | Same architecture/indexing, fine-tuned weights |

The base encoder is `thomas-sounack/BioClinical-ModernBERT-base` at revision
`c3648aa87af95837c809e6f0c5f85d08160db437`: masked mean pooling, L2 normalization,
768 dimensions. It has no retrieval fine-tuning in the `bioclinical_*` methods.
The `finetuned_*` methods use the [November 10 checkpoint](../../../docs/training/README.md),
whose hash was verified before indexing. Both models have separate collections.
All returned IDs must belong to the fixed 50-trial universe.

The recorded configuration retains its original `queries_file` path for provenance.
The identical query file now lives at `retrieval/retrieval_queries.jsonl` beneath
`evaluation/ms3/`; runners and images use that single copy.

## Reproduce rankings

From the repository root, with the prepared BioClinical snapshot under
`artifacts/embedding_eval/`:

```bash
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
uv run --locked --group embeddings python -m evaluation.ms3.run_retrieval \
  --encoders bioclinical
```

Add the trained encoder; the model files are downloaded and checked against the manifest:

```bash
export GOOGLE_CLOUD_PROJECT=trialmatch-ac215-yixiao
uv run --locked --group embeddings python -m evaluation.ms3.run_retrieval \
  --encoders bioclinical \
  --finetuned-manifest docs/training/training_manifest.json
```

Add `--encoders gemini bioclinical` with valid Google credentials for Gemini rows.
Generated rankings are separate from frozen labels. Score only after all returned
query–trial pairs have judgments; an unjudged pair is not a grade-zero label.
Question-only and patient-aware variants use different queries, so their scores
cannot be attributed solely to encoder weights. See the report for results and limits.
