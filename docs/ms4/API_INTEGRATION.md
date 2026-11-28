# MS4 Part C: dependency integration and model selection

This page records the earlier 18-test C increment. For the subsequent integration
with B's active-encoder selection, see [selection integration](SELECTION_INTEGRATION.md).

This increment closes gaps identified after the [initial backend baseline](BACKEND_VALIDATION.md).
It adds 18 integration tests and hardens the screening API's index-error boundary.
The current interface is documented in the [API Contract](API_CONTRACT.md).
The later [C/D compatibility check](D_INTEGRATION.md) records the combined host
test run against D's infrastructure branch and its separate successful CI run.

## Backend changes

Previously, lower-level index errors could reach the API's patient-input handlers:
an index connection `ValueError` or malformed JSON became HTTP 422, and malformed
query metadata could become HTTP 404 `Patient not found`. A query hit containing
an unrelated criterion ID could also enter an otherwise successful response.

The backend now:

- Translates unclassified errors specifically during `VectorIndex` construction
  and query handling to `ProviderError("INDEX_UNAVAILABLE", ...)`, with the fixed
  message `Retrieval index unavailable or invalid.` The existing workflow emits
  a full HTTP 503 `ScreenResponse`, `result_status=ERROR`, and no candidates.
- Validates query hit IDs before combining vector and lexical rankings: the
  trial must belong to the selected manifest, and its criterion must belong to
  that trial in the source data.
- Treats missing keys in artifacts loaded during workflow initialization as
  HTTP 503 `ARTIFACT_UNAVAILABLE`.

Existing `ProviderError` codes remain intact. A direct `TimeoutError` still
returns 504; a timeout wrapped by the Gemini adapter follows its existing 503
error path. Unknown patients remain 404, invalid patient input remains 422, and
partial assessments remain explicit HTTP 200 `PARTIAL` results. Error envelopes
were not globally unified. Index rebuild, switching and rollback implementation
were not changed.

## Test boundary and scenarios

The new tests exercise the real integrated FastAPI app, `ScreeningWorkflow`,
file-backed `DataStore`, retrieval, judgment validation, aggregation and embedded
Chroma. A tiny synthetic trial/patient fixture provides a known age rule and two
criteria requiring interpretation. Model adapters produce deterministic vectors
and explicit UNKNOWN judgments. The SDK timeout case uses the real Gemini
adapter with a mocked SDK client. No real model service, credentials, checkpoint
or cloud resources are used.

Some test responses have `mode=live` because they exercise live routing. This is
integration evidence with model doubles, not evidence of real Gemini or
fine-tuned-model inference, retrieval quality or clinical accuracy.

| Module | Tests | Behaviors covered |
| --- | --- | --- |
| [Dependency failures](../../services/rag_workflow/tests/test_api_dependency_failures.py) | 12 | Missing index; Chroma connection/query failure; corrupt manifest; missing/malformed/foreign query metadata; direct and SDK-wrapped timeouts; failed/invalid assessments; explanation fallback; incomplete data manifest; preserved patient-input 4xx behavior. |
| [Model selection](../../services/rag_workflow/tests/test_api_model_selection.py) | 6 | Gemini → fine-tuned → Gemini selection without state leakage; configured default/null selection; real matching index versions and isolated readiness caches; missing selected index without silent fallback; offline and invalid-selector behavior. |

Failure tests check the returned HTTP/result/error states, request-ID correlation,
provider cleanup and preservation of known assessments and supporting evidence.
Malformed dependency messages are not reflected in responses or application logs.
Model tests verify actual vector lookup and encoder usage alongside provenance;
they do not replace the whole workflow or the index with a successful response.

The fixture helper is [api_fixtures.py](../../services/rag_workflow/tests/api_fixtures.py).
It creates temporary files and indexes, leaving the shared demo data unchanged.

## Recorded verification

Run date: **2026-11-23**, Linux/Python 3.12.14, the existing host virtual
environment with the committed API/dev dependencies.

| Verification | Result |
| --- | --- |
| Full `services/rag_workflow/tests` discovery | 117 tests: **112 passed, 5 skipped**, no failures/errors. |
| Full `services/frontend/tests` discovery | **5 passed**, no failures/errors. |
| Combined discovery | **122 tests: 117 passed, 5 skipped**, no failures/errors. |
| New integration methods included above | **18 passed**, none skipped. |
| Actual localhost HTTP checker after the fixes | **8/8 passed**, using a separate offline Uvicorn process. |
| Ruff on changed Python files | Passed. |

Four skips require the optional torch/transformers dependencies; one requires
DVC. Their names and reasons are recorded in the evidence. These skips are not
counted as passes. This environment's dependency set differs from the `rag-api`
image, so its skip count must not be conflated with Jessie's earlier baseline.
No new coverage percentage is claimed.

Evidence:

- [Integration record](evidence/api-integration.json): exact test counts, commands,
  skips, tested source hashes and raw-log hashes. The source state is identified
  as worktree changes on the recorded base commit.
- [Actual HTTP report](evidence/api-http-integration.json): eight check results,
  readiness and offline screening summary.
- Raw logs in ignored `artifacts/ms4/`: `rag-regression-tests.log`,
  `application-regression-tests.log`, `api-http-integration.json` and
  `api-integration-server.log`. `dependency-tests-before.log` and
  `index-identity-before.log` retain the targeted pre-fix failures.

The earlier 51-test baseline is preserved separately. The counts here cover both
complete Python test directories plus the new tests, not just that subset.

## Commands for C and D

From the repository root, use the environment setup in
[backend validation](BACKEND_VALIDATION.md#reproduce-the-host-baseline).
Run just the new integration tests:

```bash
TRIALMATCH_MODE=offline CHROMADB_HOST= ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  services.rag_workflow.tests.test_api_dependency_failures \
  services.rag_workflow.tests.test_api_model_selection -v
```

For full backend/application regression:

```bash
TRIALMATCH_MODE=offline CHROMADB_HOST= ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  discover -s services/rag_workflow/tests -v

TRIALMATCH_MODE=offline CHROMADB_HOST= ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  discover -s services/frontend/tests -v
```

D's `yixiao/ms4-infra` branch incorporates Jessie's coverage entry point and
discovers these directories with pytest. After integrating D, use `make coverage`
or `bash scripts/ms4/check_coverage.sh`; its dedicated test image and `demo/` mount
already support C's tests. No duplicate coverage script is needed. See the
[C/D compatibility check](D_INTEGRATION.md) for ports, verified discovery and the
combined host results. The older container command in the baseline is historical.

## Handoff and remaining integration

- **A:** retain the existing handling of a 503 full `ScreenResponse`; display
  `INDEX_UNAVAILABLE` as a dependency problem, not a patient screening barrier.
  Keep PARTIAL results and their evidence visible.
- **B:** existing `gemini`/`finetuned` selection is tested, including rejection of
  missing/mismatched query data. Agree any new selection/switching interface,
  index identity, readiness invalidation and in-flight request behavior before
  integrating the new migration implementation.
- **D:** the existing coverage runner includes C's new tests and passed in the
  combined host check. Run the complete workflow on the combined C/D revision
  and collect its reports. D's green CI run predates C integration; the earlier
  Docker DNS blocker in this local environment was not resolved or retested.
- **Jessie:** use the interface, scenario table and recorded results for the
  design/test documentation; complete system acceptance after module integration.

Combined C/D Docker startup, GitHub Actions and browser E2E still need verification.
Actual live-model behavior and B's final index-switch/rollback integration remain
separate work as well.
