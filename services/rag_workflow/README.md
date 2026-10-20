# Part 3: RAG / Retrieval / Workflow (MS2)

Input: **one normalized patient record from Part 2 + a question**. Output: candidate clinical trials, **match scores**, explanations, criterion-level assessments, and references to source evidence. Built-in patients are selected by `patient_id`. The default input is the **25-patient adult T2D cohort**, rather than the four-patient sample file.

This module consumes the processed outputs of Parts 1 and 2. It adapts the tutorial's Gemini embeddings, Chroma, and model calls to TrialMatch. Cheese-specific questions, book/author metadata, and fixed 350-character document chunks are replaced with patient context and eligibility criteria. The API, CLI, and Python function share the same workflow.

Project interaction is in English: use English questions, and all generated reasons, explanations, and fallback messages are written in English. The current Part 3 walkthrough stops after CLI execution and JSON result inspection (Sections 1–2); frontend/browser integration is a later handoff to Part 5.

## 1. Quick start

Run all commands from the **TrialMatch repository root**:

```bash
cd /Users/yangzhenyu/Desktop/AC215/TrialMatch
uv sync --project services/rag_workflow --locked
uv run --project services/rag_workflow --locked python -m services.rag_workflow.cli inspect-data
```

Expected counts: 25 patients, 1,313 trials, and 18,456 criteria. This development branch is based on `feat/patient-processing`; the patient module is not present in the version of `main` used for this implementation. Do not replace the cohort with the four-patient `patients.jsonl` without updating the manifest.

**Run an offline demo without cloud access:**

```bash
uv run --project services/rag_workflow --locked python -m services.rag_workflow.cli --mode offline screen \
  --patient-id 060e72d3-912e-55cd-0c92-5faa6cb7a6db \
  --question 'Which clinical trials may suit this patient, why, and what concerns need review?' \
  --top-k 3 --output artifacts/rag_workflow/demo_offline.json
```

Offline mode uses **real BM25 retrieval and deterministic numeric rules**. Unsupported criteria remain UNKNOWN; no LLM judgments are fabricated. Use this mode to check data, interfaces, and frontend integration. It does not demonstrate an LLM run. The response always retains `mode=offline`.

## 2. Live mode: GCP + Chroma + LLM

```bash
cp services/rag_workflow/.env.example services/rag_workflow/.env
```

Edit `.env` to set `GCP_PROJECT` and the **absolute local path** to the credential JSON. Do not commit the credential file or `.env`. This local checkout already has a Git-ignored `.env` configured to use the tutorial's credential location; configure it again on another machine.

Enable `aiplatform.googleapis.com`. The service account needs `roles/aiplatform.user` on the project used for inference; the displayed role name may be Vertex AI User or Agent Platform User. Existing working credentials do not need to be recreated.

**Build the fixed 50-trial index for the first time:**

```bash
uv run --project services/rag_workflow --locked --env-file services/rag_workflow/.env \
  python -m services.rag_workflow.cli build-index
```

This embeds 607 criterion retrieval fragments with `gemini-embedding-001` at 256 dimensions, with at most four concurrent requests. Embeddings are cached under `artifacts/rag_workflow/cache/embeddings/`; embedded Chroma data is stored under `artifacts/rag_workflow/chroma/`. Repeated builds verify and reuse a completed collection without model calls; an interrupted unpublished build can reuse embedding caches. The initial build incurs model API usage. Changes to source data, the model, dimensions, or the trial subset produce a different collection version.

**ChromaDB versioning:** [INDEX_VERSIONING.md](INDEX_VERSIONING.md) explains snapshot export, DVC tracking, integrity checks, restoration and the Part 4 handoff. An actual 607-vector snapshot is cached locally with a Git-reviewable summary and DVC pointer. The shared remote still needs to be supplied by Part 4; a Git clone alone does not provide the snapshot. The snapshot has not been uploaded to shared cloud storage. For an older local index, run `build-index` once to add a checksum without re-embedding.

Each Vertex request to `gemini-embedding-001` sends one input text. The tutorial's multi-text request pattern is not reused. Long criteria may be split into traceable retrieval fragments, but screening always evaluates the complete original criterion.

**Run the complete screening workflow:**

