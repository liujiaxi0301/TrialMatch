# G01_WITH_MAPPING: response source review

## Run and provenance

- Run ID: `G01_WITH_MAPPING_user_upload_6d540aaa7bf9`.
- Source attachment: `file_000000008d84820e927a1645b18b9553`.
- [Raw response](raw/G01_WITH_MAPPING_user_upload_6d540aaa7bf9.txt): all 8,736 bytes preserved, including Markdown fences.
- Response SHA-256: `6d540aaa7bf960f87cddb07910769a91dfa18d2160c70e63378315e8b80abd6d`.
- [Run record](records/G01_WITH_MAPPING_user_upload_6d540aaa7bf9.json) includes fixed input/prompt hashes, source checks and findings.
- The user stated the same conditions as the prior run: Claude Opus 5.5, Claude web, a separate new conversation, search off and memory off. These remain user reports. Actual run time is unknown; recording time is separate.

Review was conducted by the assistant using programmatic source resolution and reading the supplied reasoning, not by an independent human or clinical expert.

## Core result and citations

The response returns **MET** for the one supplied diagnosis-only inclusion clause. It explicitly combines the patient's code/system with the provided mapping `project-policy:SNOMED-44054006-T2D` and cites the criterion. It does not infer subtype from drugs, labs or the generic Diabetes display.

All **15/15 structured citations** resolve to exact values and source owners: two criterion fields, nine patient fields and four mapping fields. The patient and mapping code/system match exactly. Quoted raw statuses, onset, null abatement and undetermined status at reference_date are present in the input. No current-status or final eligibility conclusion is supplied.

The listed unprocessed-resource counts and incidental medication/observation/condition names also match the complete input. The mapping is accurately described as a user-confirmed project rule, with no claimed independent terminology-server query.

## Preserved limitations and reasoning issue

1. **Inherited-context limitation:** the response states that unrelated personal memory context was present but unused. Preserve this alongside the user's memory-off report. It does not establish which interface/system mechanism supplied context, whether it affected the result, or verified isolation. Do not describe this as a clean isolated experiment.
2. **Minor reference-comparison error:** the reasoning says `subject_reference` string-matches `/patient/patient_id`. The literal strings differ: one is `urn:uuid:475803f3-ae29-ba8d-bdd1-25145a94eaee`, the other is `475803f3-ae29-ba8d-bdd1-25145a94eaee`. The reference resolves after removing `urn:uuid:`. This is a normalization/wording issue, not a wrong-patient field citation or unsupported core subtype assignment. The original text remains unchanged.
3. **Format warning:** Markdown fences were returned despite the JSON-only instruction. JSON was parsed without changing the raw response.

## Interpretation

The core positive-control result is consistent with the supplied evidence rule in this observed response. It shows a supported MET when an explicit mapping is provided. It does not establish that every sentence is error-free, that the model used no other internal information, or that backend grounding is enforced.

See the [paired report](paired_grounding_report.md) for the combined no-mapping/with-mapping result, source limitations and scope.
