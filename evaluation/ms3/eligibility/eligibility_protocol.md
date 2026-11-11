# TrialMatch MS3 — Eligibility Evaluation Protocol

## 1. Objective

Evaluate whether TrialMatch correctly assesses individual clinical-trial
eligibility criteria against documented synthetic patient evidence.

This is an exploratory technical pre-screening evaluation, not a clinical
determination of trial eligibility or an enrollment recommendation.

Retrieval relevance and eligibility satisfaction are separate tasks.

## 2. Frozen evaluation cohort

- Input: eligibility_cases.jsonl
- Provenance: cohort_manifest.json
- 8 purposively selected patient–trial pairs
- One evaluation cohort: E01–E08 (115 criteria)
- No development/held-out split for eligibility evaluation
- 115 criteria total: 32 inclusion, 83 exclusion
- 50-trial frozen corpus
- Patient reference date: 2021-11-30
- Trial snapshot date: 2026-10-11

Cases were selected using previously reviewed topical relevance grade 2,
not eligibility predictions.

The two dates do not represent contemporaneous clinical eligibility.
All assessments are retrospective and evidence-limited.

## 3. Evaluation units

Primary unit:
(patient_id, trial_id, criterion_id)

Secondary unit:
(patient_id, trial_id)

Evaluate fixed patient–trial pairs independently of retrieval rankings.
Do not allow retrieval to select or replace the trial during evaluation.

## 4. Reference-label rubric

MET:
Available patient evidence establishes that the complete criterion
statement is true.

NOT_MET:
Available patient evidence establishes that the complete criterion
statement is false.

UNKNOWN:
Available evidence cannot establish whether the complete statement
is true or false. Reasons may include missing, ambiguous,
contradictory, undated, outdated, or insufficiently specific facts.

These labels describe criterion satisfaction, not overall eligibility.

An inclusion criterion marked NOT_MET is a screening barrier.
An exclusion criterion marked MET is a screening barrier.

UNKNOWN must not be treated as MET, NOT_MET, or evidence of absence.

## 5. Evidence and interpretation rules

- Use only the frozen normalized patient record and trial criteria.
- Record supporting patient fact IDs for definite judgments.
- Preserve the original criterion text and criterion_id.
- Use patient_reference_date for age and temporal interpretation.
- Respect numerical thresholds, units, and measurement dates.
- Do not invent laboratory values, diagnoses, medication use,
  treatment stability, or clinical history.
- Medication orders or definitions alone do not prove administration,
  adherence, or stable treatment.
- Missing medical records do not establish absence of disease.
- Exclusion NOT_MET requires adequate affirmative negative evidence.
- Interpret AND/OR logic over the full criterion; do not judge only
  the convenient portion of a compound criterion.
- If cohort applicability, timing, units, or clinical interpretation
  remain unresolved, label UNKNOWN.
- Use external clinical knowledge only to understand terminology,
  not to invent missing patient evidence or trial requirements.
- Do not inspect model predictions while establishing gold labels.

For each reference judgment, record:
case_id, patient_id, trial_id, criterion_id, criterion_type,
criterion_text, gold_decision, reason, supporting_fact_ids,
missing_information, review_notes.

Reference labels are non-clinician evidence-based annotations.
Ambiguous clinical interpretations require explicit review notes
rather than unsupported certainty.

## Historical Snapshot Evaluation Rules

The evaluation assesses documented criterion satisfaction as of the
patient reference date (2021-11-30), not actual enrollment eligibility
at the later trial snapshot date (2026-10-11).

1. Explicit temporal windows must be respected. Historical evidence
   outside the required window cannot establish satisfaction.
2. If no time window is specified, use the latest valid measurement
   available on or before the patient reference date. Do not mark
   UNKNOWN solely because the measurement predates that date.
3. Explicit measurement conditions (e.g., seated office blood pressure)
   must be supported. A numeric value alone cannot establish that
   an unverified measurement condition was satisfied.
