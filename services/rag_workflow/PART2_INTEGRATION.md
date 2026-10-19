# Part 2 integration checkpoint — 2026-10-19

The local Part 3 checkout consumes the patient-processing delivery from
`feat/patient-processing` commit
`9d49329c0b88d1d4d887465fff06f7ca2a2908c2`. Its `services/patient_processing/`
and `evaluation/verification/` files were imported without changing the upstream
facts or reference labels. This is a local integration checkpoint, not a merge
into the team's milestone branch or a deployed-service acceptance.

## Data and index versions

- Input: `services/patient_processing/data/processed/batch25_patients.jsonl`.
- Patient SHA-256: `33ac165b9be7c564207325ae951d40b9cfdc3b72f8fb2f56e3e58193894331a1`.
- Schema: `0.3`; 25 adult T2D patients; reference date: `2021-11-30`.
- The latest delivery changes documentation and verification evidence, not the
  processor or patient facts. Regenerating the 50-trial demo manifest produced
  identical contents.
- Existing embedded Chroma index `8a7004181d978a705d94` verified successfully:
  607 vectors, `gemini-embedding-001`, 256 dimensions, Chroma 1.5.9.
- No re-embedding, Chroma snapshot change or DVC pointer change was needed.

## Validation performed

- Patient-processing tests: 6 passed.
- RAG tests: 67 passed.
- Upstream verification tests: 15 passed; all three documented input/coverage
  check commands passed.
- Offline screening: all 25 patients returned `OK` with three candidate trials.
- In-process FastAPI health and patient-list routes returned HTTP 200 and loaded
  all 25 patients.
- The local detailed integration report is
  `artifacts/rag_workflow/part2_update_validation.json` (ignored generated output).

These are compatibility and reproducibility checks, not clinical accuracy tests.
No live Gemini calls or deployed backend restart were performed. The previously
observed live grounding run's citation-validation failure remains a separate
open issue; these checks do not resolve it.

## Consuming contract and remaining deployment work

Preserve fact IDs, exact codes, units, dates, statuses and warnings. Missing facts
are not negative evidence; medication orders are not evidence of actual use.
The facts cutoff is not a known screening, consent or trial visit date. The
cohort includes two recorded deaths and must not be described as 25 eligible or
confirmed-living candidates. See the upstream [handoff](../patient_processing/MS2_HANDOFF.md)
for the complete contract and limitations.

After publishing this integration, the infrastructure owner must deploy the
same data/manifest/index bundle and restart the cached API process. No team
message, Git commit, push or shared deployment was performed by this checkpoint.
