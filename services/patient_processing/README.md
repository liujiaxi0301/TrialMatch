# Patient Processing (MS2 Part 2)

This module converts Synthea FHIR R4 transaction Bundles into one JSONL record of patient facts per patient. It processes Patient, Condition, Observation, Procedure, MedicationRequest, Medication, MedicationAdministration, MedicationDispense, and MedicationStatement. The latter two are supported but absent from this four-patient sample. It does not perform retrieval, clinical inference, or eligibility reasoning.

## Source and reproducibility

No patient data existed in the checkout before this module. The four files in `data/raw/` were extracted unchanged from the official [Synthea sample-data repository](https://github.com/synthetichealth/synthea-sample-data), [FHIR R4 November 2021 archive](https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/9959d9178ea28f4ec10f17ee238b6fabe6eb0de5/downloads/synthea_sample_data_fhir_r4_nov2021.zip) at repository commit `9959d9178ea28f4ec10f17ee238b6fabe6eb0de5`. The archive SHA-256 and each selected file's SHA-256 are in `data/sample_source.json`. Patient narratives report generator identifier `master-branch-latest-7-gcc27279b`; no more precise generator release tag is claimed. The selected records are synthetic patients from the official sample, not handwritten fixtures. Handwritten edge cases appear only inside `tests/` and are labeled test fixtures.

Three selected patients have a Type 2 Diabetes Condition. The fourth covers within-Bundle Medication references and MedicationAdministration. The selected four-patient coverage report does **not** describe coverage of the full official archive. A separate verified archive scan and 25-patient selection are described below.

## Environment and run

Python 3.12.14 and uv 0.12.23 were used for the original module validation. This module uses only the standard library. The integrated project uses Python 3.12 and the root `pyproject.toml` and `uv.lock`. From the repository root:

```bash
export UV_CACHE_DIR=/tmp/trialmatch-uv-cache
uv sync --locked
uv run --locked python services/patient_processing/scripts/process_patients.py \
  --input services/patient_processing/data/raw \
  --output services/patient_processing/data/processed/patients.jsonl \
  --reference-date 2021-11-30
uv run --locked python -m unittest discover \
  -s services/patient_processing/tests -v
```

`--input` accepts a directory of Bundle JSON files or one Bundle JSON file. The run writes `coverage_report.json` beside `--output`; use `--coverage-report` to choose another location. `--reference-date` is required. Age is calculated on that date. Clinical resources with a known event or recorded date after it are excluded. Date comparison uses the calendar date as written in the FHIR field. Undated resources remain with a warning and `event_time_certainty = undated`. Original statuses are preserved as source data; they are **not** reconstructed as historical status at the reference date. Every fact has `status_at_reference_date = undetermined`. Observation history is preserved; no latest-value shortcut is produced.

## Full archive scan and first cohort

The November 2021 archive contains 557 JSON Bundles: 555 patient Bundles and two organization/practitioner information Bundles. With `reference_date = 2021-11-30`, 439 patients are adults and 32 adults have a retained Condition coded exactly SNOMED CT `44054006` (Type 2 Diabetes). The full-archive scan is in `data/processed/archive_coverage_report.json`. It reports HbA1c, glucose, medication evidence types, and Procedure coverage **within those 32 adult T2D patients**. The first cohort of 25 is selected by sorting eligible patients by `Patient.id`, then archive member path, and taking the first 25. It is in `data/processed/batch25_patients.jsonl`; filenames, patient IDs, and input SHA-256 hashes are in `data/processed/batch25_selection.json`.

The complete archive is not committed to this module. To reproduce the scan, download the archive and verify its SHA-256, then run:

```bash
curl -fL --retry 2 -o /tmp/synthea_sample_data_fhir_r4_nov2021.zip \
  https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/9959d9178ea28f4ec10f17ee238b6fabe6eb0de5/downloads/synthea_sample_data_fhir_r4_nov2021.zip
printf '%s  %s\n' 6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778 \
  /tmp/synthea_sample_data_fhir_r4_nov2021.zip | sha256sum -c -
export UV_CACHE_DIR=/tmp/trialmatch-uv-cache
uv run --locked python services/patient_processing/scripts/select_archive_cohort.py \
  --archive /tmp/synthea_sample_data_fhir_r4_nov2021.zip \
  --expected-sha256 6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778 \
  --reference-date 2021-11-30 --count 25 \
  --output services/patient_processing/data/processed/batch25_patients.jsonl \
  --report services/patient_processing/data/processed/archive_coverage_report.json \
  --selection-manifest services/patient_processing/data/processed/batch25_selection.json
```

`MedicationRequest` means an order, `MedicationDispense` a dispensing event, `MedicationAdministration` an administration event, and `MedicationStatement` a recorded medication report. None alone proves adherence. Missing records do not imply normal findings, absence of disease, or absence of medication. Medication codes never create a Type 2 Diabetes diagnosis. The processor reports unresolved references and resource types outside this first-pass scope instead of silently treating them as clinical negatives.

See [SCHEMA.md](SCHEMA.md) for fields and the contract. `examples/fhir_to_facts_mapping.md` traces one official patient's Condition, Observation, MedicationRequest, and MedicationAdministration back to raw FHIR. Full formatted records are in `examples/anthony_patient.json` and `examples/shakira_patient.json`.

## Cohort limitations and handoff

The 25-patient cohort is a deterministic **adult T2D processing sample, not 25 eligible or confirmed-living trial candidates**. Two records have a source death date on or before `2021-11-30`. The other 23 lack such a recorded death; this does not prove current living status. Preserve the source records and selection manifest rather than silently replacing patients.

| Recorded evidence in the 25-patient cohort | Patients |
| --- | ---: |
| HbA1c / BMI / blood pressure | 25 / 25 / 25 |
| eGFR / AST / ALT | 24 / 5 / 5 |
| MedicationRequest / MedicationAdministration | 25 / 4 |
| MedicationDispense / MedicationStatement | 0 / 0 |

These counts indicate presence of exact-coded records, not measurement freshness, normal findings, adherence or absence of exclusions. Zero dispensing/statement records describe this dataset, not the patient's real treatment history. See [cohort evidence](evidence/cohort_scope.json) for codes, input hash and counting method.

`reference_date` is the facts cutoff and stored-age anchor; it is not a real screening, consent or V1 date. Actual study dates are not supplied by this module. Patient facts stay schema 0.3; no trial dates or eligibility labels are injected into the source data.

See [MS2_HANDOFF.md](MS2_HANDOFF.md) for this module's delivery checklist, validation evidence and facts contract. The user confirmed that the TF separately requested verification; the [verification package](../../evaluation/verification/README.md) is therefore included in this personal delivery. The patient processor itself still only extracts facts. Downstream clinical judgments, APIs, retrieval, containers and UI remain with their respective owners.

## Validation covered

The six tests check official-sample patient links, fact provenance, Medication references, Procedure fields, and separation of orders, definitions, and administrations. Clearly marked synthetic test fixtures check the reference-date boundary, future-event exclusion, missing dates, missing codes and values, unknown historical status, wrong-patient references, and unresolved Medication references. The full archive scan independently verifies its SHA-256, records two nonpatient Bundles separately, and saves the exact first-cohort input hashes. The sample fixtures do not stand in for official patient data.
