# TrialMatch

Team: **Orange Chicken**.

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

All three services have their own Dockerfile under `docker/`. Package versions
share one `uv.lock`; each image installs only its dependency group.

| Service | Dockerfile | Image contents |
|---|---|---|
| `trial-processing` | `docker/trial-processing.Dockerfile` | Trial processing scripts and DVC for snapshot downloads. |
| `rag-api` | `docker/rag-api.Dockerfile` | Backend, RAG workflow and web page. |
| `rag-chromadb` | `docker/chromadb.Dockerfile` | Chroma 1.5.9 server with a health check and data directory at `/data`. |

Compose mounts data, output folders and credentials, not the whole repository.
Compose waits for trial processing to finish and Chroma to be healthy before
starting the app. Index import and retrieval code belong to the backend image.
Chroma stores vectors in the `rag-chroma-data` volume mounted at `/data`.

Offline screening uses BM25 and needs no vector index. Online screening uses
the saved Gemini index restored by `make live`.

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
| `make reproduce` | Download the fixed raw trials with DVC, rebuild and verify the processed files, and start the offline app. |

Both modes use `docker-compose.yml`. Run `make up` to switch back to offline.
Processed data stays under `services/`; generated results go to `artifacts/`.

After editing only the app or web page, update only that service:

```bash
docker compose up -d --build --no-deps rag-api
```

Prefix that command with `TRIALMATCH_MODE=live` to keep online mode.
Changing RAG code only requires rebuilding `rag-api`. Changing the shared
package lock can rebuild dependencies in more than one image.

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

Set up the credentials above with access to the shared DVC storage, then run:

```bash
make reproduce
```

This restores the 1,385 raw trial JSON files tracked by `data/raw.dvc` and uses
the existing trial normalization and criterion parsing functions to rebuild
1,313 trials and 18,456 criteria. It uses `data/raw_metadata.json` for the raw
snapshot information and preserves the processing date in the demo manifest
(`2026-10-11`). It does not fetch a new ClinicalTrials.gov snapshot.

Both rebuilt files must match the demo manifest's checksums before either
processed file is replaced. The command then starts the offline app using
the existing patient data. The reproduction record is saved to
`artifacts/infra/raw_reproduction.json`. Gemini access is not needed for this command.

## Documentation

- [RAG workflow](services/rag_workflow/README.md): retrieval, criterion assessment and API format.
- [Index versioning](services/rag_workflow/INDEX_VERSIONING.md): DVC storage and Chroma snapshots.

## Cloud Setup (MS3)

- [Cloud app](https://trialmatch-15733748057.us-east1.run.app) (authorized Google login required).
- [Successful data pipeline](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261028052840?project=trialmatch-ac215-yixiao).

The app uses Cloud Run. Chroma runs on a separate VM with a persistent disk
mounted at `/data` inside its container. Only the TrialMatch subnet can reach
Chroma. Team members sign in with Google through Identity-Aware Proxy (IAP).
Cloud services use attached service accounts; no login JSON is uploaded.
The five team Google accounts have access. Open the cloud app and select the
approved account; no local Docker setup or credentials file is needed to use it.

Vertex AI Pipelines has three steps:

1. Download the fixed raw trial snapshot with DVC.
2. Rebuild trial and criterion files using the same processing code as the local demo.
3. Verify file checksums, the vector snapshot, and one offline screening request.

Each step runs in `docker/workflow.Dockerfile` and passes its output through GCS.
The app loads the validated release and restores its saved vectors into Chroma.
This pipeline checks data reproduction and application behavior. Model training
and clinical benchmark evaluation are separate work.

Cloud configuration is in `cloud/config.env`. To deploy, install the Google
Cloud CLI and uv, then sign in:

```bash
gcloud auth login
gcloud auth application-default login
bash cloud/setup.sh
```

Use `make live` once to download the fixed index snapshot if it is missing.
Then build versioned images and deploy:

```bash
bash cloud/deploy.sh build
bash cloud/deploy.sh publish
bash cloud/deploy.sh database
bash cloud/deploy.sh pipeline
bash cloud/deploy.sh app
```

The pipeline command waits for success and saves its job name, validation report,
and output release URI under `artifacts/cloud/`. The app command requires that
validated release. Cloud Build stores the three cloud images (API, Chroma, and
workflow) in Artifact Registry. Local Compose still uses the four Make commands above.

For the first deployment, open the Cloud Run service's Security tab, enable IAP,
and grant the team the IAP-secured Web App User role. For Gmail accounts, configure
an External OAuth consent screen, add the team as test users, and use IAP's
Auto Generate Credentials option under Custom OAuth. Keep unauthenticated access
disabled. This is already configured in the TrialMatch project.
Cloud Logging contains app startup logs and pipeline task logs.

The Chroma VM stays on and incurs charges even when nobody opens the app.
When the demo is not needed, pause it with:

```bash
gcloud compute instances stop trialmatch-chroma --zone=us-east1-b --project=trialmatch-ac215-yixiao
```

Use `instances start` with the same options before the next demo. Its persistent
disk keeps the vectors. Disk and storage charges continue while the VM is off.

### Monthly Budget

TrialMatch has a $5 monthly budget with email alerts at 50%, 80%, and 100%.
Budget notifications call a private shutdown handler in `cloud/budget/`.
When reported monthly costs reach $5, it sets the `trialmatch` Cloud Run service
to zero instances and stops the `trialmatch-chroma` VM. Disks, buckets, and data
are kept. Failed actions are retried. The handler never restarts the demo.

This is not a strict spending cap: billing notifications can be delayed, and
stored data still costs money. Direct Gemini calls, builds, or pipeline jobs
started outside the demo are not blocked by this handler.

The handler is already deployed. To install or update it as the project owner:

```bash
bash cloud/budget/deploy.sh
```

After reviewing the budget, manually resume the demo with:

```bash
gcloud compute instances start trialmatch-chroma --zone=us-east1-b --project=trialmatch-ac215-yixiao
gcloud run services update trialmatch --scaling=auto --region=us-east1 --project=trialmatch-ac215-yixiao
```

If the current month is still over $5, the next budget notification stops it again.
