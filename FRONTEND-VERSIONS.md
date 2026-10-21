# Frontend versions - Ovrz

**Chenyixiao: use [frontend-v2.zip](frontend-v2.zip) for the latest UI.**

## Version 2 - latest frontend

[Download frontend-v2.zip](frontend-v2.zip)

Contains eight files under `services/frontend/static/` and `INSTALL.txt`.
Extract the archive, then merge its `services/` folder into your repository root,
replacing matching files. Copy all eight files together. No backend code, data,
credentials, dependencies or tests are included.

The frontend uses the existing `/health`, `/patients`, `/patients/{patient_id}`,
`/metadata` and `POST /screen` endpoints. Local offline use has been verified.
Live mode still depends on the backend configuration, authorized GCP credentials
and a prepared live index; this UI package does not enable or validate live mode.

For Docker deployments, rebuild the app image using your existing Compose setup.
For local source serving, hard-refresh the browser after copying (Ctrl+Shift+R).
Check patient loading, screening, evidence, JSON downloads and theme switching.

UI source: `ovrz/ui-refresh`, commit `0d8f166`.

## Version 1 - original frontend

[Download frontend-v1.zip](frontend-v1.zip)

The original four static frontend files, including the separate hash-vector
retrieval demo entry point. Kept for comparison or restoring the original look.
Source: commit `b4969b80571208d3b6f726c80c61e8f21398aa90`.

## Repository scope

These are frontend-only handoff packages. The checked-in application source in
this branch remains Version 1; install Version 2 from the package above to update
the UI. Teammates' backend and infrastructure files are unchanged.
