# Milestone 2 — Orange Chicken / TrialMatch

Submission branch: `milestone2`. Application and backend source tested from
`799fd33785075d009afad57472e04ea0335662b0`; this delivery adds documentation and
run evidence without changing application behavior.

## Application mock-up

[View the three-page application mock-up and user flow](TrialMatch-MS2-Mockup.pdf).
It documents the current working UI using actual local screenshots:
select a patient and enter a question, review candidate trials, then expand
criterion-level judgments and supporting patient evidence. Each page describes
the user action, visible feedback and next step. This is the MS2 implementation
mock-up, not a reconstruction of the original MS1 design.

## Run the submitted app

From a byte-preserving clone (`git -c core.autocrlf=false clone --branch milestone2
https://github.com/liujiaxi0301/TrialMatch.git`), install Python 3.12 and uv.
Run `demo/ovrz/run-local.ps1` on Windows or `sh demo/ovrz/run-local.sh` on macOS/Linux.
Open http://127.0.0.1:8080. The Windows launcher accepts `-Port 8082`.
For containers, install/start Docker and run `make up` from the root.

## Evidence captured on 2026-10-20 (US Eastern)

This is a **local Windows offline run**, not a new Docker or Gemini run.
Preparation validates 1,313 trials and 18,456 criteria, builds/verifies
607 lexical-vector Chroma fragments, retrieves five chunks and runs screening.
The screening workflow uses BM25 plus deterministic rules; no LLM is called.
Vector retrieval is a separate diagnostic baseline, not semantic Gemini embeddings.

- `evidence/preparation.log`: actual data validation and preparation output.
- `evidence/run_manifest.json`: timestamp, Python version, source hashes and model identity.
- `evidence/request.json`, `screen_response.json`, `retrieved_context.json`: real preparation inputs/outputs.
- `evidence/http/`: actual API request, response, retrieval, metadata and status checks.
- `evidence/ui-screening.png`: running integrated V2 UI after screening.
- `evidence/server.stderr.log`, `server.stdout.log`: local server startup/request logs.

To repeat the preparation: set `TRIALMATCH_MODE=offline`, then run
`uv run --frozen python prepare_data.py` and
`uv run --frozen python -m services.frontend.prepare`.
With the server running, use `uv run --frozen python demo/ovrz/verify_http.py`.
Generated artifacts are normally ignored; the small evidence set here is deliberately committed.

## Scope and outstanding items

- Root Dockerfile, Compose, pyproject and uv.lock are included. Historical module
  Docker/Gemini evidence is under `services/rag_workflow/examples/`. A fresh
  integrated Docker run is still required to verify the complete container stack;
  Docker is not installed on the Windows machine used for this capture.
- Raw snapshot reconstruction (`make reproduce`) is unavailable because the raw
  rebuild handoff is incomplete. The working demo starts from hash-checked,
  committed processed snapshots. See root README.
- Final team presentation slides are prepared separately from this repository.
- Repository owner must confirm the required `AC215_<GroupName>` name and
  `ac215harvard` collaborator access; the current contributor cannot administer these.
- Canvas is not submitted by this delivery. Submit the full final commit SHA.

Patient records are synthetic and historical. UNKNOWN results and evidence links
are preserved; this demo does not establish clinical eligibility or clinical accuracy.
