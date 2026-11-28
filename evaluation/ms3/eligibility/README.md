# Eligibility evaluation

Evaluate criterion judgments on eight fixed synthetic patient–trial pairs,
independently of retrieval. `MET` means a criterion is true, `NOT_MET` false,
and `UNKNOWN` unresolved. For an exclusion criterion, MET is a barrier.
These are engineering reference judgments, not clinical validation.

## Frozen inputs

| File | Purpose |
| --- | --- |
| `eligibility_cases.jsonl` | E01–E08: 115 criteria across eight patient–trial pairs. |
| `cohort_manifest.json` | Source identities and SHA256 checks. |
| [eligibility_protocol.md](eligibility_protocol.md) | Annotation rules and evidence conventions. |
| `reviewed_labels/E*.json` | Non-clinician reference judgments, reasons and fact IDs. |
| `source_facts/E*.jsonl`, `trial_sources/E*.json` | Complete source snapshots for review. |
| `prepare_cases.py`, `prepare_review_packets.py` | Case selection and source-only annotation preparation. |

Case preparation writes to `artifacts/eligibility-cohort/` by default. It records
the current label-file hash; the original committed manifest remains unchanged.

Gold counts: 16 MET, 17 NOT_MET, 82 UNKNOWN. Cases have 22, 8, 23, 8, 10, 15, 15
and 14 criteria respectively. Patient reference date: November 30, 2021;
trial snapshot: October 11, 2026. Labels were prepared independently of baseline
predictions. E08 exc_001 was corrected from NOT_MET to UNKNOWN before evaluation.

The current CLI accepts only `--split all`. E01–E02 were inspected during
development, so the combined result is not an independent held-out test.
Cases are purposive, criteria within a trial are correlated, and some judgments
depend on synthetic-data conventions. No clinician adjudicated the labels.

## Inference and scoring

`run_eligibility.py` loads each fixed pair, applies deterministic rules, selects
facts for unresolved criteria, calls the configured model and validates its evidence.
Invalid support can downgrade a definite answer to UNKNOWN. Predictions are saved
before gold labels are loaded; the evaluator never changes reference labels.

Run from the repository root with the locked root uv environment and matching
processed inputs. Re-score the saved baseline without a model call:

```bash
uv run --locked python evaluation/ms3/eligibility/run_eligibility.py score \
  --predictions evaluation/ms3/eligibility/results/all_developer_baseline_predictions.jsonl
```

Scoring checks source/code/protocol hashes, case alignment, prediction integrity
and evidence IDs. It refreshes metrics JSON and disagreements CSV, not predictions
or labels. A historical artifact with different code hashes requires its original
revision; do not bypass that check.

For new inference, choose a new tag to keep the baseline intact:

```bash
uv run --locked python evaluation/ms3/eligibility/run_eligibility.py run \
  --split all --provider offline --tag offline_check
```

Offline mode tests the rules and data paths; unresolved model-dependent criteria
become UNKNOWN. For online evaluation, choose `--provider developer` with a private
`GEMINI_API_KEY`, or `--provider vertex` with the project's Google credentials.
`--model` overrides the model identifier. New metadata records provider/configuration,
source/code hashes and prediction checksum. `--overwrite` explicitly replaces a tag.

## Saved baseline

`results/all_developer_baseline_*` contains predictions, metadata, metrics and
disagreements. Twelve transient GCP_429 failures were retried; the final artifact
has zero inference failures and preserves the other 103 predictions.

| Metric | Value |
| --- | ---: |
| Criteria | 115 |
| Accuracy | 0.78261 |
| Macro-F1 | 0.54956 |
| Correct definite judgments | 8 / 33 |
| Gold-definite criteria predicted UNKNOWN | 25 |
| Opposite definite judgments | 0 |

| Gold / prediction | MET | NOT_MET | UNKNOWN |
| --- | ---: | ---: | ---: |
| MET | 4 | 0 | 12 |
| NOT_MET | 0 | 4 | 13 |
| UNKNOWN | 0 | 0 | 82 |

Accuracy is dominated by the 82 UNKNOWN reference labels. Of the 25 missed definite
judgments, 18 were downgraded by the evidence guard and seven were model UNKNOWNs.
Fifteen of those 18 original model judgments agreed with gold; three did not.
Gold supporting fact IDs were fully present in model context for 15 of the 25
cases, partially for four and absent for six. This motivates examining evidence
selection and validation, not removing the guard indiscriminately. A matching
fact ID alone does not establish clinical support, and zero opposite definite
judgments here does not prove safety.

## Tests and annotation preparation

```bash
uv run --locked python -m pytest --import-mode=importlib evaluation/ms3/eligibility/tests
uv run --locked python -m evaluation.ms3.eligibility.prepare_review_packets
```

Tests cover counts, metrics, trial-status aggregation, gold-label isolation,
baseline reproduction, tampering, duplicate predictions and inference failures.
They require no model calls. The packet command writes source-only review pages,
source snapshots and blank templates under ignored `artifacts/eligibility-review/`;
`--output-dir` selects another destination. It does not overwrite frozen labels.

Cloud orchestration is described in the [workflow guide](../../../cloud/README.md).
Evaluation quality, successful API requests and production availability are
separate measures; this benchmark does not establish the latter two.
