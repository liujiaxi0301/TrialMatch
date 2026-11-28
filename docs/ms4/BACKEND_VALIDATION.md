# MS4 Part C: initial backend validation

This page preserves the first, pre-change baseline. For subsequent backend fixes,
new tests and the latest results, see [API integration](API_INTEGRATION.md).
The later B/C handoff and current combined verification are recorded in
[selection integration](SELECTION_INTEGRATION.md).

This first increment documents the existing API and reproduces its local
baseline before changing backend behavior. It is based on `milestone3` commit
`5a114b99aea24bddb3455b5bf31bc4c1dafd7766`, on branch `xuyang/ms4-backend`.
At baseline collection, no production code, tests, dependency locks or Docker
configuration were changed. Subsequent C changes on `xuyang/ms4-backend` use
the B base that includes D's infrastructure; their verification was recorded from
the worktree before commit. The results, counts and source hashes below continue
to describe the original baseline, not that integration.

## Recorded results

Run date: **2026-11-23**. Runtime: Linux x86_64, Python 3.12.14, a repository-local
virtual environment installed from the committed `uv.lock`, and offline mode.

| Check | Result | Scope |
| --- | --- | --- |
| API operations | 25 passed | HTTP behavior, validation, errors, readiness, request IDs, logs and checker self-tests. |
| Integrated application | 5 passed | Static routes, patients, offline screening, evidence and embedded Chroma persistence. |
| Workflow | 21 passed | Rules, UNKNOWN, patient validation, provider-failure handling, source integrity and index compatibility. |
| Combined test command | **51 passed, 0 failed, 0 errors, 0 skipped** | Existing tests; 13.258 seconds in this run. |
| Actual local HTTP checker | **8/8 passed** | A separate Uvicorn process, including one actual offline screening request. |
| Data validation | Passed | Hash checks for trials, criteria and patients; 1,313 trials and 18,456 criteria; criteria reproduced from committed trial records. |
| Docker startup | Blocked | Current execution environment: read-only Docker configuration path, then container DNS failure during dependency installation. |

The eight HTTP checks cover health, patients, OpenAPI, three invalid/missing-input
requests, readiness and screening. The checker also requires request IDs. Its
screening request returned one candidate with `result_status=OK`; that candidate
still needed more information. Technical success is separate from eligibility.

Evidence prepared for this branch:

- [Baseline metadata](evidence/backend-baseline.json): commands, package versions,
  test counts, source hashes, failed startup attempts and raw-artifact hashes.
- [Local HTTP report](evidence/api-http.json): individual checks, readiness and
  screening summary from the existing checker.
- [API Contract](API_CONTRACT.md): current request/response behavior and handoffs.

Raw logs and captured examples are under ignored `artifacts/ms4/`:
`backend-tests.log`, `api-http.json`, `api-http.log`, `api-server.log`,
`api-examples.json`, `openapi.json`, `data-validation.log`,
`host-environment-setup.log`, `local-startup.log` and
`local-startup-writable-cache.log`. They are local run artifacts, not files
included automatically when this branch is pushed.

## Reproduce the host baseline

These commands reproduce the historical single-Uvicorn arrangement: the API and
UI shared port 8080. D's newer Compose arrangement uses Nginx on host port 8080,
the direct API on host port 8081, and `TRIALMATCH_SERVE_UI=false` in the backend.
See the current [runtime distinction](API_CONTRACT.md) before combining branches.

Run from the repository root, with Python 3.12 and uv installed. Use a clean shell
without custom `TRIALMATCH_*` data paths or embedding/checkpoint overrides.
The committed synthetic demo data is sufficient; no cloud credentials or model
download is needed for this scope.

```bash
mkdir -p artifacts/ms4
UV_CACHE_DIR=/tmp/trialmatch-ms4-uv-cache \
  uv sync --frozen --no-default-groups --group api --group dev --python 3.12
.venv/bin/python prepare_data.py

TRIALMATCH_MODE=offline CHROMADB_HOST= ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  services.rag_workflow.tests.test_api_operations \
  services.frontend.tests.test_application \
  services.rag_workflow.tests.test_workflow -v
```

Start the integrated app in one terminal:

```bash
TRIALMATCH_MODE=offline CHROMADB_HOST= \
  TRIALMATCH_ARTIFACTS=artifacts/ms4/server ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m uvicorn \
  services.frontend.app:app --host 127.0.0.1 --port 8080
```

After Uvicorn reports startup complete, run in another terminal:

```bash
.venv/bin/python demo/ovrz/verify_ms3_api.py \
  --base-url http://127.0.0.1:8080 --require-operations --screen \
  --output artifacts/ms4/api-http.json
```

The HTTP checker exits nonzero on failure. Stop the temporary server with Ctrl-C
after collecting the result. Use `services.frontend.app:app`, which includes the
patient-detail/metadata routes and serves the UI as well as the screening API.

