# Grounding run status

Both G01 responses are recorded. G01_NO_MAPPING returns UNKNOWN / insufficient information (9/9 structured citations resolve); G01_WITH_MAPPING returns MET using the supplied mapping (15/15 resolve). The user confirmed the same Claude Opus 5.5, Claude web, separate-new-chat, search-off and memory-off settings. The positive control reports inherited personal memory context and contains a minor reference-comparison wording issue.

See the [paired report](paired_grounding_report.md), [no-mapping review](review_G01_NO_MAPPING.md), [with-mapping review](review_G01_WITH_MAPPING.md), `summary.json` and `runs.csv`. Response collection and source review are complete with these limitations. No verified clean isolation, clinical accuracy, actual retrieval or backend-enforcement result is established. Preparation-stage zero-run metadata is preserved separately.

For each actual run preserve:

- `raw/<unique_run_id>.txt`: original complete response bytes, including errors and preambles.
- `records/<unique_run_id>.json`: case_id, run ID, recorded time, actual run time if known, source attachment ID if applicable, actual user-reported model/version/client/settings, self-reported context limitations, response SHA-256, input SHA-256 and prompt SHA-256.
- The original response and settings on failed, incomplete or repeated attempts. Use a new ID for a genuinely new attempt; never replace a prior response.
- A separate human review of field-level citations, supplied-mapping use, unsupported assertions and abstention. Structural/source-ID checks do not establish semantic grounding.

The user can return the raw answer as a pasted-text attachment together with settings. Record unverifiable settings as UNKNOWN. Do not call a run successful before the response and supporting citations are reviewed.

The two existing v2 responses and ten reference labels remain separate. This folder does not contain a new system retrieval run or an evaluation result merely because inputs were prepared.
