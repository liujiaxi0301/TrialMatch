# Module A: baseline and integration plan

Status: Module A reliability changes published and their successful data-pipeline
cloud run reviewed on 2026-11-05. B/C
interfaces below remain proposals for team review, not implemented commands or
agreed contracts.

Local compilation, configuration and failure checks are now recorded in
[module-a-checks.md](module-a-checks.md), including the original 18 core regression
tests, six release-identity tests, eight deployment-binding tests, eleven
input-data guard tests and two Chroma deployment-script tests (45 total).
Build tests now also enforce immutable tags using the real Cloud Build YAML.
GitHub Actions and a real data-pipeline success run passed at `a8f1386`.
Negative-input cloud verification and B/C integration remain pending.

## Current integration (2026-11-05)

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

`cloud/pipeline.py` compiles and submits three Vertex tasks:

1. `fetch`: verify a GCS release and restore its fixed raw DVC snapshot.
2. `process`: reproduce the trial/criterion files with `prepare_data.py --from-raw`.
3. `validate`: check the processed data and vector snapshot, then perform one
   offline screening smoke check.

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

Proposed C input: the same data release, B's artifact manifest, a fixed benchmark
version and an output location. Proposed output: metrics plus per-case results,
recording the benchmark version, actual execution mode, artifact version, case
counts and errors. C owns metric definitions. Execution failures must remain
visible and cause a failed step; a completed run with poor quality scores should
be distinguished from an execution failure.

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
