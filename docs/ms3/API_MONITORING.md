# Module E — API integration, monitoring and testing

Owner: Mengze Zhao (Orange Chicken). Baseline: `yixiao/ms3-infra`,
`50dc2ca0e5ff8a7a932ff96a126d3575e7f156ef` (`yixiao/ms3-infra`, November 11).
Development branch: `ovrz/ms3-api-monitoring-testing`.

## Scope and integration

Reuse the existing FastAPI application, frontend, screening schemas, retrieval,
and clinical rules. Module E adds operational logs, diagnostics and HTTP checks.
It does not train models, create benchmark labels, or deploy/change Cloud Run,
Chroma, IAP, IAM or the budget handler. Cloud deployment remains Module D's work.

The October 27 group handoff specifies structured logs, local/error tests,
readiness, cloud API checks, documentation and evidence. On October 28 Yixiao
reported the A/D pipeline and deployment working on `yixiao/ms3-infra`.
That report and the repository's deployment links are context, not a fresh
verification of the current cloud revision.

## Operational contract

- Existing `GET /health`: data/manifest health, with the original response unchanged.
- New `GET /ready`: 200 when data and the configured index are usable, otherwise 503.
  Offline mode requires no model or index. Live mode verifies the existing Chroma
  index against its data/model manifest and checksum. It does not build/restore
  an index or make a billable inference request. Results are cached for 30 seconds.
  `model_access=NOT_PROBED` explicitly means permissions, quota and inference
  availability are not verified; a successful live `/screen` is stronger evidence.
- Existing `/patients`, `/patients/{patient_id}`, `/metadata`, `/screen`, `/docs`,
  `/openapi.json`, `/` and static assets remain available.
- Every application HTTP response carries a fresh `X-Request-ID`. Screening
  results retain their separate `run_id`; logs link both identifiers.
- `/screen`: 200 for a valid response, including explicitly labeled PARTIAL;
  404 for missing patient; 422 for invalid input; 503 for missing artifacts,
  index/provider failures or `result_status=ERROR`; 504 for a raised TimeoutError;
  unexpected errors return sanitized 500. System errors never become a clinical
  screening barrier. Existing provider timeouts can be wrapped as
  `PROVIDER_UNAVAILABLE` and therefore return 503. There is no new overall request
  deadline or server-side cancellation guarantee.

## Structured logging

Standard Python logger `trialmatch.api` writes one JSON object per line to stdout.
Cloud Run collects these records into Cloud Logging without a new dependency.

- `http_request`: request ID, route template, method, status code, latency in ms.
- `screening_completed`: request/run IDs, mode, result status, candidate count,
  UNKNOWN count, barrier count, embedding/generation requests, cache hits,
  token usage and error codes. Live events also include the configured embedding
  provider, model, dimension, generation model, and a pinned encoder revision or
  checkpoint SHA256 when present. Offline events say `embedding_provider=NOT_USED`.
  Cached calls may have zero provider requests.
- `request_failed`: exception type only; no exception message or stack payload.
- `readiness_checked`: readiness result and check scope.
- Valid Cloud Trace headers are mapped to `logging.googleapis.com/trace`.

An allowlist excludes questions, patient IDs/records, evidence text, authorization
headers, credentials and raw exception messages from these application events.
The route is `/patients/{patient_id}`, not the actual ID. Platform request logs
and Uvicorn access logs are separate and may contain URL paths; never put tokens
or patient facts in query strings. Input validation responses remain API responses,
not log payloads. Application logs are not a clinical audit database.

Gemini's existing flat `embedding_requests`, `generation_requests`, `cache_hits`
and token counts retain their original meanings. A separate encoder's nested
`metrics.retrieval_encoder` is flattened into `retrieval_embedding_requests`,
`retrieval_embedded_texts`, and `retrieval_cache_hits`. These counters are distinct;
do not add cache hits and call that a request count. Only nonnegative integer
counters and explicitly allowed model metadata enter logs, never checkpoint
paths, nested payloads or arbitrary metric keys. Logging does not load an encoder.

## Run tests and local HTTP verification

```bash
uv run python -m unittest services.rag_workflow.tests.test_api_operations -v
uv run python -m unittest discover -s services/rag_workflow/tests -v
uv run ruff check services/rag_workflow/api.py services/rag_workflow/observability.py services/rag_workflow/readiness.py services/rag_workflow/tests/test_api_operations.py demo/ovrz/verify_ms3_api.py
```

Start the existing app with `make up`, or use a local Python environment:

```bash
TRIALMATCH_MODE=offline uv run python -m uvicorn services.frontend.app:app --host 127.0.0.1 --port 8083 --no-access-log
uv run python demo/ovrz/verify_ms3_api.py --base-url http://127.0.0.1:8083 --require-operations --screen --output artifacts/ms3-e/local-http.json
```

