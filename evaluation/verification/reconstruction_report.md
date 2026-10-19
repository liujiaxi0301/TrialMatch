# Historical verification recovery report

Recovery completed on 2026-10-18. This report describes the recovery stage, not the current annotation count. V1 subsequently paused at 22/30 confirmed clauses; v2 subsequently completed a separate 10/10 review. See the [current results](v2/results/reference_review_completed.md). Recovery itself made no model calls.

## Recovered and reconstructed artifacts

| Material | Recovery-stage result |
| --- | --- |
| Six V01-V03 responses | Original attachment bytes recovered and SHA-256 checked |
| Two complete patient records | Reconstructed from committed facts and matched against reprocessing of checked-in official FHIR |
| Three trials and 30 source clauses | Reconstructed from repository snapshots; source-text coverage checked |
| Six upload pairs per mode | Complete identical patient objects across A/B; Mode B contains no trial criteria |
| Reference template | 60 rows, with 30 active V01-V03 clauses; initially one recovered confirmation and 29 pending |
| A/B response exports | 60 model entries, not 60 independent reference clauses |
| Error-review template and categories | Structural warnings remain separate from human-confirmed errors |
| Prompts, builders and recorders | Reconstructed and explicitly distinguished from unavailable original prompts |

## Findings at recovery

- All cited fact IDs exist in the corresponding patient input; existence does not establish sufficient support.
- V01B matches nine of ten source clauses. The sixth exclusion text is missing despite ten returned entries.
- Each other response matches all ten source clauses after normalization; this checks text, not reasoning.
- V02B has a preserved preamble outside JSON.
- All three Mode A responses report inherited memory context. User-reported search-off settings do not establish strict isolation.
- Historical V01 exc_004 UNKNOWN was retained with its obesity/metabolic-syndrome rationale. Evidence links were reconstructed; original reference CSV bytes were not recovered.

Original upload bytes/hashes, original prompt wording and original review notes were unavailable. Reconstructed inputs cannot prove historical upload identity. Patient cutoff 2021-11-30 and trial snapshot 2026-10-11 describe a hypothetical comparison, not actual recruitment.

The recovery-stage `build_cases.py --check` and five initial recorder/validator tests passed. The package now has 15 tool tests; see the [final test log](evidence/verification_tests.txt). Later completion does not rewrite the recovery-stage facts above.

V04-V06 remain prepared but unrun. The remaining eight v1 references are not mandatory follow-up for the completed v2 pilot; the protocols must remain separate.
