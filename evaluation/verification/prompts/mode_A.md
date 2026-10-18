# Mode A — reconstructed protocol, 2026-10-18

This is a reconstructed prompt for future use, not evidence of the original prompt wording. Historical runs must not be rerun or replaced silently.

In a new conversation, select the actual model and turn off web search, browsing, connectors and memory if the interface permits. Record the actual settings and any unavoidable context. Upload `uploads/A/<pair_id>.json`, then use the instructions below.

---

Assess this synthetic patient's facts against the uploaded trial's eligibility criteria using only the uploaded file. Do not search, browse, use connected sources, or use memory. Report any context or settings limitation. Use every `parsed_criteria` row and check it against the full `trial_record.eligibility_text`; preserve ambiguous or compound clauses and report any omissions.

Return one JSON object with `pair_id`, `trial_id`, `search_status` (`NOT_USED`), `source_urls` (empty array), `retrieved_eligibility_text` (null), `source_criterion_issues` (array of strings), and `criteria` (array).

Each criterion must include `criterion_id`, `criterion_type` (`inclusion` or `exclusion`, retaining `unknown` when the source is ambiguous), `criterion_text`, `status` (`MET`, `NOT_MET`, `UNKNOWN`), `evidence_fact_ids` (array), `reasoning` (string), and `missing_information` (array of strings). Copy source criterion IDs and text. For an exclusion, MET means the exclusion applies; NOT_MET means evidence establishes it does not apply. Missing records are UNKNOWN, not evidence of absence.

Preserve exact fact IDs, dates, code systems, codes, units and source statuses. Medication orders, dispensing, administration and patient reports are distinct; a prescription alone does not prove actual use, stable dose or adherence. Do not invent thresholds, normal ranges, screening dates, consent dates or visit dates. `reference_date` is the processing cutoff and age anchor; it is not an actual trial visit. If a required anchor or relevant evidence is missing, explain which component is unknown. Never infer absence of another diabetes type solely from a T2D diagnosis.

Do not output eligibility probabilities or an overall enrollment decision. Do not treat these old synthetic records and newer trial snapshot as a current clinical assessment. Provide JSON only.
