# V2 mode A — offline preliminary screening

Start a new conversation. Turn off web search/browsing and connected sources. Disable memory or other inherited context if the interface permits. Record the actual settings; do not infer that a new conversation guarantees isolation. Upload only ONE file from `uploads/A/`. Do not upload the reference tables or reviewer notes.

Copy the instructions below into the model conversation.

---

Use only the uploaded JSON file for an offline preliminary screening exercise. Use `assessment_date` to assess the patient's documented facts. It is a hypothetical assessment date, NOT an actual trial screening date, consent date, or V1 date. Those actual dates remain unknown. The newer trial snapshot is intentionally replayed against older synthetic data; do not claim the trial existed, recruited at assessment_date, or is currently recruiting.

1. Read the COMPLETE patient facts, original `trial_record.eligibility_text`, and ALL `parsed_criteria`. Return every source criterion with its original ID, type and full text. Preserve compound clauses and investigator discretion. Report any raw-to-parsed omissions.
2. For each clause, give a `precheck_status` of MET, NOT_MET or UNKNOWN for preliminary assessment on assessment_date. Calculate age from birth date on assessment_date. Distinguish known facts from their applicability to a clause. Follow the supplied preliminary documented-diagnosis-duration rule, without claiming to know the first-ever true diagnosis date.
3. For inclusion, MET means supported and NOT_MET means a supported conflict. For exclusion, MET means the exclusion applies and is a conflict; NOT_MET means evidence supports that it does not apply. Missing evidence is UNKNOWN, not a negative history. Apply AND/OR logic to the full clause.
4. Separate missing clinical evidence, investigator review, reproductive-status information and consent-capacity assessment in follow-up. “Unable to give signed informed consent” concerns capacity; lack of a signed consent document does not by itself establish inability. Never invent willingness, capacity or actual study consent.
5. Preserve exact fact IDs, code systems/codes, original dates, source statuses, numeric values and units. A prescription is not administration, stable actual use or adherence. Do not silently turn an old measurement into a contemporary trial measurement or invent a recency window. Unprocessed resource types are a stated evidence-scope limitation.
6. Do not browse, retrieve external sources, use memory or invent unavailable facts. Report any context limitation honestly. Provide no enrollment probability and no final enrollment decision. The preliminary labels do not establish actual trial eligibility.

Return JSON only, with this structure (replace placeholders; the structure contains no example patient answers):

```json
{
  "pair_id": "copy uploaded pair_id",
  "trial_id": "copy uploaded trial_record.trial_id",
  "assessment_date": "copy uploaded assessment_date",
  "actual_trial_dates": {"screening_date": null, "consent_date": null, "V1_date": null},
  "search_status": "NOT_USED",
  "context_limitations": [],
  "source_criterion_issues": [],
  "criteria": [
    {
      "criterion_id": "copy source ID",
      "criterion_type": "inclusion or exclusion",
      "criterion_text": "copy full source text",
      "precheck_status": "MET or NOT_MET or UNKNOWN",
      "evidence_fact_ids": [],
      "reasoning": "Explain support, conflict or uncertainty as of assessment_date",
      "missing_clinical_information": [],
      "required_workflow_followup": []
    }
  ],
  "summary": {
    "supported_criterion_ids": [],
    "conflicting_criterion_ids": [],
    "unresolved_criterion_ids": []
  },
  "overall_enrollment_decision": null
}
```

Summary lists must match criterion labels and exclusion polarity. UNKNOWN belongs in unresolved, not conflicting. A source clause must appear in exactly one summary list. No source clause may be omitted merely because it needs study-team review.
