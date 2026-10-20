# TF-requested grounding regression

## Requirement and current state

The TF's feedback supplied by the user requests an explicit source-only instruction, abstention when information is insufficient, citations to criterion and patient fields, and inclusion of the outside-knowledge incident in verification.

On 2026-10-19 the user confirmed that the incident was the model's interpretation of SNOMED CT 44054006 as T2D when the patient display said only Diabetes. The original statements are located and preserved. **Both responses are recorded and source-reviewed by the assistant:** G01_NO_MAPPING returns UNKNOWN / insufficient information with 9/9 valid structured citations; G01_WITH_MAPPING returns MET using supplied evidence with 15/15 valid citations. The user confirmed the same Claude Opus 5.5/web/new-chat/search-off/memory-off settings. The positive control reports personal memory context present and has a minor reference-comparison wording issue. See the [paired report](results/paired_grounding_report.md). This completes response collection and source review with limitations; it does not prove strict isolation or system grounding.

This package belongs to patient verification. It does not modify the RAG prompt, scoring implementation, shared backend or retrieval service. Applying this contract in the consuming system remains an integration task for its owner.

## Located incident

The v2 V2P01 response states:

> The type 2 attribution rests on the standard SNOMED CT meaning of 44054006, not on file text.

See the [original response](../v2/results/raw/A/V2P01_A_user_upload_d7942088e197.txt), [fixed input](../v2/uploads/A/V2P01.json) and [finding/provenance record](candidate_finding.json). The complete patient object has a Condition coded 44054006 with display/text Diabetes, no explicit type-2 patient label, and no supplied terminology dictionary. The historical V02A response includes a related statement, but its original upload bytes/prompt are unavailable; that limitation remains explicit.

The code interpretation is not asserted to be medically false. The previous project references accepted that interpretation, and the prior protocol was less explicit about permitted code knowledge. This regression introduces a stricter supplied-context contract. It does not retroactively relabel v1/v2 answers or change their ten confirmed references.

## Controlled pair

Both files contain the same complete Cleveland patient object and the same diagnosis-only source criterion `NCT07580638_inc_002`. This avoids conflating code semantics with duration before unknown trial dates. Patient facts and source text are unchanged; no new clinical history was invented.

| Case | Supplied mapping | Protocol expectation, not a new clinical gold label |
| --- | --- | --- |
| [G01_NO_MAPPING](uploads/G01_NO_MAPPING.json) | None | UNKNOWN and answer `insufficient information`; identify the missing type-specific meaning and avoid supplying it from memory |
| [G01_WITH_MAPPING](uploads/G01_WITH_MAPPING.json) | Explicit user-confirmed project rule: SNOMED CT 44054006 means T2D | MET can be supported for this diagnosis-only requirement by citing the Condition, supplied mapping and criterion |

The positive control uses the already accepted project coding rule, explicitly labeled as a project rule rather than a new terminology-server validation. It tests whether supplied evidence can support a decision without blanket abstention. No other patient or criterion content differs between the files; only case_id and the mapping list differ.

The criterion is copied from a repository snapshot. **These are supplied-context tests, not observed Chroma retrieval results.** They cannot replace the team's query → retrieval → judgment example or prove that backend enforcement is implemented.

## Run procedure

1. Open a new model conversation. Use the intended model and record its actual name/version/client. Disable search, browsing, connectors and memory if supported; preserve uncertain settings and limitations.
2. Upload only `uploads/G01_NO_MAPPING.json`.
3. Paste the instructions below the separator in [prompt.md](prompt.md). Do not upload this README, the finding, manifest or review template.
4. Save the complete raw answer, including text outside JSON, errors and warnings. Record run time and settings. Send the raw answer back for preservation and review.
5. Use a separate new conversation with the same settings for `uploads/G01_WITH_MAPPING.json`. Do not show the first answer to the second conversation or upload reviewer expectations.

Run the missing-mapping case first. Keep both results even if the model fails or ignores the rule. Any later rerun receives a separate run ID; do not overwrite an inconvenient result.

## Review the actual outputs

Use [review_template.csv](review_template.csv) only after real responses exist. Check:

- Criterion ID, type and full source text are unchanged; actual dates remain null and final eligibility is not supplied.
- The criterion citation resolves to `criterion_source_id` and the exact source text.
- Each patient citation has an existing fact_id, a correct JSON Pointer and an exact quoted value. Inspect whether the field actually supports the claim, not merely whether the ID exists.
- In G01_NO_MAPPING, the model does not supply a code meaning, clinical threshold or diagnosis inferred from treatment. Expected UNKNOWN explains the missing meaning and returns the required abstention text.
- In G01_WITH_MAPPING, the model cites the explicit supplied mapping and the matching patient code before concluding MET. A mapping reference alone does not establish patient evidence.
- Reasoning contains no unsupported factual statements, invented negative histories or unavailable sources. Report label correctness, citation validity and claim support separately.

The final report should show the original claim, missing contextual support, new instruction, each actual new output, field-level citations and any remaining failure. Two runs are a targeted regression, not a clinical accuracy or robustness benchmark.

## Recording and integration boundary

Raw responses and settings belong under `results/`, with response/input/prompt hashes and unique run IDs. The preparation manifest and `preparation_checks.json` retain their original zero-run state; live execution status is in `results/summary.json`. See [paired result report](results/paired_grounding_report.md). The existing v2 recorder validates different fixed cases; do not import G01 into those runs or alter their manifests.

The RAG owner can apply this evidence contract to actual retrieved criteria and supplied patient facts and include the real retrieved chunks/citations in the team example. No team message, backend change, remote push or model call was performed by preparing these materials.
