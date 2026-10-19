# Shared Claude case: grounding verification

**Updated evidence checks:** see [GUARD_REVISION.md](GUARD_REVISION.md) for the rerun: 8 known / 6 UNKNOWN, 4/4 inclusion controls MET, and 67 automated tests passing. The normal RAG run remains PARTIAL. The sections below preserve the initial run for comparison.

**Initial result, October 19, 2026:** three selected grounding checks passed after evidence guards, but coverage was poor and the normal RAG run was `PARTIAL`. This is not a complete end-to-end pass or evidence that Gemini is intrinsically more grounded than Claude.

Source: [shared Claude sanity-test conversation](https://claude.ai/share/2450b3ad-ebee-4f78-afa2-ca455eee2485). This is a user-supplied synthetic patient, not a real patient or one of the 25 Synthea records. The shared baseline already requested closed-context reasoning. Its output is a comparison baseline, not gold truth.

## Inputs and normalization

The case uses patient `SYNTHETIC_001` and the 14 source criteria for `NCT02390973`, already present in the existing trial dataset and 50-trial index. Parts 1/2 data, source hashes, index identity and the cohort manifest were not modified.

- Preserve the original quantities, statements and "no known history" qualifiers.
- The required `reference_date=2026-10-11` is an explicitly chosen test anchor, not a date from the patient record.
- Laboratory measurements remain undated. No albumin reference range or normality flag is added.
- Prednisone remains the documented medication name; no corticosteroid-class mapping, absolute administration date or duration is added.
- Adapter fact IDs, resource types and lab-code annotations make the record compatible with schema 0.3. Each fact links to a source statement. Undocumented conditions are not encoded as false diagnoses.

Expectations were written before live execution. The three focus checks adopt a strict closed-context policy: missing albumin interpretation/timing, an unsupplied drug-class mapping and a narrower negative disease history should not yield definite decisions. These are technical verification expectations, not independently clinically validated labels.

## Layer A: fixed-trial judgment, full fixture context

This layer uses the production `numeric_rule`, `judge_batch`, evidence guards and aggregation functions, but supplies the complete small fixture to every criterion, as the original Claude baseline did. It deliberately bypasses patient-context retrieval to isolate judgment behavior. It is not a Chroma retrieval test.

Real GCP execution used `gemini-3.1-flash-lite`: three generation requests, 26,385 prompt tokens, 1,368 output tokens and no cache hits for this layer.

| Focus criterion | Claude baseline | Gemini before guard | After guard | Interpretation |
|---|---|---|---|---|
| `exc_005`: pre-operative hypoalbuminemia | NOT_MET | NOT_MET | UNKNOWN | The model inferred that 4.0 g/dL excludes the condition without a supplied range/interpretation or pre-operative timing. The explicit-negative-evidence guard rejected the conclusion. |
| `exc_007`: corticosteroid in the last month | MET | MET | UNKNOWN | The model treated the prednisone statement as satisfying this criterion. A drug-class mapping was not provided under the declared policy; the existing temporal/numeric guard rejected the definite judgment. |
| `exc_010`: gastrointestinal inflammatory disease history | NOT_MET | NOT_MET | UNKNOWN | "No known inflammatory bowel disease" did not establish absence of the broader category. The explicit-negative-evidence guard rejected the conclusion. |

All identifiers above use the `NCT02390973_` prefix. The raw model judgments still reproduced the three disputed Claude decisions; the protection came from deterministic validation after generation. The checks do not demonstrate a specialized albumin classifier or drug-class verifier.

All 14 judgments were processed without a model/schema failure in this layer. Only the type-2-diabetes inclusion criterion remained definite: **1 MET, 13 UNKNOWN; 1/4 positive inclusion controls retained; score 7.1; NEEDS_MORE_INFORMATION**.

Over-abstention is a material limitation. BMI, the glucose/HbA1c OR criterion and explicit consent evidence were downgraded by broad numerical/composite/consent guards. Explicit negative-history statements were also downgraded by a text-based guard. More UNKNOWN results must not be presented as higher accuracy.

| Criterion | Claude baseline | Gemini raw | Guarded result |
|---|---|---|---|
| inc_001 | MET | MET | UNKNOWN |
| inc_002 | MET | MET | MET |
| inc_003 | MET | MET | UNKNOWN |
| inc_004 | MET | MET | UNKNOWN |
| exc_001 | NOT_MET | NOT_MET | UNKNOWN |
| exc_002 | NOT_MET | NOT_MET | UNKNOWN |
| exc_003 | UNKNOWN | UNKNOWN | UNKNOWN |
| exc_004 | NOT_MET | NOT_MET | UNKNOWN |
| exc_005 | NOT_MET | NOT_MET | UNKNOWN |
| exc_006 | UNKNOWN | UNKNOWN | UNKNOWN |
| exc_007 | MET | MET | UNKNOWN |
| exc_008 | UNKNOWN | UNKNOWN | UNKNOWN |
| exc_009 | NOT_MET | NOT_MET | UNKNOWN |
| exc_010 | NOT_MET | NOT_MET | UNKNOWN |

## Layer B: ordinary 50-trial RAG

The normalized patient was passed to the unmodified `ScreeningWorkflow.screen` interface with a general English question and `top_k=3`:

> Which clinical trials may suit this patient? Explain supporting evidence, screening barriers, and what remains unknown, using only the supplied trial criteria and patient record.

Production patient-profile construction, hybrid BM25/vector retrieval, context selection, rules, model calls, evidence validation and explanation generation were used.

| Returned trial | Known / total | Score | Screening status |
|---|---|---|---|
| NCT04284943 | 0 / 20 | 0.0 | NEEDS_MORE_INFORMATION |
| NCT03827382 | 1 / 10 | 10.0 | NEEDS_MORE_INFORMATION |
| NCT03821636 | 1 / 11 | 9.1 | NEEDS_MORE_INFORMATION |

The benchmark trial `NCT02390973` ranked **17th of 50**, so it was not evaluated in this top-three response. This diagnosis reused the cached query embedding and made no additional model calls. The general multi-trial question differs from the original fixed-trial prompt; absence from the top three alone does not establish clinically incorrect retrieval. It does mean this end-to-end response cannot be used to claim that the original trial's grounding case passed through normal retrieval.

The overall response was **PARTIAL**. In one six-item batch, Gemini cited `F1` for `NCT04284943_exc_014`, although that criterion's selected context contained only `F0`. The same invalid local alias appeared after the one permitted repair. Per-criterion allowlists rejected the batch, leaving `exc_010` through `exc_015` UNKNOWN with `INVALID_LLM_OUTPUT`. The cited consent information existed elsewhere in the fixture/batch, but was not a valid local evidence alias for this criterion; do not describe this merely as malformed JSON or necessarily an invented patient fact.

This layer made one query-embedding request and 12 generation requests, including repairs/explanations; provider metrics reported 31,079 prompt tokens and 6,389 output tokens. The original Chroma collection was reused rather than rebuilt. No model calls are made by the automated unit tests.

## Files and rerunning

| File | Purpose |
|---|---|
| `source_case.json` | Source link, original patient statements and normalization caveats |
| `patient.json` | Separate normalized synthetic fixture for `--patient-file` or the Python workflow |
| `claude_baseline.json` | Original supplied decisions and disputed reasoning; explicitly not gold labels |
| `expectations.json` | Predeclared focused checks and positive controls |
| `live_verification.json` | Compact actual live results, raw disputed model responses, metrics, diagnostics and artifact paths |
| `../../verify_grounding.py` | Reproducible fixed-trial and full-RAG runner; defaults to offline |
| `../../tests/test_grounding_case.py` | Five automated regressions; no GCP calls |

From the repository root, run only the new automated checks:

```bash
uv run --project services/rag_workflow --locked \
  python -m unittest services.rag_workflow.tests.test_grounding_case -v
```

Run the actual live workflow using the existing configured service account and index:

```bash
uv run --project services/rag_workflow --locked \
  --env-file services/rag_workflow/.env \
  python -m services.rag_workflow.verify_grounding --live \
  --output-dir artifacts/rag_workflow/grounding_case_replay
```

The default output directory is `artifacts/rag_workflow/grounding_case`. Using another directory preserves the first run. Caches may avoid new requests on replay; inspect metrics. The recorded run exits with code 1 because the full response is PARTIAL, despite passing the three guarded focus checks. Without `--live`, the runner is offline and does not establish LLM grounding.

Inspect these first-run artifacts in VS Code:

- `artifacts/rag_workflow/grounding_case/fixed_trial_response.json`: final decisions, evidence and coverage.
- `artifacts/rag_workflow/grounding_case/fixed_trial_model_trace.json`: exact model inputs and raw proposals before aliases/guards are applied.
- `artifacts/rag_workflow/grounding_case/full_rag_response.json`: actual ordinary RAG response and errors.
- `artifacts/rag_workflow/grounding_case/retrieval_trace.json`: patient query, selected criteria, all candidate judgments and cited patient facts.
- `artifacts/rag_workflow/grounding_case/retrieval_diagnostics.json`: rank-17 finding and cached invalid-alias attempts.

## What this establishes for MS2

This adds the mentor's concrete Claude failure case to verification and provides an auditable live comparison. It demonstrates evidence guards catching unsupported certainty and per-criterion citation errors. It also documents conservative false abstentions and an incomplete ordinary retrieval run.

It does not establish overall clinical accuracy, RAG superiority over Claude, a fully passing end-to-end example for the target trial or a solution to all hallucinations. Improving supported numeric/OR/consent handling, retrieval/context coverage and isolating invalid judgments within a batch remain follow-up work. A separate clean end-to-end example may still be needed for the milestone presentation.

All 47 automated tests and Ruff passed after adding this case. A pre-existing malformed translation loop in `retrieve.tokens` was also removed so English retrieval runs again. Production scoring, evidence-guard policies, cohort data and trial data were not changed to make the case pass.
