# Two-case offline prescreening report

The two user-submitted Mode A responses are preserved unchanged. Each received complete patient facts and all five source clauses of NCT06774950. Assessment_date is the approved hypothetical 2021-11-30; actual screening, consent and V1 dates remain null.

The user reported the same settings for both: Claude Opus 5.5, separate new conversations, search off and memory off. Specific client and independent tool traces are unverified. V2P01 reports possible inherited context; interface settings alone do not prove isolation.

## Original model outputs

| Clause | V2P01 Cleveland | V2P02 Anthony | Checked fact or limitation |
| --- | --- | --- | --- |
| Documented T2D history under ten years | MET | MET | 1450 and 774 days under the supplied surrogate rule, not proof of true first diagnosis |
| Age 40-65 | MET | NOT_MET | 43 and 27 at assessment_date |
| Significant comorbidities/investigator judgment | UNKNOWN | UNKNOWN | Anthony has neuropathy; severity remains unknown |
| Reproductive-status exclusion | NOT_MET | NOT_MET | Both model answers use administrative gender male |
| Consent-capacity exclusion | UNKNOWN | UNKNOWN | Missing signatures are distinguished from inability to consent |

V2P01's model labels are 2 MET, 1 NOT_MET, 2 UNKNOWN: three supported clauses, zero conflicts, two unresolved. V2P02's are 1 MET, 2 NOT_MET, 2 UNKNOWN: two supported clauses, one conflict, two unresolved. Exclusion NOT_MET means non-trigger under the model's reasoning, not a negative inclusion result.

## Completed reference comparison

All **10/10** references were user-confirmed on 2026-10-18: 3 MET, 1 NOT_MET, 6 UNKNOWN. Review was AI-assisted, non-blinded and by a non-clinician. Five confirmation records and source links are in the [completed review](reference_review_completed.md).

**Eight model/reference labels agree and two differ**, four agreements per patient. Both differences are reproductive-status clauses: model NOT_MET versus reference UNKNOWN under the accepted rule that administrative gender alone is insufficient. Report these as evidence-rule disagreements, not independently established clinical errors. See the [ten-row comparison](reference_model_comparison.csv).

Under the reference rules Cleveland has two supported inclusions and three unresolved exclusions. Anthony has one supported inclusion, one age conflict and three unresolved exclusions. This does not establish eligibility for either patient.

## What the evidence supports

- All ten complete source clauses and 23/8 distinct evidence fact IDs passed structural/source checks; cited key dates and numerical values were checked against source facts.
- The answers distinguish opposing age conditions at an explicit date and identify missing clinical/workflow evidence.
- Anthony's neuropathy is a substantive follow-up item: diagnosis is present, but severity and investigator judgment remain unresolved.

## Limits

Two selected synthetic patients, one trial and one response per patient do not establish general performance. There was no random sampling, repeated-run study, clinical expert reference or v2 Mode B test. Reference completion does not resolve clinical unknowns. Agreement is not clinical accuracy or proof of system superiority.

The source trial snapshot is from 2026-10-11 and NOT_YET_RECRUITING; the patient records are older. This exercise tests offline reasoning only, not historical or current recruitment. No reference rule or original answer was silently changed to improve or worsen agreement.

## Delivery follow-up

Use this completed report for the personal verification handoff and TF explanation. Publication, shared container-run evidence and consuming-owner acceptance remain separate delivery actions. Retrieval/API/UI implementation remains with its owners. Any later retrieval or Mode B experiment needs its own protocol and run records.
