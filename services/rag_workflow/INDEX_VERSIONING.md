# Chroma index versioning

Git records the code, dependency lockfile, source data, snapshot summary and DVC pointer. DVC stores the exported documents, metadata and vectors. Chroma serves a restored collection. DVC runs in the `trial-processing` image.

The current local snapshot contains **607 vectors, 256 dimensions, 50 trials** from the existing Gemini index. Export and restore do not call GCP or re-embed text. The snapshot contains public trial criteria and vectors, with no patient records, credentials or model-generated patient explanations. Patient files remain versioned in Git.

## What defines a version?

| Layer | Versioned information |
|---|---|
| Git | Code, `uv.lock`, processed source files, trial-subset manifest, DVC pointer, snapshot summary |
| Logical index identity | Trial/criterion file SHA-256 hashes, selected trial IDs, embedding model, dimension, chunker revision; for BioClinical also revision, pooling, token budget and checkpoint SHA-256 |
| Exact snapshot artifact | Documents, metadata and stored vectors; DVC file checksum and a SHA-256 summary |
| Runtime database | A separate `trialmatch-<identity-hash>` collection for each identity; backend-specific readiness manifest and exact record digest |
| Database software | Chroma version recorded in the snapshot; client and server versions are pinned in their service lockfiles |

Changing data, subset, model, dimension or chunker revision creates another collection. A completed collection is reused after validation, rather than overwritten by `build-index`. Earlier collections are retained. `index-status` and live retrieval check the IDs, source text, metadata, vector dimensions and record checksum, so changing vectors without changing their count is detected.

The collection identity describes the requested data/configuration; it does not fingerprint an upstream model's internal weights. The exported artifact preserves the vectors that were actually produced. Keep the DVC pointer and source/configuration in the same Git commit to identify the exact artifact used by a release.

Runtime readiness files for HTTP Chroma are namespaced by host/port under `artifacts/rag_workflow/indexes/http-<backend-hash>/`. Embedded Chroma retains the existing `indexes/<version>.json` location. This prevents a restore into a Docker service from replacing the embedded database's checksum. Changing the HTTP hostname may require restoring/verifying the snapshot again.

Chroma can introduce float32 rounding during import. The snapshot file is checked exactly. Restored IDs/text/metadata must match exactly; vectors must match within absolute tolerance `1e-7` and relative tolerance `1e-6`. The restored database then receives its own exact record checksum, linked to the source snapshot's record checksum. Re-exporting an unchanged database is deterministic; exports from different backends can differ slightly in vector bytes. ANN index files and tie ordering are not promised to be byte-identical across platforms or database versions.

## 1. Build the data-processing environment

Run commands from the TrialMatch repository root:

```bash
docker compose build trial-processing
```

DVC and its Google Cloud Storage adapter are installed in the data-processing image. The DVC project is isolated in `services/rag_workflow/.dvc/` using DVC's subdirectory-project support; no repository-wide DVC migration is required. The container uses `core.no_scm` to work with the mounted DVC pointers and data without mounting Git history. Commit pointer changes with Git on the host. See [DVC initialization](https://dvc.org/doc/command-reference/init). The local Python CLI examples below are for development; use `make live` for the complete container workflow.

## 2. Verify the current index

```bash
uv run --locked \
  python -m services.rag_workflow.cli index-status
```

Expected: `status: VERIFIED`, `vector_count: 607`, and the collection/model/dimension/checksum. A missing or changed collection produces a structured error and exit code 1. Offline patient screening remains independent of Chroma.

For a pre-versioning local index, run `build-index` once:

```bash
uv run --locked \
  python -m services.rag_workflow.cli build-index
```

An existing complete legacy collection is validated and given a checksum without creating a cloud client or re-embedding. If no index exists, `build-index` needs the normal GCP environment and incurs embedding usage, as described in the main README. A copied ready file without a matching database is insufficient.

## 3. Export and record a data version

Stop index writers before building/exporting/restoring; the current implementation assumes one index writer. Queries may continue against an existing completed collection. No distributed write lock is implemented.

```bash
uv run --locked \
  python -m services.rag_workflow.cli export-index \
  --output services/rag_workflow/index_snapshots/current.json

docker compose run --rm trial-processing \
  dvc --cd services/rag_workflow add index_snapshots/current.json

docker compose run --rm trial-processing \
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

First obtain the snapshot using the DVC pointer and access to its matching cache/shared remote; cloning Git alone does not download the vectors.

Use a different artifact directory to test restoration while preserving the working database:

```bash
TRIALMATCH_ARTIFACTS=artifacts/rag_workflow_restore_check CHROMADB_HOST= \
  uv run --locked \
  python -m services.rag_workflow.cli restore-index \
  --input services/rag_workflow/index_snapshots/current.json

TRIALMATCH_ARTIFACTS=artifacts/rag_workflow_restore_check CHROMADB_HOST= \
  uv run --locked \
  python -m services.rag_workflow.cli index-status
