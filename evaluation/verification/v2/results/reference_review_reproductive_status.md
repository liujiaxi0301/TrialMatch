# Reproductive-status exclusion: reference confirmation

Confirmed on 2026-10-18 by the user, a non-clinician, after model outputs and AI suggestions were available. This was not blinded or independent clinical review.

**English translation of the user's confirmation:**

> I confirm both exc_002 labels as UNKNOWN: this review does not infer reproductive status from administrative gender alone.

Both decisions concern NCT06774950_exc_002: `Pregnant or breast-feeding women`.

| Pair | Available field | Confirmed reference | Original model label |
| --- | --- | --- | --- |
| V2P01 | patient.demographics.gender = male | UNKNOWN | NOT_MET |
| V2P02 | patient.demographics.gender = male | UNKNOWN | NOT_MET |

See demographics in [V2P01](../uploads/A/V2P01.json) and [V2P02](../uploads/A/V2P02.json). The [reference table](../templates/reference_answers.csv) cites the demographic fact to explain evidence limitations, not to establish reproductive status.

The user accepted the pre-existing conservative suggestion: administrative gender alone is insufficient, and absent a direct assessment the reference stays UNKNOWN. Neither the original suggestion nor model answers were changed to remove a disagreement. The confirmation does not establish presence or absence of pregnancy or breast-feeding.

The two model labels disagree with the accepted evidence rule; this is not an independently established clinical error. Report the rule, acceptance timing and reviewer limitations. Progress at this step was 8/10; see the [completed review](reference_review_completed.md) for final 10/10 state. No model rerun or clinical accuracy estimate was made.
