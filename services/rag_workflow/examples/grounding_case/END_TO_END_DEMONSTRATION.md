# End-to-end retrieval demonstration

Recorded live run: October 19, 2026. This document follows the requested sequence:
**a patient's criterion query → retrieved criteria → judgment with cited evidence**.
It traces one candidate actually returned by the normal RAG workflow, not a manually forced trial.

## 1. Patient input and question

Patient `SYNTHETIC_001` is the user-supplied synthetic case, not a real patient or a member of the Part 2 cohort. The full English statements are in [source_case.json](source_case.json); the normalized input is [patient.json](patient.json).

```text
52-year-old female.
Type 2 diabetes diagnosed 6 years ago.
BMI: 37.2 kg/m².
HbA1c: 7.8%.
Fasting glucose: 8.1 mmol/L.
```

Actual user question:

```text
Which clinical trials may suit this patient? Explain supporting evidence, screening barriers, and what remains unknown, using only the supplied trial criteria and patient record.
```

The query builder appends age, sex, diagnosis and selected measurements. The actual retrieval query was:

```text
Which clinical trials may suit this patient? Explain supporting evidence, screening barriers, and what remains unknown, using only the supplied trial criteria and patient record. age 52 female Type 2 diabetes diagnosed 6 years ago Type 2 diabetes diagnosed 6 years ago BMI  {"type": "Quantity", "data": {"value": 37.2, "unit": "kg/m\u00b2"}} HbA1c  {"type": "Quantity", "data": {"value": 7.8, "unit": "%"}}
```

The fixture reference date `2026-10-11` is a declared test anchor. Source laboratory dates are unknown; the fixture does not establish present-day patient status.

## 2. Retrieved criteria

The system searched its fixed 50-trial subset using BM25 and Chroma vector search, combined by reciprocal rank fusion (`hybrid_rrf`). It returned `NCT04284943`, `NCT03827382` and `NCT03821636`. This walkthrough follows the third returned candidate:

