# Completed v2 reference review

Completed on 2026-10-18: two selected synthetic patients, one trial NCT06774950, five complete source clauses per patient and one Mode A response each.

The user confirmed **10/10 offline references: 3 MET, 1 NOT_MET, 6 UNKNOWN**. Review was AI-assisted, non-blinded and by a non-clinician after model outputs were available. These references are not an independent clinical gold standard.

## Clause-level comparison

| Source clause | V2P01 reference | V2P01 model | V2P02 reference | V2P02 model |
| --- | --- | --- | --- | --- |
| inc_001: documented T2D history under ten years | MET | MET | MET | MET |
| inc_002: age 40-65 | MET | MET | NOT_MET | NOT_MET |
| exc_001: significant comorbidities/severity/investigator judgment | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| exc_002: pregnant or breast-feeding women | UNKNOWN | NOT_MET | UNKNOWN | NOT_MET |
| exc_003: inability to give signed informed consent | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

**Eight labels agree and two differ**, with four agreements and one difference per patient. Both differences concern reproductive status: the model used administrative gender male, while the user-confirmed reference rule requires more direct evidence and retains UNKNOWN. These are evidence-rule disagreements, not independently established clinical errors. This agreement count is not clinical accuracy or a generalization estimate.

## Confirmation evidence and retained limits

The user confirmed all five topics on 2026-10-18, after model outputs and AI suggestions were available. The quotations below are English translations of those confirmations. The complete original delivery notes, source tables and prior completion manifest are preserved byte-for-byte in the [pre-cleanup snapshot](../../history/ms2_pre_cleanup_20261020.zip) under `evaluation/verification/v2/results/`.

### Age

> I checked the birth dates and assessment date and confirm age MET for V2P01 and NOT_MET for V2P02.

### Documented diagnosis history

> I confirm both diagnosis-record dates; under the documented-history prescreening rule, both inc_001 labels are MET, retaining the limitation that the true first-ever diagnosis dates are unproven.

### Comorbidity exclusion

> I confirm both exc_001 labels as UNKNOWN; Anthony has recorded neuropathy, but severity and whether it triggers exclusion still require clinical assessment.

### Reproductive status

> I confirm both exc_002 labels as UNKNOWN: this review does not infer reproductive status from administrative gender alone.

### Consent capacity

> I confirm both exc_003 labels as UNKNOWN: consent-capacity assessment is missing; absence of a signed document does not imply inability to sign.

Age evidence gives 43/27 at assessment_date 2021-11-30, avoiding ambiguous interval endpoints. Diagnosis recorded dates are 2017-12-11 and 2019-10-18: 1450/774 days under the documented-history surrogate. True first-ever diagnosis remains unproven. Anthony has SNOMED 368581000119106 neuropathy; severity and exclusion applicability remain unresolved. Administrative gender alone does not establish reproductive status; missing signatures do not establish incapacity. Full source fact IDs and reasoning remain in the reference table.

Actual screening, consent and V1 dates remain unknown. The 2026-10-11 trial snapshot is NOT_YET_RECRUITING. Under the references, Cleveland has two supported inclusion requirements and three unresolved exclusions; Anthony has one supported inclusion, one age conflict and three unresolved exclusions. UNKNOWN is not exclusion clearance or final eligibility.

## Canonical result files

- [Current reference table](../templates/reference_answers.csv), one [frozen completion snapshot](reference_answers_confirmed_20261018.csv), and unchanged [original suggestions](../templates/reference_suggestions.csv).
- [Ten model/reference comparisons](reference_model_comparison.csv) and [current/archived source hashes](reference_review_completed.json).
- Original [responses](raw/A/) and [settings/validation records](records/), with model-reported inherited context retained for V2P01. User-reported Claude Opus 5.5/new-chat/search-off/memory-off settings are not independent tool traces.
- [Current reference check](../../evidence/v2_input_check.txt), [active tool tests](../../evidence/verification_tests.txt), and [delivery audit](../../evidence/delivery_checks.json).

All ten complete source clauses and 23/8 distinct cited fact IDs previously passed structural/source checks; those checks do not validate every clinical inference. The archived `review_V2P01_A.md`, `review_V2P02_A.md` and `two_case_pilot_summary.md` preserve the full prior source reviews and model-run report. Original model answers and reference decisions were not changed. Future policy/label changes require a new review version and preservation of this completion snapshot. No extra model run, clinical expert review or clinical accuracy estimate was created by consolidation.
