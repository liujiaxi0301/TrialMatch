# Patient facts schema v0.3

`data/processed/patients.jsonl` contains one JSON object per input FHIR R4 patient Bundle. `patient_id` is the source `Patient.id`. No eligibility labels such as `MET`, `NOT_MET`, or `UNKNOWN` are produced.

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | `0.3`. |
| `patient_id` | string | FHIR Patient ID and row key. |
| `reference_date` | ISO date | Age anchor and future-event cutoff. |
| `source_file` | string | Input Bundle path. |
| `demographics` | object | Patient source, gender, birth/death dates, age. |
| `conditions` | array[fact] | All retained Conditions, including resolved status. |
| `observations` | array[fact] | Full retained Observation history. |
| `procedures` | array[fact] | Retained Procedure history; no eligibility interpretation. |
| `medications` | object | Separate `requests`, `definitions`, `dispenses`, `administrations`, `statements` fact arrays. |
| `unresolved_medication_references` | array[string] | Original unresolved medication references. |
| `warnings` | array[object] | Source-linked missing dates, unresolved references, and out-of-scope resource counts. |
| `unprocessed_resource_types` | object | Counts by unsupported FHIR resource type in the input Bundle. |

`demographics` has `fact_id`, `resource_type`, `source_resource_id`, `source_file`, `gender`, `birth_date`, `deceased_date`, and `age_years_at_reference`. Age is `null` when birth date is unavailable or later than reference date. `deceased_date` is a raw source date and is not reinterpreted as of the reference date.

## Fact provenance and values

Every fact has `fact_id` (`<source_file>#<resource_type>/<source_resource_id>`), `resource_type`, `source_resource_id`, and `source_file`. Subject-bearing facts retain `subject_reference`; it must resolve to the Bundle's one Patient or processing fails. Source IDs alone are not assumed globally unique. `code` is the original FHIR CodeableConcept, preserving `text` and every `coding` entry's `system`, `code`, and `display`. No code or missing scalar is `null`; missing arrays are `[]`. The processor neither invents values nor interprets absent records as negatives. Subject-bearing facts also have `event_time_certainty = dated | undated` and `status_at_reference_date = undetermined`. `raw_status` is the original source status, not a reconstructed historical status.

| Fact array | Additional fields |
|---|---|
| `conditions` | `code`, `raw_status`, `raw_clinical_status`, `raw_verification_status`, `onset_date`, `onset_period`, `abatement_date`, `abatement_period`, `recorded_date` |
| `observations` | `code`, `raw_status`, `effective_date`, `effective_period`, `issued_date`, `value`, `components` |
| `procedures` | `code`, `raw_status`, `performed_date`, `performed_period` |
| `medications.requests` | `code`, `raw_status`, `intent`, `authored_on`, `dosage_instruction`, `medication_reference`, `resolved_medication_id` |
| `medications.definitions` | `code`, `raw_status` |
| `medications.dispenses` | `code`, `raw_status`, `when_handed_over`, `when_prepared`, `quantity`, medication reference fields |
| `medications.administrations` | `code`, `raw_status`, `effective_date`, `effective_period`, `dosage`, medication reference fields |
| `medications.statements` | `code`, `raw_status`, `effective_date`, `effective_period`, `date_asserted`, medication reference fields |

Observation `value` is `null` or `{ "type": "Quantity", "data": { "value": 123, "unit": "mg/dL", "system": "http://unitsofmeasure.org", "code": "mg/dL" } }` for `valueQuantity`. Other FHIR `value[x]` types retain their original payload with the matching `type`. `components` holds `{ "code": CodeableConcept|null, "value": same-value-shape|null }`. Numeric values and units are preserved; no normal range is inferred.

`medication_reference` retains the original FHIR reference. When it resolves within the Bundle, `resolved_medication_id` points to `medications.definitions` and `code` can come from the referenced Medication. Unresolved references keep `code: null` if no inline code exists and produce a warning. A definition is not itself evidence of a patient taking a drug. Requests, dispenses, administrations, and statements remain separate evidence types.

## Reference date and coverage

`reference_date` is not a trial screening, consent or V1 date. Any hypothetical downstream `assessment_date` is separate metadata, not a replacement for the source cutoff or an actual event. The 25-patient adult/T2D selection includes two source-recorded deaths on/before cutoff and is not an enrollment or living-status filter. Integration requirements are documented for review in [MS2_HANDOFF.md](MS2_HANDOFF.md); they do not change this schema or implement the consuming workflow.

Dated Conditions check `recordedDate` and onset, Observations check `issued` and effective date, Procedures check `performedDateTime` or `performedPeriod.start`, requests check `authoredOn`, administrations check effective date, dispenses check handover/preparation date, and statements check assertion/effective date. A resource is excluded if a checked date falls after `reference_date`. Comparison uses the written calendar date, without timezone conversion. Events with no usable date remain, carry `event_time_certainty = undated`, and receive a warning. Period end dates remain as raw source information even when later than `reference_date`; they are not interpreted as evidence of completion at that date. Original status fields, including a Condition's resolved status, may reflect the source snapshot rather than its historical state at the reference date; `status_at_reference_date` therefore remains `undetermined`. No latest Observation is selected; users must apply their own code, date, status, and tie-breaking rules.

`coverage_report.json` describes **only all Bundles supplied to that run**. Adults have `age_years_at_reference >= 18`. Adult T2D requires a retained Condition with exact SNOMED CT system `http://snomed.info/sct` and code `44054006`; medication use never substitutes for that diagnosis. Relevant Observation coverage is reported separately for LOINC `4548-4` (HbA1c) and `2339-0` (glucose), as patient and fact counts. Medication coverage reports patient and fact counts separately for each evidence type. These are descriptive counts of the supplied input, not sensitivity or full-dataset estimates.

The first pass assumes one Patient per Bundle, resolves only within-Bundle Medication references, and does not normalize Encounter, AllergyIntolerance, claims, or eligibility decisions. Their counts appear in `unprocessed_resource_types` and warnings. `archive_coverage_report.json` describes all 555 patient Bundles in the verified archive and separately counts two nonpatient information Bundles. It reports relevant test, medication, and Procedure coverage within the 32 adults with an exact T2D Condition. `batch25_selection.json` records the deterministic first-cohort rule and per-file hashes.
