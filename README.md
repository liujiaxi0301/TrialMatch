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

Each service has its own `Dockerfile`, `pyproject.toml` and `uv.lock`.
Images install only that service's locked dependencies.

| Service | Build directory | Image contents |
|---|---|---|
| `trial-processing` | `docker/trial-processing/` | Trial processing scripts and DVC for snapshot downloads. |
| `rag-api` | `docker/rag-api/` | Backend, RAG workflow, web page and cloud startup code. |
| `rag-chromadb` | `docker/chromadb/` | Chroma 1.5.9 server with a health check and data directory at `/data`. |

Local Compose mounts the trial scripts and backend source read-only, plus data,
output folders and credentials. The backend reloads when Python code changes;
refresh the browser after editing the web page.
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

After changing backend dependencies, update its lock and rebuild that service:

```bash
uv lock --project docker/rag-api
docker compose up -d --build --no-deps rag-api
```

Prefix the Docker command with `TRIALMATCH_MODE=live` to keep online mode.
Use the corresponding build directory for another service. Trial scripts are
read on the next processing invocation, such as `make reproduce`.
The root `pyproject.toml` and `uv.lock` support the original local Python tools;
container builds do not use them.

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
- [Successful four-step pipeline](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261112024908?project=trialmatch-ac215-yixiao).

The app uses Cloud Run. Chroma runs on a separate VM with a persistent disk
mounted at `/data` inside its container. Only the TrialMatch subnet can reach
Chroma. Team members sign in with Google through Identity-Aware Proxy (IAP).
Cloud services use attached service accounts; no login JSON is uploaded.
The five team Google accounts have access. Open the cloud app and select the
approved account; no local Docker setup or credentials file is needed to use it.
The app includes readiness checks, request IDs and structured request logs.
Gemini remains the default.

The default Vertex AI Pipeline has four steps:

1. Download the fixed raw trial snapshot with DVC.
2. Rebuild trial and criterion files using the same processing code as the local demo.
3. Verify file checksums, the vector snapshot, and one offline screening request.
4. Generate BM25 and Gemini retrieval rankings for the eight fixed MS3 queries.

Each step uses the image in `docker/workflow/`, with its own dependency files,
and passes its output through GCS. Cloud images contain code and do not use
local source mounts or automatic reload.
The app loads the validated release and restores its saved vectors into Chroma.
The last step saves `retrieval_runs.jsonl` and its configuration to GCS. It produces
rankings, not relevance scores or eligibility accuracy. Model training and human
benchmark scoring are separate work. Gemini remains the deployment default.

Optional flags add encoder training (`--trainer-image`), rankings from that
run's checkpoint (`--finetuned-retrieval-image`), frozen-label scoring
(`--retrieval-evaluation`) and fixed-pair eligibility evaluation (`--eligibility`).
Together these form eight tasks. The adapter checks input versions and output
checksums, uses the existing metric formulas and reports any unjudged candidates.
The app's four-step deployment check remains separate from these model experiments.

In the November 12 eight-task run, training and retrieval from the new checkpoint
passed. The frozen retrieval scorer found 10 unjudged query/trial pairs, and
eligibility evaluation found six `INVALID_LLM_OUTPUT` predictions among 115
criteria. These block a passing end-to-end evaluation.
The [eight-task run](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261112023318?project=trialmatch-ac215-yixiao)
contains the task outcomes and artifacts.

Details: [training](docs/ms3/module-a-training.md),
[new-model rankings](docs/ms3/module-a-finetuned-retrieval.md),
[retrieval scoring](docs/ms3/module-a-retrieval-evaluation.md) and
[eligibility evaluation](docs/ms3/module-a-eligibility.md).

Cloud configuration is in `cloud/config.env`. Deployment uses the course's
`gcloud` commands and a Docker workflow container. The pipeline uses Python
`kfp` components and Vertex AI `PipelineJob`, with GCS files between steps.

Install Docker, the Google Cloud CLI and Python 3 (for the image version hash).
Start Docker and set up `secrets/google-credentials.json` as described under
Online Screening. Then sign in to the CLI and set up the cloud resources:

```bash
gcloud auth login
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

Build records the input checksums and exact image versions in
`artifacts/cloud/release_target.json`. Publish, pipeline and app use that same
record. The app requires a successful pipeline for the selected build, so an old
successful run cannot authorize a new deployment. Rebuild once when upgrading
from the earlier release format, then follow the five commands above in order.

Pipeline logs and output references are in Vertex and `artifacts/cloud/`.
Cloud Build stores three images (API, Chroma and workflow) in Artifact Registry.
Local Compose still uses the four Make commands above. The workflow image includes
the retrieval runner and training-data preparation scripts; it does not install Torch.

The `publish` and `pipeline` commands use `docker/workflow/` and its locked
dependencies, so local uv and Python packages are not needed. Code and data are
mounted read-only; output files go to `artifacts/cloud/`. Local credentials are
mounted at `/secrets` and are never copied into an image. To compile the pipeline
without submitting a cloud job, use `bash cloud/deploy.sh pipeline --compile-only`.

Pipeline checks run in GitHub Actions without cloud credentials. See the
[retrieval protocol](evaluation/ms3/retrieval_protocol.md) for the fixed inputs
and the [method handoff](evaluation/ms3/runs_handoff.md) for the supplied experiments.

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

## Encoder Training (MS3)

**New since MS2.** MS2 retrieved with a frozen encoder. MS3 adds contrastive fine-tuning
of that encoder as a serverless Vertex AI job, tracked in Weights & Biases. Everything in
this section is new: `cloud/train_pairs.py`, `cloud/train_pairs_llm.py`, `cloud/train.py`,
`cloud/train_job.py`, `docker/trainer/`, an optional fifth pipeline task in
`cloud/pipeline.py`, and checkpoint support in
`services/rag_workflow/embedding_providers.py`. The trainer image has its own build
config, `docker/trainer/cloudbuild.yaml`, so `cloud/build.yaml` and the deployment build
are unchanged. The plan and its acceptance checklist are
in [docs/ms3/module-b-plan.md](docs/ms3/module-b-plan.md).

The fine-tuned encoder is not deployed. The app still serves the MS2 retrieval path. The
checkpoint was used only to produce extra benchmark rankings for the evaluation owner.

### What was trained

- Model: `thomas-sounack/BioClinical-ModernBERT-base` at revision
  `c3648aa87af95837c809e6f0c5f85d08160db437`. Pooling is the attention-mask mean followed
  by L2 normalization, the same function the serving provider uses; a test asserts the
  two agree.
- Objective: InfoNCE at temperature 0.05, over in-batch positives and up to four mined
  hard negatives per pair.
- Data: 5,137 training and 476 validation query/criterion pairs. 2,281 pairs have
  templated queries built from trial metadata; 3,332 have queries written by
  `gemini-3.1-flash-lite` from a criterion.
- Held-out data: the 50 trials in `services/rag_workflow/examples/demo_manifest.json` are
  the retrieval benchmark. The trainer stops before loading a model if any of them, or
  any trial present in both splits, appears in the pairs.

### Result of the run

Job `projects/15733748057/locations/us-east1/customJobs/8919501313956380672` ran on one
`n1-standard-4` with one T4 in `us-east1` and trained for 889 seconds.

| | val loss | Recall@10 | MRR@10 |
| --- | ---: | ---: | ---: |
| frozen encoder | 3.348 | 0.249 | 0.147 |
| epoch 1 | 0.964 | 0.782 | 0.477 |
| epoch 2 | 0.948 | 0.802 | 0.514 |
| epoch 3 | 0.999 | 0.802 | 0.488 |

These numbers are on 386 validation queries against 1,046 passages from training-side
trials. They are not benchmark scores. Validation loss rises in epoch 3 and MRR@10 falls
with it, so the model overfits slightly by the end; the saved checkpoint is the epoch-3
model, not the best one.

- W&B run: <https://forge.coreweave.com/wandb/jennyyang-harvard-university/trialmatch-ms3/runs/26xhkrre>.
  `train/loss` is logged every step, `val/loss`, `val/recall@10` and `val/mrr@10` at
  step 0 (frozen encoder) and after each epoch. The run config holds every hyperparameter,
  the pair-file checksums, the code commit and the image digest.
- Checkpoint: `gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model`,
  SHA256 `7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c`. The digest
  covers the weights, config and tokenizer files together and is recorded in
  `training_manifest.json` next to the checkpoint.
- Evidence: [docs/ms3/evidence/module-b/2026-11-10/](docs/ms3/evidence/module-b/2026-11-10/README.md)
  has the job record, the manifest, the full job log and the two failed attempts that
  came first.

![Training loss per step](docs/ms3/evidence/module-b/2026-11-10/wandb-train-loss.png)

![Validation loss at the frozen baseline and after each epoch](docs/ms3/evidence/module-b/2026-11-10/wandb-val-loss.png)

### Regenerate the training pairs

```bash
uv run --locked python -m cloud.train_pairs
```

```bash
uv run --locked --group embeddings --env-file services/rag_workflow/.env \
  python -m cloud.train_pairs_llm --limit 4000
