# Trial Ingestion

This module builds the clinical-trial side of the TrialMatch data pipeline.

It retrieves currently relevant Type 2 Diabetes (T2D) studies from ClinicalTrials.gov, normalizes trial metadata, and converts eligibility text into criterion-level records for downstream trial retrieval and patient–trial eligibility screening.

## Pipeline

```text
ClinicalTrials.gov API
        ↓
fetch_trials.py
        ↓
data/raw/*.json
        ↓
normalize_trial.py
        ↓
data/processed/trials.jsonl
        ↓
parse_criteria.py
        ↓
data/processed/criteria.jsonl
```

The complete pipeline can be run from the repository root with:

```bash
uv run python services/trial_ingestion/scripts/run_pipeline.py
```

## Current Scope

The current TrialMatch application domain is Type 2 Diabetes.

The ingestion pipeline retrieves ClinicalTrials.gov studies with the following recruitment statuses:

- `RECRUITING`
- `NOT_YET_RECRUITING`
- `ENROLLING_BY_INVITATION`

ClinicalTrials.gov search results are treated as candidate studies. A separate T2D relevance-selection step is applied during normalization.

## Directory Structure

```text
trial_ingestion/
├── .dvc/
│   └── config
├── .dvcignore
├── README.md
├── SCHEMA.md
├── scripts/
│   ├── fetch_trials.py
│   ├── normalize_trial.py
│   ├── parse_criteria.py
│   └── run_pipeline.py
└── data/
    ├── raw/
    │   └── *.json
    ├── raw.dvc
    ├── raw_metadata.json
    └── processed/
        ├── trials.jsonl
        └── criteria.jsonl
```

## Running the Pipeline

From the repository root:

```bash
uv run python services/trial_ingestion/scripts/run_pipeline.py
```

The pipeline runs three stages in sequence:

1. Fetch candidate trials from ClinicalTrials.gov.
2. Normalize trial metadata and select the supported T2D corpus.
3. Parse eligibility text into criterion-level records.

If any stage fails, the pipeline stops rather than continuing with incomplete output.

## Stage 1: Trial Collection

`fetch_trials.py` queries the ClinicalTrials.gov API for T2D-related studies with currently relevant recruitment statuses.

It automatically follows API pagination and stores one complete raw JSON record per trial under:

```text
data/raw/
```

A new successful fetch replaces the previous raw snapshot so stale trials are not retained across pipeline runs.

## Stage 2: Trial Normalization

`normalize_trial.py` converts raw ClinicalTrials.gov records into a consistent trial-level schema.

It also applies the current T2D relevance-selection logic using information including:

- conditions
- brief title
- official title
- brief summary

The resulting trial corpus is written to:

```text
data/processed/trials.jsonl
```

## Stage 3: Eligibility Parsing

`parse_criteria.py` converts trial eligibility text into criterion-level records.

The deterministic parser handles common ClinicalTrials.gov formats including:

- inclusion and exclusion section headers
- common header variants
- Markdown bullets
- hyphen bullets
- numbered lists
- escaped formatting such as `1\.` and `\-`
- clearly identifiable single criteria

When the source structure cannot be resolved reliably, the text is preserved with:

```text
parse_status = ambiguous
```

rather than being guessed or silently dropped.

Each output record also includes:

```text
parse_method = deterministic
```

An optional LLM-assisted fallback may later be added for ambiguous cases, but it is not required for the current ingestion pipeline.

## Outputs

The downstream TrialMatch retrieval and workflow components should consume two files.

### `trials.jsonl`

Trial-level metadata used for candidate trial retrieval and display.

### `criteria.jsonl`

Criterion-level eligibility records used for criterion retrieval and patient–criterion matching.

The two datasets are linked using:

```text
trial_id
```

See `SCHEMA.md` for the complete field-level data contract.

## Current Snapshot

A full end-to-end pipeline run produced:

```text
Raw candidate trials:        1,385
Processed T2D trials:        1,313
Criterion records:          18,456
Parsed criteria:            18,374
Ambiguous records:              82
```

These counts represent the current ClinicalTrials.gov snapshot and may change as registry data are updated.

## Data Versioning

The raw ClinicalTrials.gov snapshot is versioned with DVC.

The Git repository tracks:

```text
data/raw.dvc
data/raw_metadata.json
```

The raw JSON files themselves are stored in the shared DVC remote rather than Git.

To restore the versioned raw snapshot, run the following from `services/trial_ingestion`:

```bash
uv run dvc pull
```

The current DVC snapshot contains 1,385 raw trial JSON files.

Provenance information, including the API source, query condition, recruitment statuses, retrieval date, DVC checksum, and snapshot size, is recorded in:

```text
data/raw_metadata.json
```

Running `fetch_trials.py` or the full pipeline retrieves a new live ClinicalTrials.gov snapshot and may therefore change the raw dataset. A new snapshot should be re-versioned with DVC before being shared.

## Downstream Handoff

The retrieval/workflow module does not need to read the raw ClinicalTrials.gov files.

It should use:

```text
data/processed/trials.jsonl
data/processed/criteria.jsonl
```

For the initial retrieval workflow, records with:

```text
parse_status == "parsed"
```

can be used directly.

Ambiguous records are intentionally retained for later review or optional fallback processing.

## Module Boundary

This module is responsible for:

- ClinicalTrials.gov data collection
- API pagination
- raw data snapshots
- DVC-based raw data versioning
- data provenance metadata
- trial normalization
- T2D corpus selection
- eligibility criterion parsing
- ambiguity detection
- processed-data schema

This module is not responsible for:

- Synthea/FHIR patient preprocessing
- patient–trial retrieval logic
- patient context selection
- criterion-level `MET / NOT_MET / UNKNOWN` decisions
- final eligibility aggregation

Those responsibilities belong to downstream TrialMatch components.