```

Expected: `RESTORED`, then `VERIFIED`, both with 607 vectors. No GCP credentials are required. A restore checks the snapshot schema/checksum and matching source/configuration before inserting anything. It refuses conflicting target records, preserves existing collections, and can resume an interrupted restore if all existing records match. For conflicts, use a fresh dedicated database/path; the tool never deletes collections or volumes.

For an older version, select the Git revision containing its source data, code/configuration, trial-subset manifest and `.dvc` pointer, then run DVC checkout/pull before restoring. Merely changing a pointer while keeping incompatible source data is rejected. Selecting the corresponding source/configuration selects the historical collection. Fine-tuned encoder selection is separate runtime state, described below.

## 5. Shared storage

The default DVC remote `team` is configured in `.dvc/config`:

```text
gs://trialmatch-ac215-yixiao-dvc/dvc
```

The bucket belongs to GCP project `trialmatch-ac215-yixiao` and uses Standard storage in `us-east1`. It is private. Downloading requires object read permission; publishing new versions requires object creation permission on the bucket. Storage access is separate from Gemini access.

With the Google Cloud CLI installed, sign in on your own machine:

```bash
gcloud auth application-default login
```

Create `secrets/` and copy the credentials file printed by the command to `secrets/google-credentials.json`.
Then download the snapshot from the repository root:

```bash
docker compose run --build --rm trial-processing \
  dvc --cd services/rag_workflow pull index_snapshots/current.json.dvc
```

After recording a new snapshot with `dvc add`, upload it with:

```bash
docker compose run --rm trial-processing \
  dvc --cd services/rag_workflow push index_snapshots/current.json.dvc
```

Commit the remote configuration and matching pointer/summary to Git. Keep credentials, caches and the snapshot itself out of Git.

On 2026-10-20, the existing 607-vector snapshot was uploaded with DVC 3.67.1 and downloaded into an empty directory/cache in Google Cloud Shell. Its SHA-256 matched `6093058582c851a5cefd0cf6987650cd3610eb5416752c7ac4d82a94e9046de6`, and `dvc status --cloud` reported that the cache and remote were in sync. This check used the project owner's account. No Gemini calls were needed.

The same fresh-cache download was verified on the local Mac, followed by
restoration into Docker Chroma. From the root, `make live` downloads and restores
the snapshot automatically using the credentials mounted from `secrets/google-credentials.json`.

## 6. Restore into the separate Docker Chroma service

`make live` pulls the snapshot through `trial-processing` and restores it through `rag-api`. The downloaded file is saved under `services/rag_workflow/index_snapshots/` and shared with the RAG container. To repeat just the restore and verification while the app is running:

```bash
docker compose exec -T rag-api python -m services.rag_workflow.cli restore-index \
  --input /app/services/rag_workflow/index_snapshots/current.json

docker compose exec -T rag-api python -m services.rag_workflow.cli index-status
```

The same commands work after `make live`; both modes use the root `docker-compose.yml`. The database volume provides persistence; DVC provides retrievable snapshot versions. This is a collection export using Chroma's [Get API](https://docs.trychroma.com/docs/querying-collections/query-and-get), not a physical backup of the server's database/configuration.

## 7. Verification and review

```bash
uv run --locked \
  python -m unittest discover -s services/rag_workflow/tests -v
