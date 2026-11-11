# TrialMatch MS3 — Retrieval Benchmark Protocol

**Owner:** Jiaxi (evaluation)
**Collaborator:** Jenny (retrieval methods)  
**Purpose:** Compare how well retrieval methods rank trials relevant to a search request. **This does not evaluate patient eligibility** (`MET` / `NOT_MET` / `UNKNOWN` is assessed separately).

## 1. Fixed benchmark

- **Code/data:** `milestone2` commit `f2fedbd` and its `demo_manifest.json` checksums.
- **Queries:** `evaluation/ms3/retrieval_queries.jsonl` — Q01–Q08, each with `query_id`, `patient_id`, `question`.
- **Search universe:** Only the **50 trial IDs** in `services/rag_workflow/examples/demo_manifest.json` (not all 1,313 trials).
- **Patient source:** `services/patient_processing/data/processed/batch25_patients.jsonl`.
- **Shared input:** Each method uses the same question and patient record, starting from the existing `patient_query(patient, question)` representation in `retrieve.py`. Query rewriting may add legitimate synonyms, **not invented patient facts**.
- **Split:** Q01–Q02 for development/interface checks; Q03–Q08 for final comparison. Freeze method configurations before inspecting test-set scores; report both groups separately.

## 2. Methods and output (Jenny → Jiaxi)

Compare **BM25**, existing **BM25 + Gemini embedding hybrid**, and Jenny's new rewriting/embedding variants. Return **up to 5 distinct trial IDs**, ranked best to worst, per query and method, as `evaluation/ms3/retrieval_runs.jsonl`:

```json
{"query_id":"Q01","method":"rewrite_hybrid_v1","ranked_trial_ids":["NCT03264352","NCT03549754","NCT04880005"]}
```

*IDs above only illustrate the format.* Every returned ID must be in the fixed 50-trial corpus. Do not invent missing results; record failed runs separately. Include brief method notes: code commit, embedding/rewrite model and settings, indexed text/chunking, ranking/fusion settings, and cache use. **No full screening/LLM response is needed.**

**Fair comparison:** Keep inputs and trial universe fixed. Existing BM25 searches trial titles/conditions/summaries/criteria, while the semantic index uses criterion fragments; therefore BM25 vs existing hybrid is a **system comparison**, not proof that embeddings alone caused any difference. To isolate rewriting or embeddings, keep other components as constant as possible and document changes.

## 3. Reference labels (Jiaxi)

Manually review each **`(query_id, trial_id)`** against trial titles, summaries, conditions, and relevant criteria; judge **topic/query relevance, not whether this patient qualifies**.

| Grade | Meaning |
|---|---|
| **2** | Directly addresses the query's main topic or target population |
| **1** | Clearly related but only partially matches the query |
| **0** | No substantive match; generic T2D overlap alone is insufficient |

Save `evaluation/ms3/retrieval_labels.csv` with:

`query_id,trial_id,relevance,reason,source_reference`

**Labeling workflow:** Pool and deduplicate top-5 results from BM25, existing hybrid (if available), and Jenny's methods. Review candidates preferably without knowing which method retrieved them. If a new method returns an unjudged trial, label it **before** scoring; **never treat missing labels as grade 0**. Freeze labels and method versions for the final report. The pool is not an exhaustive judgment of all 50 trials.

## 4. Metrics and deliverables

- **Precision@3:** Share of top 3 results graded **1 or 2** (denominator 3; unreturned ranks contribute zero).
- **nDCG@5:** Ranking quality using grades **0/1/2**, gain `2^grade - 1`, and the ideal ordering of the **judged pooled candidates** for that query. Report if no relevant candidate was judged.
- Calculate per-query scores and separate Q01–Q02 development vs Q03–Q08 test averages. Flag missing labels rather than scoring them. Include 2–3 concrete ranking/error examples. Do **not** claim full-corpus Recall@K, statistical significance, or clinical accuracy.

**Handoff:** Jiaxi shares this protocol + eight queries now → Jenny returns ranked IDs and configurations → Jiaxi completes/reviews pooled labels, runs automated scoring, and produces CSV/JSON metrics + a short comparison report. Jiaxi will also develop the **separate eligibility benchmark** and provide a local evaluation command for later pipeline integration.

**Limits:** Only eight queries, synthetic patients (reference date 2021-11-30), and a historical trial snapshot (2026-10-11). Results are exploratory engineering evidence, not clinical recommendations.