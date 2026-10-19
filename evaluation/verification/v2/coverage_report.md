# Evidence coverage of the 25-patient cohort

This is a descriptive coverage audit and case-selection record. Original `coverage_manifest.json` and `proposals/` retain preparation-stage metadata, including an unset assessment date. Subsequently the user selected 2021-11-30 and completed a separate ten-clause v2 review; see the [current results](results/reference_review_completed.md). No patient fact or source date was changed.

## Recorded coverage

| Item | Patients | Interpretation |
| --- | ---: | --- |
| Exact T2D code | 25/25 | Selection rule, not a random patient population |
| HbA1c / BMI / blood pressure | 25 / 25 / 25 | Preserve values/dates; not necessarily screening measurements |
| eGFR | 24/25 | Specified LOINC codes only |
| AST / ALT | 5 / 5 | Units, upper limits and relevant dates still needed |
| At least one prescription | 25/25 | Does not establish actual use, stability or adherence |
| At least one administration | 4/25 | Does not establish long-term glucose-lowering treatment |
| Dispensing / medication statements | 0 / 0 | These evidence types are absent from this cohort |
| Insulin-name order matches | 6/25 | No matching insulin administrations/dispensing/statements; display-name scan is not full code classification |
| SGLT-2-name matches | 0/25 | gliflozin text search, not a comprehensive drug-code audit |
| Latest HbA1c within 90 days before cutoff | 7/25 | Descriptive cutoff-relative interval, not V1 or a universal recency rule |
| Recorded deaths on/before cutoff | 2/25 | Excluded from clinical demonstrations, retained for data-quality checks |

The other 23 have no recorded death before cutoff; this does not confirm survival during a trial. The cohort is an adult T2D processing sample, not 25 eligible participants. Ages span 27-104, including calendar age for recorded-deceased records.

## Selected cases

NCT06774950 has five complete source clauses, including the full compound comorbidity exclusion and investigator judgment. Cleveland (age 43) and Anthony (27) provide age support and conflict under the offline date rule. Neither case tests endpoint inclusivity for 40 or 65. Selection is purposeful, not representative, and does not establish overall eligibility.

The 2026-10-11 snapshot is NOT_YET_RECRUITING. Applying these newer criteria at hypothetical assessment_date 2021-11-30 is an offline method exercise, not proof that the trial existed or recruited then. Complete cohort facts and ZIP-member fact IDs were retained. Actual study dates remain unknown.

Original candidates remain in `proposals/cases.csv`, `proposals/patients/`, and `proposals/trials/NCT06774950.json`. Final model inputs are separate under `uploads/A/`; the preparation state must not be mistaken for the current run/review state.

## Rejected source-text candidate

NCT07376655 was rejected because parsed criteria omitted BMI continuation lines from the original text. The finding is recorded in `proposals/trial_selection_audit.json`; trial ingestion was not modified. A parsed status alone does not establish full source coverage. NCT06774950 passed the completeness check.

## Per-patient summary

Full fact IDs, raw statuses, values and dates are in `cohort_evidence_coverage.json`; CSV supports filtering. Dates below are latest valid calendar dates, with same-day facts retained in the full records.

| patient_id prefix | Age at cutoff | Latest HbA1c date | Days before cutoff | Orders / administrations | Recorded death before cutoff |
| --- | ---: | --- | ---: | --- | --- |
| 060e72d3 | 52 | 2021-08-13 | 109 | 42 / 0 | Not recorded; survival unconfirmed |
| 1293efbb | 62 | 2021-02-07 | 296 | 63 / 2 | Not recorded; survival unconfirmed |
| 165a4435 | 49 | 2021-03-25 | 250 | 22 / 0 | Not recorded; survival unconfirmed |
| 1cfa5a70 | 63 | 2021-01-13 | 321 | 26 / 2 | Not recorded; survival unconfirmed |
| 28db1c55 | 44 | 2021-03-25 | 250 | 62 / 0 | Not recorded; survival unconfirmed |
| 30db29cb | 56 | 2021-03-14 | 261 | 37 / 0 | Not recorded; survival unconfirmed |
| 3beee40e | 69 | 2021-06-21 | 162 | 77 / 0 | Not recorded; survival unconfirmed |
| 3dfce025 | 59 | 2021-10-21 | 40 | 201 / 0 | Not recorded; survival unconfirmed |
| 40ef2428 | 47 | 2021-10-21 | 40 | 6 / 0 | Not recorded; survival unconfirmed |
| 475803f3 | 43 | 2020-12-28 | 337 | 5 / 0 | Not recorded; survival unconfirmed |
| 4b10c406 | 69 | 2021-05-27 | 187 | 3 / 0 | Not recorded; survival unconfirmed |
| 509f9a77 | 56 | 2021-11-15 | 15 | 98 / 0 | Not recorded; survival unconfirmed |
| 55c5b8d3 | 79 | 2021-11-04 | 26 | 825 / 0 | Not recorded; survival unconfirmed |
| 56cfe6a5 | 51 | 2021-03-06 | 269 | 41 / 0 | Not recorded; survival unconfirmed |
| 76b289fd | 36 | 2019-05-19 | 926 | 12 / 3 | Not recorded; survival unconfirmed |
| 80534c6c | 27 | 2019-10-18 | 774 | 1 / 0 | Not recorded; survival unconfirmed |
| 83f922a9 | 57 | 2020-12-12 | 353 | 56 / 0 | Not recorded; survival unconfirmed |
| 8c6ae452 | 104 | 2016-04-12 | 2058 | 808 / 0 | Recorded; excluded from demonstrations |
| 9e84e569 | 76 | 2021-03-07 | 268 | 443 / 0 | Not recorded; survival unconfirmed |
| 9ef4db86 | 48 | 2020-11-16 | 379 | 96 / 0 | Not recorded; survival unconfirmed |
| aa01ba4c | 58 | 2021-11-12 | 18 | 45 / 0 | Not recorded; survival unconfirmed |
| aade3c61 | 36 | 2020-04-01 | 608 | 4 / 0 | Not recorded; survival unconfirmed |
| be82309d | 51 | 2021-10-16 | 45 | 36 / 0 | Not recorded; survival unconfirmed |
| c893e2b1 | 80 | 1992-07-26 | 10719 | 28 / 1 | Recorded; excluded from demonstrations |
| d362f4e5 | 47 | 2021-09-10 | 81 | 8 / 0 | Not recorded; survival unconfirmed |

## Reproduce the audit

```bash
python evaluation/verification/analyze_cohort.py
python evaluation/verification/analyze_cohort.py --check
python -m unittest discover -s evaluation/verification/tests -p test_cohort_coverage.py -v
```

The analyzer records input/output hashes. Original ZIP members were not downloaded and individually revalidated during this coverage audit; provenance uses the committed cohort, selection manifest and archive hash. Core specified LOINC/SNOMED codes are counted exactly; medication names use an explicitly labeled text scan. This does not claim exhaustive coverage of all clinical concepts.
