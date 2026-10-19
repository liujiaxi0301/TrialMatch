# V2 offline prescreening pilot

Two Mode A responses and ten user-confirmed offline references are preserved. Start with the [completed reference review](results/reference_review_completed.md) for decisions and five confirmation records, or the [model-output report](results/two_case_pilot_summary.md) for settings, source checks and limitations. Review was AI-assisted, non-blinded and by a non-clinician; the comparison is not clinical accuracy.

## Scenario and procedure

| Pair | Patient | Age at assessment | Purpose |
| --- | --- | ---: | --- |
| V2P01 | Cleveland | 43 | Supported age, documented T2D history and unresolved evidence |
| V2P02 | Anthony | 27 | Clear age conflict under the same trial and assessment rule |

The hypothetical assessment date is **2021-11-30**. Actual screening, consent and V1 dates remain null. NCT06774950 supplies five complete clauses; its 2026-10-11 snapshot is NOT_YET_RECRUITING. No historical or current recruitment availability is established.

Use [RUN_FIRST.md](RUN_FIRST.md) as the single run procedure. [manual_upload_kit.zip](manual_upload_kit.zip) packages that procedure, the prompt and both fixed inputs. Upload no reference tables or reviewer notes. The [policy](policy.json) defines date, diagnosis-history and missing-evidence rules; [recording instructions](../README.md#record-a-separate-future-response) apply to separately authorized future runs.

## File map

| Files | Role |
| --- | --- |
| `uploads/A/V2P01.json`, `uploads/A/V2P02.json` | Complete patient objects and all source criteria, without reference labels; ZIP-member fact IDs must not be replaced with v1 path-based IDs |
| [Current reference table](templates/reference_answers.csv) | Ten confirmed decisions, evidence, reasons and reviewer provenance |
| [Original suggestions](templates/reference_suggestions.csv) | Unreviewed preparation suggestions, unchanged by later confirmations |
| [Frozen reference snapshot](results/reference_answers_confirmed_20261018.csv) | One completion snapshot; any later policy/label change requires a new review version |
| [Comparison](results/reference_model_comparison.csv), [completion manifest](results/reference_review_completed.json) | Ten label comparisons and current source hashes |
| `results/raw/A/`, `results/records/` | Responses and recorded settings |
| `results/runs_A.csv`, `results/precheck_results_A.csv` | Derived model exports, never reference labels |
| `cases.csv`, `proposals/`, preparation/coverage manifests | Historical generation and selection state; live progress is in the current reference table and `results/` |

The mutable table and frozen snapshot currently match intentionally. V1's 22 historical confirmations remain separate. Revision provenance and removed-copy locations are in [delivery_revision.json](../delivery_revision.json).

## Check the delivery

From the repository root:

```bash
python evaluation/verification/build_v2.py --check
```

The builder validates fixed artifacts and mutable-reference identities/evidence without model calls or overwriting edited references. [All verification checks](../README.md#reproduce-the-checks) and their [current results](../evidence/checks.json) are documented once at the package entry point.