uv run --locked ruff check services/rag_workflow
```

The DVC integration test uses a temporary Git repository and local-directory remote. It records two versions, selects the older Git pointer, removes only its disposable working file/cache, pulls the original bytes and verifies clean status. It never pushes this branch or uploads to cloud storage. The test is in `cloud/tests/test_dvc_snapshot.py` and runs in the workflow environment.

## 8. Fine-tuned encoder catalog and selection record (MS4)

`services/rag_workflow/encoders.py` declares the fine-tuned checkpoints that may serve retrieval.
It is a `.py` file because the `rag-api` image copies only `services/rag_workflow/*.py`.

| Name | Evaluated | Role |
| --- | --- | --- |
| `train-20261110-t4-r3` | Yes, MS3 retrieval benchmark | `DEFAULT_FINETUNED` |
| `pipeline-20261112` | **No** | Demonstration target only; requires `--allow-unevaluated` |

Both use base `thomas-sounack/BioClinical-ModernBERT-base@c3648aa87af95837c809e6f0c5f85d08160db437`,
768 dimensions and a 2,048-token budget. Each entry fixes the checkpoint URI and SHA-256.

The **active** encoder is runtime state, stored beside that backend's readiness manifests:

| Backend | Selection record |
| --- | --- |
| Embedded Chroma | `$TRIALMATCH_ARTIFACTS/indexes/active-finetuned.json` |
| HTTP Chroma (Compose, Cloud Run) | `$TRIALMATCH_ARTIFACTS/indexes/http-<backend12>/active-finetuned.json` |

```json
{
  "schema_version": 1,
  "retrieval_model": "finetuned",
  "active": "pipeline-20261112",
  "previous": "train-20261110-t4-r3",
  "index_version": "<20 hex>",
  "previous_index_version": "<20 hex>",
  "activated_at": "<UTC ISO-8601>",
  "history": [{"action": "switch", "from": "…", "to": "…", "index_version": "…", "at": "…"}]
}
```

- **No record**: `Settings.for_retrieval("finetuned")` returns the MS3 settings unchanged
  (`train-20261110-t4-r3`). Cloud Run starts without a record and therefore serves the default.
- **Valid record**: the named catalog entry is used.
- **Damaged record, or an encoder not in the catalog**: `ENCODER_SELECTION_INVALID`. The record
  is never repaired, and the code never falls back silently.
- `gemini` and an unset `retrieval_model` never read the record.

## 9. Switch runbook

Run from the repository root while the stack is running (`make up` or `make live`). The same
CLI arguments apply to an embedded database.

1. Check the current state. The output includes `encoder_selection.active` and `.previous`,
   with `evaluated`, `index_version` and `index_status` for each:

   ```bash
   docker compose exec -T rag-api python -m services.rag_workflow.cli \
     --retrieval-model finetuned index-status
   ```

2. Switch. Use `--allow-unevaluated` only for the unevaluated demonstration checkpoint:

   ```bash
   docker compose exec -T rag-api python -m services.rag_workflow.cli \
     --retrieval-model finetuned switch-index --to pipeline-20261112 --allow-unevaluated
   ```

   Add `--snapshot <file>` to restore the candidate from an exported snapshot instead of
   encoding. The command checks the catalog and evaluation flag, verifies the checkpoint
   SHA-256 (downloading it once to `cache/checkpoints/`), builds or restores into the
   candidate's own collection, runs `verify()` and two probe queries, and only then replaces
   the record atomically (temporary file, `fsync`, `os.replace`). It prints `SWITCHED`, or
   `ALREADY_ACTIVE` with the record unchanged. Any error exits with status 1 and a JSON
   `{"error": CODE}`, and the record is unchanged.

3. Check `/ready?retrieval_model=finetuned`. Both screening and readiness select
   the new encoder on the next request; no API restart is needed.

Building a fine-tuned index downloads the checkpoint (about 600 MB) and encodes every criterion
fragment on CPU. It needs Google credentials with read access to the checkpoint bucket.

## 10. Rollback runbook

```bash
docker compose exec -T rag-api python -m services.rag_workflow.cli \
  --retrieval-model finetuned rollback-index
```

Rollback re-verifies the previous encoder's collection and swaps `active` and `previous`. It
never creates an encoder and never re-encodes. Running it twice alternates between the two
versions. If the previous encoder is unevaluated, add `--allow-unevaluated`.

## 11. Recovering from failures

The full failure-mode table is in `docs/ms4/EMBEDDING_INDEX.md` §2.4. Until the final record
write, every failure leaves the served index unchanged.

| Symptom | Recovery |
| --- | --- |
| `switch-index` failed during encoding | Fix the cause and rerun the same command. The partial candidate collection has no readiness manifest, is never served, and is reused |
| `EMBEDDING_CHECKPOINT_MISMATCH` | Remove `cache/checkpoints/<sha256>` and `<sha256>.complete` under the artifacts root so the checkpoint downloads again; check the catalog digest |
| `ROLLBACK_TARGET_NOT_READY` | Restore the previous encoder's snapshot with `restore-index --input <snapshot>`, then run `rollback-index` again |
| `ENCODER_SELECTION_INVALID` | Inspect the file printed in the message, then move it aside. The backend returns to the default encoder |
| `ENCODER_SELECTION_WRITE_FAILED` | The old record is intact. Fix disk space or permissions, then rerun |

For example, to move a damaged record aside on the Compose backend:

```bash
mv artifacts/infra/rag_workflow/indexes/http-66ed9a0e94e2/active-finetuned.json \
  artifacts/infra/rag_workflow/indexes/http-66ed9a0e94e2/active-finetuned.json.invalid
```

## 12. Gemini compared with fine-tuned

| | Gemini | Fine-tuned BioClinical |
| --- | --- | --- |
| Versions | One (`gemini-embedding-001`, 256 dimensions) | Catalog in `encoders.py` |
| Index source | DVC snapshot `index_snapshots/current.json` | `build-index` or `switch-index`; cloud snapshots under `{checkpoint parent}/indexes/` |
| Switching | Not applicable | `switch-index` / `rollback-index` |
| Identity | Source, subset, model, dimension, chunker | The same, plus encoder revision, pooling, token budget and checkpoint SHA-256 |
| Credentials | Vertex AI for building; none to restore | GCS read for the checkpoint; none to restore a snapshot or roll back |

**Verification.** `services/rag_workflow/tests/test_index_switching.py` covers switch,
failed switch, rollback and recovery on embedded Chroma. `make system-test` also
runs `scripts/ms4/check_index_switch.py` against the Compose Chroma server. Both
use local test checkpoints and fake encoders. Actual GCS checkpoint loading and
live inference still require credentials and are not part of offline CI.
