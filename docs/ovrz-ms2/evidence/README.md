# Evidence and scope

`frontend-tests.txt`, `pipeline/`, and `http/` record execution against this
additive checkout. Tests use the already-installed locked dependency runtime.
Teammates' original tests and code have not been edited.

The two UI screenshots were captured from the earlier local integrated demo.
The same frontend source is retained here. They illustrate the UI, while the
new logs and artifacts independently verify this checkout.

This validation is Windows, Python 3.12.14, local persistent Chroma and offline
screening. Docker execution and new cloud calls have not been performed.
Do not infer either from successful local tests.

Run IDs and timestamps naturally differ between individual requests.
The source hashes identify the fixed data.

## Screenshot files

The original PNG bytes are preserved in `docs/ovrz-ms2/evidence/screenshots.base64.json`.
Run `python demo/ovrz/restore-screenshots.py` from the repository root to restore
`ui-screening.png` and `ui-retrieval.png` under `artifacts/ovrz/screenshots/`.
This text encoding is used because the browser upload channel did not complete.
