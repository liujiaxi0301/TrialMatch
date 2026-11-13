# Retrieval utilities

`benchmark.py` supplies encoder constants, rank fusion and trial deduplication to
the MS3 ranking runner and training code. It also provides a local experimental
retrieval harness; generated outputs belong under ignored `artifacts/`.
`screen_smoke.py` checks one synthetic case through the full screening workflow.

The submitted benchmark, labels, results and reproduction commands are in
[MS3 retrieval evaluation](../ms3/retrieval/README.md).

Run the utility tests from the repository root:

```bash
uv run --locked --group embeddings python -m unittest evaluation.retrieval.test_benchmark -v
```
