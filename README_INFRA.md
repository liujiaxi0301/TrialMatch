# Infrastructure

Shared environment: Python 3.12, uv and Docker Compose.

## Modules

| Module | Purpose |
|---|---|
| `services/trial_ingestion/` | Collect trial records and parse eligibility criteria. |
| `services/patient_processing/` | Convert Synthea FHIR records into patient facts. |
| `services/rag_workflow/` | Retrieve trials and evaluate criteria using patient evidence. |
| `services/frontend/` | Provide the web interface and API. |

Docker Compose runs data preparation, Chroma and the application.
The default run reads the existing processed data directly from `services/`
in offline mode, without Gemini calls.

## Run

Start Docker and run from the repository root:

```bash
make up
```

Open http://localhost:8080, select a patient and run screening.

## Make Commands

| Command | Purpose |
|---|---|
| `make up` | Check source data, start Chroma and the app, and save the local vector snapshot. |
| `make live` | Restore the Gemini index and start the app with online screening. Requires `.env` and Google credentials. |
| `make down` | Stop the containers and keep stored data. |
| `make build` | Rebuild images after dependency or Dockerfile changes. |
| `make dev` | Open a shell in the shared development container. |
| `make run` | Run one offline screening example without the web app. |
| `make snapshot` | Export the local vector demo's index after `make up`. |
| `make pull-index` | Download the Gemini snapshot from the private DVC remote. Requires uv and `.env`. |
| `make restore-index` | Restore and verify the Gemini snapshot after `make up`. |

## Online Screening

Sign in with `gcloud auth application-default login`. Copy `.env.example` to `.env`,
set `GCP_PROJECT` and use the credentials file path printed by the login command.
The project needs billing and `aiplatform.googleapis.com` enabled.

```bash
make pull-index
make live
```

Use the screening button at http://localhost:8080. Screening uses Gemini query
embeddings, Chroma and Gemini judgments. The separate vector demo stays local.
Run `make up` to return to offline mode.

The [shared storage instructions](services/rag_workflow/INDEX_VERSIONING.md#5-shared-storage)
explain team access and uploading new snapshots. Credentials and `.env` stay out of Git.

Version records, results and snapshots are saved under `artifacts/`.
