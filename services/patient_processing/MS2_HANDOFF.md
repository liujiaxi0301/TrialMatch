# MS2 patient-processing delivery and handoff

## Ownership and delivery scope

This personal delivery covers **patient processing and patient-data documentation/evidence only**. The optional manual verification package is preserved separately and excluded from this submission. It does not modify trial ingestion, RAG/model rules, API contracts, shared infrastructure, the root README, or the frontend.

Patient implementation baseline: commit `9d6886a7ea925d9068bc38d669987036727873d5` on `feat/patient-processing`. The processor and patient facts remain unchanged. Integration and final `milestone2` submission are team responsibilities.

## Patient module: completed artifacts

| Deliverable | Files/evidence |
| --- | --- |
| Official synthetic source and reproducibility | [README](README.md), [source commit/archive/member hashes](data/sample_source.json) |
| Environment | [pyproject.toml](pyproject.toml), [uv.lock](uv.lock); Python standard library, no model/API calls |
| FHIR → facts | [processor](scripts/process_patients.py), [schema 0.3](SCHEMA.md), [source mapping](examples/fhir_to_facts_mapping.md) |
| Four-patient sample | [raw Bundles](data/raw/), [processed facts](data/processed/patients.jsonl), [coverage](data/processed/coverage_report.json) |
| Deterministic 25-patient adult T2D cohort | [facts](data/processed/batch25_patients.jsonl), [selection/member hashes](data/processed/batch25_selection.json), [archive coverage](data/processed/archive_coverage_report.json) |
| Missingness and cohort limitations | README section above; [exact-coded record presence](evidence/cohort_scope.json) |
| Tests and repeatable sample run | [six tests](tests/test_process_patients.py), [validation record](evidence/patient_delivery_checks.json), raw logs in `evidence/` |

The full archive scan is previously recorded, not rerun during this documentation handoff. The sample replay verifies the four committed source Bundles; it must not be described as revalidating all 555 archive patients.

## Run and handoff commands

From the repository root:

```bash
uv sync --project services/patient_processing --locked
uv run --project services/patient_processing --locked python services/patient_processing/scripts/process_patients.py \
  --input services/patient_processing/data/raw \
  --output /tmp/trialmatch-patient-handoff/patients.jsonl \
  --reference-date 2021-11-30
uv run --project services/patient_processing --locked python -m unittest discover \
  -s services/patient_processing/tests -v
```

The output command uses a separate directory and does not replace the 25-patient cohort. The infrastructure owner can invoke this same processor/arguments inside the shared image; this module supplies the input/output contract and logs, not a new team Docker configuration.

## Questions for consuming-module owners

These are handoff requirements/findings, **not implemented changes or confirmed acceptance**:

1. Consume `batch25_patients.jsonl` with patient schema 0.3; preserve full fact IDs, source dates, exact codes, units, raw statuses and warnings. ZIP-member IDs differ from the four-Bundle sample's path-based IDs.
2. Keep source cutoff, hypothetical assessment and actual trial events separate. A known diagnosis alone does not establish duration before an unknown consent date; a historical measurement is not automatically a trial-time measurement.
3. Missing records are UNKNOWN evidence, not normal findings or negative history. MedicationRequest is an order, not actual stable use/adherence. `status_at_reference_date=undetermined` must not be silently promoted to known historical/current status.
4. Confirm the patient-processing stage, data version and sample input/output within the shared container pipeline. This module supplies the processor, facts, schema, commands and patient-stage evidence; the shared pipeline and consuming application are separate deliverables.

## Remaining personal actions

- [x] Document patient source, schema, reproduction, coverage, deaths and evidence limitations.
- [x] Verify the patient processor with its six existing tests and a byte-identical sample replay; keep logs and source hashes.
- [ ] Obtain consuming-owner confirmation of the facts/date/missingness contract. A handoff document alone is not acceptance; no team message has been sent.
- [ ] Obtain a shared integration run record from the infrastructure/RAG owners and attach the patient stage evidence.
- [ ] Review and publish this personal branch/PR when explicitly requested; no push or merge is performed here.
- [ ] Prepare the patient's source → fact → evidence explanation for the individual TF check, and understand other modules for shared Q&A.

Clinical reference annotation, model comparisons and expanded experiments are outside this patient-processing submission.
