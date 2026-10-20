# Patient processing

Convert official Synthea FHIR R4 Bundles into source-linked **schema 0.3 patient facts**. The extractor preserves diagnoses, measurements, procedures and separate medication evidence types; it does not assign eligibility labels.

## Start here

| Need | File |
| --- | --- |
| Implementation | [process_patients.py](scripts/process_patients.py) |
| Output contract and date semantics | [SCHEMA.md](SCHEMA.md) |
| One raw FHIR to fact example | [Source mapping](examples/fhir_to_facts_mapping.md) |
| Shared RAG input | [25-patient JSONL](data/processed/batch25_patients.jsonl) |
| Exact source and selected patients | [Source manifest](data/sample_source.json), [cohort selection](data/processed/batch25_selection.json) |
| Patient-stage evidence | [Validation record](evidence/patient_delivery_checks.json), [test log](evidence/patient_tests.txt), [sample replay](evidence/sample_run.txt) |
| TF-requested verification | [Verification entry point](../../evaluation/verification/README.md) |

## Source and cohort

The four committed [raw Bundles](data/raw/) were extracted unchanged from the official [Synthea FHIR R4 November 2021 archive](https://raw.githubusercontent.com/synthetichealth/synthea-sample-data/9959d9178ea28f4ec10f17ee238b6fabe6eb0de5/downloads/synthea_sample_data_fhir_r4_nov2021.zip), pinned to source commit `9959d9178ea28f4ec10f17ee238b6fabe6eb0de5`. ZIP/member hashes are in [sample_source.json](data/sample_source.json). The generator identifier in source narratives is `master-branch-latest-7-gcc27279b`; no more precise release is claimed. Clinical histories are official synthetic data; handwritten edge fixtures occur only in tests.

| Data | Scope |
| --- | --- |
| [patients.jsonl](data/processed/patients.jsonl), [coverage_report.json](data/processed/coverage_report.json) | Four committed patients; three exact-coded T2D cases plus a Medication-reference/administration example |
| [archive_coverage_report.json](data/processed/archive_coverage_report.json) | Previously recorded scan: 557 JSON Bundles, 555 patients, 439 adults and 32 adult exact-coded-T2D patients |
| [batch25_patients.jsonl](data/processed/batch25_patients.jsonl) | First 25 after sorting adult exact-coded-T2D candidates by Patient.id, then ZIP member path |

The complete source ZIP is not committed. The 25-patient processing sample includes **two recorded deaths on/before cutoff**; absence of a death record for the others does not prove living status. It is not a random, eligible or confirmed-living candidate cohort.

All 25 have recorded HbA1c/BMI/blood-pressure evidence; eGFR/AST/ALT presence is 24/5/5. Requests/administrations occur for 25/4 patients; dispensing/statements occur for 0/0. These are record-presence counts, not freshness, adherence, normal findings or exclusion clearance. Codes, hashes and counting rules are in [cohort_scope.json](evidence/cohort_scope.json).

## Run from the repository root

The personal module uses [pyproject.toml](pyproject.toml) and [uv.lock](uv.lock), requires Python 3.10 or newer, and uses only the Python standard library. Original validation used Python 3.12.14 and uv 0.12.23.

```bash
uv sync --project services/patient_processing --locked
uv run --project services/patient_processing --locked python services/patient_processing/scripts/process_patients.py \
  --input services/patient_processing/data/raw \
  --output /tmp/trialmatch-patient-demo/patients.jsonl \
  --reference-date 2021-11-30
uv run --project services/patient_processing --locked python -m unittest discover -s services/patient_processing/tests -v
```

The temporary output preserves committed data. The processor accepts a Bundle or directory, writes coverage beside its JSONL output, and accepts `--coverage-report` for a separate report path. Its six tests cover official sample provenance/subject links, Medication references and evidence separation, plus synthetic cutoff/missing-value/invalid-reference edge cases. A four-Bundle replay is not a new full-archive scan.

To reproduce the full scan, first download the pinned archive above and verify SHA-256 `6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778`, then run:

```bash
uv run --project services/patient_processing --locked python services/patient_processing/scripts/select_archive_cohort.py \
  --archive /tmp/synthea_sample_data_fhir_r4_nov2021.zip \
  --expected-sha256 6d3c5433bcae4791bc5c30469d1445b430fb4894d5c13bda15fee0584bbd7778 \
  --reference-date 2021-11-30 --count 25 \
  --output /tmp/trialmatch-cohort-demo/batch25_patients.jsonl \
  --report /tmp/trialmatch-cohort-demo/archive_coverage_report.json \
  --selection-manifest /tmp/trialmatch-cohort-demo/batch25_selection.json
```

## Handoff contract

1. Consume schema 0.3 and preserve full fact IDs, codes, dates, units, raw statuses and warnings. ZIP-member fact IDs differ from path-based IDs in the four-Bundle sample. The shared RAG default input is the 25-patient JSONL.
2. `reference_date` is the data cutoff and stored-age anchor. Any hypothetical assessment_date is separate; neither replaces real screening, consent or V1 dates.
3. Known future event/record dates are excluded. Undated facts stay with warnings. Retain full Observation history and original statuses; every `status_at_reference_date` stays `undetermined`.
4. Missing records are not negative history. Requests are orders, definitions describe drug products, and dispensing/administration/statements remain separate; none alone establishes adherence or stable long-term use.
5. Unsupported resource types and unresolved Medication references remain explicit. The extractor resolves within-Bundle Medication references and checks patient links; it does not process every clinical resource or infer diagnoses from medications.

This personal scope covers patient processing and TF-requested verification. Shared retrieval, API, UI, containers and scoring have separate owners. Shared application integration and container-run evidence belong to the consuming team delivery; this personal branch supplies the processor, facts, schema and validation records. Presentation preparation and final team `milestone2` submission remain team actions. The former handoff and complete pre-cleanup patient/verification material are preserved in the [history archive](../../evaluation/verification/history/ms2_pre_cleanup_20261020.zip).
