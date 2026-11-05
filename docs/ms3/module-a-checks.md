# Module A: compilation, configuration and failure checks

Rechecked on 2026-11-05 on local branch `xuyang/ms3-pipeline`, after advancing
to the existing infrastructure commit
`e96a928f5a795c84e6e647c0670691b74805e748`. The initial check used `e95c2bb`
on 2026-10-29. The local fixes and test files were preserved during integration.

Yixiao implemented the original cloud pipeline and deployment. This Module A
change adds failure protection, snapshot compatibility checks, regression tests,
and CI. After review, the broader automatic build/run provenance experiment was
withdrawn. Xuyang then requested the targeted release-identity correction and
the build/validation/deployment binding, input-data hash guard and unique build
tags described below. Xuyang approved committing and publishing these changes to
the personal branch on 2026-11-05. The evidence below records local verification;
GitHub Actions and GCP execution are separate checks.

## Results

| Check | Result and scope |
| --- | --- |
| Locked environment | Installed `docker/workflow/uv.lock` with uv 0.13.1, without changing dependency files. Python 3.12.14, KFP 2.16.1, Vertex SDK 1.165.1, Chroma 1.5.9. Tests use the workflow service environment. |
| Compilation | Real KFP compilation succeeded. The generated DAG has `fetch-raw -> process-trials -> validate-data`, explicit artifact dependencies and no run-after-failed-parent override. Compile-only does not call the Vertex submission API. |
| Runtime configuration | Project, region, registry, zone, service-account naming and DVC remote agree with the current setup/deployment scripts. Bash syntax checks passed. This is configuration consistency, not live permission verification. |
| Processed data | `prepare_data.py` passed for 1,313 trials and 18,456 criteria; the trial, criterion and patient files match their fixed SHA256 values. |
| Failure and compatibility tests | All 45 tests passed: the previous 43 tests with stronger build-result and immutable-tag checks, plus 2 Chroma deployment-script tests, using the workflow service dependencies. GCS, Vertex, Cloud Build, Compute Engine and Cloud Run calls are simulated; snapshot compatibility uses real embedded Chroma and synthetic test vectors. |
| Static checks | Ruff 0.17.1, actionlint 1.7.7, and Git whitespace checks passed. |
| CI configuration | Added `.github/workflows/pipeline-checks.yml`. All six shell steps passed locally. GitHub-hosted execution is pending a push and is not claimed by these results. |

The existing data pipeline remains a reproduction and functional-validation
workflow. These results do not demonstrate training or a clinical benchmark.

## Confirmed problems and local fixes

### A failed rerun could leave an old deployable release

Previously, a failed submission, failed job or failed validation report left the
previous `artifacts/cloud/validated_release.txt` in place. The deployment script
could then consume that old success marker.

`cloud/pipeline.py` now clears the previous current-run markers before compiling
and submitting a new run. It writes a deployable-release marker only after the
new run and validation report succeed. The current deployment-validation record
is also cleared before a new build/run. Compile-only preserves existing markers.
The report's release URI must also match the current process task's output URI.

These files describe one current submission. Preserve prior-run evidence in a
separate run-specific directory before submitting another run from this checkout.

### An internally valid snapshot could be incompatible with this release

Previously, `cloud/tasks.py validate` checked the snapshot's internal schema,
count and checksum. A snapshot with different source hashes or wrong vector
dimensions could still pass that check and the independent offline screening
request, even though deployment would reject the snapshot.

Validation now restores the snapshot into a disposable embedded Chroma store
using the existing `VectorIndex.restore` checks. This validates source/configuration
identity, IDs, text, metadata, dimensions and restored records before reporting
success. The temporary store is separate from the deployed Chroma server and
requires no Gemini calls. It adds a local restore to the validation task; the
updated workflow image still needs to be built and verified on Vertex.

