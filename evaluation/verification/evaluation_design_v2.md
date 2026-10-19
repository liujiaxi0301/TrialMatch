# Design revision: traceable offline patient prescreening

## Current status

Both Mode A responses and all **10/10 user-confirmed reference labels** are recorded: 3 MET, 1 NOT_MET, 6 UNKNOWN. Eight model labels agree with the references; two reproductive-status labels differ under the accepted evidence rule. This was AI-assisted, non-blinded review by a non-clinician, not a clinical accuracy benchmark. See the [completed review](v2/results/reference_review_completed.md) and [two-case report](v2/results/two_case_pilot_summary.md).

V1 remains paused at 22/30 confirmed clauses (21 UNKNOWN, 1 MET). Its responses, strict-date decisions and snapshot are preserved. Do not revise historical results silently or transfer v1 labels into v2.

## Why the first design needed revision

1. Ordinary synthetic records do not complete study workflow. Consent, willingness, treatment decisions and the order of study activities require study-specific evidence; missing workflow data does not automatically imply clinical ineligibility.
2. Unknown real trial dates should not hide known facts. Birth dates and documented diagnoses remain useful, even when age at an actual unknown consent date cannot be confirmed. Separate an explicit offline assessment from final enrollment checks.
3. Medication evidence is limited. The 25-person cohort has no gliflozin display-name matches. Six patients have insulin orders, but no insulin match appears in administrations, dispensing or statements. Four patients have some administration record; that is not proof of long-term basal insulin use. Display-name scans are not comprehensive drug-code classification.
4. Dates and sampling limit conclusions. The original Cleveland cases use older clinical events, a 2021-11-30 cutoff and 2026 trial snapshots. V01-V03 reuse one patient against three trials and do not form a representative benchmark.
5. Repeated confirmation of UNKNOWN is not method validation. The original model outputs were not produced under this revised protocol. New rules cannot be applied retrospectively without documenting a separate experiment and scope.

## Output contract

Keep every complete source criterion, its ID and its compound logic. Separate:

| Evidence or task | Offline output | Retained limitation |
| --- | --- | --- |
| Documented facts | Diagnoses, birth date, measurements and their fact IDs | Fact presence alone does not establish a complete criterion |
| Requirements assessable at a stated date | Age and supported time calculations at assessment_date | This date does not substitute for actual screening, consent or V1 |
| Missing clinical evidence | List required measurements, severity or actual medication evidence | Do not invent recency thresholds or infer use from orders |
| Study workflow | Keep consent, capacity and investigator follow-up explicit | Do not delete source clauses or turn missing workflow into automatic exclusion |

For example, a T2D diagnosis can be documented while a formal requirement for one year before an unknown consent date remains unresolved. Any duration calculated at a hypothetical assessment date is a separate preliminary observation.

Report supported, conflicting and unresolved criteria with correct inclusion/exclusion polarity. UNKNOWN counts are not enrollment probabilities. Do not issue a final enrollment decision.

## Date and diagnosis rules

- The user selected **assessment_date = 2021-11-30** for offline replay.
- `reference_date` remains the source cutoff. Their equal values in this scenario do not make either an actual study date.
- Actual screening, consent and V1 dates remain null.
- Newer trial criteria are intentionally applied to older synthetic data as a method exercise. Recruitment at the assessment date or now is not established.
- Use the earliest retained exact-coded T2D Condition `recorded_date`; use `onset_date` only if recorded_date is missing. This is a documented-history surrogate, not proof of the true first-ever diagnosis date. The two inc_001 MET references are limited to this stated surrogate rule.

## Evidence-based case selection and completed review

The [coverage audit](v2/coverage_report.md) examined all 25 processed patients. Two recorded deaths before the cutoff were excluded from clinical demonstrations; the other 23 were not automatically declared alive. Cleveland (43) and Anthony (27) were selected against the five complete criteria of NCT06774950 to cover age support, age conflict and unresolved evidence. Ages avoid the source's ambiguous boundary wording.

Anthony has a recorded T2D neuropathy Condition. Severity and applicability to the broad exclusion still require clinical assessment. Both reproductive-status references remain UNKNOWN under the user-confirmed rule that administrative gender alone is insufficient. Both consent-capacity references remain UNKNOWN because missing signatures do not establish incapacity.

All confirmations occurred after model outputs were available. Preserve that limitation, the original suggestions and the two reproductive-status disagreements. Future policy changes require a separate version and explanation; no clinical expert validation, randomized sample, repeatability study or v2 Mode B experiment has been completed.

## Ownership

The patient extractor remains unchanged and can be reused. This revision concerns the user's verification materials and patient-facts handoff. Trial ingestion, RAG/API logic, shared containers and UI remain with their owners; this package does not implement those changes or establish integration acceptance.