```bash
uv run --project services/rag_workflow --locked --env-file services/rag_workflow/.env \
  python -m services.rag_workflow.cli --mode live screen \
  --patient-id 060e72d3-912e-55cd-0c92-5faa6cb7a6db \
  --question 'Which clinical trials may suit this patient? Explain supporting evidence, screening barriers, and concerns requiring review.' \
  --top-k 3 --output artifacts/rag_workflow/demo_live.json
```

The default generation model is `gemini-3.1-flash-lite`; override it with `GENERATIVE_MODEL`. Response `metrics` include request counts, cache hits, token counts reported by the provider, and elapsed time. Judgment cache keys include the question, evidence, prompt, model, and schema, so a changed question does not incorrectly reuse an earlier answer.

The CLI accepts `--patient-file /absolute/path/patient.json` instead of `--patient-id`. The file must contain one normalized Part 2 v0.3 patient object, not a FHIR Bundle. Place `--mode` **before** the `screen` subcommand.

### Reading a CLI result

For example, `Wrote artifacts/rag_workflow/demo_offline.json: OK, 3 candidates` means:

- `Wrote ...`: the JSON response was saved at that path.
- `OK`: the workflow completed without recorded system/model errors. It does not mean the patient meets eligibility criteria.
- `3 candidates`: three candidate trials were returned from the configured 50-trial subset. They still require criterion-level review; this is not three confirmed eligible trials.

Open the JSON in VS Code and read `mode`, `result_status`, and `errors` first. Next read `answer`, then each trial's `screening_status`, `question_response`, `match_score`, and `assessment_coverage`. Inspect `criteria_assessments` and the linked `evidence` to trace a conclusion to its source facts. `NEEDS_MORE_INFORMATION` means the available evidence does not support a complete assessment; `SCREENING_BARRIER` means at least one assessed criterion is a barrier; `POTENTIAL_MATCH_FOR_REVIEW` still requires human review. A low score with many UNKNOWN criteria is not a low enrollment probability.

Stop here for the current Part 3 walkthrough. The HTTP/browser integration below is a later handoff to Part 5.

## 3. Part 5 frontend: HTTP and Python interfaces

**Start the local API, which defaults to offline mode:**

```bash
uv run --project services/rag_workflow --locked \
  python -m uvicorn services.rag_workflow.api:app --host 127.0.0.1 --port 8080
```

For a live API, set `TRIALMATCH_MODE=live` in `.env`, add `--env-file services/rag_workflow/.env` to `uv run`, and first complete `build-index` using the same Chroma configuration. Restart the API after changing its environment.

- `GET /health`: checks data and the manifest. **It does not verify GCP permissions or vector-index readiness.**
- `GET /patients`: returns the 25 selectable patient IDs, reference dates, ages, genders, and source death dates, without returning complete patient records.
- `POST /screen`: runs screening.
- `GET /docs`: interactive FastAPI documentation. `GET /openapi.json`: OpenAPI schema.

```bash
curl -s http://127.0.0.1:8080/screen \
  -H 'Content-Type: application/json' \
  -d '{"patient_id":"060e72d3-912e-55cd-0c92-5faa6cb7a6db","question":"Which clinical trials may suit this patient, why, and what concerns need review?","top_k":3}'
```

Alternatively, provide `{"patient": <normalized patient object>, "question": "...", "top_k": 3}`. Supply exactly one of `patient` or `patient_id`. The question must not be blank, and `top_k` must be between 1 and 5. For built-in patients, the frontend only needs to send the ID; the backend loads the record from the 25-patient cohort.

Call from a Python application:

```python
from services.rag_workflow.workflow import screen_patient

result = screen_patient(patient, question="Which trials may suit this patient, and why?", top_k=3)
```

For repeated calls, reuse a `ScreeningWorkflow` instance and call `.screen(ScreenRequest(...))` to avoid reloading data. `Settings` controls the mode, models, and paths. The interface is synchronous: the MS2 frontend should show a loading state and allow for longer response times. Production asynchronous jobs and authentication are outside this version's scope.

The frontend primarily consumes these fields:

| Field | Frontend use |
|---|---|
| `mode`, `result_status`, `warnings`, `errors` | Distinguish live/offline/mock and success/partial failure/failure/no candidates; do not interpret system errors as patient ineligibility |
| `answer` | Combined response to the user's question |
| `candidate_trials[]` | Candidate trial cards |
| `trial_id`, `brief_title`, `source_url` | Trial identity, title, and ClinicalTrials.gov source |
| `recruitment_status` | Source recruitment status, separate from the screening assessment |
| `match_score`, `score_type` | Match score and its definition |
| `screening_status`, `summary`, `question_response` | Screening status, coverage summary, and explanation addressing the question |
| `criteria_assessments[]` | Optional detail view: MET / NOT_MET / UNKNOWN, reasons, and missing information |
| `evidence` | Evidence dictionary keyed by fact_id, including source dates, values, units, and provenance |
| `assessment_coverage`, `missing_information`, `screening_concerns` | Known/unknown/barrier counts, missing information, and screening concerns |

`eligibility_probability` is always `null`. The score is `match_score = 100 × (inclusion MET + exclusion NOT_MET) / total criterion count`, with UNKNOWN criteria retained in the denominator. It therefore reflects record completeness as well as criterion satisfaction and **is not an enrollment probability**. An exclusion MET or inclusion NOT_MET creates a barrier that a high score cannot offset. Ordering separates confirmed barriers before applying retrieval rank; scores never automatically authorize enrollment.

HTTP behavior: invalid requests or patient records return 422; unknown patient IDs return 404; failed live retrieval returns 503 with a structured error response; partial model failures return 200 with `result_status=PARTIAL`. The CLI exits with code 1 for ERROR/PARTIAL. `NO_CANDIDATES` is distinct from a system error and does not establish ineligibility for all trials.

`examples/mock_screening.json` is a static frontend fixture explicitly marked **mode=mock**. `examples/demo_offline.json` is an actual offline result. Live results are saved under artifacts and may be copied into examples after verification. The frontend must not silently substitute mock data when an API call fails.

## 4. File guide

| File | Purpose |
|---|---|
| `__init__.py` | Module identity and version |
| `config.py` | Environment variables, default 25-patient data path, model/index configuration, context limits, and inference budgets |
| `data.py` | Reads Part 1/2 JSONL, validates patient references/dates/fields, builds trial/criterion/patient lookups, and manages hashes and the fixed-subset manifest |
| `retrieve.py` | BM25, patient retrieval profiles, lexical/vector rank fusion, trial deduplication, and criterion-specific patient evidence selection |
| `rules.py` | Complete supported age/BMI/HbA1c/glucose comparisons, unit/sample/date checks and three-valued flat numeric OR/AND logic |
| `evidence_rules.py` | Explicit consent/test/history evidence, alternative and time-window coverage, source-provided albumin ranges, and separate medication-time/class checks |
| `providers.py` | Google Gen AI client, single-text embeddings, structured generation, caches, bounded retries, token metrics, and sanitized error messages |
| `index.py` | Criterion vector ingestion, immutable completed collections, backend-specific readiness, checksum verification and portable export/restore for embedded or HTTP Chroma |
| `index_versions.py` | Strict snapshot schema, canonical record hashing, paged reads and float32 import comparison |
| `judge.py` | Batched LLM judgments, per-criterion evidence allowlists, one repair attempt, abstention on persistent failure, and citation checks for trial explanations |
| `workflow.py` | Public function, pipeline orchestration, complete criterion coverage, rule-first assessment, LLM budgets, aggregation, scoring, evidence ledger, and responses |
| `schemas.py` | Pydantic contracts for requests, responses, states, and LLM output; rejects undefined fields |
| `api.py` | `/health`, `/patients`, `/screen`, OpenAPI, and local frontend CORS, without duplicating business logic |
| `cli.py` | inspect-data / make-manifest / build-index / index-status / export-index / restore-index / screen / export-schema commands |
| `prompts/criterion_judge.txt` | Evidence, negation, medication, and timing instructions for criterion judgments |
| `prompts/trial_explanation.txt` | Answers the question from validated assessments; disallows unsupported treatment-risk or probability claims |
| `examples/demo_manifest.json` | Fixed 50-trial subset, 25 patient IDs, three demo patient IDs, source hashes, and selection rules |
| `examples/screen_request.json` | Request example for Part 5 |
| `examples/mock_screening.json` | Complete frontend fixture explicitly labeled as mock |
| `examples/demo_offline.json` | Actual offline response using the synthetic cohort |
| `examples/demo_live.json` | Actual GCP + Chroma + LLM response, retaining its mode, timing, and cache metrics |
| `examples/contract.schema.json` | Automatically exported request/response JSON schemas |
| `examples/verification.json` | Verification results and scope; not clinical validation |
| `examples/index_versioning_verification.json` | Actual 607-vector snapshot/embedded/Docker restore verification; no new model calls |
| `index_snapshots/current.manifest.json`, `index_snapshots/current.json.dvc` | Git-reviewable snapshot summary and DVC pointer; the vector payload is Git-ignored |
| `.dvc/`, `.dvcignore` | Isolated DVC project for index snapshots; local cache/config/internal state are ignored |
| `tests/__init__.py` | Test package marker |
| `tests/test_workflow.py` | Synthetic edge cases, evidence references, failure handling, actual cohort/API integration, and embedded Chroma tests |
| `tests/test_evidence_support.py` | Regressions from live smoke testing: missing data is not negative evidence, prescriptions do not establish drug use, short-reference mapping, and context budgets |
| `tests/test_index_versions.py` | Snapshot restore, version isolation, source/checksum tampering, conflict preservation, legacy migration and credential-free CLI checks |
| `tests/test_dvc_snapshot.py` | Optional DVC/Git historical-pointer recovery test with a disposable local remote |
| `pyproject.toml`, `uv.lock` | Independent dependency definitions and locked versions, without changing Part 2's environment |
| `.env.example`, `.env` | Committable configuration template / Git-ignored local configuration |
| `.gitignore` | Excludes local configuration, the virtual environment, and caches |
| `Dockerfile` | Runnable Part 3 image using the lockfile and an unprivileged user |
| `docker-compose.yml` | Local offline API + Chroma without credential mounts; integration example for Part 4 |
| `docker-compose.live.yml` | Adds an external service-account credential mount and enables live mode |
| `README.md` | Setup, file descriptions, and team handoff instructions |
| `INDEX_VERSIONING.md` | DVC and Chroma versioning tutorial, precision limits, restoration and shared-storage handoff |

