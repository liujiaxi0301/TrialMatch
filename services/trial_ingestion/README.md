# Trial ingestion

Fetch ClinicalTrials.gov studies, select the Type 2 Diabetes corpus and parse
eligibility text into criteria. The application consumes the processed files;
it does not query the registry during screening.

## Files and data flow

```text
ClinicalTrials.gov -> fetch_trials.py -> raw/*.json
    -> normalize_trial.py -> processed/trials.jsonl
    -> parse_criteria.py -> processed/criteria.jsonl
```

| File | Purpose |
| --- | --- |
| `scripts/fetch_trials.py` | Paginated API collection; one raw JSON per trial. |
| `scripts/normalize_trial.py` | Normalize metadata and select T2D studies by conditions, titles and summary. |
| `scripts/parse_criteria.py` | Deterministic inclusion/exclusion parsing; retain unresolved text as ambiguous. |
| `scripts/run_pipeline.py` | Execute all three stages, failing if any stage fails. |
| `data/raw.dvc`, `data/raw_metadata.json` | Raw snapshot pointer, source query, statuses and provenance. |
| `data/processed/trials.jsonl` | Trial-level metadata for retrieval and display. |
| `data/processed/criteria.jsonl` | Criteria linked to trials by `trial_id`. |
| [SCHEMA.md](SCHEMA.md) | Field definitions and downstream contract. |

The parser handles common headers, bullets, numbering and escaped formatting.
It marks uncertain structure `parse_status=ambiguous` instead of guessing or
silently dropping text. `parse_method=deterministic` identifies this path.
Ambiguous records remain available for review.

## Reproduce the committed snapshot

From the repository root, follow the [credential setup](../../README.md#online-screening), then:

```bash
make reproduce
```

DVC downloads the fixed raw snapshot; processing must reproduce the recorded
checksums before replacing processed files. This does not fetch new registry data.
The snapshot is dated October 11, 2026:

| Output | Count |
| --- | ---: |
| Raw candidate trials | 1,385 |
| Processed T2D trials | 1,313 |
| Criteria | 18,456 |
| Parsed / ambiguous criteria | 18,374 / 82 |

Raw files are kept in the shared DVC remote. Git contains their pointer and the
processed files needed for credential-free local startup.

## Collect a new snapshot

With the root uv environment installed, run from the repository root:

```bash
uv run --locked python services/trial_ingestion/scripts/run_pipeline.py
```

This contacts the registry and replaces the raw snapshot after a successful fetch.
It selects `RECRUITING`, `NOT_YET_RECRUITING` and `ENROLLING_BY_INVITATION` studies,
then applies T2D relevance filtering. Counts and content can change.
Version new raw files with DVC and update downstream manifests/indexes before sharing.
For a stable demo or benchmark, restore the existing snapshot instead.
