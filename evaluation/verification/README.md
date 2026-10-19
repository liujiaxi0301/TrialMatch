# Patient verification

This package accompanies the [patient-processing handoff](../../services/patient_processing/MS2_HANDOFF.md). The user confirmed that the TF separately requested verification as part of this personal work. Trial ingestion, RAG/API, shared infrastructure, UI and final team submission have separate owners.

## Results and reading order

| Evidence | Canonical record |
| --- | --- |
| V2: two selected synthetic patients, one trial, ten user-confirmed offline references; eight model/reference agreements and two evidence-rule differences | [Completed reference review](v2/results/reference_review_completed.md), [model-output report and limitations](v2/results/two_case_pilot_summary.md) |
| Grounding: UNKNOWN without a supplied code mapping, MET with the mapping; 9/9 and 15/15 structured citations resolve | [Paired grounding report](grounding/results/paired_grounding_report.md), [protocol](grounding/README.md) |
| V1: six recovered A/B responses, three trials, one patient; review paused at 22/30 confirmations | [Recovery report](reconstruction_report.md), [historical rules](review_rules.md) |
| Missingness, deaths and candidate selection across the 25-patient cohort | [Coverage report](v2/coverage_report.md), [design revision](evaluation_design_v2.md) |
| Current reproducibility checks and file audit | [Check record](evidence/checks.json), [delivery audit](evidence/delivery_checks.json) |

V2 review was AI-assisted, non-blinded and by a non-clinician after model outputs were available. Its ten labels are **3 MET, 1 NOT_MET, 6 UNKNOWN**; the two differences concern the reproductive-status evidence rule. These counts are not clinical accuracy. UNKNOWN does not clear an exclusion or establish eligibility.

The hypothetical assessment date is 2021-11-30; actual screening, consent and V1 dates remain unknown. The trial snapshot is dated 2026-10-11 and NOT_YET_RECRUITING. These observations do not establish recruitment availability, clinical eligibility or system-wide performance. Model-reported inherited context remains documented in V2P01 and the grounding positive control; user-reported search/memory settings do not prove isolation.

## Files and procedures

- [V2 file guide](v2/README.md) and the single [run procedure](v2/RUN_FIRST.md) describe fixed inputs, settings and reference-review separation. The ZIP packages that same procedure and the two complete inputs.
- Current labels are in [v2/templates/reference_answers.csv](v2/templates/reference_answers.csv). Keep one [frozen completion snapshot](v2/results/reference_answers_confirmed_20261018.csv); later policy or label changes need a new review version.
- V1 reconstructed inputs/protocols are distinguished from original run provenance in [manifest.json](manifest.json) and [recovery_manifest.json](recovery_manifest.json). Original upload bytes and prompt wording were unavailable. V01B matches only nine of ten source clauses. V04-V06 were prepared but never run.
- V1's [policy snapshot](results/policy_v1_snapshot/snapshot_manifest.json) preserves its separate strict-date policy and 22 confirmations. Do not transfer these labels into v2.
- [Provenance](LANGUAGE_AND_PROVENANCE.md) and [delivery_revision.json](delivery_revision.json) explain transformations, retained snapshots and removal of redundant copies. Exact pre-revision bytes are backed up outside the repository; those backups are not required to run the delivered checks.

Generation-time statuses in `cases.csv`, proposal files and preparation manifests are historical. Live run/review state is in `results/` and the current reference table. Original responses and settings remain under each experiment's `results/raw/` and `results/records/`; model exports must not be edited as reference labels.

## Reproduce the checks

Run from the repository root; no model calls are made:

```bash
python evaluation/verification/build_cases.py --check
python evaluation/verification/analyze_cohort.py --check
python evaluation/verification/build_v2.py --check
python -m unittest discover -s evaluation/verification/tests -v
```

The builders verify source hashes, complete criteria, fixed inputs, reference identities and evidence IDs. They preserve edited references and refuse to replace changed fixed inputs. The current [logs](evidence/) contain one log per check, with exit codes and hashes in [checks.json](evidence/checks.json).

## Record a separate future response

Follow the experiment's protocol and preserve actual settings; leave unverified settings UNKNOWN. Do not rerun merely to remove a disagreement or upload reference answers to the model.

```bash
python evaluation/verification/record_v2.py \
  --pair V2P01 --response /absolute/path/to/response.txt \
  --model 'Actual model name' --model-version 'Actual version' \
  --interface 'Actual interface' --search-enabled FALSE --context-isolation UNKNOWN
```

For historical v1 formats use `record_run.py`; `--import-recovered` imports preserved responses idempotently. Recorders retain errors, invalid JSON and incomplete responses; identical imports do not create another run. Grounding uses its [separate procedure](grounding/README.md).

## Handoff

The two-case reference review and grounding response/source review are recorded with their limitations. Publication to the personal `feat/patient-processing` branch was authorized on 2026-10-19. Team `milestone2` integration, consuming-owner acceptance, shared integration evidence and presentation preparation remain tracked in the [patient handoff](../../services/patient_processing/MS2_HANDOFF.md#remaining-actions). No larger sample, clinical expert review or v2 Mode B requirement is established by the supplied rubric/feedback. No team merge or team message has been performed.
