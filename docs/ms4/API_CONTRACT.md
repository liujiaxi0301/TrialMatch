# MS4 API Contract — Part C

Contract for the C+B integration on Part B commit `c36fe77`, which includes
D's infrastructure. Part C's API boundary hardening and selection-lifecycle
changes are on `xuyang/ms4-backend`; verification was recorded from the worktree
before commit. They classify dependency failures, preserve patient-validation
and partial-result behavior, and
keep screening and readiness aligned with the active fine-tuned encoder. See
[API integration](API_INTEGRATION.md), [selection integration](SELECTION_INTEGRATION.md)
and the historical [backend baseline](BACKEND_VALIDATION.md) for their separate
verification scopes. This document does not establish a combined Docker/CI pass.

The backend entry point remains
`services.frontend.app:app`: it extends the RAG API with patient-detail and
metadata routes. Backend ownership includes Python routes under
`services/frontend/`, as well as `services/rag_workflow/`.

| Runtime | Default local addresses and UI hosting |
| --- | --- |
| Recorded C host baseline | One Uvicorn application served the API and static UI at `http://localhost:8080` on the MS3 baseline. This is historical evidence. |
| C+B checkout, including D's Compose layout | Nginx `frontend` serves the UI at `http://localhost:8080` and proxies API paths to `rag-api:8080`. Direct backend access is `http://localhost:8081`. Compose sets `TRIALMATCH_SERVE_UI=false` on the backend, so it does not serve the static UI. |

D's host ports can be overridden with `APP_PORT` and `API_PORT`; the backend's
container port is still 8080. Browser requests use relative paths on the frontend
origin, so the split does not require a cross-origin API URL in the UI.
Interactive documentation and OpenAPI remain `/docs` and `/openapi.json`,
reachable through that proxy or the direct API port. See the current
[Compose configuration](../../docker-compose.yml) and
[Nginx routes](../../docker/frontend/nginx.conf).

Implementation references: [HTTP adapter](../../services/rag_workflow/api.py),
[application routes](../../services/frontend/app.py),
[schemas](../../services/rag_workflow/schemas.py),
[workflow](../../services/rag_workflow/workflow.py), and
[MS3 operations guide](../ms3/API_MONITORING.md).

## Endpoints

| Method and path | Input | Response and scope |
| --- | --- | --- |
| `GET /health` | None | `status`, `mode`, patient count, configured trial-subset count and a scope note. Checks data/manifest availability, not live model or vector readiness. |
| `GET /metadata` | None | Mode, synthetic-data flag, patient/trial/subset counts, source hashes and reference/snapshot dates. |
| `GET /patients` | None | `{"patients": [...]}`; each item has `patient_id`, `reference_date`, age, gender and death date. |
| `GET /patients/{patient_id}` | Built-in patient ID | Full normalized patient object; unknown ID returns 404. |
| `GET /ready` | Optional query parameter `retrieval_model=gemini` or `finetuned` | Readiness report; HTTP 200 when ready, 503 otherwise. Invalid model names return 422. See readiness limits below. |
| `POST /screen` | JSON `ScreenRequest` | `ScreenResponse` for a completed workflow, including `PARTIAL` or `ERROR`; validation and raised exceptions may use a different error body. |
| `POST /retrieve` | `ScreenRequest`, requiring built-in `patient_id` | Separate lexical token-hash vector demonstration: query, collection, source hashes and retrieved chunks. It does not assess eligibility or select Gemini/fine-tuned retrieval. |
| `GET /docs`, `GET /openapi.json` | None | Interactive documentation and generated OpenAPI. |

`/retrieve` uses `LocalVectorDemo`, does not pass `retrieval_model` to a model
selector, and needs its own prepared index. The main screening UI uses `/screen`.
The HTTP adapter alone does not include `/patients/{patient_id}`, `/metadata`,
`/retrieve` or the static UI. Use `services.frontend.app:app` for the full API;
browser tests of D's Compose layout should target its Nginx frontend.

## Screening request

Send `Content-Type: application/json`. Exactly one of `patient_id` and `patient`
must be non-null. Unknown top-level request fields are rejected.

| Field | Accepted value |
| --- | --- |
| `patient_id` | Built-in patient ID, 1–250 characters; omit or set null when supplying `patient`. |
| `patient` | Normalized patient object; omit or set null when supplying `patient_id`. This is not raw FHIR. |
| `question` | Required string, 1–2,000 characters; whitespace-only values are rejected. |
| `top_k` | Integer from 1 to 5; default 3. It is a retrieval limit, not a guarantee of that many candidates. |
| `retrieval_model` | `"gemini"`, `"finetuned"`, null or omitted. Non-null selection is accepted by `/screen` only in live mode. |