## Historical container handoff to D

The baseline's unmodified `make up` command was attempted. Docker first could not create
`/home/agent/.docker/buildx` because the directory was read-only. A retry with
`DOCKER_CONFIG=/tmp/trialmatch-ms4-docker` reached the image build but dependency
installation could not resolve the package host. A host-network container DNS
probe also failed. This does not establish a Dockerfile defect or a successful
clean-checkout Docker run for this C checkout. D's later infrastructure evidence
is described separately below.

The baseline exposed an independent test-runner requirement: API operations
tests import `demo.ovrz.verify_ms3_api`, but that baseline's normal `rag-api`
image and Compose mounts did not include `demo/`. The command below records the
original proposed explicit demo mount; it was **not executed successfully in
Docker in this run**. It is retained as historical handoff context, not the
preferred command for D's updated test setup.

```bash
docker compose run --rm --no-deps -T \
  -e TRIALMATCH_MODE=offline -e CHROMADB_HOST= \
  -e ANONYMIZED_TELEMETRY=False -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/demo:/app/demo:ro" \
  rag-api python -m unittest \
  services.rag_workflow.tests.test_api_operations \
  services.frontend.tests.test_application \
  services.rag_workflow.tests.test_workflow -v
```

These tests use temporary embedded Chroma stores; this command does not verify
the Compose Chroma service or network. Jessie's separate coverage command is
`bash scripts/ms4/check_coverage.sh` on `jiaxi/ms4-validation` commit
`7b95a35f98803f6f7a1380469a8555527b7ffdeb`. That script is not part of this branch's
MS3 baseline. Reuse it through team integration rather than creating a second
coverage implementation.

## Updated D integration target

D's infrastructure branch at `91f163ffbf30c7b5853b16625da19683818fd61f` now supplies
an `api-tests` service with `demo/` mounted read-only and a dedicated coverage
runner. After integrating C with that branch, use D's existing entry point:

```bash
make coverage
# Equivalent entry point:
bash scripts/ms4/check_coverage.sh
```

The [test Compose configuration](https://github.com/liujiaxi0301/TrialMatch/blob/91f163ffbf30c7b5853b16625da19683818fd61f/docker-compose.test.yml)
and [coverage script](https://github.com/liujiaxi0301/TrialMatch/blob/91f163ffbf30c7b5853b16625da19683818fd61f/scripts/ms4/check_coverage.sh)
provide the image build, mounts, offline test settings, reports and failure gate.
The old manual `rag-api` command above is not needed for that runner. Neither
entry point was executed successfully during this baseline run; later combined
verification is recorded in [selection integration](SELECTION_INTEGRATION.md).

D's [Actions run 45272384781](https://github.com/liujiaxi0301/TrialMatch/actions/runs/45272384781)
at `91f163f` succeeded with the `application`, `pipeline` and `retrieval-runtime`
jobs. This is evidence for that D revision; C's additions were not included
in that run. It does not establish Docker or CI results for the combined C/D
checkout. In D's Compose layout, browser checks target Nginx at
`http://localhost:8080`, while direct API checks target `http://localhost:8081`.

## Next C increment and dependencies

| Priority | Work | Completion evidence |
| --- | --- | --- |
| 1 | Share the current contract with A and B, including distinct HTTP/result/criterion states and existing error shapes. | Request/response examples and agreed expectations; retain current frontend compatibility until a change is agreed. |
| 2 | Add API integration tests for lower-level provider/index failures while retaining the actual workflow. | Assertions on error propagation, retained partial results/evidence and request IDs; avoid replacing the entire workflow as the only proof. |
| 3 | Exercise `gemini`/`finetuned` request selection and matching readiness selection. | Tests at the provider/index boundary; separately record any real live-model run. |
| 4 | Integrate B's finalized index selection/switching interface. | Agreed version identity, error codes, readiness-cache handling, in-flight request behavior and rollback ownership. |
| 5 | Deliver C's final commands and evidence to D and Jessie. | Reproducible commands, passing reports and updated runtime/API documentation. |

Existing tests already cover many 422/404/503/504/PARTIAL mappings. Several API
error tests replace `ScreeningWorkflow.screen`; those prove the adapter's mapping
but do not by themselves prove that a lower-level failure traverses the complete
call chain. Reuse the existing suite and extend that missing boundary coverage.

This result is not GitHub Actions evidence, browser E2E, live Gemini/fine-tuned
inference, index migration/rollback validation, or full-suite coverage. Jessie's
reported 83% and 103 passed/1 skipped were not rerun here. The 51 tests are an
intentional Part C subset, not a conflicting full-suite total. The run emitted
an existing Starlette TestClient/httpx deprecation warning; all tests still
passed and dependencies were left unchanged.
