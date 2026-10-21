# Ovrz MS2 demo

English app skeleton using the team's screening backend and fixed data snapshots.
This is the original demo UI; the later UI refresh and theme changes are separate.

## Start locally

Requires Python 3.12 and uv. Preserve JSONL bytes for the source hash checks:

```bash
git -c core.autocrlf=false clone --branch ovrz/ms2-demo https://github.com/liujiaxi0301/TrialMatch.git
cd TrialMatch
```

Windows PowerShell:

```powershell
.\demo\ovrz\run-local.ps1
# Optional alternative port:
.\demo\ovrz\run-local.ps1 -Port 8082
```

macOS/Linux:

```bash
sh demo/ovrz/run-local.sh
```

Open http://127.0.0.1:8080/ (or your selected port). Keep the terminal running.
The launcher installs locked dependencies, prepares data and starts the app.
If source hash checks fail after a Windows checkout, use the byte-preserving
clone above; do not replace the upstream data manifest.

## Run with Docker

From the repository root with Docker Engine running:

```bash
docker compose -f demo/ovrz/compose.yml up --build --wait --wait-timeout 300
docker compose -f demo/ovrz/compose.yml ps -a
docker compose -f demo/ovrz/compose.yml logs --no-color
docker compose -f demo/ovrz/compose.yml down
```

Compose starts Chroma, prepares the data/index, then serves the UI and API on
127.0.0.1:8080. Stop any other service using that port first. Named volumes
persist across `down`. Dockerfile, `pyproject.toml` and `uv.lock` are required
for reproducibility. Docker has not been run on the local preparation machine.

## Use the app

Select a synthetic patient, enter a trial-related question, and run screening.
Expand criteria to inspect decisions, evidence, missing information and trial
source links. View/download the actual JSON response. The separate vector
retrieval button displays retrieved criterion text and provenance.

- **Offline screening:** BM25 retrieval and deterministic rules; no LLM calls.
  Unsupported criteria remain UNKNOWN.
- **Vector demo:** Chroma cosine retrieval using 512-dimensional token-hash
  vectors, not pretrained semantic embeddings or an eligibility decision.
- **Live screening:** the team's Gemini/Chroma workflow, requiring authorized
  cloud credentials and a corresponding live index. It uses a separate index
  from the local hash-vector demo.

To opt into live mode, set `GCP_PROJECT`, `GCP_LOCATION` and an absolute
`GOOGLE_APPLICATION_CREDENTIALS` path outside the repository. Then run:

```bash
docker compose -f demo/ovrz/compose.yml -f demo/ovrz/compose.live.yml run --rm rag-api python -m services.rag_workflow.cli --mode live build-index
docker compose -f demo/ovrz/compose.yml -f demo/ovrz/compose.live.yml up -d --wait --wait-timeout 300
```

`/health` checks data/manifest readiness, not cloud authorization. Confirm the
response mode, `result_status` and errors. Live execution has not been verified
on the local preparation machine.

## Data and submission evidence

The processed snapshots contain 1,313 trials, 18,456 criteria and 25 synthetic
patients. The fixed demo subset contains 50 trials / 607 indexed fragments.
Patient reference date: 2021-11-30. Trial snapshot date: 2026-10-11. This is a
historical research demonstration, not a current enrollment assessment.
UNKNOWN does not mean absent; exclusion MET is a barrier. Scores are not
enrollment probabilities. All results require review.

Preparation writes fresh inputs, outputs and source hashes to
`artifacts/ovrz/ms2/` (ignored by Git). One original local run is retained in
[evidence/pipeline](evidence/pipeline), including input, retrieved context,
screening output, log and manifest. See [evidence scope](evidence/README.md).
Container run logs/screenshots must still be captured on a Docker-capable host
for the team's MS2 submission.

## Code locations

- `services/frontend/`: UI, API adapter, preparation and vector demo.
- `demo/ovrz/`: environment, containers and cross-platform launchers.
- [API.md](API.md): endpoint contract and response semantics.
- Existing [trial](../../services/trial_ingestion/README.md),
  [patient](../../services/patient_processing/README.md) and RAG modules supply
  data and screening logic; they are unchanged by this delivery.

Review the addition against `rag-workflow` base commit
`8eba4c0c560d1c58a2c390e63b70ed5bd7cf2470`. The root README/configuration,
teammates' modules and their tests are retained. Presentation notes, screenshot
bundles, duplicate HTTP captures and demo-specific test scripts were removed
from this branch to keep the handoff small.