Example request using a patient in the committed demo data:

```json
{
  "patient_id": "060e72d3-912e-55cd-0c92-5faa6cb7a6db",
  "question": "Which type 2 diabetes trials may suit this patient?",
  "top_k": 3
}
```

Inline patients must use patient schema version `0.3`, including a valid reference
date, demographics and preserved unique fact IDs. The backend also validates
array/object shapes, age, evidence codes, subject references and dates relative
to the patient reference date. Use the
[patient schema](../../services/patient_processing/SCHEMA.md) and
[`validate_patient`](../../services/rag_workflow/data.py) for the exact format.
The request schema's `patient` dictionary does not fully describe these runtime
checks in OpenAPI.

## Screening response and display semantics

| Response fields | Meaning for consumers |
| --- | --- |
| `schema_version` | Current response version is `"0.1"`. |
| `run_id` | Identifier for the returned screening workflow result. |
| `patient_id`, `patient_reference_date`, `question` | Inputs and reference date associated with this result. |
| `mode`, `result_status` | Execution mode and technical result; inspect both HTTP status and `result_status`. |
| `answer`, `candidate_trials` | Explanation text and structured candidates. |
| `warnings`, `errors` | Scope warnings and recorded failures. Each error has `code`, `message` and optional `criterion_id`. |
| `provenance` | Source hashes, selected retrieval/embedding configuration, generation model, trial subset and score definition. |
| `metrics` | Latency, candidate/corpus counts and, when used, provider/cache counters. |

The workflow currently emits these technical outcomes. `result_status` is typed
as a string in the response schema, not an OpenAPI enum.

| `result_status` | HTTP status | Current workflow condition |
| --- | --- | --- |
| `OK` | 200 | Candidates exist and no errors were recorded. Criteria may still be UNKNOWN. |
| `PARTIAL` | 200 | Candidates exist and errors were recorded. Display the retained results with their errors and limitations. |
| `NO_CANDIDATES` | 200 | No candidates and no recorded errors. This does not establish patient ineligibility. |
| `ERROR` | 503 | Errors were recorded and no candidates were produced; body is the full `ScreenResponse`. |

Each candidate includes `trial_id`, title/recruitment information,
`screening_status`, criterion assessments, an `evidence` map keyed by fact ID,
missing information, screening concerns, source URL and snapshot date.
`assessment_coverage` reports `total`, `completed`, `known`, `unknown` and
`screening_barriers`; it is not code-test coverage.

- Criterion decisions are `MET`, `NOT_MET` or `UNKNOWN`. An inclusion `NOT_MET`
  or exclusion `MET` is a screening barrier. UNKNOWN is not negative evidence.
- Candidate statuses are `SCREENING_BARRIER`, `NEEDS_MORE_INFORMATION` and
  `POTENTIAL_MATCH_FOR_REVIEW`. Complex/ambiguous trial structure can force
  `NEEDS_MORE_INFORMATION` even when individual barriers are present; retain
  concerns and warnings in the UI.
- `match_score` is criterion satisfaction, not eligibility probability. UNKNOWN
  stays in its denominator. `eligibility_probability` is null and
  `review_required` remains true in current workflow results.
- Follow assessment `evidence_fact_ids` into that candidate's `evidence` map.
  Context IDs, when present, describe context rather than proof of a decision;
  the current response ledger is populated from supporting evidence IDs.

### Captured offline response excerpt

The [initial backend baseline](BACKEND_VALIDATION.md) captured a real local HTTP
response using the example patient and question above with `top_k=1`. The
following is an excerpt, not a complete `ScreenResponse`; omitted fields include
the run ID, assessments, evidence, warnings and other provenance fields. Full
local captures are in `artifacts/ms4/api-examples.json`.

```json
{
  "schema_version": "0.1",
  "mode": "offline",
  "result_status": "OK",
  "errors": [],
  "candidate_trials": [
    {
      "trial_id": "NCT04670666",
      "screening_status": "NEEDS_MORE_INFORMATION",
      "match_score": 0.0,
      "eligibility_probability": null,
      "assessment_coverage": {
        "total": 25,
        "completed": 0,
        "known": 0,
        "unknown": 25,
        "screening_barriers": 0
      },
      "review_required": true
    }
  ],
  "provenance": {"retrieval_model": "bm25"}
}
```

This illustrates why `OK` must not be displayed as patient eligibility: the
request completed, while all 25 criteria in this result remain UNKNOWN.

## HTTP errors and request tracing

