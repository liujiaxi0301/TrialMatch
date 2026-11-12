# Module A: baseline and integration plan

Local retrieval-evaluation update (2026-11-11 ET): C's `da31297` retrieval bundle
is imported unchanged, with the original query path retained for compatibility.
`--retrieval-evaluation` adds CPU scoring after this run's fine-tuned rankings,
using C's formulas and pinned labels. The graph has seven tasks, or eight with
eligibility. Missing labels block scoring with a diagnostic; historical reports
remain separate. Local verification and integrated cloud execution are separate
gates. See [module-a-retrieval-evaluation.md](module-a-retrieval-evaluation.md).

Local new-model retrieval update (2026-11-11, after `6053b7d`):
`--finetuned-retrieval-image` connects Jenny's ranking entry point to this run's
training artifact and validation report. It verifies the checkpoint and publishes
rankings/config/manifest from a separate CPU image. Training plus retrieval has
six tasks, or seven with eligibility. The optional scoring integration is described above.
See [module-a-finetuned-retrieval.md](module-a-finetuned-retrieval.md).

Local training-input update (2026-11-11): extra `--train-pairs` now require
`--train-pairs-sha256`. The trainer verifies the exact bytes it parses before
model loading; the submitter checks the resulting pair-source records before
publishing success. Workflow and trainer images need rebuilding for the new
interface. See [module-a-training.md](module-a-training.md); no cloud run is claimed.

Local eligibility update (2026-11-11): C's fixed-pair evaluator from `243f6bc`
is imported unchanged and connected by the optional `--eligibility` flag after
`validate-data`. It runs independently of B's training and checks model-call
failures before publishing success. See [module-a-eligibility.md](module-a-eligibility.md).
Default/data-only, training-only, eligibility-only and combined configurations
contain 4, 5, 5 and 6 tasks respectively. Cloud verification remains pending.

Local integration update (2026-11-11): Jenny's `55e88ba` training implementation is
being merged into `xuyang/ms3-pipeline` for review. The default four-node DAG is
preserved; selecting `--trainer-image` adds `train-encoder` after validation, with
batch size 8. The training manifest is checked before local success markers are
written. See [module-a-training.md](module-a-training.md) for the interface,
verification and remaining work. No integrated training cloud run is claimed.
The historical evidence below continues to describe the earlier four-node run.

Status (2026-11-10): the integrated four-step data/retrieval cloud run has passed
an offline consistency review of exported cloud records. The runtime graph was
also reviewed in chat; its original image file still needs archiving.
The `retrieve-trials` JSON log export has been reviewed and archived; it confirms
the task identity, release, 48 ranking rows and successful completion. The other
nodes' log exports remain pending. Training and formal scoring are not included.
The broader B/C training/evaluation interfaces below remain proposals for team
review, not implemented commands or agreed contracts.

Local compilation, configuration and failure checks are now recorded in
[module-a-checks.md](module-a-checks.md), including the original 18 core regression
tests, six release-identity tests, eight deployment-binding tests, eleven
input-data guard tests and two Chroma deployment-script tests (45 total).
Build tests now also enforce immutable tags using the real Cloud Build YAML.
These 45 checks and the cloud success run at `a8f1386` are the November 5 record.
The integrated November 10 branch has 47 passing CI tests. The negative-input
cloud checksum test has now passed independent review of its original archive:
the exact checksum error and all three blocked descendants are confirmed.
Training/formal-scoring integration remains pending.

## Current integration (2026-11-10)

- Local `xuyang/ms3-pipeline` was fast-forwarded to `yixiao/ms3-infra` at
  `50dc2ca0e5ff8a7a932ff96a126d3575e7f156ef` before this evidence/test update.
- The DAG is `fetch-raw -> process-trials -> validate-data -> retrieve-trials`.
  Its final node produces BM25/Gemini rankings for the fixed query protocol.
- Yixiao's run `trialmatch-data-pipeline-20261110055153` succeeded at recorded
  source `6cae15b387cb4de2e344b49864b68f7d0b24ab6a`. Xuyang exported its metadata
  and artifacts; [the evidence review](evidence/module-a/gcp-20261110/README.md)
  found consistent task dependencies, image/build records, releases and hashes,
  with 48 ranking records covering eight queries and six methods.
- Exact run-commit compilation agrees with the cloud specification, accounting
  for disabled runtime caching and the API's duplicate deployment config. The
  only changes from that commit to `50dc2ca` are README and frontend files.
