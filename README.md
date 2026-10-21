# TrialMatch

TrialMatch uses synthetic patient records to retrieve type 2 diabetes clinical
trials and review eligibility criteria. Results include supporting evidence,
screening barriers and missing information.

## Modules

| Module | Purpose |
|---|---|
| `services/trial_ingestion/` | Collect ClinicalTrials.gov records and parse eligibility criteria. |
| `services/patient_processing/` | Convert Synthea FHIR records into patient facts. |
| `services/rag_workflow/` | Retrieve candidate trials and assess criteria using patient evidence. |
| `services/frontend/` | Provide the patient selection interface, results and API. |

## Quick Start

Shared environment: Python 3.12, uv, DVC and Docker Compose.
Python dependencies and DVC run inside Docker; no local Python or uv is needed.

Install Docker and make, start Docker, and run from the repository root:

```bash
make up
```

Open http://localhost:8080, select a patient and run screening.
The default offline mode uses the included processed data and requires no Google credentials.

| Command | Purpose |
|---|---|
| `make up` | Build images, check the existing processed data, and start Chroma and the offline app. |
| `make live` | Build images, download and restore the Gemini index, and start online screening. |
| `make down` | Stop the containers and keep stored data. |
| `make reproduce` | Download versioned raw trials, rebuild and check the processed files, then start the offline app. |

Both modes use `docker-compose.yml`. Run `make up` to switch back to offline.
Processed data stays under `services/`; generated results go to `artifacts/`.

## Online Screening

Install the Google Cloud CLI and sign in with `gcloud auth application-default login`.
Create `secrets/` and copy the credentials file printed by the command to `secrets/google-credentials.json`.
Copy `.env.example` to `.env` and set `GCP_PROJECT`.
Compose mounts the same credentials file for DVC and Gemini.
The account needs access to the shared DVC storage and the project's Gemini service.
The project needs billing and `aiplatform.googleapis.com` enabled.

```bash
make live
```

Credentials and `.env` stay out of Git. `make up` does not need them.
See [shared storage](services/rag_workflow/INDEX_VERSIONING.md#5-shared-storage)
for access and uploads. `make reproduce` uses the same container and credentials for DVC.

## Data Reproduction

`make reproduce` requires the raw snapshot's DVC pointer (`data/raw.dvc`),
metadata (`data/raw_snapshot.json`) and rebuild script (`scripts/rebuild_snapshot.py`)
under `services/trial_ingestion/`. Rebuilt files are checked against the demo
manifest before replacing the processed data. The command stops if required
files are missing or checksums do not match.

## Documentation

- [RAG workflow](services/rag_workflow/README.md): retrieval, criterion assessment and API format.
- [Index versioning](services/rag_workflow/INDEX_VERSIONING.md): DVC storage and Chroma snapshots.