The existing API has several error shapes. Clients must not assume that every
failure contains `detail.code`, or that every 503 contains a `ScreenResponse`.
The examples below illustrate shapes; they are not captured run evidence.

| Situation | HTTP status | Body shape |
| --- | --- | --- |
| Request/query validation failure | 422 | FastAPI `{"detail": [{"loc": [...], "msg": "...", "type": "...", ...}]}`. |
| Unknown built-in patient | 404 | `{"detail": "Patient not found"}`. |
| Workflow `ValueError` / `TypeError`, including invalid inline patient or explicit model selection in offline screening | 422 | `{"detail": "..."}`. |
| Data/manifest unavailable or malformed during screening workflow construction, including missing manifest keys | 503 | `{"detail": {"code": "ARTIFACT_UNAVAILABLE", "message": "Data or manifest unavailable."}}`. |
| Missing data encountered during screening | 503 | `{"detail": "Processed data or manifest is missing"}`. |
| Fine-tuned selection record invalid during request resolution | 503 | `{"detail": {"code": "ENCODER_SELECTION_INVALID", "message": "Screening dependency unavailable."}}`; no workflow result was produced. |
| `ProviderError` escaping to the HTTP adapter | 503 | `{"detail": {"code": "...", "message": "Screening dependency unavailable."}}`. |
| Provider/index error captured by the workflow, with no candidates | 503 | Full `ScreenResponse` with `result_status="ERROR"` and `errors`. |
| Unclassified vector-index construction/query failure or invalid query-hit metadata | 503 | Full `ScreenResponse` with `result_status="ERROR"`; `errors` contains `code="INDEX_UNAVAILABLE"` and the fixed message `Retrieval index unavailable or invalid.`. |
| Direct `TimeoutError` reaching the adapter | 504 | `{"detail": {"code": "SCREENING_TIMEOUT", "message": "Screening timed out. No eligibility conclusion was made."}}`. |
| Unexpected exception before response starts | 500 | Sanitized `detail` object with `code="INTERNAL_ERROR"`, plus `request_id`. |

Errors caught while processing candidates may instead yield a 200 `PARTIAL`
response. Provider network/SDK timeouts are normally wrapped by
[`GeminiProvider`](../../services/rag_workflow/providers.py) as `ProviderError`
(for example `PROVIDER_UNAVAILABLE` or `GCP_504`), so they follow the workflow's
ERROR/PARTIAL path rather than guaranteeing HTTP 504.

Part C's index boundary checks run before retrieval results enter ranking or
patient-facing assessments. A query hit must reference a trial in the selected
manifest and a criterion belonging to that trial. Missing/invalid hit metadata,
out-of-subset trials, wrong-trial criteria and otherwise unclassified index
construction/query exceptions become `INDEX_UNAVAILABLE`, without exposing the
underlying exception text or treating the dependency failure as a patient 404
or request 422. These retrieval failures occur before candidates are produced.
Existing `ProviderError` codes pass through this boundary unchanged, and direct
`TimeoutError` continues to use the adapter's 504 path. Patient 404/422 responses
and the existing 200 `PARTIAL` policy are unchanged; error envelopes remain
different across these paths.

Every backend application HTTP response gets a generated `X-Request-ID` header; the
middleware does not echo a client-supplied request ID. A workflow response also
has a separate `run_id`, and screening logs link the two. Validation/raised-error
responses need not have a `run_id`. Use the header to trace API requests;
Nginx-served static pages and `/healthz` are outside this backend middleware.

The current browser aborts a screening fetch after five minutes and allows user
cancellation. These actions do not guarantee cancellation of backend work. The
UI should preserve structured `ERROR` responses and show warnings for `PARTIAL`;
HTTP 200 alone does not establish a complete assessment or eligibility.

## Retrieval selection and readiness: handoff to Part B

[`Settings.for_retrieval`](../../services/rag_workflow/config.py) creates the
per-request encoder configuration. An omitted or null selector keeps the
environment-derived settings and does not read the active fine-tuned record.
Explicit `gemini` also remains independent of that record.

| Choice | Current screening behavior |
| --- | --- |
| Offline mode, model omitted/null | BM25 and deterministic rules; no embedding or LLM calls. Provenance reports `bm25`. |
| Offline mode, explicit model | After successful selection resolution, `/screen` returns 422: `Retrieval model selection requires live mode`. A damaged fine-tuned record fails earlier with 503. |
| Live `gemini` | Gemini embedding model, dimension 256. |
| Live model omitted/null | Server settings, normally Gemini; an environment-configured encoder is preserved rather than replaced by the active fine-tuned selection. |
| Live `finetuned` | Active catalog entry for this Chroma backend, dimension 768; configuration includes revision and checkpoint SHA256. With no selection record, it uses the MS3 `train-20261110-t4-r3` default. |

