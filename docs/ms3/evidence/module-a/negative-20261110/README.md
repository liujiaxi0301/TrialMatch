# November 10: cloud checksum-failure verification

**Independent evidence review: PASSED.** Xuyang ran the isolated test in Cloud
Shell. Twenty offline evidence checks independently confirmed the actual input
fault, the cloud exception and all three blocked downstream tasks.

The final conclusion is in [audit.json](audit.json) and
[review-status.json](review-status.json). The earlier [preflight](preflight.json)
and [screenshot observation](run-observation.json) are historical preparation and
intermediate records; their pending statuses are not the latest review status.

## Actual cloud result

| Item | Verified evidence |
| --- | --- |
| Pipeline job | `xuyang-ms3-hash-20261110t193643z-65e00490` |
| Project / region | `trialmatch-ac215-yixiao` / `us-east1` |
| Execution (America/New_York, EST) | November 10, 14:36:45–14:39:30; approximately 2 min 45 sec |
| Pipeline state | `PIPELINE_STATE_FAILED`, as expected |
| `fetch-raw` | `FAILED`; actual CustomJob `6958957732422483968`; worker exited with status 1 |
| `process-trials` | `NOT_TRIGGERED`; no start time or executor job |
| `validate-data` | `NOT_TRIGGERED`; no start time or executor job |
| `retrieve-trials` | `NOT_TRIGGERED`; no start time or executor job |
| Specific exception | `ValueError: Checksum mismatch: services/trial_ingestion/data/raw.dvc` |
| Log export | 16 entries for the actual fetch CustomJob, no pagination truncation reported |

[Open the negative run](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/xuyang-ms3-hash-20261110t193643z-65e00490?project=trialmatch-ac215-yixiao).

This is a successful **negative test**: the intentionally corrupted input caused
the pipeline to fail and prevented downstream execution. A generic permission or
network failure would not establish that result. The exact checksum exception is
present in [the worker logs](raw/fetch-logs-0.json), independently of the runner's
own `PASSED` verdict.

The ERROR entries are traceback lines for this failure, not thirteen separate
failed experiments. Their log timestamps extend beyond Vertex's node end time;
the error is attributed by the exact executor job ID and concrete file name.
The first collection attempt waited for the log evidence. No cause is inferred
for the timestamp difference.

## Fixed baseline and isolated fault

The test reused the reviewed successful run
`trialmatch-data-pipeline-20261110055153`, recorded source
`6cae15b387cb4de2e344b49864b68f7d0b24ab6a`, and image:

```text
us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch/workflow@sha256:452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad
```

All four task definitions and dependencies match the positive baseline. Caching
is disabled for every task. The test release and output root are isolated under:

```text
gs://trialmatch-ac215-yixiao-ms3/negative-tests/xuyang/xuyang-ms3-hash-20261110t193643z-65e00490/
```

The original `raw.dvc` is 106 bytes; the damaged copy is 107 bytes, exactly one
additional newline. The test manifest changes only this file's URI and retains
the original expected hash. The other six file entries are unchanged.

| Bytes | SHA256 |
| --- | --- |
| Original, still expected by manifest | `5246c092e13ba7c41fbc2419e4760966cb6bf882b8b1abddc1a64ec7f3c5e6e9` |
| Damaged test copy | `e848b176ac64bf1c8e676f52e5dd3611ce3523e76369d9db4ca52f8ca3641fff` |

Upload responses and subsequent generation-pinned readback records agree on the
two test objects' locations, generations, sizes and MD5. The exported SHA256
values also match the actual archived bytes. The reviewed helper uses create-only
preconditions and does not update original releases or existing deployments.

Vertex reserved one `raw` output artifact in `PENDING` state for the failed task.
That metadata record is not a produced dataset. The three downstream tasks have
no output metadata, start times or executor jobs.

## Preserved files and audit

[raw/](raw/) contains all 17 files from the upload, byte-for-byte unchanged:

- `plan.json`, `baseline-job.json`, `baseline-release.json` and original `raw.dvc`.
- Damaged file/manifest, upload records and cloud readback records.
- Submission attempt/response, final Vertex job, fetch logs and runner result.
- `runner.py` and the original inventory of 16 payload-file hashes.

All original inventory entries match. Uploaded `runner.py` matches both the
preflight source hash and the locally reviewed script; it was not executed during
this audit. A common credential-literal scan found no private keys or access tokens.

Uploaded archive: `ms3-negative-20261110.tar.gz`, 19,286 bytes.

SHA256: `d7447062010f7d318ecbb719c34c5e0fc5a57557b225698cf18b009cbd874acf`.

## Scope and remaining work

This proves **one real cloud checksum-rejection case and downstream blocking**
for the recorded image and DAG. The experiment submitted the Vertex specification
directly. It did not test Python-runner success-marker cleanup, deployment-shell
behavior, missing files, schema errors, model training or formal scoring.

The cloud run was performed by Xuyang; this review used exported API records and
logs rather than making new authenticated cloud calls. No additional job was
submitted during the review. The runtime-graph and checksum-error screenshots
were reviewed in chat and match the archived records. The original
[runtime-graph PNG](02-checksum-failure-test.png) was supplied and archived on
November 12; the separate checksum-error image is still not archived. The exact
exception remains available in the worker logs. Earlier review JSON files retain
their original screenshot-availability notes; the current image is recorded in
the [November 12 inventory](../screenshots-20261112.json).

## Presentation

Use the graph and error line together, under **Failure Handling: Invalid Data
Stops the Pipeline**. The graph shows the matching run name, a red `fetch-raw`,
three grey descendants and a duration of 2 min 45 sec. The archived worker log
contains the exact checksum exception at 14:40:05.927 EST. Open that log alongside
the [graph image](02-checksum-failure-test.png); the earlier error-line image was
reviewed in chat but is not part of this upload.

Label the outcome **1 failed, 3 not triggered**. The console also shows
`3/4 steps completed`; that counter is not evidence of three successful task
executions. The explicit API states remain FAILED / NOT_TRIGGERED.

Suggested explanation:

> We added one byte to an isolated data copy while keeping its expected checksum.
> Vertex rejected the input in fetch-raw and left all three downstream steps
> untriggered, preventing invalid data from reaching later stages.

Reproduction and recovery instructions are in
[module-a-cloud-failure.md](../../../module-a-cloud-failure.md). B/C integration
remains a separate team deliverable. Changes to the image or DAG need their own
verification; this result is not automatically evidence for a later version.