On PowerShell set `$env:TRIALMATCH_MODE='offline'` before starting Python.
The fixed JSONL datasets must retain the repository's LF bytes: automatic Windows
CRLF conversion changes their checksums. This development checkout uses local-only
Git attributes to preserve the three processed files; no source data or manifest
hashes were changed.
The smoke checker makes real HTTP requests. `--screen` opts into one screening
request; on a live service this may incur Gemini usage. Without it, only health,
patient listing, OpenAPI and invalid-input checks run. It does not follow redirects,
so an IAP login page cannot be mistaken for a passing JSON API response.

## Cloud handoff and monitoring evidence

Existing cloud URL: https://trialmatch-15733748057.us-east1.run.app
Project: `trialmatch-ac215-yixiao`; region: `us-east1`; service: `trialmatch`.
The service is protected by IAP. Browser login and programmatic authentication
are different; do not disable IAP or make the service public to run a test.
Use an approved short-lived IAP token or a Module D-approved authenticated proxy.
The CLI accepts a token via `--token-stdin`, never a command-line token argument.
It never saves tokens, cookies or authorization headers in its report.

After D deploys a revision containing this branch, run the same HTTP checks against
that URL with `--require-operations`. An older deployment may lack `/ready` and
the new logs; baseline checks without that flag do not establish E deployment.

In GCP Console, open Logging > Logs Explorer and use:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="trialmatch"
jsonPayload.message="http_request"
```

Add `jsonPayload.status_code>=400` for errors, or
`jsonPayload.request_id="<returned-X-Request-ID>"` to trace one request.
For screening summaries filter `jsonPayload.message="screening_completed"`.
Capture one successful request, one 422 invalid request, and their matching logs.
Use the native Cloud Run metrics for request volume, error rate and latency.
Report PARTIAL results and UNKNOWN coverage separately from HTTP success.
Do not claim latency percentiles from a single screening run.

Final evidence under `docs/ms3/evidence/`: automated test results, actual HTTP
check report, cloud revision tested, success/error log screenshots, and API docs
screenshot. Synthetic cases only. Screenshots must come from actual runs.
Local passing tests do not establish cloud readiness or clinical accuracy.

References: [Cloud Run logging](https://docs.cloud.google.com/run/docs/logging),
[IAP programmatic authentication](https://docs.cloud.google.com/iap/docs/authentication-howto).

## Integration handoff

The single Module E commit changes `services/rag_workflow/api.py`, adds
`observability.py` and `readiness.py` beside it, the API operations test module,
the host-side HTTP verifier, this guide and four small evidence files. No frontend,
model, dataset, Dockerfile, cloud script, dependency lock or benchmark is changed.

The API Dockerfile already copies `services/rag_workflow/*.py`; it includes the new
runtime modules automatically when the image is rebuilt. Rebuild/deploy the image
after merging this commit. The HTTP verifier runs on the host against the exposed
API URL; it need not be copied into the production image. Module D owns deployment
and any Cloud Run probe configuration. Adding `/ready` does not configure a cloud
startup/liveness probe by itself.

## Recorded verification — November 11, 2026 (America/New_York)

- All 25 Module E tests passed, including safe logging of separate BioClinical
  metrics, pinned model identity, malformed diagnostics, and negative smoke checks.
- Real localhost offline and live HTTP checks both passed (8/8 each). Live
  screening used the public Synthea synthetic sample, an existing 607-vector
  Gemini snapshot, 1 embedding call and 5 generation calls with no cache hits.
  The request took 13.375 seconds. This one run does not establish performance
  percentiles or clinical accuracy; 22 of 23 candidate criteria were UNKNOWN.
- Temporary E overlays on infra `50dc2ca0` and Jenny `55e88bac` each passed all
  25 E tests in the default Gemini/offline configuration. No BioClinical model
  inference or trained checkpoint loading was exercised by these tests.
- Ruff passed for all five Module E Python files. The broader RAG test discovery
  ran 97 tests: 77 passed, 18 errored and 2 skipped. Errors were Windows DVC cache
  deletion permissions and Chroma file locks; optional Torch tests were skipped.
  No assertion failure was reported. The whole suite is not passing on Windows.
- Cloud Run metadata was readable (200); revision `trialmatch-00004-hpk` reported
  `CONDITION_SUCCEEDED` with IAP enabled. Anonymous API checks returned 401.
  This establishes access control, not an authenticated E API run. This commit
  has not been deployed, and cloud E logs/screenshots remain a post-deployment
  integration check with Module D.

See [verification.json](evidence/module-e/verification.json),
[offline HTTP checks](evidence/module-e/offline-http.json),
[live HTTP checks](evidence/module-e/live-http.json), and
[actual application logs](evidence/module-e/application-logs.jsonl).
Large test logs, temporary compatibility snapshots, databases and caches stay in
ignored `artifacts/ms3-e/20261111/` rather than Git.
