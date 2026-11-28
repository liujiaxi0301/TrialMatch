# API and Monitoring

Locally, Nginx serves the web page and proxies requests to FastAPI.
The [Cloud Run deployment](https://trialmatch-15733748057.us-east1.run.app)
hosts the page and API together using the standalone image target.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| `GET /health`, `GET /metadata` | Service mode, data and manifest information. |
| `GET /ready` | 200 when data/index checks pass, otherwise 503. Checks cache for 30 seconds while the selected settings stay unchanged. |
| `GET /patients`, `GET /patients/{patient_id}` | Patient list and selected record. |
| `POST /screen` | Candidate trials, assessments, evidence and provenance. |
| `GET /docs`, `GET /openapi.json` | Interactive documentation and schema. |

Live requests accept `retrieval_model=gemini` or `finetuned` in the JSON body.
`/ready` accepts it as a query parameter. Readiness checks do not call Gemini or
verify inference quota; `model_access=NOT_PROBED` reflects that limit.
The fine-tuned encoder selection is re-read per request; switching or rollback
starts a fresh readiness probe. A damaged selection record returns 503 with
`ENCODER_SELECTION_INVALID`. No restart is needed.
See the [request and response guide](../services/rag_workflow/README.md#api-contract).

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
make coverage
```

The existing host-side HTTP checker can make one actual screening request:

```bash
uv run --locked python scripts/verify_api.py \
  --base-url http://localhost:8080 --require-operations --screen \
  --output artifacts/api/http.json
```

For the public cloud app, use
`--base-url https://trialmatch-15733748057.us-east1.run.app`; no token is needed.
Without `--screen`, the checker does not call a model. In live mode a screening
request uses Gemini. Redirects do not count as successful API responses.
