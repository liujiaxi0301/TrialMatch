# November 10 four-step Vertex pipeline: evidence review

**Artifact consistency: PASSED. Evidence collection: PARTIAL.** The exported
Vertex API record shows that the pipeline and its four container tasks succeeded.
Twenty offline consistency checks passed. The runtime-graph screenshot was
subsequently reviewed in chat: the run ID matches, all four nodes are green and
the header shows `4/4 steps completed`. Its original image file is not yet
available in this checkout for archiving. The subsequent `retrieve-trials` JSON
log export has now been verified and archived: 11 entries match the exact job,
release and outputs. Logs from the other three nodes remain uncollected; see
[audit.json](audit.json) and [review-status.json](review-status.json).

This is a review of the cloud records exported through Xuyang's authenticated
Cloud Shell. No new cloud job, deployment, or direct authenticated cloud query
was performed during this review. Uploaded collector code was compared with the
prepared original, not executed.

## What ran

`fetch-raw -> process-trials -> validate-data -> retrieve-trials`

| Record | Verified value |
| --- | --- |
| Project / region | `trialmatch-ac215-yixiao` / `us-east1` |
| Pipeline run | `trialmatch-data-pipeline-20261110055153` |
| Result | `PIPELINE_STATE_SUCCEEDED`; all four named tasks `SUCCEEDED` with CustomJob references |
| Execution time (UTC) | November 10, 05:51:55–06:04:51 |
| Source commit recorded by build and container | `6cae15b387cb4de2e344b49864b68f7d0b24ab6a` |
| Cloud Build | `f6edb1ef-dbb1-4389-b014-9b7f1b48ff82`, `SUCCESS` |
| Source version | `2c8b5da003025134` |
| Workflow image digest | `sha256:452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad` |
| Data validation report | `PASSED`; 1,313 trials, 18,456 criteria, 25 patients, 607 vectors; offline smoke `OK` |
| Retrieval output | 48 records: 8 queries × 6 BM25/Gemini methods; five unique trial IDs per record, all within the fixed 50-trial universe |

[Open this Vertex run](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261110055153?project=trialmatch-ac215-yixiao).

This run supports data reproduction, validation and BM25/Gemini ranking generation.
It does not establish trainable-model training, human-reference benchmark scores,
clinical validation, a negative-input cloud test, or a new API deployment.
Ranking review checked schema, IDs and coverage only; no held-out relevance
judgements were inspected or metrics calculated.

## Versions and attribution

Yixiao supplied the integrated infrastructure/retrieval run. Xuyang collected and
reviewed its evidence after synchronizing `yixiao/ms3-infra` into the local
`xuyang/ms3-pipeline` branch. The run includes the earlier Module A reliability
work, Jenny's committed retrieval work and Jiaxi/Jessie's fixed query protocol.

The local branch and separate [GitHub Actions result](github-actions.json) are at
`50dc2ca0e5ff8a7a932ff96a126d3575e7f156ef`, where 47 tests passed. The cloud run
records `6cae15b`, not `50dc2ca`. Git shows only `README.md`,
`services/frontend/app.py` and `services/frontend/static/app.js` changed between
those commits; pipeline code and dependencies are unchanged.

The build's `_SOURCE_COMMIT` and retrieval config's `code_commit` agree. The
Cloud Build source tarball was not downloaded or compared byte-for-byte with
Git, so this is corroborated recorded provenance, not proof of a clean build
checkout. The November 5 run remains separately archived in
[gcp-20261105](../gcp-20261105/README.md).

## Input and output handoff

**Input release:**

```text
gs://trialmatch-ac215-yixiao-ms3/releases/2c8b5da003025134/452cc045ae11c1e42d8f7071cdae565f79e1b57aa9924b3d26c2140ad89a62ad/c8627e7addd3d265a61eb137d28691c545b4786b321e9e1981a9035e748e2125/release.json
```

**Validated output release:**

```text
gs://trialmatch-ac215-yixiao-ms3/pipelines/15733748057/trialmatch-data-pipeline-20261110055153/process-trials_6552156984404082688/processed/release.json
```

**Rankings directory:**

```text
gs://trialmatch-ac215-yixiao-ms3/pipelines/15733748057/trialmatch-data-pipeline-20261110055153/retrieve-trials_-2671215052450693120/rankings/
```

The rankings directory contains `retrieval_runs.jsonl` and
`retrieval_runs.config.json`. The latter binds the rankings to the processed
release, query-file hash, source data hashes and retrieval settings.

## Checks and preserved files

- [raw/](raw/) preserves all 16 files from the upload without modification,
  including its original `PARTIAL` summary and four empty log-query responses.
  All 15 entries in its [inventory](raw/inventory.json) match their SHA256 values.
