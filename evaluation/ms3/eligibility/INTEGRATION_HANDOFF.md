# MS3 Module C — Eligibility Evaluation Handoff

Owner: Jiaxi
Status: Local evaluation completed; 8 automated tests passed.

See [README.md](README.md) for benchmark details, metrics,
reproduction instructions, and test commands.

## 1. Entry Point

`evaluation/ms3/eligibility/run_eligibility.py`

Two supported operations:

- `run --split all --provider developer --tag <tag>`:
  generate predictions using Gemini and score them.
- `score --predictions <path>`:
  score saved predictions without model calls.

## 2. Inputs and Outputs

Inputs:
- Frozen E01–E08 benchmark (115 criteria)
- Compatible processed patient/trial data
- Predictions JSONL and matching metadata for score mode
- Gemini credentials only for new online inference

Outputs:
- `_predictions.jsonl`
- `_metadata.json`
- `_metrics.json`
- `_disagreements.csv`

The orchestration layer must check
`official_reporting_ready == true` in metrics JSON.
Model-call failures must not count as successful evaluation.

## 3. Integration Constraints

- Scoring validates data, prediction, and code SHA256 hashes.
- Historical predictions require matching source/code versions.
- Do not disable hash checks or overwrite the frozen baseline.
- The CLI currently uses local paths, not GCS URIs.
- Cloud tasks must stage inputs and publish outputs to GCS.

## 4. Team Handoff

Module C (Jiaxi):
- Frozen gold labels, scoring logic, evaluation tests and metrics

Module A / Infrastructure:
- Vertex task integration, runtime environment, GCS artifacts
  and cloud execution logs

The local evaluator is complete. Vertex integration has not
yet been verified and must not be claimed as completed.