Both live choices use the configured Gemini generation model for criterion
assessment. Selecting a retrieval model does not select a different generator.
Consumers should read returned provenance, not infer actual execution from the
requested label alone. `/screen` resolves the settings once and uses that same
snapshot for workflow execution, response provenance and screening logs. A
switch or rollback after resolution changes subsequent requests, not the
encoder settings of an in-flight request.

`GET /ready?retrieval_model=finetuned` checks data and the selected index in live
mode. Reports include `ready`, `mode`, `check_scope`, `checked_at`,
`cache_ttl_seconds`, `model_access` and `checks`. Each request resolves the
selection before considering cached readiness. The API retains only the latest
resolved `Settings` and probe for each selector. With unchanged settings, the
probe may reuse its report for 30 seconds. An observed change in resolved settings
creates a fresh probe; returning from that observed change to an older encoder
does not revive its earlier cached report.
No API restart is needed after switch or rollback.

- Live readiness checks existing index compatibility/counts without inference,
  and reports `model_access="NOT_PROBED"`. A 200 does not prove Gemini access,
  quota or successful inference.
- Offline readiness marks index/model access `NOT_REQUIRED`; even an accepted
  `retrieval_model` query does not validate a live encoder or index in that mode.
- A damaged fine-tuned selection returns 503 with `ready=false`,
  `check_scope="encoder_selection"` and
  `checks.encoder_selection.code="ENCODER_SELECTION_INVALID"`. This report has
  `cache_ttl_seconds=0`; the selector's prior probe is discarded. A repaired or
  removed record is resolved again on the next readiness request, with a fresh
  probe even if it returns to the same encoder.
- Failed readiness uses the report shape, not the `/screen` error envelope;
  inspect `checks` for failure codes.

The 30-second report cache still applies to changes within an unchanged index
configuration; it is not a guarantee of immediate detection of every index
mutation. The API compares resolved settings rather than selection-record
revisions: an A → B → A switch entirely between readiness requests can still
reuse A's unexpired report. Readiness is a point-in-time check, not a lock on the
next request.
Selection-error handling does not repair the record or silently fall back.

Part B's [switch/rollback CLI](../../services/rag_workflow/INDEX_VERSIONING.md)
owns catalog activation and index verification. The HTTP API exposes no index
mutation endpoint, and this integration adds no active-encoder field to
`/metadata` or `/ready`. Use `index-status` for the catalog name and inspect
screening provenance for the encoder configuration used by that result.

## Primary user flow

This logical flow shows backend interactions. In D's Compose layout, browser API
requests and responses pass through the Nginx frontend on the same origin.

```mermaid
sequenceDiagram
    actor User
    participant UI as Browser UI
    participant API as Integrated FastAPI app
    participant Flow as ScreeningWorkflow
    participant Data as DataStore / manifest
    participant Retrieval as Retriever / selected index
    participant Model as Embedding / Gemini providers
    UI->>API: GET /health, /patients, /metadata
    API-->>UI: Mode, patient list, data metadata
    User->>UI: Select patient
    UI->>API: GET /patients/{patient_id}
    API-->>UI: Normalized patient
    User->>UI: Enter question and run screening
    UI->>API: POST /screen
    API->>API: Validate ScreenRequest
    API->>API: Resolve retrieval settings once
    API->>Flow: screen(request, resolved settings)
    Flow->>Data: Load/validate patient and trial subset
    alt Offline mode
        Flow->>Retrieval: BM25 retrieval
        Retrieval-->>Flow: Candidate trials
        Flow->>Flow: Rules; unsupported criteria stay UNKNOWN
    else Live mode
        Flow->>Retrieval: Retrieve using selected encoder/index
        Retrieval->>Model: Embed query as needed
        Model-->>Retrieval: Query vector
        Retrieval-->>Flow: Candidate trials
        Flow->>Model: Assess unresolved criteria; explain results
        Model-->>Flow: Judgments/explanations or provider errors
    end
    Flow->>Flow: Validate evidence and aggregate results/errors
    Flow-->>API: ScreenResponse
    API->>API: Log with the same resolved settings
    API-->>UI: 200 result or 503 ERROR; X-Request-ID
    UI-->>User: Results, evidence, missing information and warnings
```

Validation or raised exceptions use the HTTP-error paths above and may stop this
sequence before a `ScreenResponse` is constructed. For Part A, preserve request
field names and technical/clinical state distinctions. For Part B, retain
per-request model selection and coordinate any changes to index/error semantics
with C before frontend or test expectations change.
