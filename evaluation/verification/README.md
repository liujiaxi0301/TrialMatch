# Verification recovery and remaining work

**TF-requested personal verification (user confirmation, 2026-10-18):** the user confirmed that verification was separately requested by the TF, so this package is included with the patient-processing delivery. This additional requirement is user-reported, not attributed to the general MS2 rubric. Trial ingestion, RAG/API rules, shared containers, UI and final team submission are owned separately; this package records evidence/findings without modifying those implementations. See the patient's [MS2 handoff](../../services/patient_processing/MS2_HANDOFF.md) and [repeatable checks](evidence/checks.json). Original answers, human decisions and fixed inputs remain unchanged. Recovery-time branch/commit notes below describe that earlier snapshot; no remote push or merge has been performed.

**V2 progress:** the user selected assessment_date **2021-11-30** for offline preliminary screening. Actual screening/consent/V1 dates remain unknown. V2P01 and V2P02 A responses are preserved; all ten source clauses and 23/8 distinct evidence IDs passed structural/source checks. The age prechecks correctly distinguish 43 from 27. Both runs are user-confirmed as Claude Opus 5.5, independent new conversations, search/memory off. Context caveats remain recorded. See [两例并排结果](v2/results/two_case_pilot_summary.md). All ten human-reference rows remain unconfirmed; no accuracy score has been computed.

**Methodology revision:** v1 review is paused at 22/30 confirmed clauses (21 UNKNOWN, 1 MET). The decisions and provenance are preserved in `results/policy_v1_snapshot/`. Do not use this table as validated clinical-prescreening performance evidence. See [修订验证方案](evaluation_design_v2.md): separate EHR-based prescreening from study-workflow confirmation and select cases based on evidence coverage. The v1 and v2 protocols and labels must not be mixed.

**Coverage analysis completed:** [25 人证据覆盖与下一轮建议](v2/coverage_report.md) and `v2/cohort_evidence_coverage.csv` describe the current cohort. Two recorded prior deaths are flagged; no death record does not establish that a patient is alive. The original case-proposal snapshot is in `v2/proposals/`; finalized scenario inputs using the user-selected date are in `v2/uploads/A/`. These are not confirmed gold labels. A separate candidate with omitted source text was rejected. Run `python evaluation/verification/analyze_cohort.py --check` to verify the generated coverage/proposal snapshot, and `python evaluation/verification/build_v2.py --check` for the finalized v2 test package.

Status checked on 2026-10-18. This is the reconstructed verification package, not the original verification README. See [重建检查结果](reconstruction_report.md) for the completed first step.

## Recovered evidence

The six original user-pasted responses for V01–V03 were downloaded from attachments in the prior chat (`01a13c1f-a2ff-7588-8756-99f437a7b0ec`). They are preserved byte-for-byte in `results/raw/A/` and `results/raw/B/`. `recovery_manifest.json` records attachment IDs, file hashes, sizes, and model-reported status counts. Recovery dates are not original run dates.

| Pair | Trial | Mode A model statuses | Mode B model statuses |
| --- | --- | --- | --- |
| V01 | NCT07156539 | 1 MET, 9 UNKNOWN | 1 MET, 9 UNKNOWN |
| V02 | NCT07580638 | 2 MET, 8 UNKNOWN | 1 MET, 9 UNKNOWN |
| V03 | NCT07658417 | 1 MET, 9 UNKNOWN | 1 MET, 9 UNKNOWN |

These are model outputs, not verified reference labels or accuracy measurements. All three pairs concern the same synthetic patient, Cleveland (`475803f3-ae29-ba8d-bdd1-25145a94eaee`). Mode A supplied criteria with search off; mode B supplied the trial ID with search on. The model and interface were reported by the user as Claude Opus 5.5 on Claude web; tool traces are not independently available.

Content alignment confirms missing retrieved text for V01B's sixth exclusion criterion: only 9 of its 10 entries match source clauses. The other five responses each match all 10 source clauses after whitespace/Markdown-escape normalization. T2D-code interpretation disputes in V02B/V03 still require human review. All three mode A responses report automatically supplied memory context; user-reported search-off settings do not establish strict context isolation. Parsing ten entries alone does not establish complete or correct criteria.

Patient/trial inputs, case lists, prompts, review tables and tools have been reconstructed from commit `9d6886a` and the recovered attachments. `manifest.json` records source, fixed-input and reconstructed-prompt hashes. Original upload bytes/hashes and original prompt wording are unavailable; matching cited fact IDs and source clauses does not establish full historical upload identity. The original reference CSV and review notes are also unavailable. V01 `exc_004 = UNKNOWN` is carried forward from the user's explicit historical confirmation, with evidence links rebuilt from the source conditions. On 2026-10-18 the user confirmed V02 `inc_002 = MET` based on SNOMED CT `44054006`, and V03 `inc_004 = UNKNOWN` because the actual consent date needed for its one-year duration requirement is unknown. The user also confirmed V01 `inc_002 = UNKNOWN`: prescriptions do not establish actual stable use. Human-reference progress is recorded in the editable reference table and review rules; see the completion checklist for current counts.

