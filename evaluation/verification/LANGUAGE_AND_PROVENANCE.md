# Evidence provenance and delivery revisions

Patient facts, criterion identities, decisions, evidence IDs, numerical values and experiment limitations are retained. No additional model run or clinical review was created by these delivery revisions.

## Original-byte provenance

Before text conversion, all 187 personal delivery files were backed up outside the repository with SHA-256 hashes. Historical prose and confirmation quotations were translated, and fullwidth semicolons in verification copies were normalized to ASCII. [delivery_revision.json](delivery_revision.json) distinguishes original hashes from current delivery hashes and records the external backup. Translated copies must not be described as byte-identical originals.

Upstream trial-ingestion files and patient-processing code/data were unchanged. V2 patient inputs, model prompts and all grounding inputs/raw responses retained their original bytes. Metadata preserves original run-time hashes separately from current delivery-manifest hashes.

## Consolidated delivery layout

A second external backup preserves all 188 files immediately before deduplication. Its location, manifest hash, removed-file hashes and canonical replacements are recorded in the `deduplication` section of [delivery_revision.json](delivery_revision.json). External backups are for provenance and rollback; delivered checks use repository files only.

- The single v2 procedure is [RUN_FIRST.md](v2/RUN_FIRST.md); the upload ZIP contains that same guide.
- Each policy retains a current reference table and one necessary frozen snapshot: [v1 snapshot manifest](results/policy_v1_snapshot/snapshot_manifest.json) and [v2 completion snapshot](v2/results/reference_answers_confirmed_20261018.csv). Duplicate translated tables and the working archive were removed.
- The five v2 confirmation records remain linked from the [completed review](v2/results/reference_review_completed.md). Their user quotations are translations, with original bytes preserved in the external backup.
- [checks.json](evidence/checks.json) indexes one current log per reproducibility check. Stage-by-stage and duplicate logs are preserved in the external backup. [delivery_checks.json](evidence/delivery_checks.json) records the final consistency audit.

V1 remains paused at 22/30 confirmations; v2 retains ten (3 MET, 1 NOT_MET, 6 UNKNOWN) with eight model agreements and two differences. The [grounding pair](grounding/results/paired_grounding_report.md) retains both responses, the inherited-context limitation and the minor reasoning finding. These revisions do not imply publication, retrieval/backend enforcement or clinical accuracy.
