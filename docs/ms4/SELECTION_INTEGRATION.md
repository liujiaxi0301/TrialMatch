# Part C: active-encoder API integration

Part C now uses `jenny/ms4-index` commit
`c36fe7784816b9c50468b186f53ca133803ff25c` as its base; that revision includes
D's infrastructure. The previous C fixes and tests were preserved. The additional
C changes are on `xuyang/ms4-backend`. Verification below was recorded from the
worktree before commit.

## API behavior

The request and response schemas are unchanged. `retrieval_model` remains
null/omitted, `gemini`, or `finetuned`. The latter resolves B's active encoder for
the configured Chroma backend; no record means the MS3 default. Omitted/null
preserves the server configuration, and explicit Gemini does not read the
fine-tuned selection record.

- **Readiness follows selection.** Every `/ready` request resolves settings
  before looking up a probe. Each selector retains only its latest probe, with
  a lock protecting resolution and replacement. Observed settings changes,
  including a return to an earlier encoder, create a new probe. Stable settings
  retain the existing 30-second report cache and make no model calls.
- **Selection failure is a service error.** A corrupt selection returns HTTP
  503, `ready=false`, `check_scope=encoder_selection`, and
  `checks.encoder_selection.code=ENCODER_SELECTION_INVALID`. This safe report
  has a zero cache TTL and contains no raw path or parser error. The previous
  probe is discarded, so recovery checks the index again.
- **A request uses one encoder snapshot.** The HTTP adapter resolves settings
  once and passes them to the workflow and completion logger. A switch during
  execution affects subsequent requests. It cannot mislabel the completed
  request's log or turn an otherwise completed response into a 500 merely
  because logging re-read a damaged selection. Direct `screen(request)` callers
  remain compatible; `resolved_settings` is an internal optional keyword.
- **Malformed records fail at their source.** B's record loader now translates
  invalid UTF-8 and non-string `active`/`previous` fields into the same typed
  selection error. Patient-input validation still returns 422, and unknown
  patients still return 404 under a valid selection.

Selection errors on `/screen` use `detail.code`. Index failures caught inside the
workflow can instead return a full HTTP 503 `ScreenResponse` with
`result_status=ERROR` and `errors[]`. The [API Contract](API_CONTRACT.md) describes
both envelopes. The B handoff and index runbook were updated to match.

No active-encoder field or mutation endpoint was added. Use `index-status` for
the catalog name, `/ready`'s index version for readiness, and `/screen` provenance
for the settings actually used. An unchanged settings configuration still has a
30-second index-report cache; an unobserved A → B → A transition can reuse A's
unexpired report. This is not a lock or a guarantee against every index mutation.

## Regression tests

[test_api_selection_lifecycle.py](../../services/rag_workflow/tests/test_api_selection_lifecycle.py)
adds **12 tests** using the real API, workflow, selection loader, embedded Chroma,
and B's switch/rollback functions. Tiny synthetic checkpoint files and model
adapters avoid cloud calls and downloads. They cover:

- Default → switch → rollback in one application, with matching index versions,
  response provenance and no readiness model calls.
- Cold/warm selection corruption, invalid UTF-8, invalid field types, repair and
  removal of the record, plus lost index manifests after recovery or rollback.
- A switch or record corruption during generation, including matching completion
  logs and the next request's behavior.
- Failed switches and refused rollbacks preserving the currently served encoder.
- Existing 404/422 behavior and independence of omitted/null/Gemini selection.

The original 11-test pre-fix run recorded eight failure entries, including
subtests. A separate regression reproduced non-UTF-8 corruption before fixing
that boundary. The final combined run below includes all 12 methods and the
encoding subcase, along with the earlier 18 C integration tests.

```bash
TRIALMATCH_MODE=offline CHROMADB_HOST= ANONYMIZED_TELEMETRY=False \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest \
  services.rag_workflow.tests.test_api_selection_lifecycle -v

make coverage
```

D's coverage discovery automatically includes the new file.

## Verification and evidence

Verification ran on November 27, 2026 (America/New_York; November 28 UTC).
A temporary checkout combined A `b2b4286`, B `c36fe77`, D `91f163f`, E `ddc8816`,
and the current C source. A/E remain outside the working C branch. D's internal
runner (`bash scripts/ms4/check_coverage.sh --container`) was executed using host
Python 3.12.14; here the flag bypasses Docker orchestration.

| Check | Result |
| --- | --- |
| Combined backend tests | 140 passed, 4 skipped, no failures/errors |
| Frontend Python/API tests | 6 passed, no failures/errors |
| Total application Python suite | **146 passed, 4 skipped, 0 failures/errors** |
| New selection lifecycle tests included above | **12 passed** |
| Combined Python statement coverage | **85%** displayed: 1,841 / 2,161 statements; threshold 50% |
| Ruff lint / format | Passed |
| Separate localhost HTTP checker on current C code | **8/8 passed** |
| Docker `make coverage` | Build blocked by container DNS resolving the package host; no container tests executed |

The four skips require optional torch/transformers packages absent from this host.
No combined GitHub Actions, browser/Nginx run, HTTP Chroma verification, or actual
model inference is claimed for this increment.

[Machine-readable evidence](evidence/selection-integration.json) records source
hashes, branch revisions, dependency versions, counts and artifact hashes.
Authoritative final test output is in ignored
`artifacts/ms4/selection-integration/combined-coverage-host.log`; JUnit and coverage
XML/HTML reports are under its `combined/` directory. The same artifact folder
contains the real HTTP report, pre-fix failures and the Docker build failure.
Historical C and B evidence is preserved rather than relabeled as this run.

The next team handoff is the C revision and updated contract, followed by a full
workflow on the published integration revision. Jessie can then replace the
older aggregate counts with that revision's final CI results.
