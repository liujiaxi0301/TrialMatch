# RAG Workflow

Retrieve candidate trials and assess their complete criteria against source-linked
patient facts. All results require review. Retrieval relevance is separate from
patient eligibility.

## Quick Start

From the repository root, use `make up` for the offline app or `make live` for online
screening. Setup and credentials are in the [project README](../../README.md).

| Mode | Retrieval | Assessment |
| --- | --- | --- |
| Offline | BM25 | Python rules; unsupported criteria remain UNKNOWN. |
| Live, Gemini | BM25 plus Gemini embeddings, fused with reciprocal rank fusion | Rules and Gemini. |
| Live, Fine-tuned BioClinical | BM25 plus the evaluated November 10 encoder, in its own Chroma collection | The same rules and Gemini. |

Select the retrieval model in the web page or pass `retrieval_model` to the API.
The trained option uses CPU and verifies the checkpoint SHA256 before loading.
Its vectors are kept separate from Gemini vectors.

For a standalone offline CLI request with the root uv environment:

```bash
uv run --locked python -m services.rag_workflow.cli --mode offline screen \
  --patient-id 060e72d3-912e-55cd-0c92-5faa6cb7a6db \
  --question 'Which trials may suit this patient, and what needs review?' \
  --top-k 3 --output artifacts/rag_workflow/demo_offline.json
```

Global CLI options such as `--mode live --retrieval-model finetuned` go before
`screen` or `build-index`. Standalone live use also needs the chosen encoder's
dependencies, credentials and an index built/restored with the same configuration.
Use `make live` for the integrated Docker setup.

## Data and Workflow

| Input | Path |
| --- | --- |
| Trials | `services/trial_ingestion/data/processed/trials.jsonl` |
| Criteria | `services/trial_ingestion/data/processed/criteria.jsonl` |
| Patients | `services/patient_processing/data/processed/batch25_patients.jsonl` |
| Fixed 50-trial subset | `services/rag_workflow/examples/demo_manifest.json` |

The workflow combines a question with a patient profile, retrieves candidates,
loads all criteria for each candidate, selects relevant patient facts, applies
rules/model assessment, validates the evidence and aggregates the response.
The default cohort has 25 patients. Patient reference date: `2021-11-30`;
trial snapshot: `2026-10-11`.

Source hashes, the trial subset, embedding model and dimensions define an index
version. `make live` restores the saved 607-fragment Gemini snapshot from shared DVC
storage and prepares the separate trained-encoder index. See
[INDEX_VERSIONING.md](INDEX_VERSIONING.md) for export, restoration and version checks.
A Git clone contains pointers, not the vector snapshot or model weights.

## API Contract

The integrated web app exposes the RAG API. Use http://localhost:8080/docs for
interactive schemas, or `/openapi.json` for the generated specification.

| Route | Purpose |
| --- | --- |
| `GET /health` | Data and manifest health. |
| `GET /ready` | Data and selected-index readiness; no model inference. |
| `GET /patients` | Selectable patient summaries. |
| `POST /screen` | Screening request and structured response. |

```bash
curl http://localhost:8080/screen -H 'Content-Type: application/json' -d \
  '{"patient_id":"060e72d3-912e-55cd-0c92-5faa6cb7a6db","question":"Which trials may suit this patient?","top_k":3}'
```

Supply exactly one of `patient_id` or a normalized schema-0.3 `patient` object.
`top_k` is 1–5. Live requests may add `retrieval_model` as `gemini` or `finetuned`;
omitting it retains the configured default. `/ready` accepts the same optional
query parameter. It verifies the data/index, not Gemini permissions or quota.

| Response field | Meaning |
| --- | --- |
| `mode`, `result_status`, `errors`, `warnings` | Mode and technical outcome: OK, PARTIAL, ERROR or NO_CANDIDATES. |
| `candidate_trials` | Trial identity, recruitment status, screening status and criterion assessments. |
| `criteria_assessments`, `evidence` | MET / NOT_MET / UNKNOWN judgments and original fact IDs, dates, values and units. |
| `assessment_coverage`, `missing_information` | Known/unknown counts and missing evidence. |
| `provenance`, `metrics` | Actual retrieval model, checkpoint identity, generation model and usage. |

`OK` is a successful request, not confirmed eligibility. An inclusion NOT_MET or
exclusion MET is a screening barrier. Missing or ambiguous evidence remains UNKNOWN.
`match_score = 100 * (inclusion MET + exclusion NOT_MET) / total criteria`, including
UNKNOWN criteria in the denominator. It is not a probability; `eligibility_probability`
is null. A high score cannot cancel a barrier.

Malformed requests return 422; unknown patients return 404; unavailable data/indexes
or model failures can return 503. Partial assessments may return HTTP 200 with
`result_status=PARTIAL`. The CLI exits nonzero for ERROR/PARTIAL. API errors must not
be replaced by mock results. [Logging and error handling](../../docs/ms3/API_MONITORING.md).

## Assessment Boundaries

- Every candidate is assessed against its full original criteria, not just retrieved fragments.
- Each criterion receives at most 12 source facts. Oversized facts are omitted whole.
- Judgment batches contain up to six criteria, with at most 12 batches per request.
  Criteria beyond the budget remain UNKNOWN.
- Proposed model judgments are checked against source IDs, units, dates and deterministic
  rules. Invalid outputs get at most one repair attempt, then remain UNKNOWN with an error.
- Prescriptions do not prove medication use. Missing records do not prove a negative history.
- Complex logic, medication timing and unsupported evidence often remain UNKNOWN.
- Historical synthetic records do not establish current enrollment eligibility or treatment safety.

## Code and Checks

| File | Purpose |
| --- | --- |
| `config.py`, `data.py` | Settings, fixed inputs and data checks. |
| `retrieve.py`, `index.py`, `embedding_providers.py` | Query/evidence selection, Chroma and embeddings. |
| `rules.py`, `workflow.py`, `providers.py` | Rules, model calls and aggregation. |
| `schemas.py`, `api.py`, `cli.py` | Shared contract and entry points. |
| `observability.py`, `readiness.py` | Request logs and readiness checks. |

```bash
uv run --locked python -m unittest discover -s services/rag_workflow/tests -v
```

Tests use local data and mocks unless explicitly configured otherwise. Historical MS2
examples remain under `examples/`; they are not current cloud verification.
MS3 benchmarks and their limitations are documented in
[evaluation/ms3](../../evaluation/ms3/README.md).
