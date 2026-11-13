# Evidence-guard test fixture

These synthetic inputs support `test_grounding_case.py` and `verify_grounding.py`.
They check that missing dates, reference ranges and qualified history do not become
unsupported definitive judgments.

- [Source statements](source_case.json) and [normalized patient](patient.json).
- [Example model claims](claude_baseline.json), used to test rejection of unsupported claims.
- [Expected checks](expectations.json).

The example model claims are not gold labels. This fixture is not a clinical
accuracy benchmark; MS3 evaluation is under `evaluation/ms3/`.