The repository-level `.dockerignore` excludes virtual environments, credentials, and artifacts from the build context. The root `.gitignore` adds exclusions for Part 3 local state, and the root README links to this module. Part 1/2 processing code and data were not modified.

## 5. Data and assessment boundaries

Default inputs:

```text
services/trial_ingestion/data/processed/trials.jsonl
services/trial_ingestion/data/processed/criteria.jsonl
services/patient_processing/data/processed/batch25_patients.jsonl
```

The manifest selects the first 50 trials by trial_id among recruiting studies with 3–25 criteria and no detected ambiguous or cohort/group/arm markers. This is a reproducible, conservative technical subset, **not a guarantee of correct clinical logic**. After changing input data, explicitly regenerate the manifest. A source-hash mismatch produces an error instead of silently reusing a stale index.

```bash
uv run --project services/rag_workflow --locked python -m services.rag_workflow.cli make-manifest --trial-count 50
```

Workflow: patient record + question → BM25/vector retrieval → candidate trials → all criteria for each candidate from processed data → criterion-relevant patient facts → rules/LLM → validation → aggregation. A few highly similar retrieved criteria do not establish eligibility for an entire trial.

- Inclusion MET is favorable; inclusion NOT_MET is a barrier.
- Exclusion MET is a barrier; exclusion NOT_MET is favorable. Missing records do not establish NOT_MET.
- UNKNOWN, incomplete, or ambiguous assessments prevent POTENTIAL_MATCH_FOR_REVIEW.
- Every model batch must return all requested criteria and cite only the patient facts supplied for each criterion.
- Model inputs use local evidence aliases such as F0/F1. Outputs map back to Part 2's original fact_id values; aliases never replace source references in the API. Each criterion receives at most 12 facts and approximately 12,000 characters. Oversized facts are omitted whole rather than having clinical values truncated, so UNKNOWN remains possible.
- `validation_warnings` records why a proposed model judgment was downgraded to UNKNOWN; `model_decision` preserves the proposal for audit. Complex numeric/temporal/severity logic not verified by deterministic rules, unsupported negative evidence, and drug-use claims based only on prescriptions are conservatively downgraded. This version consequently has a high UNKNOWN rate.
- Invalid structure or references receive at most one repair attempt. Persistent failures become UNKNOWN with an error. A 403 is not repeatedly retried with delays; rate limits and temporary service failures use bounded backoff.
- A request allows at most 12 judgment batches of up to six criteria each, plus trial explanation calls. Criteria beyond the budget remain UNKNOWN and stay in the score denominator.
- Patient dates are interpreted relative to `reference_date=2021-11-30`; the trial snapshot is `2026-10-11`. This is a historical synthetic-record demonstration against a fixed registry snapshot, not evidence of current enrollment eligibility.
- Part 2 does not process resource types such as AllergyIntolerance, and some clinical statuses remain uncertain. These limitations are retained in warnings. Prescriptions, medication definitions, and administrations are separate evidence types.
- Explanations of "risk" primarily cover screening barriers and issues needing review. The corpus does not contain complete treatment adverse-event information and cannot establish treatment safety.
- Valid schemas and source IDs do not establish semantic correctness. LLM explanations, negative evidence, complex AND/OR logic, and medication timing still require manual review.

