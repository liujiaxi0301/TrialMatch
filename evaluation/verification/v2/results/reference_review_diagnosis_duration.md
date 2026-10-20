# Documented T2D history: reference confirmation

Confirmed on 2026-10-18 by the user, a non-clinician, after model outputs and AI suggestions were available. This was not blinded or independent clinical review.

**English translation of the user's confirmation:**

> I confirm both diagnosis-record dates; under the documented-history prescreening rule, both inc_001 labels are MET, retaining the limitation that the true first-ever diagnosis dates are unproven.

Both decisions concern NCT06774950_inc_001: `Patients with newly diagnosed type 2 diabetes (less than 10 years)`.

Use the earliest retained exact-coded T2D Condition (SNOMED CT 44054006) recorded_date, or onset_date only if recorded_date is missing. Both records have recorded_date. MET here applies only to this predeclared documented-history surrogate, not proof that the real enrollment clause is satisfied.

| Pair | Condition source_resource_id | Recorded date | assessment_date | Documented duration | Confirmed label |
| --- | --- | --- | --- | --- | --- |
| V2P01 | 0f2e975a-ba64-1b75-a602-7d9436c7fb47 | 2017-12-11 | 2021-11-30 | 1450 days, under ten years | MET |
| V2P02 | 35e47ee0-a817-3fe3-29a4-f195dbe54b67 | 2019-10-18 | 2021-11-30 | 774 days, under ten years | MET |

See conditions in [V2P01](../uploads/A/V2P01.json) and [V2P02](../uploads/A/V2P02.json). Full fact IDs, reasons and reviewer provenance are in the [reference table](../templates/reference_answers.csv).

The earliest retained record is not proof of the true first-ever diagnosis date. Missing earlier history is not evidence that diabetes was absent. Real study dates and enrollment eligibility remain unknown. Progress at this step was 4/10; see the [completed review](reference_review_completed.md) for final 10/10 state. No additional model call, policy change or clinical accuracy estimate was made.
