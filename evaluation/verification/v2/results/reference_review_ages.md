# Age-reference confirmation

Confirmed on 2026-10-18 by the user, a non-clinician, after seeing model outputs and AI suggestions. This was not blinded or independent clinical review.

**English translation of the user's confirmation:**

> I checked the birth dates and assessment date and confirm age MET for V2P01 and NOT_MET for V2P02.

Both decisions concern NCT06774950_inc_002: `Age (between 40 and 65)`.

| Pair | Birth date | Offline assessment_date | Age | Confirmed label |
| --- | --- | --- | --- | --- |
| V2P01 | 1977-12-05 | 2021-11-30 | 43 | MET |
| V2P02 | 1994-08-12 | 2021-11-30 | 27 | NOT_MET |

Evidence is `patient.demographics` in [V2P01](../uploads/A/V2P01.json) and [V2P02](../uploads/A/V2P02.json), with full fact IDs in the [reference table](../templates/reference_answers.csv). Count completed birthdays at the assessment date. Neither age tests whether 40 or 65 is included in the source interval.

Actual screening, consent and V1 dates remain unknown. This confirms an offline age precheck, not actual enrollment age or eligibility. At this step progress was 2/10; later confirmations completed [10/10](reference_review_completed.md). Stage logs are retained in the external pre-cleanup backup.
