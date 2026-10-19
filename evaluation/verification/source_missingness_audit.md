# Cleveland source-data missingness audit

On 2026-10-18, the original FHIR Bundle was compared with the complete processed record used by V01-V03. This is a single-patient audit, not a claim about all Synthea exports.

| Resource / fact type | Raw FHIR count | Processed count |
| --- | ---: | ---: |
| Condition / conditions | 24 | 24 |
| Observation / observations | 147 | 147 |
| Procedure / procedures | 39 | 39 |
| MedicationRequest / medications.requests | 5 | 5 |
| MedicationAdministration | 0 | 0 |
| MedicationDispense | 0 | 0 |
| MedicationStatement | 0 | 0 |

For the four clinical types actually present, the processor's checked event dates were not after reference_date; the latest records were dated 2020-12-28. Their counts were not reduced by cutoff filtering. The Bundle has no Consent or ResearchSubject resources. That absence alone does not prove that no other field contains relevant text.

Distinguish four explanations:

1. **The export lacks the evidence.** Orders without administrations, dispensing or statements do not establish actual use, stable dose or adherence. Missing disease records do not establish negative history. One sample does not define all Synthea capabilities.
2. **The evidence belongs to study workflow.** Actual consent, willingness, screening and V1 dates cannot be invented from routine encounters. This patient archive is from 2021, clinical events end in 2020, and trial snapshots are from 2026.
3. **Facts exist but do not resolve the requested timepoint.** Birth date, historical HbA1c, BMI and blood pressure are present. Under v1's agreed rule, reference_date cannot replace real trial dates; these UNKNOWN results do not mean Synthea failed to generate age or measurements.
4. **Extraction scope is limited.** Encounter, DiagnosticReport, DocumentReference and CarePlan are reported in `unprocessed_resource_types` rather than emitted as independent facts. Complete counts of core resources do not constitute an audit of all other resource content. A requirement that depends on them needs source review.

The supported conclusion is that supplied evidence does not establish a criterion. It does not establish the patient's actual disease status or prove that the model cannot understand the criterion. Reports should separate source missingness, extraction scope, unknown study dates and model reasoning.
