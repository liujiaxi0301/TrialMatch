# Trial Ingestion Schema

This document defines the processed data contract for the TrialMatch clinical-trial ingestion pipeline.

The pipeline produces two processed files:

```text
data/processed/
├── trials.jsonl
└── criteria.jsonl
```

The two files are linked by `trial_id`.


# 1. `trials.jsonl`

Each line represents one normalized clinical trial selected for the current Type 2 Diabetes (T2D) TrialMatch corpus.

## Fields

| Field | Type | Nullable | Description |
|---|---|---:|---|
| `trial_id` | string | no | ClinicalTrials.gov NCT identifier. Primary key. |
| `brief_title` | string | yes | Short trial title. |
| `official_title` | string | yes | Full official trial title. |
| `overall_status` | string | yes | ClinicalTrials.gov recruitment status. |
| `conditions` | list[string] | no | Conditions associated with the trial. |
| `keywords` | list[string] | no | Investigator-provided keywords. |
| `mesh_terms` | list[string] | no | MeSH terms derived by ClinicalTrials.gov. |
| `study_type` | string | yes | Study type, such as `INTERVENTIONAL`. |
| `phases` | list[string] | no | Clinical trial phases when available. |
| `brief_summary` | string | yes | Short trial description. |
| `minimum_age` | string | yes | Structured minimum eligible age. |
| `maximum_age` | string | yes | Structured maximum eligible age. |
| `sex` | string | yes | Structured sex eligibility field. |
| `healthy_volunteers` | boolean | yes | Whether healthy volunteers are accepted. |
| `eligibility_text` | string | yes | Original eligibility criteria text. |
| `locations` | list[object] | no | Normalized study-site locations. |
| `enrollment_count` | integer | yes | Planned or actual enrollment count. |
| `enrollment_type` | string | yes | Enrollment type, such as estimated or actual. |
| `start_date` | string | yes | Trial start date. |
| `completion_date` | string | yes | Trial completion date. |
| `last_update_date` | string | yes | Most recent ClinicalTrials.gov update date. |
| `source` | string | no | Data source. Currently `ClinicalTrials.gov API v2`. |
| `snapshot_date` | string | no | Date when the processed snapshot was generated. |

## Example

```json
{
  "trial_id": "NCT06864546",
  "brief_title": "Example Trial",
  "official_title": null,
  "overall_status": "RECRUITING",
  "conditions": ["Diabetes Mellitus, Type 2"],
  "keywords": [],
  "mesh_terms": ["Diabetes Mellitus, Type 2"],
  "study_type": "INTERVENTIONAL",
  "phases": [],
  "brief_summary": "Example study summary.",
  "minimum_age": "40 Years",
  "maximum_age": "70 Years",
  "sex": "ALL",
  "healthy_volunteers": false,
  "eligibility_text": "Inclusion Criteria:\n...",
  "locations": [],
  "enrollment_count": 100,
  "enrollment_type": "ESTIMATED",
  "start_date": "2026-01-01",
  "completion_date": "2027-01-01",
  "last_update_date": "2026-09-01",
  "source": "ClinicalTrials.gov API v2",
  "snapshot_date": "2026-10-11"
}
```


# 2. Location Structure

Each item in `locations` uses the following structure:

| Field | Type | Nullable |
|---|---|---:|
| `facility` | string | yes |
| `status` | string | yes |
| `city` | string | yes |
| `state` | string | yes |
| `zip` | string | yes |
| `country` | string | yes |
| `latitude` | number | yes |
| `longitude` | number | yes |

Example:

```json
{
  "facility": "Example Medical Center",
  "status": "RECRUITING",
  "city": "Boston",
  "state": "Massachusetts",
  "zip": "02115",
  "country": "United States",
  "latitude": 42.0,
  "longitude": -71.0
}
```


# 3. `criteria.jsonl`

Each line represents one eligibility criterion or one unresolved eligibility-text segment.

