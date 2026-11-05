# Guard revision: changes and before/after results

## Example used

The same synthetic patient `SYNTHETIC_001` and the 14 criteria of `NCT02390973` were used before and after the October 19, 2026 revision. This fixed-trial test supplies the full small fixture and bypasses retrieval. Patient values, qualifiers, trial data and index were retained; no albumin range or prednisone class mapping was added.

## What changed and why

| Change | Why the old behavior was insufficient | Before → after in this case |
|---|---|---|
| Calculate supported BMI thresholds with matching units. | Seeing a number was enough to trigger abstention. | `inc_001`: UNKNOWN → MET; 37.2 ≥ 35. |
| Evaluate fully parsed flat OR/AND comparisons using three-valued logic. | The HbA1c/glucose OR expression was rejected without calculating its branches. | `inc_003`: UNKNOWN → MET; HbA1c 7.8 ≥ 6.5 or fasting glucose 8.1 ≥ 7 is sufficient. |
| Recognize explicit consent-capacity statements. | A consent keyword blocked even explicit evidence. | `inc_004`: UNKNOWN → MET; the source explicitly says able to consent. |
| Check pregnancy-specific negative text as well as correctly named Boolean evidence. | A negative text result was rejected because it was not Boolean false. | `exc_001`: UNKNOWN → NOT_MET, retaining a test-timing review warning. |
| Verify explicit negative-history scope and time coverage. | “No history” was confused with missing records; “or” triggered a blanket composite guard. | `exc_002`, `exc_004`, `exc_009`: UNKNOWN → NOT_MET. All named alternatives/windows are covered; “no known history” remains qualified. |
| Replace generic blocks with specific missing-evidence checks for albumin, medications and disease-category scope. | Old UNKNOWN decisions did not identify what was missing or actually compute time. | `exc_005`, `exc_007`, `exc_010`: UNKNOWN → UNKNOWN, now with explicit reasons below. |

For `exc_005`, albumin interpretation/range and pre-operative timing remain missing. For `exc_007`, two weeks before the fixture reference date is 2026-09-27, inside the last-month window; the date check passes, but a supplied medication-class mapping is missing. For `exc_010`, absence of known IBD does not establish absence of every gastrointestinal inflammatory disease. A general disease ontology has not been added.

These are bounded evidence checks, not a universal clinical language parser. Unsupported mixed expressions, conflicts, severity or subjective judgments can remain UNKNOWN.

## Recorded before/after comparison

| Measure | Old guards | Revised evidence checks |
|---|---|---|
| MET / NOT_MET / UNKNOWN | 1 / 0 / 13 | 4 / 4 / 6 |
| Definite / total | 1 / 14 | 8 / 14 |
| Inclusion positive controls retained | 1 / 4 | 4 / 4 |
| Match score | 7.1 | 57.1 |
| Screening result | NEEDS_MORE_INFORMATION | NEEDS_MORE_INFORMATION |

The score is favorable criteria divided by all criteria, not an enrollment probability. The same captured original Gemini proposals were also replayed through the new guards without new model calls and yielded the same eight definite outcomes. This supports attributing the coverage change to evidence validation; it does not establish clinical accuracy.

Implementation: `rules.py` calculates supported comparisons; `evidence_rules.py` checks bounded source statements; `judge.py` validates cited evidence; `workflow.py` runs supported rules before model calls. The 67 RAG tests and Ruff passed at the recorded checkpoint.

The ordinary retrieval run is a separate result and still PARTIAL due to a per-criterion citation-alias failure. See [end-to-end demonstration](END_TO_END_DEMONSTRATION.md) for that path and [grounding comparison](GROUNDING_COMPARISON.md) for the Claude/Gemini/RAG table. Machine-readable evidence is in [guard_revision_verification.json](guard_revision_verification.json); [live_verification.json](live_verification.json) preserves the initial run.
