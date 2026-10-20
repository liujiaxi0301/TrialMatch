# Mode B — reconstructed protocol, 2026-10-18

This is a reconstructed prompt for future use, not evidence of the original prompt wording. Historical runs must not be rerun or replaced silently.

In a separate new conversation, select a model that can search the web, enable search, record the actual model and settings, and upload `uploads/B/<pair_id>.json`. Do not supply mode A's criteria or answers. Use the instructions below.

---

Assess this synthetic patient's facts against the specified trial. First retrieve the full eligibility text, preferably from the official ClinicalTrials.gov record. Record actual source URLs, access date, retrieval method, and limitations. Search snippets, page shells or blank numbered items do not establish complete retrieval. Do not invent missing criterion text; explicitly report partial or failed retrieval, including when the number of missing criteria is unknown.

Return one JSON object with `pair_id`, `trial_id`, `search_status` (`FOUND`, `PARTIAL`, or `NOT_FOUND`), `source_urls` (array), `source_accessed_at` (date), `retrieved_eligibility_text` (full retrieved text or null), `source_criterion_issues` (array of strings), and `criteria` (array). Assign stable IDs such as `<trial_id>_web_inc_001` and `<trial_id>_web_exc_001` to the actual retrieved clauses. Preserve compound and ambiguous clauses; do not silently drop them.

Each criterion must include `criterion_id`, `criterion_type` (`inclusion`, `exclusion`, or `unknown`), `criterion_text`, `status` (`MET`, `NOT_MET`, `UNKNOWN`), `evidence_fact_ids` (array), `reasoning` (string), and `missing_information` (array of strings). For an exclusion, MET means the exclusion applies. Missing records are UNKNOWN, not evidence of absence.

Preserve exact fact IDs, dates, code systems, codes, units and source statuses. Medication orders, dispensing, administration and patient reports are distinct; a prescription alone does not prove actual use, stable dose or adherence. Do not invent thresholds, normal ranges, screening dates, consent dates or visit dates. `reference_date` is the processing cutoff and age anchor, not an actual trial visit. Explain unknown components. A T2D diagnosis alone does not establish absence of another diabetes type.

Do not output eligibility probabilities or an overall enrollment decision. Do not describe newer live criteria as the same historical snapshot without evidence. These synthetic records and newer trial data do not establish current clinical eligibility. Provide JSON only.
