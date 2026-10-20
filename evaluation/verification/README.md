# Patient verification

**Presentation route:** [patient extraction](../../services/patient_processing/README.md) → [25-patient coverage](v2/coverage_report.md) → [completed two-case review](v2/results/reference_review_completed.md) → [grounding pair](grounding/results/paired_grounding_report.md).

This is the TF-requested personal verification package. It prepares supplied-context experiments, preserves manually obtained answers/settings, and checks source evidence. Model calls are not made by the builders or recorders. Shared retrieval, scoring, API, UI and container integration remain with their owners. This personal branch supplies the patient-facts contract and supplied-context verification evidence.

## Current results and limits

| Experiment | Evidence | Interpretation |
| --- | --- | --- |
| V2: Cleveland (43) and Anthony (27), one trial, five clauses each | [Completed review](v2/results/reference_review_completed.md), [ten-row comparison](v2/results/reference_model_comparison.csv) | Ten user-confirmed references: 3 MET, 1 NOT_MET, 6 UNKNOWN; eight model agreements and two reproductive-status evidence-rule differences |
| Grounding: same patient/clause, mapping absent versus supplied | [Paired report](grounding/results/paired_grounding_report.md), [prompt/procedure](grounding/README.md) | UNKNOWN / insufficient information without mapping; MET with mapping; 9/9 and 15/15 structured citations resolve |

V2 review was AI-assisted, non-blinded and by a non-clinician after outputs were visible. Its diagnosis-duration rule uses documented history, not proven first-ever diagnosis. Actual screening/consent/V1 dates remain unknown; assessment_date 2021-11-30 is hypothetical. The 2026-10-11 trial snapshot is NOT_YET_RECRUITING. V2P01 and the grounding positive control report inherited-context caveats. The grounding report retains a minor reference-comparison wording issue. These observations establish neither clinical accuracy/eligibility nor clean isolation or system-wide grounding.

## File map

| Files | Role |
| --- | --- |
| `analyze_cohort.py`, `build_v2.py` | Check descriptive coverage, complete source clauses, fixed inputs and editable reference identities |
| `record_v2.py`, `common.py` | Preserve actual raw answers/settings and validate structure, dates, fact IDs and inclusion/exclusion polarity |
| `v2/policy.json`, `v2/prompt_A.md`, [RUN_FIRST.md](v2/RUN_FIRST.md) | Fixed scenario, evidence rules, actual prompt and manual procedure |
| `v2/uploads/A/`, `v2/manual_upload_kit.zip` | Two complete patient/criterion inputs; no reference labels in the upload kit |
| `v2/proposals/`, coverage JSON/CSV/manifests | Fixed source snapshots and historical selection/coverage state; generated statuses are not live progress |
| [Current references](v2/templates/reference_answers.csv), [frozen snapshot](v2/results/reference_answers_confirmed_20261018.csv), original suggestions | Human decisions, completion freeze and pre-review suggestions remain separate |
| `v2/results/raw/`, `v2/results/records/`, result CSVs | Original model answers, settings and derived model exports; never edit exports as reference labels |
| `grounding/uploads/`, prompt, manifests and `results/` | Controlled inputs, original outputs/settings and source review; preparation zero-run fields are historical |
| `evidence/`, `tests/`, [manifest.json](manifest.json) | Current check logs, ten active tool tests, archive/source hashes and cleanup provenance |
| [History ZIP](history/ms2_pre_cleanup_20261020.zip), `check_history.py` | Exact pre-cleanup snapshot and isolated historical reproduction |

## Reproduce the checks

From the repository root, using the [patient module uv environment](../../services/patient_processing/README.md#run-from-the-repository-root):

```bash
uv run --project services/patient_processing --locked python evaluation/verification/analyze_cohort.py --check
uv run --project services/patient_processing --locked python evaluation/verification/build_v2.py --check
uv run --project services/patient_processing --locked python -m unittest discover -s evaluation/verification/tests -v
uv run --project services/patient_processing --locked python evaluation/verification/check_history.py --run-checks
```

The first three commands check current materials and ten active tests. The last verifies the snapshot, reconstructs a temporary historical checkout, and runs its three checks plus all fifteen original verification tests. No model/cloud calls are made and no historical files are restored into the working tree. Current [checks](evidence/checks.json) and [layout audit](evidence/delivery_checks.json) distinguish these counts.

## History and provenance

The [archive](history/ms2_pre_cleanup_20261020.zip) contains all **155 patient/verification files exactly as published on the original personal branch at commit `9d49329c0b88d1d4d887465fff06f7ca2a2908c2`**, including V1 inputs/code/tests, six recovered A/B answers, original/current hash records, five full confirmation notes and the former handoff. `SNAPSHOT.json` lists every member hash plus the three external trial-source hashes required for replay. Current inputs, patient facts, model labels and user references are unchanged by this cleanup.

V1 remains historical: one patient against three trials, six recovered responses, 22/30 active reference clauses confirmed (21 UNKNOWN, 1 MET); V04-V06 were prepared but unrun. Original prompt/upload bytes were unavailable; V01B aligns only nine of ten source clauses. Historical policies must not be silently applied to V2. Earlier translation/original-byte provenance and external-backup references remain in the archived delivery revision; the ZIP preserves integrated delivery copies, not a new claim of verbatim original attachments.

For manual inspection outside the working tree:

```bash
python -m zipfile -e evaluation/verification/history/ms2_pre_cleanup_20261020.zip /tmp/trialmatch-ms2-history
```

The extracted `evaluation/verification/` contains original V1 prompts, raw responses and per-step review notes. Current manifests explicitly separate active source hashes from archived ones. Do not add new references or rerun models simply to remove disagreements.

## Record a separately authorized future run

Follow [RUN_FIRST.md](v2/RUN_FIRST.md), preserve actual settings and record unknown settings as UNKNOWN. Upload no reference answers or review notes.

```bash
uv run --project services/patient_processing --locked python evaluation/verification/record_v2.py \
  --pair V2P01 --response /absolute/path/to/response.txt \
  --model 'Actual model name' --model-version 'Actual version' \
  --interface 'Actual interface' --search-enabled FALSE --context-isolation UNKNOWN
```

Run IDs cannot replace different existing bytes/settings. Failed or incomplete outputs remain visible. No clinical expert reference, larger benchmark, repeated-run study or V2 Mode B result is claimed.
