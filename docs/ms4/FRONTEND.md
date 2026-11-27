# Frontend and browser E2E (Part A)

## Scope and integration

This work starts from `yixiao/ms4-infra` at
`91f163ffbf30c7b5853b16625da19683818fd61f`, on the separate
`ovrz/ms4-frontend-e2e` branch. It adds criterion-level human review to the
existing UI and extends the existing Playwright suite. Backend, cloud and
container source files are unchanged.

The frontend uses relative URLs: `GET /health`, `GET /patients`,
`GET /patients/{patient_id}`, `GET /metadata`, and `POST /screen`.
Screening sends `patient_id`, `question`, `top_k` (1–5), plus
`retrieval_model` in live mode. Rendering uses the existing response fields:
`run_id`, `patient_id`, `patient_reference_date`, `result_status`, and
`candidate_trials`. Each candidate supplies its trial ID, status, coverage,
criterion assessments, evidence ledger and missing information.

The current infra contract works without an API change. As of November 26,
2026, no new Sharon MS4 backend branch or human-review save endpoint was found
among the remote branches. Compatibility with that unpublished API is therefore
not verified. Part C should provide the branch/PR and the request, response and
error contract before server-side review saving is added.

## User flow

1. Search for a patient ID and select the synthetic patient. Review the reference
   date and source records; the question is scoped to that patient.
2. Enter a screening question, choose the number of trials, and select
   **Run screening**. The loading indicator appears and conflicting controls
   are disabled. Cancel stops waiting in the browser; the server may continue.
3. Review candidate trials, their screening status, missing information and
   **Criteria & evidence**. Inclusion MET and exclusion MET have different
   meanings; UNKNOWN remains explicit.
4. Open **Add a human assessment** under a criterion. Choose MET, NOT_MET or
   UNKNOWN, enter a reason, and select **Apply local review**. The original
   assessment stays visible. **Restore original assessment** removes the
   current annotation while retaining the local change history.
5. Select **Export human review**, inspect the JSON and download it. The export
   links changes to the original run, patient, trial and criterion. **Export /
   view JSON** continues to export the unchanged backend response.

Human reviews exist only in memory for this screening session. Refreshing,
changing patient/model or starting another screening clears them. The UI tells
users to export first. Annotations do not change backend scores, trial statuses
or original evidence. No patient annotations are stored in browser localStorage.
The export uses `trialmatch-human-review-v1`, includes UTC timestamps and an
apply/restore history, and declares `persistence: local_export_only`. It is not
a server audit log or an authenticated reviewer record.

An empty candidate list has an explicit message. HTTP failures show an error;
cancel and the five-minute timeout restore controls. Screening POST requests are
not automatically retried. These states are covered by the browser tests below.

## Files

- `services/frontend/static/review.js`: session state, review controls,
  required reasons, restore and JSON export. User text uses DOM text content.
- `services/frontend/static/review.css`: review controls in dark/light themes
  and on narrow screens.
- `services/frontend/static/app.js`: mount review controls after rendering;
  clear review state with the old results.
- `services/frontend/static/index.html`: load the two review assets.
- `services/frontend/e2e/review.spec.js`: added browser scenarios.
- `services/frontend/e2e/screening.spec.js`: existing real screening tests.
- `services/frontend/e2e/playwright.config.js`: shared browser configuration;
  `REPORT_DIR` optionally changes the artifact location.

## Run and hand off to Part D

The existing Dockerfile copies the whole static directory, including the new
assets. No new runtime package or container change is needed. Rebuild after
changing static files; an already built image does not update itself.

```bash
make up
make e2e
```

The existing Compose test image uses locked `@playwright/test` 1.56.1 and Chromium.
Tests expect offline mode, the committed 25-patient snapshot and `top_k` up to 3.
Compose supplies `BASE_URL=http://frontend:8080`; the host UI is
`http://localhost:8080`. Reports go to `artifacts/ms4/` through the existing
`/reports` volume. `make e2e` needs the services started first.

For a local Python backend serving the UI, set `TRIALMATCH_MODE=offline` and
`TRIALMATCH_SERVE_UI=true`, then run the following from a prepared project Python
environment. This is a separate host test path, without Nginx:

```bash
python -m uvicorn services.frontend.app:app --host 127.0.0.1 --port 8090
```

In another terminal, install the existing locked browser dependencies with
`npm ci --prefix docker/frontend`. Set `NODE_PATH` to the absolute
`docker/frontend/node_modules` directory, `BASE_URL=http://127.0.0.1:8090`, and
`REPORT_DIR` to an absolute output directory. Install Chromium and run:

```bash
node docker/frontend/node_modules/@playwright/test/cli.js install chromium
node docker/frontend/node_modules/@playwright/test/cli.js test --config services/frontend/e2e/playwright.config.js
```

If `PLAYWRIGHT_BROWSERS_PATH` is customized, use the same value for installation
and test execution. The suite produces an HTML report, JUnit XML, screenshots,
and traces on failure. Generated browser binaries and reports stay under ignored
`artifacts/`, outside the source change.

## Verification and hand off to Part E

Local verification on November 26, 2026 uses an actual Python/FastAPI offline
backend: **13 browser tests passed**, together with **31 existing Python API
tests** (`services.frontend.tests.test_application` and
`services.rag_workflow.tests.test_api_operations`). The successful screening, evidence rendering, review/export, trial
isolation, patient selection, session reset and narrow-screen tests do not
intercept the API. Empty response, provider failure, cancel and timeout cases
deliberately intercept only `/screen` to reproduce those states. These are UI
behavior tests, not measurements of clinical decision quality.

Results are recorded locally in `artifacts/ms4/local/browser-tests.txt`,
`browser-results.xml`, `playwright-report/index.html` and `api-tests.txt`.
Screenshots include `screening.png`, `human-review.png` and
`human-review-mobile.png`. The human-review security test deliberately includes
an HTML-looking string and verifies it is displayed as text.

The current machine has no Docker command, so this verification does not cover
the Compose/Nginx path, cloud deployment, paid model calls or the unpublished
Part C API. Part D can run the same suite through `make e2e` and collect the
container results. Part E can use the user flow above and the local screenshots
as the UI/UX chapter materials, with the session-only review limitation stated.
