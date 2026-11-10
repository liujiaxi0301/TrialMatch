# Retrieval runs handoff (Jenny -> Jiaxi)

Rankings for the fixed benchmark in [retrieval_protocol.md](retrieval_protocol.md).
Labelling, scoring and the comparison report remain with the evaluation owner;
nothing here computes a metric or inspects Q03-Q08 relevance.

- Rankings: [`retrieval_runs.jsonl`](retrieval_runs.jsonl) — 48 rows, 6 methods x Q01-Q08.
- Method configuration: [`retrieval_runs.config.json`](retrieval_runs.config.json) —
  code commit, encoder and revision, indexed text, fusion settings and cache use.
- Runner: [`run_retrieval.py`](run_retrieval.py).

All returned IDs are checked against the 50-trial manifest universe before the
file is written; the run fails rather than emitting an out-of-universe ID.

## Methods

| Method | Query construction | Ranking |
| --- | --- | --- |
| `bm25_question` / `bm25_patient` | question text / production `patient_query` | BM25 over title, conditions, summary and all criteria |
| `bioclinical_dense_*` | same pair | cosine over criterion fragments, best criterion hit per trial |
| `bioclinical_hybrid_*` | same pair | RRF (k=60) over [BM25, BioClinical dense] |

BioClinical is `thomas-sounack/BioClinical-ModernBERT-base` at revision
`c3648aa87af95837c809e6f0c5f85d08160db437`, masked mean pooling, L2 normalized,
768 dimensions. **It is a frozen masked language model with no retrieval
fine-tuning**, so treat it as an encoder baseline, not a trained clinical
retriever. Document vectors were restored from the prepared snapshot; no
documents were re-embedded for this run. Gemini rows are omitted because the
existing BM25 and Gemini-hybrid results already cover those cells.

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

| Query | Distinct trials across all six methods | New from BioClinical only |
| --- | ---: | ---: |
| Q01 | 18 | 8 |
| Q02 | 15 | 6 |
| Q03 | 18 | 9 |
| Q04 | 21 | 11 |
| Q05 | 16 | 7 |
| Q06 | 15 | 6 |
| Q07 | 17 | 7 |
| Q08 | 17 | 8 |

40 of the 50 corpus trials appear somewhere in these rankings.

## Observations offered without scores

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

Requires the prepared BioClinical snapshot under `artifacts/embedding_eval/`.
Add `--encoders gemini bioclinical` with valid credentials for the Gemini rows.
