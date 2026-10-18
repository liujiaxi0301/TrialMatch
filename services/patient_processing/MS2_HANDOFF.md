# MS2 patient-processing delivery and handoff

## Ownership and delivery scope

This personal delivery covers **patient processing, patient-data documentation/evidence, and TF-requested verification**. The user confirmed on 2026-10-18 that the TF separately requested verification as part of this personal work. This scope clarification is user-reported; it is not presented as a requirement stated in the general MS2 rubric. Trial ingestion, RAG/model rules, API contracts, shared infrastructure, the root README and frontend are not modified by this delivery.

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
| TF-requested verification | [method and package](../../evaluation/verification/README.md), [v2 results](../../evaluation/verification/v2/results/two_case_pilot_summary.md), [tool checks](../../evaluation/verification/evidence/checks.json) |

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

## TF-requested verification: current evidence and limits

The package is included under `evaluation/verification/`. It preserves original responses, prompts/protocols, complete case inputs, source hashes, settings, human-review state and repeatable structural checks.

- V2 contains two user-submitted Mode A responses, five source clauses each, for synthetic patients Cleveland and Anthony against `NCT06774950`.
- Hypothetical assessment_date is the user-selected `2021-11-30`; actual screening/consent/V1 dates remain unknown. The trial snapshot is `2026-10-11`, NOT_YET_RECRUITING, so availability at assessment_date or now is not established.
- The user reported Claude Opus 5.5, new conversations, search/memory off. Client/context caveats remain; these are reported settings, not independently verified model identity or tool traces.
- Ten source clauses and 23/8 distinct evidence IDs passed structural/source checks. All ten v2 human-reference rows remain unconfirmed. No clinical accuracy, system superiority, final enrollment decision, or complete RAG evaluation is claimed.
- V1's recovered A/B responses and 22 prior review decisions remain under their original policy. V04–V06 were prepared but not run; v2 Mode B was not run. No extra model run or gold label is created by including the files.

From the repository root, these commands check the supplied records without model calls:

```bash
python evaluation/verification/build_cases.py --check
python evaluation/verification/analyze_cohort.py --check
python evaluation/verification/build_v2.py --check
python -m unittest discover -s evaluation/verification/tests -v
```

See the [verification README](../../evaluation/verification/README.md) and [current checks](../../evaluation/verification/evidence/checks.json). The package supplies the requested verification evidence at its documented stage; TF acceptance or any further reference annotation is not implied.

## Questions for consuming-module owners

These are handoff requirements/findings, **not implemented changes or confirmed acceptance**:

1. Consume `batch25_patients.jsonl` with patient schema 0.3; preserve full fact IDs, source dates, exact codes, units, raw statuses and warnings. ZIP-member IDs differ from the four-Bundle sample's path-based IDs.
2. Keep source cutoff, hypothetical assessment and actual trial events separate. A known diagnosis alone does not establish duration before an unknown consent date; a historical measurement is not automatically a trial-time measurement.
3. Missing records are UNKNOWN evidence, not normal findings or negative history. MedicationRequest is an order, not actual stable use/adherence. `status_at_reference_date=undetermined` must not be silently promoted to known historical/current status.
4. Confirm the patient-processing stage, data version and sample input/output within the shared container pipeline. This module supplies the processor, facts, schema, commands and patient-stage evidence; the shared pipeline and consuming application are separate deliverables.

## Remaining personal actions

- [x] Document patient source, schema, reproduction, coverage, deaths and evidence limitations.
- [x] Verify the patient processor with its six existing tests and a byte-identical sample replay; keep logs and source hashes.
- [x] Include TF-requested verification with original answers/settings, source-linked case inputs, tools and explicit limitations.
- [ ] Confirm whether the TF needs additional independent reference review or experiments beyond the supplied two-case pilot; do not report unreviewed references as gold.
- [ ] Obtain consuming-owner confirmation of the facts/date/missingness contract. A handoff document alone is not acceptance; no team message has been sent.
- [ ] Obtain a shared integration run record from the infrastructure/RAG owners and attach the patient stage evidence.
- [ ] Review and publish this personal branch/PR when explicitly requested; no push or merge is performed here.
- [ ] Prepare the patient's source → fact → evidence explanation for the individual TF check, and understand other modules for shared Q&A.

Any further verification experiment should state its protocol, independent reference-review status and denominator. Team retrieval/inference/API/infra/UI implementation remains outside this personal delivery.