4. Missing evidence must not be interpreted as evidence of absence.
5. Conflicting results, incompatible units, or insufficient evidence
   for the full criterion should receive UNKNOWN.
6. All definite judgments refer only to the historical evidence
   available at the fixed patient reference date, not current health
   status or prospective clinical enrollment.

These rules apply consistently to inclusion and exclusion criteria.

## 6. Trial-level reference status

SCREENING_BARRIER:
At least one inclusion criterion is NOT_MET or one exclusion
criterion is MET.

POTENTIAL_MATCH_FOR_REVIEW:
All criteria have definite favorable decisions, with no barrier.

NEEDS_MORE_INFORMATION:
No confirmed barrier, but one or more criteria are UNKNOWN,
or the full screening assessment cannot be established.

Trial-level status is derived from criterion-level reference labels.
It is not an enrollment probability.

## 7. Model evaluation

Compare pipeline predictions against reference labels at matching
patient_id, trial_id, and criterion_id.

Report the full eight-case cohort and individual case results.

Primary criterion-level metrics:
- Three-class confusion matrix (MET, NOT_MET, UNKNOWN)
- Accuracy
- Per-class precision, recall, and F1
- Macro-F1 with class supports and undefined cases disclosed

Safety and abstention diagnostics:
- Gold UNKNOWN predicted as MET or NOT_MET
- Gold definite predicted as UNKNOWN
- Opposite definite judgments (MET versus NOT_MET)
- Evidence citation validity and factual support
- Reasons and missing-information quality

Secondary trial-level metrics:
- Screening-status agreement
- Confirmed barrier detection and missed barriers
- False potential-match classifications

Report results separately for inclusion and exclusion criteria
and, where available, by prediction method:
rule, llm, llm_abstain, abstain.

Show pooled criterion metrics and per-case results.
Criteria within a trial are not independent observations.

Do not silently drop missing predictions or failed runs.
Record errors, coverage, and their denominators explicitly.

## 8. Error-analysis categories

- Numerical threshold or unit error
- Incorrect temporal interpretation
- Unsupported inference from missing records
- Incorrect medication-state interpretation
- Compound or conditional logic error
- Incorrect criterion applicability
- Evidence selection or citation error
- Unnecessary abstention
- Unsupported definite judgment
- Aggregation or system failure

## 9. Experimental procedure

1. Freeze cohort and provenance.
2. Prepare source-only, prediction-blinded review packets.
3. Independently annotate criterion-level reference labels.
4. Audit ambiguous judgments and freeze the label file.
5. Run the fixed-pair eligibility evaluation harness.
6. Validate output completeness and evidence references.
7. Calculate metrics and perform error analysis.
8. Report limitations and reproducibility details.

The current implementation combines deterministic rules,
LLM judgments, and evidence guards.

Offline and live configurations must be reported separately.
Any access limitations or alternative LLM provider must be documented.

## 10. Limitations

- Small, purposively selected synthetic-data sample
- Non-clinician reference judgments
- Potential class imbalance, especially UNKNOWN
- Historical patient records versus later trial snapshot
- No clinical enrollment confirmation
- No claim of generalization to all trials or patients

This benchmark measures evidence-grounded technical screening,
not real-world clinical trial eligibility.

## Synthetic Pregnancy/Lactation-Only Criterion Convention

For this retrospective, non-clinical Synthea benchmark only, a synthetic patient recorded as male, irrespective of age, may be treated as NOT_MET for an exclusion mentioning
pregnancy, pregnancy risk, or lactation alone, where no other reproductive
planning condition is present. This is an explicitly agreed demographic
annotation proxy, NOT medical proof about an individual patient's anatomy
or pregnancy capacity, and MUST NOT be generalized to clinical decisions.
An explicit contrary source fact must be evaluated on its own merits.

Do not apply this proxy to broader OR criteria such as E01 exc_013 that
also ask whether the patient is planning to have a baby: that separate
question remains UNKNOWN without supporting information.

Positive type 2 diabetes evidence does not imply a documented absence of
type 1 diabetes. Follow the same negative-evidence rule as E01 exc_004.

