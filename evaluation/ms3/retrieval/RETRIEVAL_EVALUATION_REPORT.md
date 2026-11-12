# TrialMatch MS3 — Retrieval Evaluation Report

**Evaluation date:** 2026-11-11
**Reporting split:** Q03–Q08 (6 queries)
**Development split:** Q01–Q02 (2 queries)
**Scope:** Retrieval topic relevance, not patient eligibility

## Executive summary

Fine-tuning substantially improved the frozen BioClinical encoder on this
small, fixed retrieval benchmark. The fine-tuned question-only hybrid
achieved the highest reporting P@3 (0.5556),
while question-only BM25 achieved the highest reporting nDCG@5
(0.6511).

BM25 is the preferred current default for this benchmark because it
has stronger graded ranking quality and no zero-P@3 reporting query.
The fine-tuned question-only hybrid remains a promising alternative,
particularly for Q04 and Q08. Neither result establishes clinical
readiness or general performance beyond this benchmark.

## 1. Evaluation design

The evaluation follows `retrieval_protocol.md`:

- Fixed 50-trial search universe from the milestone2 demo manifest.
- Eight frozen requests, with Q01–Q02 for development and Q03–Q08
  for reporting.
- Historical trial snapshot and synthetic patient records; patient
  reference date is 2021-11-30.
- Relevance scale: 2 = direct, 1 = partial, 0 = no substantive match.
- P@3 counts grades 1 or 2 as relevant.
- nDCG@5 uses gain `2^grade - 1` and the ideal ordering of all
  judged pooled candidates for each query.
- No unjudged returned trial is treated as irrelevant.

The expanded Gold contains **182 unique query-trial judgments**:
107 retained judgments and 75 additional reviews. All 166 distinct
query-trial pairs returned by Jenny's ten methods are covered.
Sixteen older judgments outside the current ten-method pool
are retained in the full Gold.

Additional candidates were reviewed using method-blind packets.
The relevance judgments are non-clinician, user-reviewed assessments
with AI-assisted review suggestions. They are not independent
clinical-expert annotations or multi-annotator consensus labels.

## 2. Retrieval methods and results

Jenny's handoff contains ten methods: BM25, frozen BioClinical dense,
frozen BioClinical + BM25 RRF, fine-tuned dense, and fine-tuned
dense + BM25 RRF, each with question-only and patient-aware queries.

Two additional legacy hybrid baselines are displayed below.
The two legacy BM25 runs are omitted from this table because their
rankings exactly reproduce the corresponding Jenny BM25 runs.

All methods are evaluated on the same Gold and reporting queries.

| Source | Method | P@3 | nDCG@5 | Zero-P@3 queries |
|---|---|---:|---:|---:|
| Jenny handoff | `bm25_question` | 0.5000 | 0.6511 | 0/6 |
| Jenny handoff | `finetuned_hybrid_question` | 0.5556 | 0.6200 | 1/6 |
| Legacy baseline | `Hybrid Question-only (legacy)` | 0.3889 | 0.5988 | 1/6 |
| Jenny handoff | `finetuned_dense_question` | 0.3889 | 0.4712 | 0/6 |
| Jenny handoff | `bioclinical_hybrid_question` | 0.2222 | 0.2448 | 3/6 |
| Jenny handoff | `finetuned_hybrid_patient` | 0.0000 | 0.1520 | 6/6 |
| Legacy baseline | `BM25 + Gemini/Chroma Hybrid` | 0.1111 | 0.1226 | 4/6 |
| Jenny handoff | `bm25_patient` | 0.0556 | 0.1033 | 5/6 |
| Jenny handoff | `finetuned_dense_patient` | 0.0556 | 0.1006 | 5/6 |
| Jenny handoff | `bioclinical_dense_question` | 0.0000 | 0.0318 | 6/6 |
| Jenny handoff | `bioclinical_dense_patient` | 0.0000 | 0.0303 | 6/6 |
| Jenny handoff | `bioclinical_hybrid_patient` | 0.0000 | 0.0219 | 6/6 |

Cross-family comparisons describe end-to-end system behavior:
indexed text and retrieval components may differ. The most
controlled fine-tuning comparisons are within Jenny's frozen
versus fine-tuned encoder pairs.

## 3. Fine-tuning ablation

Jenny's handoff reports the same query construction, indexed
criterion fragments, pooling, normalization, similarity and RRF
configuration across each frozen/fine-tuned pair. Encoder weights
are the principal documented change.

The frozen model is BioClinical-ModernBERT-base without
retrieval-specific fine-tuning. The fine-tuned checkpoint was
trained on 5,137 query/criterion pairs; according to the handoff,
benchmark trials, queries, patients and Gold labels were excluded.

Reporting-set changes (fine-tuned minus frozen):

