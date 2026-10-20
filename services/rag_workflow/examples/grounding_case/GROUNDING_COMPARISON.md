# Grounding case: Claude, raw Gemini and the RAG judgment layer

Recorded case: October 19, 2026. Patient `SYNTHETIC_001`; fixed trial `NCT02390973`; 14 criteria. Inputs: [source statements](source_case.json) and [normalized fixture](patient.json).

## What is being compared

| Output | Procedure | Evidence record |
|---|---|---|
| Claude baseline | Original shared conversation assesses the supplied patient and all 14 criteria; closed-context instructions were already present. | [claude_baseline.json](claude_baseline.json), [source conversation](https://claude.ai/share/2450b3ad-ebee-4f78-afa2-ca455eee2485) |
| Raw Gemini | Initial live `gemini-3.1-flash-lite` proposals before the original guards, with the full small fixture supplied to every criterion. | The `same_captured_model_response_replay.results[].same_gemini_proposal` fields in [guard_revision_verification.json](guard_revision_verification.json); initial focus responses in [live_verification.json](live_verification.json). |
| Revised RAG judgment layer | Production evidence rules, Gemini where needed, citation validation and guards, followed by aggregation. Full fixture context and the fixed trial are supplied explicitly. | `criterion_comparison` and `fixed_trial_after` in [guard_revision_verification.json](guard_revision_verification.json). |

**This is a fixed-trial judgment comparison, not a retrieval comparison.** It bypasses Chroma candidate selection and patient-context retrieval to hold the small case context available. The revised RAG layer includes deterministic rules; it is not a third standalone model.

The initial Gemini proposals are preserved for comparison. Replaying the same proposals through revised guards produced the same eight definite decisions as the revised live fixed-trial run. Thus the guard comparison does not rely only on a different favorable model sample. Not every revised live criterion made a new Gemini call: supported evidence checks ran first.

## All 14 decisions

IDs below have prefix `NCT02390973_`. MET means the named condition is present/satisfied; an **exclusion MET is a barrier**, whereas exclusion NOT_MET is favorable.

| Criterion suffix | Claude | Raw Gemini (initial run) | Revised RAG judgment layer |
|---|---|---|---|
| `inc_001` | MET | MET | MET |
| `inc_002` | MET | MET | MET |
| `inc_003` | MET | MET | MET |
| `inc_004` | MET | MET | MET |
| `exc_001` | NOT_MET | NOT_MET | NOT_MET |
| `exc_002` | NOT_MET | NOT_MET | NOT_MET |
| `exc_003` | UNKNOWN | UNKNOWN | UNKNOWN |
| `exc_004` | NOT_MET | NOT_MET | NOT_MET |
| `exc_005` | NOT_MET | NOT_MET | UNKNOWN |
| `exc_006` | UNKNOWN | UNKNOWN | UNKNOWN |
| `exc_007` | MET | MET | UNKNOWN |
| `exc_008` | UNKNOWN | UNKNOWN | UNKNOWN |
| `exc_009` | NOT_MET | NOT_MET | NOT_MET |
| `exc_010` | NOT_MET | NOT_MET | UNKNOWN |

| Summary | Claude | Raw Gemini | Revised RAG judgment layer |
|---|---|---|---|
| MET / NOT_MET / UNKNOWN | 5 / 6 / 3 | 5 / 6 / 3 | 4 / 4 / 6 |
| Confirmed exclusion barriers | 1 (`exc_007`) | 1 (`exc_007` proposal) | 0 confirmed; information remains missing |
| Overall result | NOT_ELIGIBLE in baseline | No separately recorded raw aggregate; `exc_007` would be a barrier under the same aggregation rule | NEEDS_MORE_INFORMATION |
| Recorded match score | Not reported | Not reported | 57.1 = 8 favorable / 14 total × 100 |

The five MET decisions in the baseline include four inclusions and one exclusion. Do not summarize them as five favorable matches. A change from NOT_ELIGIBLE to NEEDS_MORE_INFORMATION does not establish eligibility.

## Why three decisions differ

| Criterion | Supplied evidence | Claude / raw Gemini | Revised RAG result and reason |
|---|---|---|---|
| `exc_005`: pre-operative hypoalbuminemia | Serum albumin is 4.0 g/dL; no source range or pre-operative date. | NOT_MET, inferring normality. | UNKNOWN: a source-provided reference range/interpretation and pre-operative timing are insufficient. No built-in normal range is used. |
| `exc_007`: corticosteroid in the last month | Oral prednisone for asthma two weeks ago; no drug-class mapping. | MET, classifying prednisone as a corticosteroid. | UNKNOWN: the actual time check passes (2026-09-27 inside 2026-09-11 through 2026-10-11), but `MEDICATION_CLASS_NOT_SUPPLIED`. |
| `exc_010`: gastrointestinal inflammatory disease history | No known inflammatory bowel disease. | NOT_MET. | UNKNOWN: the narrower negative history does not cover the complete broader category. |

These checks enforce the declared closed-context evidence policy. They are not proof that the models searched the web, and do not assert that a pharmacological statement is medically false. In particular, missing an allowed classification source is different from failing the time window.

## Limits and relationship to the end-to-end demo

- This is one synthetic sanity-test case, not clinical gold truth or an accuracy benchmark. The Claude model/version was not available in the shared record; prompts, packaging and interfaces differ.
- Source labs are undated; the fixture reference date `2026-10-11` is a test anchor. No albumin range, prednisone class mapping or new clinical facts were inserted.
- No web-search tool was configured for this Gemini provider, but pretrained knowledge can still influence model output. The guards check selected supported evidence patterns, not all possible clinical reasoning.
- Ordinary top-three retrieval selected `NCT04284943`, `NCT03827382`, `NCT03821636`, not the fixed trial. Its result is PARTIAL because a citation-validation error remains. Do not treat the fixed-trial comparison as a successful full retrieval run.
- See [END_TO_END_DEMONSTRATION.md](END_TO_END_DEMONSTRATION.md) for the actual retrieved candidate and [GUARD_REVISION.md](GUARD_REVISION.md) for old/new guard behavior.

To reproduce both layers using the existing service-account configuration and matching index:

```bash
uv run --project services/rag_workflow --locked \
  --env-file services/rag_workflow/.env \
  python -m services.rag_workflow.verify_grounding --live \
  --output-dir artifacts/rag_workflow/grounding_case_comparison_replay
```

This can make billed model requests or reuse caches. It does not rerun Claude. It exits 1 if the ordinary workflow remains PARTIAL; offline execution does not establish model grounding.