## Fields

| Field | Type | Allowed Values | Description |
|---|---|---|---|
| `trial_id` | string | — | Parent NCT identifier. |
| `criterion_id` | string | — | Unique criterion identifier. |
| `criterion_type` | string | `inclusion`, `exclusion`, `unknown` | Eligibility criterion type. |
| `criterion_text` | string | — | Criterion text used by downstream retrieval and screening. |
| `parse_status` | string | `parsed`, `ambiguous` | Whether criterion structure was resolved reliably. |
| `parse_method` | string | `deterministic`, `llm` | Method used to produce the current representation. |

## Example

```json
{
  "trial_id": "NCT06864546",
  "criterion_id": "NCT06864546_inc_003",
  "criterion_type": "inclusion",
  "criterion_text": "Age between 40 and 70 years.",
  "parse_status": "parsed",
  "parse_method": "deterministic"
}
```


# 4. Criterion ID Convention

Criterion IDs use the following format:

```text
<NCT_ID>_<TYPE>_<SEQUENCE>
```

Prefixes:

```text
inc = inclusion
exc = exclusion
unk = unknown
```

Examples:

```text
NCT06864546_inc_001
NCT06864546_inc_002
NCT06864546_exc_001
NCT06864546_unk_001
```


# 5. Parsing Status

## `parsed`

The parser identified a usable criterion type and criterion boundary.

```json
{
  "parse_status": "parsed",
  "parse_method": "deterministic"
}
```

## `ambiguous`

The original text is retained because the parser could not determine the structure reliably.

Examples include:

- unclear inclusion/exclusion section type,
- unclear criterion boundaries,
- natural-language eligibility paragraphs,
- multi-cohort eligibility structures.

```json
{
  "criterion_type": "unknown",
  "parse_status": "ambiguous",
  "parse_method": "deterministic"
}
```

Ambiguous records should be preserved rather than dropped or guessed.


# 6. Parsing Method

## `deterministic`

The record was produced by the rule-based eligibility parser.

This value may appear with either:

```text
parse_status = parsed
```

or:

```text
parse_status = ambiguous
```

## `llm`

Reserved for records that may later be resolved using an LLM-assisted fallback parser.

LLM fallback is not required for records already parsed reliably.


# 7. Missing Value Policy

The following conventions are used across processed files:

- Missing scalar values are stored as `null`.
- Missing boolean values are stored as `null`.
- Missing list fields are stored as `[]`.
- `trial_id` is required.
- Trials without `eligibility_text` may remain in `trials.jsonl`.
- Trials without eligibility text do not generate criterion records.
- Empty eligibility placeholders such as `-` or `\-` do not generate criterion records.


# 8. Criterion Parsing Rules

The deterministic parser follows these rules:

- Preserve inclusion and exclusion labels where identifiable.
- Recognize common header variants such as:
  - `Inclusion Criteria`
  - `Exclusion Criteria`
  - `Main Inclusion Criteria`
  - `Main Exclusion Criteria`
  - `No Inclusion Criteria`
  - `Non-Inclusion Criteria`
- Split explicit bullet lists.
- Split explicit numbered lists.
- Support escaped ClinicalTrials.gov formatting such as `1\.` and `\-`.
- Do not split a single criterion solely because it contains `and` or `or`.
- Preserve numeric thresholds, negation, medication requirements, and time windows.
- If structure cannot be resolved safely, preserve the text with `parse_status = ambiguous`.


# 9. Downstream Contract

Downstream TrialMatch components should use:

```text
trials.jsonl
```

for trial-level retrieval and metadata, and:

```text
criteria.jsonl
```

for criterion-level retrieval and patient–criterion matching.

The datasets should be joined using:

```text
trial_id
```

The ingestion pipeline does not determine patient eligibility.

Patient-level outputs such as:

```text
MET
NOT_MET
UNKNOWN
```

belong to the downstream eligibility-screening workflow.