```

These write `artifacts/training/pairs.jsonl` and `artifacts/training/pairs_llm.jsonl`.
The second needs Gemini credentials the first time; responses are cached on disk, so a
repeat makes no request.

The files the run trained on are stored at
`gs://trialmatch-ac215-yixiao-ms3/training/pairs/20261110/` and their SHA256 values are in
the training manifest. Use those copies to reproduce the run. Regenerating today gives
the same queries, positives and splits, but hard negatives differ in 3 of 2,281 rows and
188 of 3,332 rows: negative mining broke score ties by hash order when those files were
made, and now breaks them by a fixed order.

### Try the trainer locally

A small run on a laptop, without W&B credentials:

```bash
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
WANDB_MODE=offline uv run --locked --group training python -m cloud.train \
  --pairs artifacts/training/pairs.jsonl --output artifacts/training/smoke \
  --limit 48 --epochs 1 --batch-size 8 --max-negatives 2 --max-length 128
```

```bash
uv run --locked --group training python -m unittest cloud.tests.test_train cloud.tests.test_train_job
```

### Reproduce the Vertex AI run

Experiment tracking setup, once per project: create the Secret Manager secret
`wandb-api-key` holding a W&B API key, and grant
`trialmatch-pipeline@trialmatch-ac215-yixiao.iam.gserviceaccount.com` the Secret Manager
Secret Accessor role on it. The job reads the key at run time. It is never in Git, the
image, the job spec or the logs. Without a readable key the run is tracked offline
instead of failing.

Sign in as in Cloud Setup, then build the trainer image:

```bash
gcloud builds submit . --project=trialmatch-ac215-yixiao --region=us-east1 \
  --config=docker/trainer/cloudbuild.yaml \
  --substitutions="_REGISTRY=us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch,_VERSION=$(git rev-parse HEAD)" \
  --gcs-source-staging-dir="gs://trialmatch-ac215-yixiao-ms3/builds/source" \
  --service-account="projects/trialmatch-ac215-yixiao/serviceAccounts/trialmatch-build@trialmatch-ac215-yixiao.iam.gserviceaccount.com" \
  --suppress-logs --format=json > trainer_build.json
```

The image digest is `results.images[0].digest` in `trainer_build.json`. The image is
based on Vertex's prebuilt `pytorch-gpu.2-4.py310` container and takes about 30 minutes
to build.

Submit the job with the image pinned by digest. This is the command of our second run;
the first differed only in its run ID and evidence directory:

```bash
export GOOGLE_CLOUD_QUOTA_PROJECT=trialmatch-ac215-yixiao
uv run --project docker/workflow --locked python -m cloud.train_job \
  --image us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch/trainer@sha256:97c872638eabbf681d020d6bb1c1f534a707e3798b997d57ad435d7bd964fea9 \
  --pairs gs://trialmatch-ac215-yixiao-ms3/training/pairs/20261110/pairs.jsonl gs://trialmatch-ac215-yixiao-ms3/training/pairs/20261110/pairs_llm.jsonl \
  --run-id train-20261110-t4-repro --batch-size 8 \
  --evidence docs/ms3/evidence/module-b/2026-11-10/reproduction
```

Vertex AI job configuration, all defaults of `cloud/train_job.py` except the batch size:

| Setting | Value |
| --- | --- |
| Machine | `n1-standard-4`, 1 x `NVIDIA_TESLA_T4`, region `us-east1` |
| Service account | `trialmatch-pipeline@trialmatch-ac215-yixiao.iam.gserviceaccount.com` |
| Time limit | 5,400 seconds, after which Vertex cancels the job |
| Training | 3 epochs, batch size 8, 4 negatives per pair, max length 256, learning rate 2e-5, seed 0, fp16 |
| Output | `gs://trialmatch-ac215-yixiao-ms3/training/<run-id>/` |

