# Evidence and scope

`frontend-tests.txt`, `pipeline/`, and `http/` preserve the original frontend
delivery's local execution records. Tests used the already-installed locked
dependency runtime. These are historical per-session records, not a summary
of all subsequent team validation.

The two UI screenshots show the earlier local integrated demo. The current V2
screenshots and mock-up are linked from [the MS2 documentation](../../ms2/README.md).

This historical session used Windows, Python 3.12.14, local persistent Chroma
and offline screening. Its `verification.json` fields `docker_executed: false`
and `new_cloud_model_calls: false` apply only to that local session.
The team separately confirms that the integrated Docker workflow ran successfully;
screenshots of that run were not retained. Historical module Docker/Gemini
verification records are in `services/rag_workflow/examples/` at the repository root.

Run IDs and timestamps naturally differ between individual requests.
The source hashes identify the fixed data.

## Screenshot files

The original PNG bytes are preserved in `docs/ovrz-ms2/evidence/screenshots.base64.json`.
Run `python demo/ovrz/restore-screenshots.py` from the repository root to restore
`ui-screening.png` and `ui-retrieval.png` under `artifacts/ovrz/screenshots/`.
This text encoding is used because the browser upload channel did not complete.