The initial regression run reproduced six failing assertions across stale
success markers, a report referencing another output, and incompatible snapshots.
After the fixes and additional input-failure checks, all 18 tests passed.
The original 2026-11-05 rerun passed all 18 core tests in the service's locked
environment. After adding six tests for the release-identity fix, all 24 tests
passed, together with the six local CI commands. Eight more tests now cover
build/validation/deployment binding, including failures and an in-flight build change.
Those 32 tests passed. Eleven more tests cover input-data capture, changes during
build, checked-copy publication, data fingerprints and cloud-manifest checks.
Those 43 tests passed, but the simulated registry initially omitted immutable-tag
enforcement. The build tests now read the real Cloud Build YAML and enforce that
rule, and two more tests cover new and existing Chroma VMs. The current rerun
passed all 45 tests and all six local CI commands.
See [current test output](evidence/module-a/local-tests-20261105.txt) and
[integration check results](evidence/module-a/integration-checks-20261105.json).
The [initial test output](evidence/module-a/local-tests.txt) is retained separately.

## Reproduce locally

From the repository root, using Python 3.12 and uv (verified with uv 0.13.1):

```bash
uv sync --project docker/workflow --locked --no-dev --python 3.12
docker/workflow/.venv/bin/python prepare_data.py
docker/workflow/.venv/bin/python -m unittest discover -s cloud/tests -v
uv tool run ruff==0.17.1 check cloud/pipeline.py cloud/tasks.py cloud/release.py cloud/tests
bash -n cloud/deploy.sh cloud/setup.sh
```

Compilation can be checked without submitting a job:

```bash
docker/workflow/.venv/bin/python -m cloud.pipeline \
  --project=trialmatch-ci \
  --region=us-east1 \
  --bucket=trialmatch-ci-data \
  --image=example/workflow:ci \
  --release=gs://trialmatch-ci-data/releases/fixed/release.json \
  --compile-only
```

The `ci` image and release are illustrative inputs, not verified
registry/storage objects. The output is `artifacts/cloud/pipeline.yaml`.
Use the built image and published release from the deployment workflow for an
actual submission.

## Continuous integration

[Pipeline checks](../../.github/workflows/pipeline-checks.yml) runs on all pull
requests, pushes to `milestone3`, `yixiao/ms3-infra` and `xuyang/ms3-*`, and manual
dispatch. It uses read-only repository permissions and requires no GCP secrets.
External actions are pinned to commit hashes.

The job installs the workflow service lockfile, runs Ruff and shell syntax checks,
validates the committed data, runs the regression tests, and compiles the DAG
with illustrative inputs. The tests use synthetic vectors and mock cloud calls;
they exercise the real local snapshot restore and offline screening code.

The workflow passed actionlint and its shell steps were executed locally.
An actual GitHub Actions run will provide separate evidence after the approved
changes are pushed. These checks do not build a Docker image or submit a Vertex job.

## Release identity correction

Review reproduced a conflict in the withdrawn digest-publication implementation:
the input release directory depended only on the source version, while its
immutable manifest also contained an image digest. Rebuilding unchanged source
could produce a different image digest, causing a second publication to fail.

`cloud/release.py` now identifies an input release by the source version, the full
workflow image SHA256 digest and a data fingerprint. `cloud/deploy.sh build` captures the
successful Cloud Build JSON result (with streamed logs suppressed), selects the
exact workflow and API images from `results.images`, and saves their digests and
the Cloud Build ID, unique image tag, input-file hashes and data fingerprint in an atomic
`artifacts/cloud/release_target.json` record (schema 4). The build's source-version marker
is written only after this succeeds. Failed builds or invalid/missing digests
cannot leave the preceding build selected for publication.

Both `publish` and `pipeline` read and validate this same record against the
current version, registry and bucket. They do not look up an image tag
again. The image URI uses `@sha256:...`, and the input release URI is:

```text
gs://<bucket>/releases/<source-version>/<64-character-workflow-digest>/<data-fingerprint>/release.json
```

