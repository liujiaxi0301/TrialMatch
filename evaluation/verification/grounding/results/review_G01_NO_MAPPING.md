# G01_NO_MAPPING: response source review

## Run and provenance

- Run ID: `G01_NO_MAPPING_user_upload_baa833933332`.
- Source attachment: `file_00000000f43881f6a2c2d98ca1bab832`.
- [Raw response](raw/G01_NO_MAPPING_user_upload_baa833933332.txt): all 6,545 bytes preserved, including Markdown fences.
- Response SHA-256: `baa833933332d3c6c6312741c08a79ef414467571d0ea08ac4dc3b9bd32cb6e4`.
- [Run record](records/G01_NO_MAPPING_user_upload_baa833933332.json) includes input/prompt/preparation-manifest hashes and per-citation checks.
- The user reported Claude Opus 5.5 and confirmed Claude web, a new conversation, search off and memory off. Unknown initial settings and the later confirmation are retained in amendment history; this was not a second model run. Actual run timestamp is unknown; recording time is labeled separately.

Review was conducted by the assistant through source resolution and reading the response. It is not an independent human or clinical expert assessment. Settings and the model's no-tool report are not independent tool traces.

## Observed result

| Item | Observed result |
| --- | --- |
| Case/criterion identity and full text | Match the supplied input |
| Criterion status | UNKNOWN |
| Required abstention | Exact answer `insufficient information` |
| Structured citations | 9/9 resolve with exact values and matching source owners |
| Criterion citations | One, to the exact source requirement |
| Patient citations | Eight, across the Diabetes and Prediabetes Conditions |
| Invented terminology mapping | None cited or used to assign a subtype |
| Actual trial dates / final decision | Dates remain null; no final enrollment decision |

The response explains that display/text Diabetes does not explicitly supply a subtype and that the allowed mapping list is empty. It treats code 44054006 as opaque under this new test policy rather than supplying its remembered meaning. Missing evidence produces UNKNOWN, not NOT_MET. Raw active status is not promoted to status at assessment_date.

## Citation and reasoning qualifications

The response says its array indices were counted manually. Programmatic resolution independently checked every provided JSON Pointer, quoted value and owning fact ID; the quoted indices are correct.

Secondary mentions of source-active Prediabetes, HbA1c/Glucose observations and metformin text were checked against the complete input. Their detailed status/lab/medication fields are not all included as structured citations. The response says those items do not supply the subtype; this is a citation-completeness caveat, not an observed false diagnosis claim. Any mention of undetermined later status is an evidence limitation, not an extra requirement added to the diagnosis-only source clause.

The raw answer has a Markdown code fence despite the JSON-only request. It parsed successfully; this is preserved as a format warning rather than repaired or counted as a grounding failure.

## Scope and remaining work

This one observed response is consistent with the no-mapping abstention rule. It does not establish absence of all internal model knowledge, general reliability or a causal improvement over the historical response, whose policy differed.

The G01_WITH_MAPPING response has now also been recorded. It returns MET with patient/mapping/criterion citations, while reporting inherited memory context and retaining a minor reference-comparison wording issue. See the [paired report](paired_grounding_report.md). Response collection and source review are complete; no clean context-isolation, Chroma retrieval, backend-enforcement, clinical accuracy or final eligibility result is claimed. Earlier v1/v2 references remain unchanged.
