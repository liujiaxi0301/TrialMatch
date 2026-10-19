# MS2 patient-processing handoff

## Ownership

This personal delivery covers **patient processing, its documentation/evidence, and TF-requested verification**. The verification scope was confirmed by the user on 2026-10-18; it is not presented as a separate requirement in the general rubric. Trial ingestion, RAG/API, shared infrastructure, root README, UI and final `milestone2` submission have separate owners.

Patient implementation baseline: `9d6886a7ea925d9068bc38d669987036727873d5` on `feat/patient-processing`. The processor and patient facts are unchanged.

## Delivered artifacts

| Deliverable | Canonical files/evidence |
| --- | --- |
| Official synthetic source and reproduction | [README](README.md), [source/member hashes](data/sample_source.json), [pyproject.toml](pyproject.toml), [uv.lock](uv.lock) |
| FHIR to facts | [Processor](scripts/process_patients.py), [schema 0.3](SCHEMA.md), [source mapping](examples/fhir_to_facts_mapping.md) |
| Four-patient sample | [Raw Bundles](data/raw/), [facts](data/processed/patients.jsonl), [coverage](data/processed/coverage_report.json) |
| Deterministic 25-patient adult T2D cohort | [Facts](data/processed/batch25_patients.jsonl), [selection/member hashes](data/processed/batch25_selection.json), [archive coverage](data/processed/archive_coverage_report.json) |
| Missingness and deaths | [Cohort limitations](README.md#cohort-limitations-and-handoff), [record-presence audit](evidence/cohort_scope.json) |
| Patient validation | [Six tests](tests/test_process_patients.py), [sample replay and test record](evidence/patient_delivery_checks.json), logs in `evidence/` |
| TF-requested verification | [Package entry point](../../evaluation/verification/README.md), [completed reference review](../../evaluation/verification/v2/results/reference_review_completed.md), [grounding paired report](../../evaluation/verification/grounding/results/paired_grounding_report.md), [current checks](../../evaluation/verification/evidence/checks.json) |

The full archive scan is previously recorded. The committed four-Bundle replay does not revalidate all 555 archive patients. The 25-patient cohort includes two recorded deaths; it is not a cohort of 25 eligible or confirmed-living patients.

Verification records include complete case inputs, responses, settings, source hashes and review provenance. V2 has ten user-confirmed references and two evidence-rule differences from the model. Grounding records both controlled responses and citation checks. The linked reports retain non-clinician/non-blinded review limits, unknown actual trial dates, model-reported inherited context and the positive control's minor reasoning issue. These observations do not establish clinical accuracy, enrollment eligibility or backend enforcement.

## Run the patient stage

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

The output uses a separate directory and preserves the committed cohort. Verification has its own [reproducibility commands](../../evaluation/verification/README.md#reproduce-the-checks); no model calls are needed. [Delivery provenance](../../evaluation/verification/LANGUAGE_AND_PROVENANCE.md) explains presentation changes and removal of redundant copies.

## Contract for consuming owners

These are handoff requirements; consuming-owner acceptance and shared integration are not confirmed:

1. Consume `batch25_patients.jsonl` with schema 0.3. Preserve complete fact IDs, source dates, exact codes, units, raw statuses and warnings. ZIP-member IDs differ from the four-Bundle sample's path-based IDs.
2. Keep the source cutoff, hypothetical assessment date and actual trial events separate. A known diagnosis does not establish duration before an unknown consent date; a historical measurement is not automatically a trial-time measurement.
3. Missing records are UNKNOWN evidence. MedicationRequest is an order, not actual stable use/adherence. `status_at_reference_date=undetermined` must not be promoted to known historical/current status.
4. Invoke the supplied processor/arguments within the shared image and record patient input/output versions. The shared pipeline and consuming application remain separate deliverables.

## Remaining actions

- [x] Document source, schema, reproducibility, coverage and evidence limitations.
- [x] Preserve six passing patient tests and a byte-identical sample replay.
- [x] Complete the two-case, ten-clause non-clinician reference review and freeze its evidence.
- [x] Record the TF-requested grounding pair, source review and limitations.
- [x] Consolidate guides, redundant reference copies, working archives and check logs.
- [ ] Obtain consuming-owner acceptance of the facts/date/missingness contract.
- [ ] Obtain shared integration evidence from infrastructure/RAG owners, including the patient stage.
- [x] Authorize publication of this reviewed revision to `feat/patient-processing` (2026-10-19).
- [ ] Coordinate inclusion of the personal delivery in the team's `milestone2` submission.
- [ ] Prepare the patient source-to-fact-to-evidence explanation for the individual TF check and shared Q&A.

Further TF validation requirements, if specified, need a separate scope/protocol. A clinical expert, larger benchmark or v2 Mode B run is not established as mandatory by the supplied general rubric/feedback. No team message has been sent.
