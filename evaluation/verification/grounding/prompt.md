# Closed-context grounding regression

Start a separate new conversation for each case. Disable search, browsing, connected sources and memory where supported. Record actual settings and any limitations. Upload exactly one file from `uploads/`; do not upload this experiment's README, finding, manifest or review template.

Paste all instructions below the separator.

---

Evaluate only the single source criterion in the uploaded JSON. Use only that package's patient facts, criterion text, evidence policy and explicitly supplied terminology mappings. The package is a supplied-context regression exercise, not a live vector-retrieval trace or final trial-screening assessment.

Rules:

1. Preserve case_id, criterion_id, criterion_type and full criterion_text. Cite the supplied criterion_source_id for the requirement being assessed.
2. Treat medical codes as opaque identifiers unless the package explicitly supplies their clinical meaning in an allowed_terminology_mappings entry or in a patient source field. Do not use remembered SNOMED/RxNorm/LOINC meanings, outside medical thresholds, treatment associations, browsing or memory to supply a missing clinical fact. A diagnosis named by a trial requirement does not establish that diagnosis in the patient.
3. Use ordinary string comparison, explicit mappings and stated logical/arithmetic rules. Keep source codes, values, units and dates unchanged. A prescription is not proof of actual stable use or a diagnosis. A source status is not a reconstructed status at a later visit.
4. If required evidence or clinical meaning is absent, return precheck_status UNKNOWN and answer exactly "insufficient information". Explain the missing evidence. Do not use NOT_MET for missing evidence. If evidence explicitly supports a definite result under the supplied policy, report that result with citations rather than abstaining automatically.
5. Cite exact patient fact IDs and JSON Pointer field paths with verbatim values. Cite a supplied mapping_id whenever a mapping supports an inference. A valid fact ID alone does not support an unstated code meaning. Each factual claim in the reasoning must be traceable to supplied evidence; clearly label unresolved points as missing information.
6. Do not invent actual screening, consent, V1 or enrollment dates. Actual trial dates remain null. Provide no enrollment probability or final eligibility decision.
7. Report any inherited-context, attachment-reading or settings limitation honestly. Self-reported search/context settings are not independently verified tool traces. Preserve errors or uncertainty instead of repairing missing evidence.

Return JSON only. Replace placeholders with source values; include only the one criterion supplied:

```json
{
  "case_id": "copy uploaded case_id",
  "criterion_id": "copy uploaded trial_criterion.criterion_id",
  "criterion_type": "copy uploaded trial_criterion.criterion_type",
  "criterion_text": "copy full source criterion text",
  "precheck_status": "MET or NOT_MET or UNKNOWN",
  "answer": "insufficient information when UNKNOWN; otherwise a concise supported answer",
  "criterion_source_id": "copy uploaded criterion_source_id",
  "evidence": [
    {
      "source_type": "criterion, patient or terminology_mapping",
      "source_id": "supplied criterion_source_id, patient fact_id or mapping_id",
      "field_path": "/exact/JSON/Pointer/in/the/upload",
      "quoted_value": "exact source field value; retain its JSON type where applicable"
    }
  ],
  "reasoning": "Explain each supported inference with its source IDs; identify missing evidence without supplying outside clinical knowledge",
  "missing_information": [],
  "search_status": "NOT_USED or state the actual limitation",
  "context_limitations": [],
  "actual_trial_dates": {"screening_date": null, "consent_date": null, "V1_date": null},
  "overall_enrollment_decision": null
}
```

Every citation must resolve to an exact field in this upload. Do not invent a mapping, patient field or source ID. Do not claim that this one-criterion exercise assesses the complete trial or proves clinical eligibility.
