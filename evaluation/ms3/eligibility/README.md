# TrialMatch MS3 — Eligibility Evaluation

## 1. Purpose and Scope

This module evaluates TrialMatch's existing criterion-level eligibility
assessment pipeline on fixed synthetic patient–trial pairs.

It measures how consistently the system assigns:

- `MET`: The criterion is satisfied.
- `NOT_MET`: The criterion is not satisfied.
- `UNKNOWN`: Available evidence is insufficient for a definitive judgment.

For exclusion criteria, `MET` means the exclusion condition is present.
It does not mean that the patient is eligible for the trial.

This benchmark evaluates eligibility judgments, not trial retrieval.
Patient–trial pairs are fixed, so retrieval rankings cannot change the
evaluation cohort.

The results are exploratory engineering evidence, not clinical validation
or patient enrollment recommendations.

## 2. Frozen Benchmark

| Item | Value |
| --- | --- |
| Cases | E01–E08 |
| Patient–trial pairs | 8 |
| Total criteria | 115 |
| Gold MET | 16 |
| Gold NOT_MET | 17 |
| Gold UNKNOWN | 82 |
| Patient reference date | 2021-11-30 |
| Trial snapshot date | 2026-10-11 |
| Evaluation split | `all` |

Criteria per case: E01=22, E02=8, E03=23, E04=8,
E05=10, E06=15, E07=15, E08=14.

The benchmark uses purposively selected Synthea patient records and
historical ClinicalTrials.gov trial snapshots.

The current CLI treats all eight cases as a single exploratory evaluation
set. E01–E02 were previously used during development and inspection, so
the eight-case result must not be described as an independent held-out
test evaluation.

### Benchmark files

| Path | Purpose |
| --- | --- |
| `eligibility_protocol.md` | Annotation conventions and evidence rules |
| `eligibility_cases.jsonl` | Fixed patient–trial pairs |
| `cohort_manifest.json` | Source provenance and SHA256 checks |
| `reviewed_labels/E*.json` | Frozen reference judgments |
| `source_facts/E*.jsonl` | Patient evidence snapshots for audit |
| `trial_sources/E*.json` | Trial source snapshots |
| `review_packets/E*.md` | Human annotation review materials |

Gold annotations were prepared independently of baseline predictions.
One documented pre-evaluation correction changed E08 exc_001 from
NOT_MET to UNKNOWN to conform to the benchmark protocol.

The reviewed labels contain supporting fact identifiers, reasons,
missing-information fields, and review notes.

These are non-clinician reference annotations. Some labels depend on
explicit synthetic-data conventions or human interpretation of ambiguous
trial language.

## 3. System Under Evaluation

The evaluator reuses the existing TrialMatch implementation:

1. `evidence_rule()` applies deterministic rules where supported.
2. `ContextSelector` selects patient facts for unresolved criteria.
3. `judge_batch()` invokes the configured model.
4. `evidence_guard` checks evidence support and may downgrade a
   definitive prediction to UNKNOWN.
5. The evaluation harness compares saved predictions with frozen gold
   decisions and computes metrics.

The evaluation runner is:

`evaluation/ms3/eligibility/run_eligibility.py`

The production inference components are under:

`services/rag_workflow/`

The runner bypasses trial retrieval but preserves the existing
criterion-judgment path.

Predictions are written to disk before gold labels are loaded for scoring.
The evaluator does not modify gold-label files.

## 4. Reproducing the Evaluation

Run commands from the repository root.

Prerequisites:

- Python environment resolved by the repository's `uv.lock`
- Processed patient, trial, and criterion data matching the cohort manifest
- Frozen benchmark files and original evaluation implementation
- Gemini credentials only when executing new online inference

### A. Re-score the saved baseline (no model call)

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
  evaluation/ms3/eligibility/run_eligibility.py score \
  --predictions \
  evaluation/ms3/eligibility/results/all_developer_baseline_predictions.jsonl
```

This verifies saved prediction integrity, source checksums, case alignment,
code/protocol hashes, valid evidence identifiers, and scoring outputs.

It does not call Gemini.

The score command writes or refreshes the corresponding metrics JSON and
disagreements CSV. It does not rewrite the predictions or gold labels.

The evaluator intentionally rejects predictions when its recorded
pipeline/protocol hashes do not match the current files. Reproducing a
historical run may therefore require the original code revision rather
than an updated integrated branch.

### B. Run an offline, rule-only check

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
  evaluation/ms3/eligibility/run_eligibility.py run \
  --split all --provider offline --tag offline_check
```

This exercises the rule and data paths without a model call.
Criteria requiring LLM interpretation become UNKNOWN.

Offline results are not official model-evaluation results.

### C. Run a new Gemini Developer API evaluation

Set `GEMINI_API_KEY` privately in the shell environment.

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
  evaluation/ms3/eligibility/run_eligibility.py run \
  --split all --provider developer --tag new_run
