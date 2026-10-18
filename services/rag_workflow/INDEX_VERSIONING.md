# ChromaDB index versioning (MS2)

This is a logical snapshot workflow for Part 3. Git records the code, dependency lockfile, source data, snapshot summary and DVC pointer. DVC stores the exported documents, metadata and vectors. Chroma serves a restored collection. DVC runs on a developer machine or in CI; it is not installed in the database container.

The current local snapshot contains **607 vectors, 256 dimensions, 50 trials** from the existing Gemini index. Export and restore do not call GCP or re-embed text. The snapshot contains public trial criteria and vectors, with no patient records, credentials or model-generated patient explanations. Patient files remain under the existing Git workflow; this change does not migrate Parts 1/2 to DVC.

## What defines a version?

| Layer | Versioned information |
|---|---|
| Git | Code, `uv.lock`, processed source files, trial-subset manifest, DVC pointer, snapshot summary |
| Logical index identity | Trial/criterion file SHA-256 hashes, selected trial IDs, embedding model, dimension, chunker revision |
| Exact snapshot artifact | Documents, metadata and stored vectors; DVC file checksum and a SHA-256 summary |
| Runtime database | A separate `trialmatch-<identity-hash>` collection for each identity; backend-specific readiness manifest and exact record digest |
| Database software | Chroma version recorded in the snapshot; client lockfile and Compose image pinned independently |

Changing data, subset, model, dimension or chunker revision creates another collection. A completed collection is reused after validation, rather than overwritten by `build-index`. Earlier collections are retained. `index-status` and live retrieval check the IDs, source text, metadata, vector dimensions and record checksum, so changing vectors without changing their count is detected.

The collection identity describes the requested data/configuration; it does not fingerprint an upstream model's internal weights. The exported artifact preserves the vectors that were actually produced. Keep the DVC pointer and source/configuration in the same Git commit to identify the exact artifact used by a release.

Runtime readiness files for HTTP Chroma are namespaced by host/port under `artifacts/rag_workflow/indexes/http-<backend-hash>/`. Embedded Chroma retains the existing `indexes/<version>.json` location. This prevents a restore into a Docker service from replacing the embedded database's checksum. Changing the HTTP hostname may require restoring/verifying the snapshot again.

Chroma can introduce float32 rounding during import. The snapshot file is checked exactly. Restored IDs/text/metadata must match exactly; vectors must match within absolute tolerance `1e-7` and relative tolerance `1e-6`. The restored database then receives its own exact record checksum, linked to the source snapshot's record checksum. Re-exporting an unchanged database is deterministic; exports from different backends can differ slightly in vector bytes. ANN index files and tie ordering are not promised to be byte-identical across platforms or database versions.

## 1. Install the optional tooling

Run commands from the TrialMatch repository root:

```bash
uv sync --project services/rag_workflow --locked --group versioning
```

The `versioning` dependency group includes DVC and its Google Cloud Storage adapter. Normal API/Docker installations do not install this group. The DVC project is isolated in `services/rag_workflow/.dvc/` using DVC's subdirectory-project support; no repository-wide DVC migration is required. See [DVC initialization](https://dvc.org/doc/command-reference/init).

## 2. Verify the current index

```bash
uv run --project services/rag_workflow --locked \
  python -m services.rag_workflow.cli index-status
```

Expected: `status: VERIFIED`, `vector_count: 607`, and the collection/model/dimension/checksum. A missing or changed collection produces a structured error and exit code 1. Offline patient screening remains independent of Chroma.

For a pre-versioning local index, run `build-index` once:

```bash
uv run --project services/rag_workflow --locked \
  python -m services.rag_workflow.cli build-index
```

An existing complete legacy collection is validated and given a checksum without creating a cloud client or re-embedding. This migration has already been completed in this local checkout. If no index exists, `build-index` needs the normal GCP environment and incurs embedding usage, as described in the main README. A copied ready file without a matching database is insufficient.

## 3. Export and record a data version

Stop index writers before building/exporting/restoring; MS2 assumes one index writer. Queries may continue against an existing completed collection. No distributed write lock is implemented.

```bash
uv run --project services/rag_workflow --locked \
  python -m services.rag_workflow.cli export-index \
  --output services/rag_workflow/index_snapshots/current.json

uv run --project services/rag_workflow --locked --group versioning \
  dvc --cd services/rag_workflow add index_snapshots/current.json

uv run --project services/rag_workflow --locked --group versioning \
  dvc --cd services/rag_workflow status
```

Expected: `Data and pipelines are up to date.` after `dvc add`.

| File | Purpose | Storage |
|---|---|---|
| `index_snapshots/current.json` | Complete portable snapshot, including vectors | DVC cache/remote; Git-ignored |
| `index_snapshots/current.json.dvc` | DVC checksum and output path | Git |
| `index_snapshots/current.manifest.json` | Readable source/model/subset/count and snapshot SHA-256 | Git |
| `.dvc/config`, `.dvc/.gitignore`, `.dvcignore` | Isolated DVC configuration and exclusions | Git |
| `.dvc/cache/`, `.dvc/tmp/`, `.dvc/config.local` | Cache, internal state and machine-specific settings | Git-ignored |