## Files and commands

- `inputs/patients/`: two complete processed patient records, revalidated against checked-in raw FHIR and the original processor. Their official-sample file hashes match `sample_source.json`.
- `inputs/trials/`: three complete trial records and their 30 source criteria. `trial_audit.json` checks full original-text coverage and agreement with the stored parser output. These are repository snapshots, not freshly fetched websites.
- `uploads/A/` and `uploads/B/`: six reconstructed pairs per mode; both modes use identical patient objects. Mode B includes no trial criteria. Only V01–V03 belong to this round.
- `templates/reference_answers.csv`: editable human-reference table. Filter `in_round1 = TRUE` for the 30 active source criteria. The other 30 rows are preparation only.
- `templates/reference_suggestions.csv`: 30 criterion-level review suggestions using the user-confirmed policy of leaving actual trial dates unknown. User-confirmed decisions are labeled explicitly; all other rows are unreviewed assistant suggestions. See [review rules](review_rules.md).
- `results/records/`: immutable per-run metadata and parsed results. `original_run_timestamp` and `original_upload_sha256` remain null when unknown; reconstructed hashes and recovery-recording times are labeled separately.
- `results/runs_A.csv`, `runs_B.csv`, `model_results_A.csv`, `model_results_B.csv`: derived exports. Do not edit these; exporting regenerates them.
- `results/error_review.csv`: editable per-response human error review, separate from source-reference judgments. See [error categories](error_taxonomy.md).
- `prompts/mode_A.md`, `prompts/mode_B.md`: reconstructed protocols for future runs. They were not applied retrospectively to historical responses.

From the repository root:

```bash
python evaluation/verification/build_cases.py --check
python -m unittest discover -s evaluation/verification/tests -v
```

`build_cases.py` without `--check` creates missing fixed files and the initial review template. It refuses to overwrite changed fixed files and preserves an existing human-reference table. `--check` checks sources, hashes, fixed input contents, reference keys and evidence links without writing.

Recovered-response imports are idempotent and do not call a model:

```bash
python evaluation/verification/record_run.py --import-recovered
```

For a **new** response, preserve the actual settings and give it a new run ID:

```bash
python evaluation/verification/record_run.py \
  --mode A --pair V01 --response /absolute/path/to/response.txt \
  --model 'Actual model name' --model-version 'Actual version' \
  --interface 'Actual interface' --search-enabled FALSE
```

The recorder preserves invalid JSON and incomplete/invalid responses as failed or warned runs rather than discarding or repairing them. It aligns clauses by normalized text and type, not web IDs or position. An unaligned clause can reflect retrieval failure or source drift and needs inspection. These structural checks do not verify clinical reasoning or compute scores. A new CLI run can record known settings; it cannot independently verify a remote model's tool trace.

## Ordered completion checklist

1. **Restore the verification package — completed.** Six original responses are recovered; inputs, provenance, case list, tables, prompts and tools are reconstructed and checked. Original upload byte identity remains unknown. Only V01–V03 are in this round; V04–V06 were prepared but not run.
2. **Write the review rules — in progress.** The user confirmed that actual consent/screening/V1 dates remain unknown; reference_date must not substitute for them. The coding, old-measurement, medication and missing-history rules and review suggestions are documented in `review_rules.md` and `templates/reference_suggestions.csv`. Separate proposed rules from user/team-confirmed rules. Exclusion MET means the exclusion applies.
3. **Policy v1 human review — paused at 22/30 confirmed.** The remaining 8 source criteria are not being confirmed until the evaluation design is revised. Existing decisions are preserved with their original policy and provenance. See `templates/reference_answers.csv` for the authoritative decisions and `review_rules.md` for their explanations.
4. **Finish the A/B comparison and first-round report.** Align criteria by content, record retrieval completeness separately from reasoning, and review evidence, time, numbers/units, negation, citations, medication evidence, and UNKNOWN handling. Score only reviewed reference rows and state the denominator. Report the one-patient/three-trial scope, all three mode A context limitations, unavailable original upload hashes, and the 2021 patient reference date versus 2026 trial snapshot. Do not claim current eligibility or superiority over general models.
5. **Confirm the patient-facts handoff with Jenny.** The module already has schema v0.3, examples, and 25 patient records. Confirm expected file, field names, fact IDs, reference-date handling, and missing/medication semantics with the consuming workflow. Run one integration example once that interface is known. Team acceptance is not established by local schema documentation.
6. **Prepare the repository handoff.** Review the diff, commit and push the agreed materials, and check/create the appropriate PR when requested. Patient processing is on remote `feat/patient-processing` at `9d6886a`; current remote `main` is `a206a35` and does not contain that commit. PR existence has not been checked. No commit, push, or merge was performed during this recovery.

## Patient module checks completed

The patient-processing feature branch was restored locally. All six existing unit tests pass. The checked-in sample contains four patient records; the first cohort contains 25 unique patients, all schema v0.3 at reference date 2021-11-30. The full-archive report records 555 patients and 32 adults with the exact T2D code. These count checks do not reproduce the full archive scan.
