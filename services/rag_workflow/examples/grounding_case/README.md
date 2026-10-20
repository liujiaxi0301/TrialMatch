# RAG demonstration and grounding case

These documents answer three separate questions. Recorded results are from October 19, 2026; restructuring the documentation makes no new model requests.

| Read this | Question answered | Scope |
|---|---|---|
| [END_TO_END_DEMONSTRATION.md](END_TO_END_DEMONSTRATION.md) | How does a patient query lead to retrieved criteria and a judgment with cited patient evidence? | Normal RAG retrieval; follows returned trial NCT03821636. The overall run remains PARTIAL. |
| [GROUNDING_COMPARISON.md](GROUNDING_COMPARISON.md) | How do Claude, raw Gemini and the RAG judgment layer differ on the same case? | Fixed NCT02390973 and full patient context; no retrieval comparison. |
| [GUARD_REVISION.md](GUARD_REVISION.md) | What changed in the guards, why, and with what before/after result? | Same fixed-trial fixture; 1 known → 8 known out of 14. |

## Inputs and recorded evidence

- [source_case.json](source_case.json): original source statements and normalization caveats.
- [patient.json](patient.json): normalized synthetic input; not a Part 2 cohort patient.
- [claude_baseline.json](claude_baseline.json): supplied Claude decisions, not gold labels.
- [expectations.json](expectations.json): predeclared focused checks and positive controls.
- [live_verification.json](live_verification.json): initial live-run record, including raw disputed Gemini proposals.
- [guard_revision_verification.json](guard_revision_verification.json): revised results and replay holding original model proposals constant.
- `../../verify_grounding.py`: runner for fixed-trial and ordinary RAG layers; live command in the comparison document.

Local generated artifacts are under `artifacts/rag_workflow/grounding_case/` (initial run) and `artifacts/rag_workflow/grounding_case_guard_revision/` (revised run). They are Git-ignored; the tracked documents include the relevant excerpts and compact records.

The fixture reference date is a declared test anchor; source labs remain undated. All three documents preserve the distinction between incomplete evidence and confirmed absence, between a retrieval candidate and an eligible patient, and between a fixed-trial check and a complete workflow pass.
