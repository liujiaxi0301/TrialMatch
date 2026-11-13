# Retrieval runs handoff (Jenny -> Jiaxi)

Rankings for the fixed benchmark in [retrieval_protocol.md](retrieval_protocol.md).
Labelling, scoring and the comparison report remain with the evaluation owner;
nothing here computes a metric or inspects Q03-Q08 relevance.

- Rankings: [`retrieval_runs.jsonl`](retrieval_runs.jsonl) — 80 rows, 10 methods x Q01-Q08.
  The 48 rows of the six earlier methods are unchanged, line for line.
- Method configuration: [`retrieval_runs.config.json`](retrieval_runs.config.json) —
  code commit, encoder and revision, indexed text, fusion settings and cache use.
- Runner: [`run_retrieval.py`](../run_retrieval.py).

All returned IDs are checked against the 50-trial manifest universe before the
file is written; the run fails rather than emitting an out-of-universe ID.

## Methods

| Method | Query construction | Ranking |
| --- | --- | --- |
| `bm25_question` / `bm25_patient` | question text / production `patient_query` | BM25 over title, conditions, summary and all criteria |
| `bioclinical_dense_*` | same pair | cosine over criterion fragments, best criterion hit per trial |
| `bioclinical_hybrid_*` | same pair | RRF (k=60) over [BM25, BioClinical dense] |
| `finetuned_dense_*` | same pair | as BioClinical dense, with the fine-tuned checkpoint |
| `finetuned_hybrid_*` | same pair | RRF (k=60) over [BM25, fine-tuned dense] |

BioClinical is `thomas-sounack/BioClinical-ModernBERT-base` at revision
`c3648aa87af95837c809e6f0c5f85d08160db437`, masked mean pooling, L2 normalized,
768 dimensions. **It is a frozen masked language model with no retrieval
fine-tuning**, so treat it as an encoder baseline, not a trained clinical
retriever. Document vectors were restored from the prepared snapshot; no
documents were re-embedded for this run. Gemini rows are omitted because the
existing BM25 and Gemini-hybrid results already cover those cells.

## Fine-tuned encoder (added 2026-11-10)

The `finetuned_*` methods use the same model and revision after contrastive fine-tuning
on Vertex AI. Query construction, indexed text, pooling, normalization, similarity and
fusion are identical to the `bioclinical_*` rows, so the encoder weights are the only
difference between the two families.

- Checkpoint: `gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model`,
  SHA256 `7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c`, verified
  locally before indexing.
- Training evidence: [`docs/ms3/evidence/module-b/2026-11-10/`](../../../docs/ms3/evidence/module-b/2026-11-10/README.md).
- Training data: 5,137 query/criterion pairs, part corpus-templated and part written by
  an LLM, from trials outside the 50-trial universe. The trainer asserts that no
  universe trial is in the pairs. No benchmark query, patient or label was used.
- Its vectors live in their own collection (`trialmatch-431a2592eb61038bd5cc`; the
  frozen encoder's is `trialmatch-521ce7bbbd24d65deb8e`), so the two never mix.

The only quality numbers that exist for this checkpoint are on its internal validation
pairs, which come from the same generators as its training pairs. They say nothing about
these eight queries. Whether fine-tuning helped on the benchmark is for the labels to
decide, and the fine-tuned rows may turn out worse than the frozen ones.

## Harness check

`bm25_question` for Q08 reproduces the published ranking exactly:

```
NCT02836808, NCT04932928, NCT05129345, NCT03811470, NCT04783441
```

So the two harnesses agree on shared inputs, and differences in the BioClinical
rows come from the encoder rather than from a different corpus or query builder.

## Labelling load

These methods surface trials outside the existing BM25 pools, so the pool grows
before anything can be scored. Unjudged trials must not be scored as grade 0.

| Query | Distinct trials, six earlier methods | New from BioClinical only | Distinct trials, all ten methods | New from fine-tuned only |
| --- | ---: | ---: | ---: | ---: |
| Q01 | 18 | 8 | 20 | 2 |
| Q02 | 15 | 6 | 19 | 4 |
| Q03 | 18 | 9 | 21 | 3 |
| Q04 | 21 | 11 | 26 | 5 |
| Q05 | 16 | 7 | 18 | 2 |
| Q06 | 15 | 6 | 20 | 5 |
| Q07 | 17 | 7 | 18 | 1 |
| Q08 | 17 | 8 | 24 | 7 |

The fine-tuned rows add 29 query-trial pairs that none of the six earlier methods
returned. If the earlier pools are fully judged, those 29 are the pairs still to label.
45 of the 50 corpus trials now appear somewhere in these rankings (40 before).

## Observations offered without scores

These three were written for the six earlier methods and have not been redone for the
fine-tuned rows.

- Query construction changes the result set almost completely rather than
  reordering it. Mean top-5 overlap between the question and patient variants of
  the same method is 0.62/5 for BM25, 0.50/5 for BioClinical dense and 1.00/5 for
  BioClinical hybrid. Whatever the labels say, these are different retrievals,
  not different orderings of one retrieval.
- The effect appears under a second, unrelated encoder, so it is a property of
  the query builder rather than of any one embedding model.
- For Q08, BioClinical dense returns neither of the two trials previously graded
  2 under either query construction; the hybrid recovers one at rank 3 through
  its BM25 component.

## Reproduce

```bash
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
uv run --locked --group embeddings python -m evaluation.ms3.run_retrieval \
  --encoders bioclinical
```

With the fine-tuned rows (the checkpoint is downloaded and verified against the manifest):

```bash
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
export GOOGLE_CLOUD_PROJECT=trialmatch-ac215-yixiao
uv run --locked --group embeddings python -m evaluation.ms3.run_retrieval \
  --encoders bioclinical \
  --finetuned-manifest docs/ms3/evidence/module-b/2026-11-10/training_manifest.json
```

The committed file was produced with `--finetuned-checkpoint` pointing at a local copy of
the same checkpoint, digest-checked. Re-running the form above reproduced the same 80 rows.

Requires the prepared BioClinical snapshot under `artifacts/embedding_eval/`.
Add `--encoders gemini bioclinical` with valid credentials for the Gemini rows.