- Trial: **NCT03821636** — Impact of Long Alimentary Limb or Long Biliary Limb Roux-en-Y Gastric Bypass on Type 2 Diabetes Remission in Severely Obese Patients.
- Matched criterion: `NCT03821636_inc_002`.
- Criterion source text: **All patient with type 2 diabetes**.
- Recorded cosine distance: `0.187741`; RRF score: `0.02911605`. These are retrieval signals, not eligibility scores.
- Source: [trial record](https://clinicaltrials.gov/study/NCT03821636), stored snapshot `2026-10-11`. Recruiting status describes that snapshot, not a fresh registry lookup.

After retrieval, the workflow evaluates all 11 complete criteria for the candidate, not only the matching fragment.

## 3. Patient evidence selected for judgment

| Patient fact ID | Source text | Supports |
|---|---|---|
| `fixture:claude_synthetic_001#diagnosis` | Type 2 diabetes diagnosed 6 years ago. | `NCT03821636_inc_002`: All patient with type 2 diabetes |
| `fixture:claude_synthetic_001#bmi` | BMI: 37.2 kg/m². | `NCT03821636_inc_001`: BMI ≥ 35 kg/m2 |

Both IDs resolve to [source_case.json](source_case.json), respectively `statements.diagnosis` and `statements.bmi`, via [patient.json](patient.json). Fact IDs/resource types are adapter metadata; the original statements are preserved. The rule can check a supported quantity directly; model-evaluated criteria receive a selected patient context and must cite an allowed local fact ID.

## 4. Judgment with cited evidence

Actual criterion-level excerpts (other response fields omitted):

```json
[
  {
    "criterion_id": "NCT03821636_inc_001",
    "criterion_text": "BMI ≥ 35 kg/m2",
    "decision": "MET",
    "reason": "Verified BMI 37.2 kg/m2 against the supplied threshold; source is undated; no recency is asserted or required by this statement.",
    "evidence_fact_ids": [
      "fixture:claude_synthetic_001#bmi"
    ],
    "method": "rule",
    "validation_warnings": [
      "UNDATED_MEASUREMENT_NO_RECENCY_CLAIM"
    ]
  },
  {
    "criterion_id": "NCT03821636_inc_002",
    "criterion_text": "All patient with type 2 diabetes",
    "decision": "MET",
    "reason": "The patient has a documented diagnosis of type 2 diabetes.",
    "evidence_fact_ids": [
      "fixture:claude_synthetic_001#diagnosis"
    ],
    "method": "llm",
    "validation_warnings": []
  }
]
```

The first decision checks `37.2 ≥ 35` with matching units. Its warning explicitly preserves the missing measurement date. The second is a Gemini judgment tied to the supplied diagnosis. No external diagnosis or normal range is introduced.

The remaining criterion decisions are retained, including UNKNOWN:

| Criterion ID | Complete source criterion | Decision | Cited patient fact IDs |
|---|---|---|---|
| `NCT03821636_inc_001` | BMI ≥ 35 kg/m2 | MET | `fixture:claude_synthetic_001#bmi` |
| `NCT03821636_inc_002` | All patient with type 2 diabetes | MET | `fixture:claude_synthetic_001#diagnosis` |
| `NCT03821636_inc_003` | Patients who were candidates for obesity surgery in accordance with French recommendation | UNKNOWN | No supporting citation |
| `NCT03821636_exc_001` | Severe cognitive or mental disorders | UNKNOWN | No supporting citation |
| `NCT03821636_exc_002` | patient who have already undergone obesity surgery | UNKNOWN | `fixture:claude_synthetic_001#surgery_history` |
| `NCT03821636_exc_003` | Severe and non-stabilised eating disorders | UNKNOWN | No supporting citation |
| `NCT03821636_exc_004` | The likely inability of the patient to participate in lifelong medical follow-up | UNKNOWN | No supporting citation |
| `NCT03821636_exc_005` | Alcohol or psychoactive substances dependence | UNKNOWN | `fixture:claude_synthetic_001#substance_history` |
| `NCT03821636_exc_006` | The absence of identified prior medical management of obesity | UNKNOWN | No supporting citation |
| `NCT03821636_exc_007` | Diseases that are life-threatening in the short and medium term; | UNKNOWN | No supporting citation |
| `NCT03821636_exc_008` | Contraindications to general anaesthesia. | UNKNOWN | No supporting citation |

For example, `NCT03821636_inc_003` remains UNKNOWN because the source does not document candidacy under the French recommendations. Its recorded missing-information request is:

```text
Documentation confirming the patient meets French recommendations for obesity surgery candidacy.
```

## 5. Trial-level output

Actual response excerpt:

```json
{
  "trial_id": "NCT03821636",
  "screening_status": "NEEDS_MORE_INFORMATION",
  "match_score": 18.2,
  "score_type": "criterion_satisfaction_v0",
  "eligibility_probability": null,
  "summary": "2/11 criteria known; 0 confirmed barriers; 9 unknown.",
  "assessment_coverage": {
    "total": 11,
    "completed": 11,
    "known": 2,
    "unknown": 9,
    "screening_barriers": 0
  }
}
```

The match score is `100 × (inclusion MET + exclusion NOT_MET) / total criteria`.
Here that is `100 × 2 / 11 = 18.2` after rounding. UNKNOWN remains in the denominator. The score is not an enrollment probability; no confirmed barrier is not proof of eligibility.

Actual generated explanation, with criterion citations:

> The patient is currently being evaluated for trial NCT03821636. Favorable evidence includes a BMI of 37.2 kg/m2 [NCT03821636_inc_001] and a confirmed diagnosis of type 2 diabetes [NCT03821636_inc_002], both of which meet the inclusion criteria. However, the screening status is 'NEEDS_MORE_INFORMATION' because several critical criteria remain unknown. Specifically, it is unknown if the patient meets the French recommendations for obesity surgery candidacy [NCT03821636_inc_003] or if they have a history of prior medical management of obesity [NCT03821636_exc_006]. Furthermore, there is no information regarding potential exclusion criteria, including severe cognitive or mental disorders [NCT03821636_exc_001], prior obesity surgery [NCT03821636_exc_002], severe eating disorders [NCT03821636_exc_003], ability to commit to lifelong follow-up [NCT03821636_exc_004], substance dependence [NCT03821636_exc_005], life-threatening diseases [NCT03821636_exc_007], or contraindications to general anesthesia [NCT03821636_exc_008]. Further clinical review is required to address these missing data points.

The structured judgments above connect those criterion citations to patient fact IDs. The explanation is generated text and must be reviewed against the structured evidence; it is not an independently validated clinical answer.

## 6. Run status and reproducibility

This candidate has 11/11 assessments completed, with 2 definite and 9 UNKNOWN decisions. **The overall three-candidate response is still PARTIAL**: another candidate, `NCT04284943`, has six `INVALID_LLM_OUTPUT` entries after a per-criterion citation alias fails validation and one repair. This example demonstrates an actual retrieval-to-evidence path; it does not claim that the entire live run passed.

The recorded configuration used `gemini-embedding-001` (256 dimensions), `gemini-3.1-flash-lite`, and index `8a7004181d978a705d94` (607 fragments). The configured 25-patient file hash in response provenance describes the cohort, not this inline synthetic patient; this case is identified by its linked fixture.

From the repository root, with credentials configured and the matching Chroma index available:

```bash
uv run --locked \
  --env-file .env \
  python -m services.rag_workflow.cli --mode live screen \
  --patient-file services/rag_workflow/examples/grounding_case/patient.json \
  --question 'Which clinical trials may suit this patient? Explain supporting evidence, screening barriers, and what remains unknown, using only the supplied trial criteria and patient record.' \
  --top-k 3 --output artifacts/rag_workflow/end_to_end_replay.json
```

This invokes the normal retrieval workflow and may make billed model calls; caches may be reused. A replay is a new run, not a guarantee of byte-identical model text. The CLI exits 1 for PARTIAL.

Original local run artifacts (generated and Git-ignored):

- `artifacts/rag_workflow/grounding_case_guard_revision/retrieval_trace.json`
- `artifacts/rag_workflow/grounding_case_guard_revision/full_rag_response.json`

The excerpts above are included in this tracked document so reviewers can inspect the demonstrated path from GitHub without those local artifacts. For the separate fixed-trial model comparison, see [GROUNDING_COMPARISON.md](GROUNDING_COMPARISON.md).
