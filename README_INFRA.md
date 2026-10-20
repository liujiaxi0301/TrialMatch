# MLOps Infrastructure (MS2 Part 4)

The shared environment uses Python 3.12, uv 0.13.1 and the root `uv.lock`.
This integration uses Parts 1, 2, 3 and 5 without changing their code.

## Running the Project

Run from the repository root with Docker running:

```bash
make up        # Prepare data, start the app and Chroma, export the offline index
make down      # Stop containers; keep data and snapshots
make run       # Run Part 3's offline CLI without the web app
make dev       # Open the shared development environment
make snapshot  # Export the current local vector index again
make build     # Rebuild images after changing dependencies or Dockerfile
```

After `make up`, open http://localhost:8080. Select a patient and click
**Run screening** to see candidate trials, criterion decisions and source facts.
**Inspect vector retrieval** separately retrieves criterion chunks from Chroma.

The first image build/download needs internet. The application runs on CPU,
without GCP credentials or LLM calls.

## Compose Services

| Service | Purpose |
|---|---|
| `trial-processing` | Run Part 1's criterion parser on its committed normalized trials, check that the output matches, and copy Part 2's patient data. Exits when done. |
| `rag-chromadb` | Store vectors in the persistent `rag-chroma-data` volume. |
| `prepare` | Run Part 5's existing preparation code: build/verify the local vector index and save one offline screening example. Exits when done. |
| `rag-api` | Serve Part 5's UI and Part 3's API together on port 8080. Starts after preparation succeeds. |
| `workspace` | Optional development shell, started by `make dev`. |

Offline screening uses Part 3's BM25 retrieval and rules. Unsupported criteria
remain UNKNOWN. The separate Chroma demonstration uses Part 5's 512-dimensional
lexical hash vectors, not Gemini embeddings. These are two different paths.

## Data and Versions

| Data | Source and version |
|---|---|
| Normalized trials | `services/trial_ingestion/data/processed/trials.jsonl`: 1,313 trials, snapshot 2026-10-11. |
| Criteria | Part 1's parser reproduces all 18,456 committed criteria exactly, including 82 marked ambiguous. |
| Patients | `services/patient_processing/data/processed/batch25_patients.jsonl`: 25 synthetic patients, reference date 2021-11-30. |
| Trial subset | `services/rag_workflow/examples/demo_manifest.json`: 50 trials and input SHA-256 hashes. |
| Chunks and vectors | 607 fragments. Part 3's index identity records the data hashes, subset, model, dimensions and chunker. |

`trial-processing` writes copies to `artifacts/infra/data/`; `prepare` and
`rag-api` read those same copies. Input hashes must match the supplied manifest.
The original datasets are unchanged, and startup does not download new data.
Raw-trial download and normalization are still pending the matching raw snapshot.

Local outputs:

- `artifacts/infra/data/data_versions.json`: source paths and SHA-256 hashes.
- `artifacts/infra/ms2/`: request, retrieved context, screening response and run manifest.
- `artifacts/infra/snapshots/`: portable local-vector snapshot and checksum summary,
  exported with Part 3's existing code. Includes chunk text, metadata and vectors.
- `artifacts/rag_workflow/demo_offline.json`: standalone `make run` output.

Git versions the processed inputs, manifest, code and dependency lockfile.
Snapshot filenames use the index identity; the Docker volume keeps runtime data.
These local outputs are Git-ignored and are not a shared data backup.
For changes to input data, stop the app first and update the matching manifest
with Part 3's owner.

## Development

Inside `make dev`, use `uv add package-name`. Share both `pyproject.toml` and
`uv.lock` when changing dependencies, then run `make down`, `make build` and
`make up`. Startup builds missing images and reuses existing ones.

## Verified Locally

Checked on 2026-10-20 with Docker Desktop on macOS:

- Data processing reproduced the committed criteria exactly.
- The browser loaded 25 patients and returned three candidate trials from `/screen`.
- The retrieval button queried the real 607-fragment Chroma collection.
- Part 5's existing `demo/ovrz/verify_http.py` passed against the running app.
- `make run` succeeded. `make down` followed by `make up` reused the index.
- The exported local-vector snapshot restored into a separate database and
  returned three retrieved chunks.

HTTP responses, startup logs, screenshots and the restore record are saved under
`artifacts/infra/`. No new test suite was added, and no LLM calls were made.
The initial build used a temporary Docker client configuration because the
local credential helper stalled; the normal `make up` restart then passed.

## TODO

- Part 1: obtain the original raw trial snapshot matching the committed data,
  with its download date and checksum. Then connect raw ingestion/normalization
  and record that data version. Do not substitute a fresh registry download.
- Part 3: obtain the actual Gemini snapshot `index_snapshots/current.json`.
  The Git branch contains its DVC pointer and summary, but not the vectors.
- Team: choose shared storage and provide access so raw data and index snapshots
  can be uploaded and restored by teammates. Follow Part 3's `INDEX_VERSIONING.md`.
- For a later live run: obtain the GCP project ID and approved credential setup,
  restore/build the matching Gemini index, then verify model calls.