The existing immutable-file and manifest checks in `cloud/tasks.py publish`
remain in place. Identical source/image/data can be republished; a different
image or data fingerprint gets a different directory; changed data at an existing URI is rejected.
Processed releases still use Vertex's per-task output directory and preserve the
input manifest's image reference.

Six additional regression tests exercise the real publisher against in-memory
storage and the real Bash deployment script with fake `gcloud`/`uv` executables.
They cover same-source rebuilds, repeat publication, preservation of historical
releases, digest pinning between steps, missing/invalid digests, failed builds and
missing or inconsistent local records. The fake commands make no cloud calls.

An older checkout has no target record or a schema-1/2/3 record: run
`bash cloud/deploy.sh build` before using the updated `publish`/`pipeline`
commands. Previously published releases remain usable through their existing
URI and the direct `cloud.pipeline` CLI. Direct runs without `--release-target`
produce data-validation evidence only; the updated `app` requires a bound run.
The new record describes one current build; preserve it with run evidence before
rebuilding, and execute these commands serially in a checkout. Cloud Build logs
remain available in the Cloud Console. Actual Cloud Build JSON capture and
digest-pinned Vertex execution still require a cloud verification run.

## Build, validation and deployment binding

Review reproduced an inherited deployment gap: after pipeline A passed, building
API B and invoking `app` paired the new API tag with A's old output release.
The source-only version marker also could not distinguish two builds of the same
source with different API image contents.

The build record now includes the Cloud Build ID and both image digests. At the
start of a real run, `cloud.pipeline --release-target=...` loads a fixed copy and
checks that its workflow image and input release match the submitted parameters.
Only a successful job, a passing report and the matching processed output can
produce `artifacts/cloud/validated_deployment.json`. This atomic record contains:

- `schema_version: 1` and `status: PASSED`;
- the complete `build_target` snapshot, including build ID, source version,
  unique image tag, workflow/API images, input-file hashes, data fingerprint and input release;
- `project`, `region`, `pipeline_job` and `validated_release_uri`.

A build change detected while the pipeline is running prevents this record from
being issued. Starting another build or pipeline clears the current record and
legacy success markers before target/dependency checks. The Python entry point
also clears them for direct runs; compile-only preserves existing evidence.

`cloud.release deployment` compares the entire saved build target with the
current one, checks project/region and requires a passing record with a job and
output URI. `cloud/deploy.sh app` performs this check before calling Cloud Run,
then takes both the API digest and output release from that checked binding.
An old `validated_release.txt` or a mutable API tag cannot select deployment inputs.

Regression checks run the real compiler, validation-record writer and deployment
script, replacing external calls only. They cover A-to-B rebuilds with identical
source versions, restored old success records, changed API digests, malformed or
missing records, wrong project/region, SDK wait failures, target-resolution
failure, in-flight build changes and successful deployment arguments.

This establishes which build the successful data pipeline belongs to. The data
pipeline does not execute the API image; real API startup and endpoint tests
remain necessary after deployment. The workflow and API Dockerfiles include
`cloud/release.py`, which supplies the shared publication-file list and checks.

## Input-data hash guard

Review reproduced a first-publication gap: changing local data after a build
could publish new bytes under that build's selected release. The existing GCS
immutability check could only compare against files already uploaded. A source
version alone also omitted the Git-ignored vector snapshot.

The updated flow is:

1. Before invoking Cloud Build, hash the seven explicit paths in
   `cloud.release.FILES`: the raw DVC pointer, raw metadata, trials, criteria,
   patients, demo manifest and `index_snapshots/current.json`. This list is shared
   with the publisher and does not depend on Git tracking. A missing file stops
   the build before any cloud request.
2. After a successful build, hash those inputs again. Changed or missing files
   prevent activation of `release_target.json` and `image_version.txt`. Existing
   deployment permission has already been cleared when the new build starts.
3. Store the hashes as `input_sha256` in the schema-4 target. `data_fingerprint`
   is SHA256 over the sorted, compact JSON hash map. Include it in the release
   address so changing only the ignored snapshot produces a distinct release
   even if the source version and workflow image digest stay the same.