The command waits for the job, recomputes the checkpoint SHA256 from GCS against the
manifest, writes `job.json`, `training_manifest.json` and `job.log` into the evidence
directory, and exits non-zero unless the job succeeded and the digest matches. Add
`--dry-run` to print the job spec without submitting. A run ID can be used once.

We ran it twice. The second run (`reproduction/` in the evidence directory) had the same
configuration, the same validation metrics at every epoch and the same checkpoint SHA256
as the first. That is one repeat on the same GPU type and image.

Two things the job does that are worth knowing:

- Before training it embeds one padded batch on CPU and on the GPU and compares them. On
  this image's PyTorch 2.4 the default `sdpa` attention path returned non-finite
  embeddings on CUDA, so the job uses the `eager` path, which matched CPU to 2.4e-7. We
  did not find the root cause of the `sdpa` failure.
- Batch size 16 runs out of memory on a T4 with the `eager` path, which is why the run
  uses 8.

Without GPU quota the same job runs on CPU with `--accelerator-count 0` and a larger
`--machine-type`. The job spec for that was checked with `--dry-run` only; no CPU job
has been run.

### Rankings from the fine-tuned encoder

```bash
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
export GOOGLE_CLOUD_PROJECT=trialmatch-ac215-yixiao
uv run --locked --group embeddings python -m evaluation.ms3.run_retrieval \
  --encoders bioclinical \
  --finetuned-manifest docs/ms3/evidence/module-b/2026-11-10/training_manifest.json
```

This downloads the checkpoint, verifies it against the manifest's SHA256, indexes the 50
benchmark trials into a collection of its own, and writes
`evaluation/ms3/retrieval_runs.jsonl` with four `finetuned_*` methods beside the six
earlier ones. It produces rankings only. Scoring belongs to the evaluation owner; see
[the handoff](evaluation/ms3/runs_handoff.md).

### In the pipeline

`cloud/pipeline.py` preserves the four data/retrieval tasks and adds an optional fifth
task, `train-encoder`, after `validate-data` when given a digest-pinned `--trainer-image`.
Training and the existing Gemini retrieval both consume the validation report. The
training task rebuilds corpus pairs from that release; `--train-pairs` supplies extra
LLM pairs, with one `--train-pairs-sha256` value per URI in the same order. The
trainer checks downloaded bytes before loading the model. Rebuild both workflow
and trainer images for this interface; the historical trainer image cannot accept
the new checksum argument. Its default batch size is 8 (`--trainer-batch-size` can override it).

The integration is described in
[Module A training integration](docs/ms3/module-a-training.md). It checks the training
manifest's release, image, output path, checksum metadata and batch size before saving
any success markers. `--finetuned-retrieval-image` consumes this run's checkpoint,
and `--retrieval-evaluation` scores those rankings with the frozen benchmark.
The separate baseline retrieval node and deployed app still use Gemini.
A failed task fails the full pipeline and prevents new success markers.

`--eligibility` independently adds `evaluate-eligibility`, using C's eight fixed
patient/trial pairs (115 criteria) with Vertex Gemini. It requires a digest-pinned
workflow image rebuilt with the evaluator. Both training and eligibility may be
enabled together. Eligibility does not consume the trained encoder; scoring that
model's retrieval rankings remains separate. Model-call errors fail the task and
retain diagnostic artifacts. See [Module A eligibility integration](docs/ms3/module-a-eligibility.md).

### Limitations

- Queries are templated from trial metadata or written by an LLM. There are no human
  relevance labels, and no clinician reviewed any pair.
- The data is small: 5,613 pairs from one disease area.
- About 72% of the LLM-written pairs have an exclusion criterion as the positive, and
  some of those queries describe having the condition the criterion excludes. The model
  is trained to match topic, not eligibility direction.
- Hard negatives are mined by lexical overlap, so they are weak. Templated queries share
  topic words with their positives by construction.
- The validation pairs come from the same generators as the training pairs. The Recall@10
  gain is an internal diagnostic. Negative mining also crosses the training/validation
  trial split; that issue remains with Module B before claiming an independent validation
  result. The latest pipeline checkpoint also needs the unjudged retrieval pairs
  reviewed before its benchmark scores can be reported.
- No early stopping and no best-checkpoint selection: the saved model is the last epoch.
- Patients are synthetic. Nothing in this project is clinically validated.