```

A new tag prevents accidental replacement of the saved baseline.
Do not use `--overwrite` unless replacement is intentional.

The model identifier, provider, inference configuration, source hashes,
code hashes, and prediction checksum are recorded in run metadata.

Vertex AI is also supported through `--provider vertex`, provided
the appropriate Google Cloud configuration and permissions are available.

The current CLI accepts `--split all` only. Older examples referring
to `dev` or `reporting` do not apply to the current frozen cases.

## 5. Baseline Artifacts and Results

The completed baseline is identified by:

`all_developer_baseline`

| Output | Contents |
| --- | --- |
| `results/all_developer_baseline_predictions.jsonl` | 115 criterion predictions |
| `results/all_developer_baseline_metadata.json` | Model, configuration, hashes, provenance |
| `results/all_developer_baseline_metrics.json` | Metrics and case-level breakdowns |
| `results/all_developer_baseline_disagreements.csv` | Incorrect predictions and inference failures |

The final baseline contains zero inference failures. Twelve transient
GCP_429 failures from an earlier run were retried, and the recovered
predictions replaced those failed outputs. The previously successful
103 predictions were preserved.

### Criterion-level results

| Metric | Result |
| --- | ---: |
| Total evaluated criteria | 115 |
| Accuracy | 0.78261 |
| Macro-F1 | 0.54956 |
| Inference failures | 0 |
| Correct definite gold judgments | 8 / 33 |
| Gold definite predicted UNKNOWN | 25 |
| Opposite definite judgments | 0 |

Confusion matrix (gold rows, prediction columns):

| Gold \ Predicted | MET | NOT_MET | UNKNOWN |
| --- | ---: | ---: | ---: |
| MET | 4 | 0 | 12 |
| NOT_MET | 0 | 4 | 13 |
| UNKNOWN | 0 | 0 | 82 |

Overall accuracy is strongly influenced by the high prevalence of
UNKNOWN gold labels (82/115). Therefore, accuracy alone overstates
the system's ability to resolve definitive eligibility criteria.

### Error analysis

There were 25 gold-definite criteria predicted as UNKNOWN.

- 18 were downgraded by the Evidence Guard.
- 7 were output as UNKNOWN by the model itself.
- Among the 18 guard downgrades, 15 original model judgments agreed
  with gold, while 3 disagreed with gold.
- All gold supporting fact IDs entered the model context for 15 of
  these 25 cases; partial coverage occurred in 4, and no coverage in 6.

These observations identify evidence selection and post-generation
validation as important areas for investigation.

Presence of a gold fact ID in the model context does not automatically
establish that the fact clinically supports the gold judgment.

The absence of opposite definitive judgments in this small benchmark
must not be interpreted as proof of clinical safety.

## 6. Automated Tests

Tests are in:

`evaluation/ms3/eligibility/tests/test_evaluation.py`

Run from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --locked python \
  -m unittest discover \
  -s evaluation/ms3/eligibility/tests \
  -p 'test_*.py' -v
```

Eight automated tests passed in the verified local run.

They cover:

- Frozen case and label counts
- Metric correctness on synthetic inputs
- Trial-level status aggregation
- Gold-loader isolation during the tested inference path
- Reproduction of saved baseline metrics
- Detection of tampered prediction files
- Rejection of duplicate criterion predictions
- Handling of inference failures separately from valid UNKNOWN outputs

Tests do not require new Gemini calls.

## 7. Integration Contract

The evaluation module provides two operations:

- `run`: execute fixed-pair eligibility inference and score the outputs.
- `score`: validate and score an existing prediction artifact.

Inputs include fixed patient–trial cases, compatible processed data,
saved predictions (for scoring), metadata, and frozen gold labels.

Machine-readable outputs include:

- Predictions JSONL
- Metadata JSON
- Metrics JSON
- Disagreements CSV

The scoring operation can be invoked by a higher-level orchestration
workflow after prediction artifacts are available.

This repository module does not by itself demonstrate an executed
Vertex AI eligibility-evaluation pipeline. Cloud orchestration and
deployment are separate team integration responsibilities.

## 8. Limitations and Reproducibility

- Only eight synthetic patient–trial pairs are evaluated.
- The cases are purposively selected rather than randomly sampled.
- Criteria within the same trial are correlated.
- The gold judgments were not independently adjudicated by clinicians.
- E01–E02 were inspected during development.
- Some reference judgments use synthetic-data annotation conventions.
- Citation IDs are checked for validity against patient facts, but
  clinical evidentiary sufficiency is not automatically established.
- The patient reference date and trial snapshot date differ.
- Gemini model behavior can vary across runs and provider configurations.
- Existing results are tied to recorded input and code hashes.

No additional model performance or deployed-system monitoring claims
should be inferred from this offline benchmark.