## 6. Docker integration for Part 4

Local development can use embedded Chroma. Setting `CHROMADB_HOST` switches to a separate HTTP Chroma service. Their storage differs: restore a matching exported snapshot or build the index in the target service when switching. Embedding caches can be reused, but copying an index-ready file does not populate the target database. See [INDEX_VERSIONING.md](INDEX_VERSIONING.md) for restoration without new embedding calls.

```bash
docker compose --env-file services/rag_workflow/.env \
  -f services/rag_workflow/docker-compose.yml up --build
```

Offline mode does not require a credential mount. The API binds to `127.0.0.1:8080` on the host. For live mode, use both Compose files and ensure the credential path in `.env` exists:

```bash
docker compose --env-file services/rag_workflow/.env \
  -f services/rag_workflow/docker-compose.yml \
  -f services/rag_workflow/docker-compose.live.yml up --build -d

docker compose --env-file services/rag_workflow/.env \
  -f services/rag_workflow/docker-compose.yml \
  -f services/rag_workflow/docker-compose.live.yml \
  exec rag-api python -m services.rag_workflow.cli build-index
```

Source data is mounted at `/app/services`, outputs/caches at `/app/artifacts/rag_workflow`, and Chroma uses a separate volume. The service-account JSON is mounted read-only at `/secrets/llm-service-account.json`. Replace the tutorial-specific `../llm-rag:/app` mount when integrating TrialMatch. Do not run `down -v` against existing Chroma data.

This is a local demonstration API without public authentication/authorization. Part 4 should add access controls and deployment configuration before exposing it beyond the local machine.

## 7. Verification

```bash
uv run --project services/rag_workflow --locked python -m unittest discover -s services/rag_workflow/tests -v
uv run --project services/rag_workflow --locked ruff check services/rag_workflow
```

Tests do not automatically call GCP. They cover the actual 25-patient/50-trial inputs, inline-patient and patient-ID requests, incorrect subject references and future facts, age and HbA1c rules, missing units/dates, conflicting same-day results, exclusion direction, UNKNOWN handling, missing/duplicate/fabricated references, repair limits, 403 handling, the HTTP contract, and Chroma upserts/persistence/model-version isolation.

Actual live-run records are in `examples/verification.json` and `artifacts/rag_workflow/`. These technical checks are not clinical-validity or accuracy evaluations. Full 25-patient × full-corpus inference, double annotation, and ablation experiments are deferred to later milestones.

Original MS2 checks: 25 automated tests, Ruff, a real 607-fragment embedding index, a live CLI run for one synthetic patient and three candidates (`OK`, no system errors), a Docker build, and an offline container run without network access or credentials. Of the current English live example's 59 criteria, 3 received definite assessments and 56 remained UNKNOWN. This describes coverage, not accuracy. Live timing includes cache hits; see the verification record. HTTP endpoints were checked with TestClient; the complete Compose stack has not been deployed as a persistent service.

The Chroma versioning revision passes 42 automated tests, including 15 index-version tests and one real DVC/Git historical-pointer recovery test, plus Ruff. The existing 607-vector snapshot was recovered from the DVC cache and restored into fresh embedded and isolated Docker HTTP Chroma stores. Three stored-vector probes returned the same top-five trial IDs across all three databases. No new model calls were made; the temporary Docker service was removed. Shared GCS storage remains a Part 4 configuration step. Details are in `examples/index_versioning_verification.json`.

Three separate guides document the October 19 recorded case:

