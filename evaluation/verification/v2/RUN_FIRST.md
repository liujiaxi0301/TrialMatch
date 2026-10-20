# Run the v2 Mode A procedure

This is the manual v2 procedure. The pre-cleanup guide/ZIP and original-byte revision records are preserved in the history archive indexed by `../manifest.json`. The model prompt and patient facts are unchanged. For current completed results, see [the reference review](results/reference_review_completed.md).

The approved offline assessment date is 2021-11-30. Actual screening, consent and V1 dates remain unknown. The trial snapshot is dated 2026-10-11 and NOT_YET_RECRUITING; the exercise does not establish recruitment in 2021 or now.

1. Start a new model conversation. Record the actual model name, version and interface. Turn off search, browsing and connected sources; disable memory where supported. Record uncertain settings as UNKNOWN.
2. Upload only `uploads/A/V2P01.json`. It contains the complete Cleveland facts, complete trial text and five source clauses, without reference answers. Check attachment readability and preserve any truncation or capacity warning.
3. Open `prompt_A.md` and paste all instructions below its separator into the model conversation.
4. Save the full response unchanged, including preambles, errors or omissions, and record actual model/search/context settings.
5. After recording the first response, use a separate new conversation with the same settings for `uploads/A/V2P02.json`. Do not expose the other response or reference answers to either model conversation.

This stage tests Mode A using complete supplied facts and criteria. Mode B requires a separate design and record. Building materials does not itself call a model or establish accuracy.

At preparation time no reference label was confirmed. Later all ten references were confirmed by a non-clinician after viewing model outputs. Keep that timeline explicit. Do not upload reference tables or reviewer notes to the model, and preserve a separate version for any later policy/label change.