Changing `current.json` alone does not record a new DVC version: rerun `dvc add`, then commit the new pointer and summary together after review. A Git commit records the selected DVC version; historical snapshots remain available in the DVC cache/remote. Do not commit the snapshot itself or a live Chroma storage directory. [DVC add](https://dvc.org/doc/command-reference/add) explains the pointer/cache relationship.

## 4. Restore into a fresh local database

First obtain the snapshot. On this machine it is already available. Another machine needs the DVC pointer **and** access to its matching cache/shared remote; cloning Git alone does not download the vectors.

Use a different artifact directory to test restoration while preserving the working database:

```bash
TRIALMATCH_ARTIFACTS=artifacts/rag_workflow_restore_check CHROMADB_HOST= \
  uv run --project services/rag_workflow --locked \
  python -m services.rag_workflow.cli restore-index \
  --input services/rag_workflow/index_snapshots/current.json

TRIALMATCH_ARTIFACTS=artifacts/rag_workflow_restore_check CHROMADB_HOST= \
  uv run --project services/rag_workflow --locked \
  python -m services.rag_workflow.cli index-status
```

Expected: `RESTORED`, then `VERIFIED`, both with 607 vectors. No GCP credentials are required. A restore checks the snapshot schema/checksum and matching source/configuration before inserting anything. It refuses conflicting target records, preserves existing collections, and can resume an interrupted restore if all existing records match. For conflicts, use a fresh dedicated database/path; the tool never deletes collections or volumes.

For an older version, select the Git revision containing its source data, code/configuration, trial-subset manifest and `.dvc` pointer, then run DVC checkout/pull before restoring. Merely changing a pointer while keeping incompatible source data is rejected. Selecting the corresponding source/configuration selects the historical collection; there is no independent global "active collection" switch.

## 5. Shared storage: handoff to Part 4

**No shared remote or cloud bucket has been configured or uploaded to in this change.** The local cache is working, but the Git branch by itself cannot distribute the snapshot. Before team delivery, Part 4 must supply an existing shared storage location and grant the required access.

After the team chooses an existing GCS bucket, each developer can configure it locally. Replace the placeholder below; it is not an existing bucket:

```bash
uv run --project services/rag_workflow --locked --group versioning \
  dvc --cd services/rag_workflow remote add --local --default team \
  gs://YOUR_EXISTING_BUCKET/trialmatch/rag-indexes
```

Authenticate using the team's approved GCP credential method. GCS object permissions are separate from Vertex AI model-inference permissions. Keep credential paths/settings in local configuration. The optional adapter is installed, but real GCS credentials/access were not tested here. See [DVC remote configuration](https://dvc.org/doc/command-reference/remote/add).

Once review is approved, the publisher uploads the snapshot with `dvc push`, then publishes the matching Git pointer/summary. A teammate retrieves it with:

```bash
uv run --project services/rag_workflow --locked --group versioning \
  dvc --cd services/rag_workflow pull index_snapshots/current.json.dvc
```

`git push` publishes code/pointers; `dvc push` publishes data to the configured remote. Neither substitutes for the other. The local verification uses a disposable local-directory remote, not a GCS upload. Until shared storage is configured, a published Git pointer still requires access to the original local DVC cache or a later upload of that snapshot.

## 6. Restore into the separate Docker Chroma service

Part 4 can start the existing Compose services, pull the snapshot **on the host**, and restore it through the RAG container. The existing read-only services mount makes the pulled snapshot available without putting it in the image:

```bash
docker compose --env-file services/rag_workflow/.env \
  -f services/rag_workflow/docker-compose.yml \
  exec rag-api python -m services.rag_workflow.cli restore-index \
  --input /app/services/rag_workflow/index_snapshots/current.json

docker compose --env-file services/rag_workflow/.env \
  -f services/rag_workflow/docker-compose.yml \
  exec rag-api python -m services.rag_workflow.cli index-status
```

The same commands work with the live Compose override when it is included in the deployment command. Build/pull a RAG image containing this revision first. No frontend work or API contract changes are required. The database volume provides persistence; DVC provides retrievable snapshot versions. This is a collection export using Chroma's [Get API](https://docs.trychroma.com/docs/querying-collections/query-and-get), not a physical backup of the server's database/configuration.

## 7. Verification and review

```bash
uv run --project services/rag_workflow --locked --group versioning \
  python -m unittest discover -s services/rag_workflow/tests -v
uv run --project services/rag_workflow --locked ruff check services/rag_workflow
```

The DVC integration test uses a temporary Git repository and local-directory remote. It records two versions, selects the older Git pointer, removes only its disposable working file/cache, pulls the original bytes and verifies clean status. It never pushes this branch or uploads to cloud storage. Without the optional group that test is skipped; index tests still run.

`examples/index_versioning_verification.json` records the real 607-vector embedded/Docker restore checks. Stored document vectors are used as retrieval probes, so this verifies database restoration rather than a new LLM screening run. New model calls and frontend testing are outside this change.

For review, inspect this guide, `index.py`, `index_versions.py`, the three CLI commands, snapshot summary/pointer and the new tests. Review code, source/configuration and snapshot pointer together before publishing.
