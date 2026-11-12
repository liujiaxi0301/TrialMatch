# API and Monitoring

The FastAPI app serves the web page and screening API locally and on
[Cloud Run](https://trialmatch-15733748057.us-east1.run.app).
The cloud page and API are public and require no login.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /health`, `GET /metadata` | Service mode, data and manifest information. |
| `GET /ready` | 200 when data/index checks pass, otherwise 503. Cached for 30 seconds. |
| `GET /patients`, `GET /patients/{patient_id}` | Patient list and selected record. |
| `POST /screen` | Candidate trials, assessments, evidence and provenance. |
| `GET /docs`, `GET /openapi.json` | Interactive documentation and schema. |

Live requests accept `retrieval_model=gemini` or `finetuned` in the JSON body.
`/ready` accepts it as a query parameter. Readiness checks do not call Gemini or
verify inference quota; `model_access=NOT_PROBED` reflects that limit.
See the [request and response guide](../../services/rag_workflow/README.md#api-contract).

Each response includes `X-Request-ID`. Screening responses also have a separate
`run_id`; logs connect the two. Invalid input returns 422, missing patients 404,
provider/index failures 503, raised timeouts 504 and unexpected errors a sanitized
500. A partial assessment can return 200 with `result_status=PARTIAL`.
Provider timeouts wrapped as `PROVIDER_UNAVAILABLE` return 503. There is no new
server-side cancellation guarantee when a user cancels a browser request.

## Logs

The `trialmatch.api` logger writes JSON to stdout. Cloud Run sends it to Cloud
Logging. No separate logging service is needed.

| Event (`jsonPayload.message`) | Fields |
| --- | --- |
| `http_request` | Request ID, route template, method, status code, latency. |
| `screening_completed` | Request/run IDs, mode, result status, candidates, UNKNOWN/barrier counts, selected models and usage. |
| `request_failed` | Exception type without the exception message. |
| `readiness_checked` | Readiness result and check scope. |

Screening logs identify the selected embedding provider, model, dimension and
checkpoint SHA256, plus the generation model. Encoder calls/cache hits are counted
separately from Gemini calls. Questions, patient records, evidence text, credentials
and authorization headers are excluded from these application events.
Platform/Uvicorn request logs are separate and may include URL paths.

In the TrialMatch project's **Logging > Logs Explorer**, use:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="trialmatch"
jsonPayload.message="http_request"
```

Add `jsonPayload.status_code>=400` for HTTP errors, or
`jsonPayload.request_id="<X-Request-ID>"` to trace one request.
Use `jsonPayload.message="screening_completed"` for screening summaries.
Cloud Run's Metrics tab shows request volume, errors and latency.
Report PARTIAL and UNKNOWN separately from HTTP success.

## Tests and HTTP Checks

Start the local app with `make up` or `make live`, then run:

```bash
docker compose exec -T rag-api python -m unittest services.rag_workflow.tests.test_api_operations -v
```

The existing host-side HTTP checker can make one actual screening request:

```bash
uv run --locked python demo/ovrz/verify_ms3_api.py \
  --base-url http://localhost:8080 --require-operations --screen \
  --output artifacts/ms3-api/http.json
```

For the public cloud app, use
`--base-url https://trialmatch-15733748057.us-east1.run.app`; no token is needed.
Without `--screen`, the checker does not call a model. In live mode a screening
request uses Gemini. Redirects do not count as successful API responses.

## Evidence and Limits

On November 12, cloud revision `trialmatch-b7738f4` returned three candidates,
`result_status=OK` and no recorded errors for both Gemini and Fine-tuned BioClinical.
The encoder provenance matched the evaluated November 10 checkpoint; both choices
used Gemini for generation. [Online response screenshot](evidence/cloud-screening.jpg).

After public access was enabled on November 12, the page and API documentation
returned 200 without cookies or authorization headers. All eight HTTP checks passed,
including one live screening request with `result_status=OK`.

The original module checks are in [verification.json](evidence/module-e/verification.json),
[offline HTTP checks](evidence/module-e/offline-http.json),
[live HTTP checks](evidence/module-e/live-http.json) and
[application log samples](evidence/module-e/application-logs.jsonl).
Those November 11 local records are historical, not the later cloud run.
They also record Windows cache/Chroma file-lock issues in the wider test suite.
Current integration verification used macOS/Linux; it does not establish a full
Windows test pass. Successful requests do not establish clinical accuracy or
latency percentiles. Temporary logs and test outputs stay under ignored `artifacts/`.