- Six downloaded GCS objects match recorded sizes, SHA256 and MD5. Their object
  generations are preserved in [gcs-objects.json](raw/gcs-objects.json).
- Both release manifests list the same seven files and hashes. Six Git-tracked
  files also match the run commit. Cloud source data and ignored vector snapshot
  bytes were not re-downloaded; vector restoration/count evidence comes from the
  validation report.
- Task artifact URIs connect the four nodes. The validation and retrieval records
  reference this exact run's processed release and agree on source hashes.
- Exactly one build matched the workflow digest, recorded commit and execution
  chronology among the nine returned build records; no further page was reported.
- [compiled-pipeline.yaml](compiled-pipeline.yaml) was regenerated locally from
  `6cae15b` with the run's image and project parameters using `--compile-only`.
  It is not an exported submission file. It matches the cloud specification after
  accounting only for the SDK disabling four cache defaults and the API adding
  an identical typed `deploymentConfig` alias. The runtime path explicitly sets
  `enable_caching=False`; all four tasks executed.
- A scan found no common access-token or private-key literals in the archive.

Uploaded archive SHA256:
`2eb649539e1c348206d6a6d005170d56dc0e0d62dc3f6339110894f9e8d45b89`.

## Supplemental retrieval log export

[supplemental/retrieve-trials-logs.json](supplemental/retrieve-trials-logs.json)
preserves the uploaded `downloaded-logs-20261110-141610.json` without modification.
Its SHA256 is `fa3c98a4a74a2e689859b18834e64f0751f36e27a89064f9c1d88663aa139b1b`.
[The supplemental review](supplemental/retrieve-trials-review.json) passed nine
checks: all 11 entries belong to project `trialmatch-ac215-yixiao`, monitored
resource `ml_job`, and CustomJob `5535151747103719424`, which is the retrieval
executor recorded in `raw/vertex-job.json`.

The log confirms the exact processed release and seven verified files; eight
queries, six methods and 48 rows; the expected rankings output directory; and
successful CustomJob completion. Four application events occur within the node's
execution interval. Later service teardown and success messages extend to
01:07:16 EST (06:07:16 UTC), after the node end timestamp. These are separate
service lifecycle events, and no application output is outside the node interval.
All exported entries have INFO severity; this says nothing about unexported logs.

The original archive's `PARTIAL` summary and empty log responses remain unchanged.
The new log export supplements them. Four-node success was already established by
the Vertex job record; collecting every node's logs is not a prerequisite for
that conclusion or a reason to rerun the successful pipeline.

## Remaining evidence

1. Archive the original PNG/JPG of the screenshot already reviewed in chat. It
   shows the matching run name, four green nodes and 12 min 56 sec duration.
   Displayed times, November 10 00:51:55–01:04:51 America/New_York, agree with
   05:51:55–06:04:51 UTC in the exported job. No image file is currently saved here.
2. The retrieval log export is complete. Full Logs Explorer showed 11 results with
   `resource.type="ml_job"` and `resource.labels.job_id="5535151747103719424"`,
   matching the exported retrieval CustomJob. The original collector incorrectly
   filtered on `aiplatform.googleapis.com/CustomJob` as the monitored resource
   type. All 11 entries are now archived in the supplemental directory.
   The observed query/time range is recorded in `review-status.json`; the
   original empty responses are preserved.
3. Optionally complete the log collection for `fetch-raw`, `process-trials` and
   `validate-data` with [one query](supplemental/remaining-node-logs.lql).
   Its three job IDs come from the actual Vertex task metadata. Paste it into
   Logs Explorer and export the returned entries as JSON. Retrieval logs do not
   establish these other nodes' log contents. Preserve original screenshots as
   files when available; neither image is currently saved in this checkout.

Service log messages such as `Waiting for training program to start` are generic
CustomJob lifecycle messages. The observed application outputs establish
retrieval execution, not trainable-model training. The retrieval screenshot is
cropped: its node name, timestamps and output count agree with the previously
reviewed run, but that initial cropped image does not display the run ID or query.
The later full Logs Explorer screenshot supplies the matching CustomJob ID and query.

A separate local collector copy now queries `ml_job`; the original uploaded
collector remains unchanged in `raw/`. A fake API matching the observed query
reproduced the old collector's `PARTIAL` result, then all seven offline tests
passed after the correction. The corrected collector has not been run against
GCP, and its passing local tests do not replace a real log export.

No pipeline rerun is needed merely to retrieve these existing records. Broader
Module A work still includes a separate negative-input cloud check and integration
with B's training and C's formal scoring when their callable entry points are ready.
