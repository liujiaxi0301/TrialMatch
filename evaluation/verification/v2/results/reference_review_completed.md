# Completed v2 reference review

Completed on 2026-10-18: two selected synthetic patients, one trial NCT06774950, five complete source clauses per patient and one Mode A response each.

The user confirmed **10/10 offline references: 3 MET, 1 NOT_MET, 6 UNKNOWN**. Review was AI-assisted, non-blinded and by a non-clinician after model outputs were available. These references are not an independent clinical gold standard.

## Clause-level comparison

| Source clause | V2P01 reference | V2P01 model | V2P02 reference | V2P02 model |
| --- | --- | --- | --- | --- |
| inc_001: documented T2D history under ten years | MET | MET | MET | MET |
| inc_002: age 40-65 | MET | MET | NOT_MET | NOT_MET |
| exc_001: significant comorbidities/severity/investigator judgment | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| exc_002: pregnant or breast-feeding women | UNKNOWN | NOT_MET | UNKNOWN | NOT_MET |
| exc_003: inability to give signed informed consent | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

**Eight labels agree and two differ**, with four agreements and one difference per patient. Both differences concern reproductive status: the model used administrative gender male, while the user-confirmed reference rule requires more direct evidence and retains UNKNOWN. These are evidence-rule disagreements, not independently established clinical errors. This agreement count is not clinical accuracy or a generalization estimate.

## Confirmation evidence and retained limits

1. [Age](reference_review_ages.md): 43 and 27 at the explicit assessment date; neither tests source-interval endpoints.
2. [Documented history](reference_review_diagnosis_duration.md): 1450 and 774 days. True first-ever diagnosis dates are unproven; MET is limited to the documented-history surrogate.
3. [Comorbidities](reference_review_comorbidities.md): Anthony has recorded neuropathy; severity and exclusion applicability still require clinical assessment.
4. [Reproductive status](reference_review_reproductive_status.md): the accepted evidence rule does not confirm actual pregnancy/breast-feeding status.
5. [Consent capacity](reference_review_consent_capacity.md): missing capacity assessments remain unknown; absence of signatures is not incapacity.

Each linked record preserves the confirmation source; quotations are translated where needed. No new review decision is implied.

Assessment_date is 2021-11-30 for offline replay of older synthetic data. Actual screening, consent and V1 dates remain unknown. The trial snapshot is 2026-10-11, NOT_YET_RECRUITING, so historical or current recruitment is not established.

Under the references, Cleveland has two supported inclusion requirements and three unresolved exclusions. Anthony has one supported inclusion, one clear age conflict and three unresolved exclusions. UNKNOWN is not exclusion clearance, an enrollment probability or a final eligibility decision.

## Reference and validation files

- [Current reference table](../templates/reference_answers.csv) and one [frozen completion snapshot](reference_answers_confirmed_20261018.csv). They currently match intentionally.
- [Model/reference comparison](reference_model_comparison.csv) and [completion source hashes](reference_review_completed.json).
- [Current reference check](../../evidence/v2_input_check.txt), [15 passing tool tests](../../evidence/verification_tests.txt) and [delivery audit](../../evidence/delivery_checks.json).
- [Revision provenance](../../LANGUAGE_AND_PROVENANCE.md) and [removed-copy index](../../delivery_revision.json).

The revision index distinguishes original run provenance from translated or punctuation-normalized delivery copies. Original bytes and removed working copies are backed up outside the repository. The five linked confirmation records, patient facts, source identities, labels and evidence IDs remain in this delivery. Future policy or label changes require a new review version; preserve this completion snapshot.

No extra model run, Mode B experiment, repeatability study or clinical expert validation was completed by this review.
