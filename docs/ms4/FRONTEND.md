# Frontend and browser testing

## Scope and integration

The integrated frontend adds criterion-level human review and browser tests to
the existing screening UI. The original backend response remains unchanged.

The frontend uses relative URLs: `GET /health`, `GET /patients`,
`GET /patients/{patient_id}`, `GET /metadata`, and `POST /screen`.
Screening sends `patient_id`, `question`, `top_k` (1–5), plus
`retrieval_model` in live mode. Rendering uses the existing response fields:
`run_id`, `patient_id`, `patient_reference_date`, `result_status`, and
`candidate_trials`. Each candidate supplies its trial ID, status, coverage,
criterion assessments, evidence ledger and missing information.

The current API has no human-review save endpoint. Review annotations remain
session-only and can be exported as JSON; server-side persistence is not implemented.

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

## Run locally

The existing Dockerfile copies the whole static directory, including the new
assets. No new runtime package or container change is needed. Local Compose mounts static files, so refreshing shows edits. Deployment images
must be rebuilt after source changes.

```bash
make up
make e2e
```

The existing Compose test image uses locked `@playwright/test` 1.56.1 and Chromium.
Tests expect offline mode, the committed 25-patient snapshot and `top_k` up to 3.
Compose supplies `BASE_URL=http://frontend:8080`; the host UI is
`http://localhost:8080`. Reports go to `artifacts/ms4/` through the existing
`/reports` volume. `make e2e` needs the services started first.

## Verification

The suite includes actual browser-to-API screening, evidence rendering, review/export,
trial isolation, patient selection, session reset and narrow-screen tests. Empty
responses, provider failures, cancellation and timeouts deliberately intercept only
`/screen` to reproduce those states. HTML-looking review text must render as text.
`make e2e` executes the suite through Nginx and the offline backend. Current integrated
results are in [Test Documentation](TEST_DOCUMENTATION.md).