- [CI at 50dc2ca](https://github.com/liujiaxi0301/TrialMatch/actions/runs/42865683063)
  passed 47 tests and the accompanying validation/static/compilation checks.
- The evidence collector reported `PARTIAL` because all four log queries returned
  no entries. Later console and JSON evidence showed the correct monitored
  resource is `ml_job`; the collector used the wrong type. Eleven retrieval
  log entries are now archived and agree with the release and outputs. The
  remaining three nodes' logs can be exported together; screenshot files still
  need archiving. These collection gaps do not change the successful states
  recorded in the Vertex job or block a separate failure-verification task.
- Next integration work: connect B's trainable model and C's formal scoring when
  their entry points are ready. Preserve runtime-graph image files for the report.
  Ranking generation alone is not training or a scored benchmark.
- The [cloud checksum-failure helper](module-a-cloud-failure.md) is now prepared:
  15 offline checks and Vertex request-schema validation passed. It reuses the
  reviewed four-node spec and immutable image, creates an isolated bad input and
  evaluates fetch failure plus all three downstream tasks. Xuyang executed it in
  Cloud Shell as `xuyang-ms3-hash-20261110t193643z-65e00490`. The
  [independent archive review](evidence/module-a/negative-20261110/README.md)
  passed 20 consistency checks: the damaged copy, unchanged expected hash,
  concrete checksum exception and three NOT_TRIGGERED descendants agree with
  the raw records. The failure graph and checksum-error images have been reviewed
  in chat and are optional presentation material, omitted from this commit at
  the user's choice. This test
  does not cover Python-runner marker cleanup or every invalid-input scenario.

## Previous integration (2026-11-05)

- Local branch `xuyang/ms3-pipeline` now includes the existing upstream commit
  `e96a928f5a795c84e6e647c0670691b74805e748`, which separates service dependencies.
- The stale-success-marker, report/release binding and snapshot-compatibility
  fixes are preserved. The 18 core regression tests use `docker/workflow/uv.lock`.
- A GitHub Actions workflow runs data validation, regression tests, static checks
  and compilation without cloud credentials. Its commands passed locally and in
  [GitHub Actions run 42100990939](https://github.com/liujiaxi0301/TrialMatch/actions/runs/42100990939),
  including all 45 regression tests.
- The original pipeline implementation and 2026-10-28 cloud run belong to Yixiao's
  existing work. The current Module A contribution adds reliability, tests, CI
  and verification of those changes in the 2026-11-05 data-pipeline run.
- After review, the user selected only the core reliability changes and CI.
  The broader automatic build/run provenance feature remains deferred.
- The user subsequently requested the focused release-identity correction:
  input release paths include both source version and workflow image digest.
  Build saves a small target record; publication and pipeline submission consume
  the same immutable image/release pair. Six additional regression tests cover
  repeat publication, rebuilding, failure handling and script integration.
- The user then approved binding API deployment to the successful data-pipeline
  run. Build records include the Cloud Build ID and workflow/API digests;
  `validated_deployment.json` binds that build to the verified output. Deployment
  rejects stale/mismatched records and uses the pinned API image.
- The approved build-to-publication data guard hashes all seven publication
  inputs before and after build, including the ignored index snapshot. Schema-4
  targets store those hashes and a data fingerprint used in release addresses.
  Publication verifies staged copies before GCS access; bound pipeline submission
  checks the cloud manifest against the target. Eleven additional tests cover
  this guard, and the six CI commands pass locally.
- The approved immutable-tag correction uses source version plus Cloud Build ID
  for all three image tags and stores the tag in the schema-4 target. Pipeline/API
  consumers remain pinned by digest; first-time Chroma VM creation uses the saved
  tag. Existing VMs are left unchanged. Tests now model immutable registry tags.
- Xuyang approved publication of the reviewed changes to the personal branch as
  `a8f138630dd5aa8ff4ff4d6844a76f5a4c473170`. GitHub Actions succeeded, then Xuyang
  ran `build -> publish -> pipeline` in Cloud Shell. The
  [evidence review](evidence/module-a/gcp-20261105/README.md) found consistent
  records for build `55298693-4647-4890-b5eb-bf0a22f2fae0` and successful pipeline
  `trialmatch-data-pipeline-20261105205047`. This covers the current data workflow;
  a runtime graph screenshot, negative-input cloud verification and B/C integration
  remain outstanding.

## Baseline inspected on 2026-10-29

- MS2 baseline: `milestone2` at `f2fedbd416e9c89a3da6337c291d83d1f5ea4eb0`.
- Existing MS3 infrastructure: `yixiao/ms3-infra` at
  `e95c2bb8c9cd28183ef426095d63354b317d519e`, a descendant of that MS2 baseline.
- Module A local working branch starts from this infrastructure commit so its
  existing pipeline and release format can be reused.
- No remote `milestone3` branch was advertised when branches were inspected.
  The final team integration branch is still to be established.

The infrastructure README links to a successful Vertex data-pipeline run and a
Cloud Run app. Those are existing team records; cloud execution and access were
not independently verified during this baseline check.

## What already exists

`cloud/pipeline.py` now compiles and submits four Vertex tasks:

1. `fetch`: verify a GCS release and restore its fixed raw DVC snapshot.
2. `process`: reproduce the trial/criterion files with `prepare_data.py --from-raw`.
3. `validate`: check the processed data and vector snapshot, then perform one
   offline screening smoke check.
4. `retrieve`: consume the validation report and produce BM25/Gemini rankings
   plus configuration for the fixed MS3 queries and 50-trial universe.

`cloud/tasks.py` publishes release files with checksums and passes task outputs
through GCS. `cloud/deploy.sh` consumes the validated release for deployment.
The validation report explicitly excludes training and clinical benchmarking.
That smoke check must remain distinguishable from Module C's benchmark results.

## Local baseline verification

Python 3.12.14 ran `python prepare_data.py` successfully:

- Trial records: 1,313; criterion records: 18,456.
- The trial, criterion and 25-patient files matched the supplied SHA256 manifest.
- Re-parsing the trial criteria reproduced the committed criterion file exactly.
- The manifest selects 50 trials and 25 patients.
- Trial processing date: `2026-10-11`; patient reference date: `2021-11-30`.
- Local version report: `artifacts/infra/data_versions.json` (generated/ignored).

This check used committed processed data. It did not restore raw DVC data,
download the vector snapshot, build a container, call Gemini, or submit a cloud job.

## Ownership and proposed handoffs

| Owner | Responsibility | Handoff |
| --- | --- | --- |
| A | Pipeline orchestration, input validation, artifact/version records | Validated data release URI and pipeline run metadata |
| B | Training implementation and experiment tracking | Callable entry point, training artifact and experiment record |
| C | Fixed benchmark, quality metrics and comparisons | Callable evaluation entry point and machine-readable metrics |
| D | Cloud resources, IAM, image publishing and runtime deployment | Project/region, bucket, service account, images and deployment interface |
| E | Deployed API tests, application logging and integration evidence | API test results and accessible logs |

Proposed B input: the validated `release.json` URI plus explicit run configuration
and an output location. Proposed output: a training manifest identifying the
source release, artifact URI/checksum, workflow type, configuration, code/image
version and experiment run reference. An index experiment may represent the
training requirement only after the team confirms that approach with the TF.

Original proposed C input: the same data release, B's artifact manifest, a fixed benchmark
version and an output location. Proposed output: metrics plus per-case results,
recording the benchmark version, actual execution mode, artifact version, case
counts and errors. C owns metric definitions. Execution failures must remain
visible and cause a failed step; a completed run with poor quality scores should
be distinguished from an execution failure.

The delivered C eligibility evaluator instead uses fixed patient/trial pairs and
does not consume B's checkpoint. Its independent branch is now implemented
locally; the broader model/retrieval comparison above remains separate work.

Keep the existing data-release schema usable by deployment. Agree any new
model/evaluation release fields with D before changing that interface.

## Proposed training/evaluation integration

The following sequence describes the original broader integration plan and
depends on B/C providing their entry points. It is separate from the completed
local reliability work above. The course workflow requirement permits
preprocessing, training and/or evaluation; training and experiment tracking
still require their own team deliverables.

1. Review the existing data tasks for reusable validation and configurable paths;
   document their current input/output contract and add focused failure checks.
2. Confirm the B/C handoffs and D's runtime configuration. Continue with local
   component work while cloud access or teammate implementations are pending.
3. Extend the existing DAG with B's training task and C's evaluation task. Pass
   GCS/Vertex artifacts between tasks; make dependencies explicit. Do not create
   a second independent data pipeline with conflicting release conventions.
4. Compile the complete pipeline and verify that the expected tasks, artifact
   inputs and configuration appear in the generated specification.
5. Run it on Vertex, check the resulting artifacts and exercise a deliberately
   invalid input in a separate test location. Preserve evidence of failure before
   downstream work starts, as well as evidence of a complete successful run.
6. Document reproduction commands, configuration, versions, run IDs, logs and
   output URIs under the MS3 documentation and evidence directory.

Module A completion requires actual integrated execution and inspectable output
artifacts. Compilation, a placeholder training task, or the existing single-case
offline smoke check alone does not establish that completion.
