# Ovrz's MS2 application delivery

This branch adds the English application skeleton and supporting delivery
materials. It calls the team's real screening backend. It does not modify any
file that existed at the base commit.

Base: `rag-workflow`, commit `8eba4c0c560d1c58a2c390e63b70ed5bd7cf2470`.
That branch already includes the patient and trial modules. The current `main`
does not include all those dependencies. A PR to `main` would therefore show
other teammates' commits too. Review this contribution against its stated base.

The original application contribution added:

- `services/frontend/`: frontend, thin API wrapper, vector demo, preparation, tests.
- `demo/ovrz/`: local launchers and verification scripts.
- `docs/ovrz-ms2/`: handoff, presentation notes, checklist and evidence.

The infrastructure integration now maintains Docker, Compose and dependencies
at the repository root. The launchers use that shared environment. Application
code, source data, RAG logic and existing tests are unchanged. See
[the shared setup](../../README.md).

## Quick start

Python 3.12 and uv are required for local development. On Windows, preserve
the source JSONL bytes because the upstream manifest checks their hashes:

```bash
git -c core.autocrlf=false clone --branch yixiao/infra https://github.com/liujiaxi0301/TrialMatch.git
cd TrialMatch
```

The integrated submission is published on `milestone2`; clone that branch
for the submitted version. The earlier branch history remains available.

Windows PowerShell:

```powershell
.\demo\ovrz\run-local.ps1
```

macOS/Linux:

```bash
sh demo/ovrz/run-local.sh
```

Open http://127.0.0.1:8080/ and keep the terminal running.
If another demo already uses the port, stop it or run the PowerShell launcher
with `-Port 8081`. An existing checkout with converted CRLF data can fail the
manifest check; use a fresh byte-preserving checkout as above. Do not weaken
the integrity check or replace teammates' manifests.

## Container startup

From the repository root, with Docker Engine running:

```bash
docker compose -f docker-compose.yml up --build --wait --wait-timeout 300
```

The shared Compose project validates the trial and patient snapshots, starts
Chroma, runs preparation, then starts the app/API. Data is read directly from `services/`.
Preparation builds/verifies 607 criterion vectors, retrieves context and saves
a real offline screening response.

Python services use the root Dockerfile, `pyproject.toml` and `uv.lock`.
Chroma uses its pinned upstream image and a persistent named volume. Outputs
are saved under `artifacts/infra/`. Only the application port is exposed,
on loopback.

```bash
docker compose -f docker-compose.yml ps -a
docker compose -f docker-compose.yml logs --no-color
docker compose -f docker-compose.yml exec -T rag-api python demo/ovrz/verify_http.py
docker compose -f docker-compose.yml down
```

`down` preserves volumes. The Windows script
`demo/ovrz/verify-container.ps1` captures the actual container logs and HTTP
input/output. Stop the existing local service before using port 8080 for Docker.

The original frontend delivery was verified without Docker. Shared Docker
commands are in [README.md](../../README.md); local run evidence
is saved under `artifacts/infra/`.

## What to demonstrate

1. Search/select a synthetic patient and inspect the reference date.
2. Enter a trial-related question and choose 1–5 candidate trials.
3. Run screening and inspect the returned trial IDs and source links.
4. Expand criteria to review decisions, evidence and missing information.
5. Open/download the actual response JSON.
6. Use `/docs` to call `/retrieve` and inspect Chroma context and provenance.
   V2 intentionally removes the old Inspect vector retrieval button.

The frontend calls HTTP endpoints; it does not substitute mock results when
requests fail. Loading, cancel and error states are visible. Changing patients
clears prior results. Browser cancellation does not guarantee backend cancellation.
The simple question keyword guard is a UX aid, not an LLM intent classifier.

## Modes and limits

- Default `/screen`: upstream BM25 retrieval plus deterministic rules.
  Unsupported criteria remain UNKNOWN. There is no LLM call.
- `/retrieve`: separate real Chroma cosine retrieval with deterministic
  512-dimensional signed token-hash vectors over 607 fragments. These are
  lexical vectors, not pretrained semantic embeddings. It returns context,
  not an eligibility decision.
- Opt-in live `/screen`: existing Gemini embeddings, Chroma, LLM/rule routing
  and evidence validation. Requires authorized cloud credentials and a
  corresponding live index. No new cloud execution was performed here.

The local baseline and Gemini index have different model identities and
collections. The local probe does not replace the team's live index or change
the default BM25 screening path.

For live operation, follow the root [credential setup](../../README.md#online-screening):
copy the Google credentials to `secrets/google-credentials.json` and configure `.env`.
Cloud calls can incur charges. After normal offline startup:

```bash
make live
```

Verify the LIVE label, actual response status, errors and metrics.
`/health` is not a cloud-readiness check.

## Data and versioning

The existing processed snapshot contains 1,313 trials and 18,456 criterion
records. The fixed demonstration subset contains 50 trials and 607 index
fragments. There are 25 synthetic Synthea patient records.

The patient reference date is 2021-11-30; the registry snapshot is 2026-10-11.
These are different concepts. Two cohort records have a source death date on
or before the reference date. The UI preserves the date and does not present
these records as confirmed eligible or currently living candidates.

Source SHA-256 hashes are in the upstream manifest, `/metadata`, the retrieval
result and saved run manifest. Index identity includes hashes, trial subset,
model, dimensions and chunker version.

This demonstration starts from committed, versioned processed snapshots.
It does not download today's trial registry on each run. Collection and
preprocessing are documented in the unchanged
[trial module](../../services/trial_ingestion/README.md) and
[patient module](../../services/patient_processing/README.md).
Those scripts remain in the image. The team should explain the full
collection-to-retrieval process and the snapshot boundary in the presentation.

## Verification and handoff

```powershell
$env:PYTHONUTF8 = '1'
uv run --locked python -m unittest discover -s services/frontend/tests -v
uv run --locked python demo/ovrz/verify_http.py
```

See [evidence](evidence/README.md), [API contract](API.md), and
[MS2 application mock-up and user flow](../ms2/TrialMatch-MS2-Mockup.pdf).

Tests check software behavior and provenance, not clinical accuracy.
