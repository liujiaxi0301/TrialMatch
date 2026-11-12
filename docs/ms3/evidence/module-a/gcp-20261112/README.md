# November 12 integrated Vertex run: scoring blocked

Pipeline `trialmatch-data-pipeline-20261112172151` ran at source
`96a1ab99463f8e3363a6b4f74a1b1eeb2df4fa59` in `us-east1`, project
`trialmatch-ac215-yixiao`. The exported Vertex record reports
`PIPELINE_STATE_FAILED`, with six successful tasks and one failed task.

[Open the original Vertex run](https://console.cloud.google.com/vertex-ai/locations/us-east1/pipelines/runs/trialmatch-data-pipeline-20261112172151?project=trialmatch-ac215-yixiao).

The original [runtime-graph PNG](03-training-evaluation-blocked.png) is archived
unchanged from the November 12 screenshot upload. It shows the same run ID,
six green tasks, the failed evaluation node and 40 min 42 sec duration. See the
[gallery and captions](../screenshots.md) and [image inventory](../screenshots-20261112.json).

| Task | Recorded state |
| --- | --- |
| `fetch-raw` | SUCCEEDED |
| `process-trials` | SUCCEEDED |
| `validate-data` | SUCCEEDED |
| `retrieve-trials` | SUCCEEDED |
| `train-encoder` | SUCCEEDED |
| `retrieve-finetuned` | SUCCEEDED |
| `evaluate-retrieval` | FAILED: ten unjudged query/trial pairs |

Training used batch size 8 and one T4. Its manifest records 934.6 seconds of
training and online [W&B run kv0ifsun](https://forge.coreweave.com/wandb/jennyyang-harvard-university/trialmatch-ms3/runs/kv0ifsun).
The following ranking task produced 48 rows for eight queries and six methods,
with configuration and checksums bound to this run's checkpoint and data release.
The W&B URL was recorded in the evidence; access to the live page was not checked
as part of the offline review.

The scorer raised `UnjudgedResults` and saved `unjudged_pairs.json`. No scoring
CSVs or scoring success manifest were produced. The collector's three missing-file
errors refer exactly to those expected-but-unproduced outputs, not additional
training or retrieval failures. Offline recomputation of label coverage reproduced
the exact ten-pair diagnostic without inventing labels or inspecting held-out scores.

[review.json](review.json) records 44 offline consistency checks against the
uploaded archive and fixed repository sources. All 48 files listed in the original
archive's checksum manifest matched. Checkpoint weight bytes were not included or
downloaded during this review; their manifest identity was checked, and the cloud
ranking task recorded success after its own checkpoint verification.

[raw/](raw/) contains selected original records copied without modification.
[inventory.json](inventory.json) identifies their SHA256 values and the original
uploaded archive. It does not claim to contain the full training/build logs or
model weights. No uploaded collector code was executed to perform this review.

For the selected MS3 evaluation, use the [historical report and reproduction
guide](../../../submission-evidence.md), which uses Jenny's November 10 checkpoint
and C's original 182-label version. The November 12 run remains failed, and its
checkpoint has no completed benchmark scores. This run also contains no eligibility
task and performs no API deployment.