- [End-to-end retrieval demonstration](examples/grounding_case/END_TO_END_DEMONSTRATION.md): actual patient question, hybrid retrieval, retrieved criteria, patient evidence IDs, judgments and score for returned trial `NCT03821636`. The overall three-candidate run remains PARTIAL.
- [Claude / Gemini / RAG grounding comparison](examples/grounding_case/GROUNDING_COMPARISON.md): all 14 decisions for fixed trial `NCT02390973`. Claude and initial raw Gemini each have 5 MET, 6 NOT_MET and 3 UNKNOWN; the revised RAG judgment layer has 4 MET, 4 NOT_MET and 6 UNKNOWN. This isolates judgment behavior and bypasses retrieval.
- [Guard revision](examples/grounding_case/GUARD_REVISION.md): concise changes, reasons and old/new results on that same fixed-trial fixture. Definite outcomes increased from 1/14 to 8/14, preserving all four inclusion positive controls. The 67 RAG tests and Ruff passed at the checkpoint.

The [case file guide](examples/grounding_case/README.md) links original inputs, compact live reports and replay commands. No clinical-accuracy or full end-to-end pass is claimed; source data and the synthetic fixture are unchanged.

## 8. Team handoff

**Part 5 (frontend):**

1. Share Section 3, `screen_request.json`, `mock_screening.json`, and `contract.schema.json`.
2. Inputs: a selected patient ID and a question. Results: trial cards, match_score, screening_status, and question_response. Detail views can use criteria_assessments and evidence.
3. Start with the static mock, then the local offline API, then live mode. Display the mode, errors, and UNKNOWN states; do not label scores as enrollment probabilities.

**Part 4 (infrastructure/integration):**

1. Share `pyproject.toml`, `uv.lock`, the Dockerfile, both Compose files, and `.env.example`.
2. Agree on API port 8080, Chroma host/port, read-only inputs from both data modules, persistent artifacts, and credential mounts.
3. Incorporate this example into the team's root Compose/Makefile without duplicating databases. Expose `build-index`, `index-status`, `export-index`, `restore-index` and `screen`.
4. Follow [INDEX_VERSIONING.md](INDEX_VERSIONING.md): agree on shared DVC storage, grant object access, publish/pull the snapshot separately from Git, and restore into the target Chroma service. DVC runs on the host/CI, not inside the database image.

**Parts 1 and 2 (data):**

- Preserve criterion_id, criterion_type, parse_status, snapshot_date, patient reference_date, and original fact_id values.
- Notify Part 3 when processed files change so the manifest/index can be regenerated. Do not silently mix data versions.
- Report multi-cohort or context-loss concerns to Part 1. Downstream processing should return UNKNOWN rather than rewriting source data.

**Git handoff:**

- The delivery branch is `rag-workflow`, based on `feat/patient-processing`, so it includes Part 2's data. The Part 3 implementation is reviewed relative to that base; publishing this branch does not merge it into main.
- Review changes with `git diff origin/feat/patient-processing --stat` and `git status --short`; inspect new files as well.
- Until Part 2 is merged into main, make this dependency clear to reviewers. Review Part 3 against the patient branch first if appropriate, then update the base after Part 2 merges. Do not attribute Part 2's commits to Part 3.
- Commit `services/rag_workflow/` and the root README/.gitignore/.dockerignore changes. Exclude `.env`, credentials, `.venv`, artifacts, and Chroma caches.
- Demo screenshots/videos should show the synthetic-data label, patient reference date, trial snapshot, and mode. Report the current high UNKNOWN rate accurately.

Suggested handoff message:

> Part 3 provides a unified patient-ID/normalized-record + question interface returning candidate trials, match scores, explanations, criterion assessments, and fact_id evidence. Part 5 can start with the example mock and schema, then connect to POST /screen. Part 4 can use the module's Compose configuration to integrate data, Chroma, and credentials. The 25-patient T2D cohort is on the patient-processing branch, which Part 3 depends on. Scores describe criterion satisfaction, not enrollment probabilities; UNKNOWN states and API failures are returned explicitly.

The English-interaction revision passed 20 CLI-focused checks and regenerated the English request, mock, offline, and live examples. No browser or HTTP server was started for this revision. The successful live replay reused cached responses from actual English GCP calls; see `english_cli_revision` in the verification record.
