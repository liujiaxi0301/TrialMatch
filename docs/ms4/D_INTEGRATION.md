# Part C / D compatibility check

This is the historical November 23 compatibility check. The current local C
branch now includes B/D; later verification is in
[selection integration](SELECTION_INTEGRATION.md).

Checked on **2026-11-23** against D's `yixiao/ms4-infra` commit
`91f163ffbf30c7b5853b16625da19683818fd61f` and the local, uncommitted C changes
on `xuyang/ms4-backend`.

C's backend changes apply cleanly to D. An isolated checkout combining both
passed the application Python tests and D's formatting/lint rules. The working
C branch has not been merged, committed or pushed by this check.

## Runtime and test handoff

| Purpose | D's interface |
| --- | --- |
| Start the offline application | `make up` |
| Browser/UI, with API proxy | `http://localhost:8080` (`APP_PORT`) |
| Direct API | `http://localhost:8081` (`API_PORT`) |
| Chroma | Internal `rag-chromadb:8000`; persistent `rag-chroma-data` volume |
| API tests and coverage | `make coverage`, or `bash scripts/ms4/check_coverage.sh` |
| Lint, format and coverage | `make check` |
| Full container/browser checks | `make ci` |
| Reports | `artifacts/ms4/` |

These commands are available after integrating D's branch. Nginx serves static
assets and proxies API paths; the backend still runs
`services.frontend.app:app`, with static hosting disabled by
`TRIALMATCH_SERVE_UI=false`. Browser requests remain on the frontend origin.

D's coverage script discovers both application test directories through pytest,
including C's 18 new integration tests. The test container mounts `services/`
and `demo/`, and supplies the required test dependencies. C needs no additional
test command, image, coverage implementation or cloud credentials.

D's changes to `config.py`, `embedding_providers.py` and `workflow.py` are
formatting changes. Its workflow formatting and C's error-boundary change apply
at different locations. It does not change C's HTTP adapter, retriever or schemas.

## Verified results and limits

D's [Actions run 45272384781](https://github.com/liujiaxi0301/TrialMatch/actions/runs/45272384781)
completed successfully at the commit above. The `application`, `pipeline` and
`retrieval-runtime` jobs all succeeded, and the `ms4-application-reports` artifact
was uploaded. This run contains D's changes, not the local C additions.

For the combined check, a detached D checkout received C's three production-file
changes and three new test/helper files. The internal command
`bash scripts/ms4/check_coverage.sh --container` was run with the host Python
environment, offline settings and D's pytest/coverage versions. Here the flag
skips container orchestration; it does **not** mean this was a Docker run.

| Combined host check | Result |
| --- | --- |
| Backend tests | 112 passed, 4 skipped, 0 failures/errors |
| Frontend Python/API tests | 6 passed, 0 failures/errors |
| Total | **118 passed, 4 skipped, 0 failures/errors** |
| New C integration tests, included above | **18 passed**, no skips |
| Application Python coverage | **83%** displayed (1,610 / 1,946 lines), above 50% |
| Ruff lint and format check | Passed across D's configured Python directories |

The four skips require optional torch/transformers packages absent from the host.
D moved the DVC test into the separate pipeline suite and added one frontend API
test, so directory counts differ from C's earlier baseline. This 83% is a new
measurement with its own environment and source state, independent of Jessie's
earlier 83% baseline.

[Machine-readable evidence](evidence/cd-compatibility.json) records the source
and artifact hashes, dependency versions, exact counts, skip reasons and CI
reference. Local XML/HTML coverage, JUnit results and logs are under
`artifacts/ms4/cd-compatibility/`; these ignored artifacts are not automatically
included in a pushed branch. Historical C evidence remains unchanged.

## Remaining handoff

- Integrate the C changes with D and run the complete `make ci` / GitHub Actions
  workflow on that combined revision. The host check does not validate its
  container startup, Nginx/browser path or remote Chroma persistence.
- Give Yixiao the C revision and test paths; D's existing discovery already
  includes them. Give Jessie the combined CI link and its reports once available.
- Integrate B's final index interface and A's frontend behavior separately.
  Deterministic model adapters in C's tests do not validate real model inference
  or final index migration/rollback behavior.
