# Cloud checksum failure check

The [recorded negative test](evidence/module-a/negative-20261110/README.md)
corrupts a separate raw-data pointer. Fetch fails with a checksum error, and
the three downstream tasks do not execute. The failed pipeline is the expected outcome.

## Reproduce

From the repository root in Cloud Shell, with access to the TrialMatch project:

```bash
python3 scripts/ms3/verify_checksum_failure.py run
```

This submits a new Vertex job and writes two objects under an isolated test prefix.
It uses the fixed November 10 baseline and incurs normal cloud task charges.
Original releases and deployed services are unchanged. To collect the same job
after an interrupted session, use `collect` instead of submitting again:

```bash
python3 scripts/ms3/verify_checksum_failure.py collect
```

`PASSED` requires the exact checksum error and all three downstream tasks blocked.
Missing evidence or unrelated failures do not count as a pass.

## Offline tests

```bash
docker/workflow/.venv/bin/python scripts/ms3/test_verify_checksum_failure.py
```

These tests use simulated cloud calls and the saved positive-run job and release
records. They do not submit cloud jobs.