4. Before publication, copy all seven inputs into a temporary directory and check
   the copies against the target. No GCS calls occur until every file passes.
   Upload those same copies so later edits to the original files cannot change
   what is published. Temporary files are removed on success and failure.
5. For a real bound pipeline run, check the GCS input manifest's schema, image
   and complete hash map against the target before Vertex submission. Each task
   still verifies its downloaded bytes. The process step also checks reproduced
   output against the input hashes before publishing. Compile-only stays offline.
   The successful deployment record carries the complete target, including these
   data fields, and deployment must match it.

Regression tests cover unchanged/repeated publication; modification and deletion
of each input before first publication; ignored-snapshot changes; malformed
hash records; mutation during a simulated build and during upload; preservation
of earlier releases; and mismatched cloud manifests stopping before submission.
No real GCS objects or running services are changed by these tests.

To use the updated commands, restore the fixed index snapshot before `build`.
On a hash mismatch, restore the original input or rebuild with the intended
data; a rebuild does not guarantee the data will pass the later semantic and
snapshot-compatibility checks. Existing schema-1 GCS releases keep their format
and remain readable. Local schema-1/2/3 build targets require a rebuild. Legacy
direct publication without `--release-target` has no build binding; the supported
deployment flow passes the target and verifies it again before submission.

## Unique build tags in an immutable repository

Review found that `cloud/setup.sh` creates Artifact Registry with immutable tags,
while `cloud/build.yaml` originally tagged images only by source version. A
rebuild of the same source producing a different image digest could be rejected
by the registry before a new release target was recorded. Adding digests to GCS
release addresses did not resolve that earlier image-push conflict.

The corrected Cloud Build YAML uses `${_VERSION}-${BUILD_ID}` for both Docker
build arguments and the published image list, for API, workflow and Chroma.
`BUILD_ID` is supplied by Cloud Build for each build. The source hash stays in
`source_version` and `image_version.txt`; the schema-4 target additionally stores
`image_tag`. Target validation requires that tag to equal the source version plus
the recorded build ID. Build-result parsing only accepts API/workflow image names
with that exact tag and valid digests. Source-only tags and other-build tags fail.

Pipeline and API deployment continue to use pinned digests. `database` resolves
the saved tag before making cloud calls and uses it when creating the Chroma VM;
an existing VM is left unchanged. Repository immutability remains enabled.
The GCS release address and manifest format are unchanged by this correction.

The deployment-script tests now load the actual Cloud Build YAML, expand the
source version and simulated build ID, check build/push image names agree, and
enforce a simulated immutable registry. Two builds of identical source with
different API, workflow and Chroma digests receive distinct tags, and all earlier
tag mappings remain unchanged. Additional checks cover exact build-result tags,
stale target rejection, Chroma creation with an existing published tag, and
skipping an existing VM. These are local simulations; actual Cloud Build
substitution and registry pushes remain part of the GCP verification run.

## Scope after review

This change contains the three core reliability protections, the targeted
release-identity, unique build tags, deployment-binding and input-data hash fixes, regression tests, CI and supporting
documentation. The build/validation records supply and check deployment inputs; the
broader automatic build/run audit manifests remain deferred.

The data-change and immutable-tag findings are fixed in local tests. Actual
Cloud Build, Vertex and API execution of these changes remains to be verified.

## Still to verify in GCP

No cloud job, DVC download, image build/upload or deployment was performed in
this integration check. The user previously provided the successful 2026-10-28
run's console screenshots, reports, image details and build source archive for
handoff verification. Those records cover Yixiao's earlier build, rather than
the newer container configuration or these reliability fixes.

After building the updated workflow image, verify actual bucket/IAM access,
a complete run with the stored Gemini snapshot, and upstream-failure behavior
on Vertex using a separate invalid-input release. Record job IDs, logs and
outputs separately from these local tests. Training/evaluation integration with
B and C remains a later step.
