# Retained execution evidence

`pipeline/` contains one original local offline run: `request.json`,
`retrieved_context.json`, `screen_response.json`, `run_manifest.json` and
`run.txt`. These are historical outputs, not newly generated verification.

The run used Windows, Python 3.12.14 and local persistent Chroma. Its manifest
records the source SHA-256 hashes and dataset scope. No successful Docker run
or live Gemini call is implied by these files.

To generate fresh local evidence, run either launcher in `demo/ovrz/`, or use
the locked environment to run `python -m services.frontend.prepare` with
`TRIALMATCH_MODE=offline` and `TRIALMATCH_ARTIFACTS=artifacts/ovrz/rag_workflow`.
Outputs go to the ignored `artifacts/ovrz/ms2/` directory. Run IDs/timestamps
will differ. Capture Docker logs and running-instance screenshots separately
when preparing the team's milestone submission.