| Frozen -> Fine-tuned | Delta P@3 | Delta nDCG@5 |
|---|---:|---:|
| `bioclinical_dense_question` -> `finetuned_dense_question` | +0.3889 | +0.4394 |
| `bioclinical_dense_patient` -> `finetuned_dense_patient` | +0.0556 | +0.0703 |
| `bioclinical_hybrid_question` -> `finetuned_hybrid_question` | +0.3333 | +0.3751 |
| `bioclinical_hybrid_patient` -> `finetuned_hybrid_patient` | +0.0000 | +0.1302 |

The largest improvements occur for question-only retrieval.
Patient-aware fine-tuned variants remain substantially weaker
on this benchmark. These outcomes do not establish why
patient-aware query construction underperforms.

## 4. Per-query comparison

| Query | BM25 P@3 | Fine-tuned hybrid P@3 | BM25 nDCG@5 | Fine-tuned hybrid nDCG@5 |
|---|---:|---:|---:|---:|
| Q03 | 1.0000 | 1.0000 | 0.7739 | 0.6427 |
| Q04 | 0.6667 | 1.0000 | 0.7215 | 0.7520 |
| Q05 | 0.3333 | 0.3333 | 0.3179 | 0.1230 |
| Q06 | 0.3333 | 0.0000 | 0.4693 | 0.2021 |
| Q07 | 0.3333 | 0.3333 | 1.0000 | 1.0000 |
| Q08 | 0.3333 | 0.6667 | 0.6241 | 1.0000 |

Representative ranking evidence:

- **Q04 (diabetic kidney disease):** The fine-tuned hybrid
  retrieved grades [2, 1, 2] in the top three, versus BM25
  [2, 1, 0]. The gain is in identifying a directly relevant
  renal study within the top three.
- **Q08 (CGM and T2D self-management):** The fine-tuned hybrid
  ranked the two grade-2 trials at positions 1 and 2,
  achieving nDCG@5 = 1.0000. BM25 ranked those trials at
  positions 2 and 5.
- **Q06 (GLP-1 receptor agonists):** BM25 placed a grade-2
  trial first. The fine-tuned hybrid placed its grade-2
  result fourth, yielding zero relevant results in its top
  three. This is a clear top-rank regression.
- **Q05 (lifestyle interventions):** BM25 retrieved a grade-2
  trial at rank 4, while the fine-tuned hybrid returned no
  grade-2 trials in its top five.
- **Q03 (metabolic surgery):** Both methods achieved P@3 = 1,
  but BM25 retained more grade-2 results in the top five.

The fine-tuned hybrid improves nDCG@5 in Q04 and Q08,
ties in Q07, and trails BM25 in Q03, Q05 and Q06.
Its aggregate P@3 advantage corresponds to one additional
relevant result across the 18 reporting top-three positions.

## 5. Recommendation

Use **BM25 question-only** as the current retrieval default
for the fixed MS3 benchmark. Its reporting scores are
P@3 = 0.5000 and
nDCG@5 = 0.6511,
with zero zero-P@3 reporting queries.

Retain **fine-tuned hybrid question-only** as an experimental
candidate, with reporting P@3 = 0.5556
and nDCG@5 = 0.6200.
Investigate query-specific regressions and tune retrieval
without using Q03–Q08 reporting labels as a development set.

Do not use this benchmark alone to authorize clinical deployment.

## 6. Limitations and reproducibility

- Only six reporting queries and a fixed 50-trial universe.
- Pooled relevance judgments are incomplete for the full
  50-trial corpus, so full-corpus Recall@k is not estimated.
- nDCG uses the 182-label pooled Gold, not the full corpus.
  Historical scores from smaller Gold pools are not directly
  comparable to these updated scores.
- Grading is non-clinician and AI-assisted, not expert adjudicated.
- The synthetic patient reference date and historical trial
  snapshot differ; retrieval relevance is not eligibility.
- The sample is too small to support significance or
  generalization claims.
- Fine-tuned vs frozen comparisons follow Jenny's reported
  matched settings; the training and encoding provenance
  are documented in `runs_handoff.md` and
  `retrieval_runs.config.json`.

Evaluation code: `evaluate_retrieval_complete.py`.

Saved artifacts in `results/`:

- `ms3_retrieval_all14_per_query.csv`
- `ms3_retrieval_all14_summary.csv`
- `ms3_retrieval_finetune_deltas.csv`
- `ms3_retrieval_evaluation_manifest.json`

The scoring script uses write-once output protection:
existing result files must be preserved or moved aside
before a clean reproduction run.

**Gold SHA256:** `9a31a38eb1573b8cce81559763ef500aef2c2962b2c771cc3332231879344159`
**Jenny rankings SHA256:** `043561602395f71cee8966416aa67362da0cad96b9833ac8c1db6a758d8a8a3f`

This is an offline retrieval benchmark, not a clinical
decision-support performance validation.
