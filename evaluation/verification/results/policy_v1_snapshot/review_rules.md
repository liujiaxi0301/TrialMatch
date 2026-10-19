> Historical v1 policy snapshot, rendered for delivery. Original bytes are preserved outside the repository.

# Historical v1 review rules

V1 review is **paused at 22/30** confirmed source clauses (21 UNKNOWN, 1 MET). These historical rules do not define v2 references. See the [revised design](../../evaluation_design_v2.md) and [completed v2 review](../../v2/results/reference_review_completed.md).

The historical decisions and tables are retained in the v1 policy snapshot. [Revision provenance](../../LANGUAGE_AND_PROVENANCE.md) distinguishes original bytes from delivery copies. The reference table retains criterion-level decisions, evidence, reviewer and confirmation provenance; unconfirmed rows remain unconfirmed.

## Actual trial dates

The user confirmed on 2026-10-18 that actual screening, consent and V1 dates remain unknown. Patient `reference_date = 2021-11-30` is a data cutoff and stored-age anchor, not a study date. A clause dependent on an unknown study date remains UNKNOWN when other evidence cannot resolve it. Preserve known subfacts without claiming the complete compound clause is met.

Under this strict v1 rule, V01 age at consent remains UNKNOWN despite known age 43 at reference_date. Historical model decisions and reasoning are retained; any presentation-only conversion is recorded in the delivery revision. V2 subsequently introduced a separate explicit offline assessment date; do not silently substitute that policy into v1.

## Diagnosis coding

The user confirmed V02 inc_002 MET: SNOMED CT `http://snomed.info/sct` code `44054006` supports the diagnosis-only T2D requirement. The source display Diabetes does not override the exact code. This does not establish a duration before unknown consent or exclude other diabetes types; V01 exc_002 remains UNKNOWN.

## Measurements and time

Preserve dates, values and units. Cleveland's latest HbA1c is 5.62%, BMI 28.49 kg/m2 and blood pressure 117/80 mmHg, all dated 2020-12-28. The user confirmed V01 inc_003, inc_004 and exc_001 UNKNOWN because trial-relevant measurements or the actual screening timepoint are unavailable. Do not invent a 30/90-day recency threshold absent from the source. Unit conversions require a verifiable basis.

## Medication evidence

The user confirmed V01 inc_002 UNKNOWN. Orders, dispensing, administrations and statements are distinct. A prescription alone does not prove actual use, adherence, stable dose or a required duration. List drug types, dose, duration and missing evidence separately for compound requirements.

## Missing evidence and logical polarity

No record is not explicit absence. Exclusion MET means it applies; NOT_MET requires support that it does not apply. For an AND clause, a supported false component can establish NOT_MET; known true components with necessary unknown components remain UNKNOWN. For an OR clause, one supported true branch can establish MET. Do not mechanically label every compound clause UNKNOWN merely because some branches are unknown.

V01 severe hematological/hemolysis history is insufficient. For V01 exc_004, the historical user confirmation says obesity and metabolic syndrome do not trigger that clause, but other endocrine history is insufficient to clear the complete exclusion.

## Confirmed scope

| Pair | Confirmed clauses | Labels | Retained limitations |
| --- | --- | --- | --- |
| V01 | All 10 | 10 UNKNOWN | Unknown consent/screening dates, historical measurements, incomplete actual-use and relevant history |
| V02 | All 10 | 1 MET, 9 UNKNOWN | T2D diagnosis-only MET; age timepoint, medications, consent, comorbidity severity and liver/kidney evidence remain unresolved |
| V03 | inc_001 and inc_004 | 2 UNKNOWN | Trial consent/activity chronology and diagnosis duration before unknown consent |

V01's four-week infection/trauma/surgery window and the longer of 12 weeks or five half-lives for other trial participation cannot be assessed without dates/history. V02's insulin, three-drug count, TZD/GLP-1, prior Chiglitazar, severe comorbidity and AST/ALT/eGFR exclusions remain UNKNOWN under the documented evidence gaps. Missing willingness is not refusal; missing treatment history is not never-use.

The remaining eight V03 clauses are not confirmed. The current English table preserves all 60 prepared rows, including the 30 active V01-V03 source clauses; V04-V06 remain preparation only. Do not calculate v2 performance from v1 labels or represent these decisions as expert clinical validation.
