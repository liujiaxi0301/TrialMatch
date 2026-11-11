# TrialMatch MS3 — Evaluation

This directory contains two independent evaluation modules.

## Retrieval

See [retrieval/README.md](retrieval/README.md).

Evaluates how well retrieval methods rank clinical trials relevant to a search question. Uses graded relevance labels (0/1/2), Precision@3, and nDCG@5.

## Eligibility

See [eligibility/README.md](eligibility/README.md).

Evaluates criterion-level patient-trial eligibility judgments (MET / NOT_MET / UNKNOWN), independently of the retrieval benchmark.

These offline evaluations do not establish clinical deployment readiness.
