# Grounding regression: observed paired results

## Purpose and method

The TF requested a source-only verification case after the model interpreted SNOMED 44054006 as T2D although the patient display said Diabetes. The user confirmed the original incident. The [finding record](../candidate_finding.json) preserves the original quotes and source hashes.

Two separate supplied-context cases use the same complete Cleveland patient object, the same diagnosis-only source clause `NCT07580638_inc_002`, and the same stricter prompt. Only case_id and the supplied mapping list differ. Expected policy behavior was recorded before these two responses. Previous v1/v2 answers and references were not relabeled.

The user reported Claude Opus 5.5 on Claude web, separate new conversations, search off and memory off for both runs. Independent tool traces and actual run timestamps are unavailable. The with-mapping answer nevertheless reports inherited personal memory context; this remains an isolation limitation.

## Observed outputs

| Case | Supplied mapping | Core observed result | Structured source checks |
| --- | --- | --- | --- |
| G01_NO_MAPPING | Empty list | UNKNOWN; exact answer `insufficient information`; no remembered subtype meaning supplied | 9/9 citations resolve: one criterion and eight patient fields |
| G01_WITH_MAPPING | Explicit project coding rule | MET based on matching patient code/system, supplied mapping and criterion | 15/15 citations resolve: two criterion, nine patient and four mapping fields |

The missing-mapping response abstains rather than treating missing meaning as a negative diagnosis. The positive-control response uses supplied evidence instead of abstaining automatically. These core outputs are consistent with the new context policy in this observed pair.

Per-run reviews: [no mapping](review_G01_NO_MAPPING.md) and [with mapping](review_G01_WITH_MAPPING.md). [runs.csv](runs.csv) and [summary.json](summary.json) record results; raw responses and per-run metadata remain unchanged after import, except explicitly recorded metadata amendments.

## Findings that limit the conclusion

- The with-mapping response reports unrelated personal memory context present but unused, despite user-reported memory-off settings. Neither the absence of its influence nor strict isolation is independently established.
- Its reasoning incorrectly calls the `urn:uuid:` reference and bare patient ID a literal string match. They match after reference-prefix normalization. Source citations are valid; the wording issue is retained separately from the supported core diagnosis inference.
- Both answers use Markdown code fences despite a JSON-only request. Both parse successfully; this is a format warning.
- Some secondary statements in the no-mapping reasoning have source support but not exhaustive structured field citations. A valid cited field is not proof that every sentence is supported; assistant source review and its qualifications are explicit.
- This is one patient, one criterion and one run per condition, with assistant review after outputs were visible. It is not a clinical accuracy benchmark, a robustness study or a causal comparison against the older, differently specified protocol.

## Delivery status and system boundary

**The requested incident, stricter prompt, two raw responses and source-level comparison are now recorded.** The personal verification package documents both observed abstention without a mapping and supported use of an explicitly supplied mapping, with the limitations above.

It does not establish a clean isolation experiment, actual Chroma retrieval or backend enforcement. The team RAG example still needs actual query → retrieved criteria → judgment with criterion/patient citations and the deployed grounding instruction. Shared scoring, retrieval, API, UI and container changes remain with their respective owners. No clinical eligibility decision, system-wide reliability claim, remote push or merge is implied.
