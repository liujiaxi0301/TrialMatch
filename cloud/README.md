# Cloud workflow

Deployment commands and credentials are in the [project README](../README.md#cloud-deployment-and-pipeline).
This guide covers the optional training and evaluation tasks in `pipeline.py`.

## Pipeline and artifacts

The default Vertex pipeline restores the pinned raw trials, processes them,
validates source/output hashes and produces BM25/Gemini retrieval rankings.
Tasks exchange versioned artifacts through GCS; task caching is disabled.
`release.py` binds deployment inputs to image digests and file checksums.

```text
fetch-raw -> process-trials -> validate-data -> retrieve-trials
                                  |
                                  +-> train-encoder -> retrieve-finetuned -> evaluate-retrieval
                                  |
                                  +-> evaluate-eligibility
```

The last two lines are optional. Training produces a checkpoint and manifest;
retrieval verifies that checkpoint and writes rankings/configuration; scoring
writes metrics or an explicit list of unjudged query–trial pairs. Eligibility
assessment uses its own fixed patient–trial cases, independently of retrieval.
Completed training does not imply that scoring passed or that the model is better.

| Option | Behavior |
| --- | --- |
| `--trainer-image IMAGE@sha256:...` | Train an encoder on a T4 after data validation. Corpus pairs are generated from the validated release. |
| `--trainer-batch-size 8` | Batch size verified for the existing T4 configuration. |
| `--train-pairs URI ...` | Add pair files from GCS; each requires a matching `--train-pairs-sha256` in the same order. |
| `--wandb-secret projects/.../secrets/wandb-api-key/versions/latest` | Read the W&B key through Secret Manager. Confirm online tracking in the output manifest. |
| `--finetuned-retrieval-image IMAGE@sha256:...` | Consume this pipeline's trained checkpoint with a separate CPU retrieval image; requires training. |
| `--retrieval-evaluation` | Score the new rankings against the frozen benchmark; requires fine-tuned retrieval. |
| `--eligibility` | Assess the fixed eight patient–trial pairs after validation. |
| `--eligibility-model MODEL` | Select the Gemini model for that assessment. |
| `--compile-only` | Write the pipeline specification without submitting a paid job. |

## Submit or compile

Build images through `cloud/deploy.sh build` and the trainer/retrieval Cloud Build
configurations under `docker/`. Pass the resulting immutable digests, not mutable
tags. The workflow image contains the frozen benchmark bundle.

```bash
uv run --project docker/workflow --locked python -m cloud.pipeline \
  --project trialmatch-ac215-yixiao --region us-east1 \
  --bucket trialmatch-ac215-yixiao-ms3 \
  --image "$WORKFLOW_IMAGE" --release "$RELEASE_URI" \
  --trainer-image "$TRAINER_IMAGE" --trainer-batch-size 8 \
  --wandb-secret projects/trialmatch-ac215-yixiao/secrets/wandb-api-key/versions/latest \
  --finetuned-retrieval-image "$RETRIEVAL_IMAGE" --retrieval-evaluation \
  --compile-only
```

Set the four variables to the build digests and published release URI first.
Remove `--compile-only` to submit. Google credentials, project access, T4 quota
and the pipeline service account's storage/Vertex/secret permissions are required.
The root deployment wrapper also accepts pipeline options:
`bash cloud/deploy.sh pipeline --compile-only`.

## Validation and model identity

- Raw DVC hashes, processed-file hashes and the trial manifest must match the release.
- All 50 benchmark trials are excluded from training pairs. Added pairs must match
  the reviewed expected hashes; duplicated inputs and hash mismatches fail validation.
- Retrieval verifies actual checkpoint files against the training manifest. Model,
  revision and dimension identify separate collections; incompatible vectors are not mixed.
- `retrieval_benchmark.json` pins the scorer, queries and 182 labels. Missing judgments
  fail scoring rather than being counted as irrelevant. A new checkpoint may need
  new labels even if an older checkpoint was evaluated successfully.
- The web app still selects the evaluated November 10 checkpoint described in the
  [training guide](../docs/training/README.md). Submitting a pipeline does not switch it.

Cloud regression tests cover input integrity, task dependencies, frozen evaluation
inputs and failure handling. They run in GitHub Actions without paid model calls:

```bash
uv sync --project docker/workflow --locked --python 3.12
docker/workflow/.venv/bin/python -m pytest --import-mode=importlib \
  cloud/tests --ignore=cloud/tests/test_retrieval_runtime.py -k 'not PoolingTests'
```

Historical cloud screenshots, build records and the November 12 scoring failure
are preserved in the [MS3 submission](https://github.com/liujiaxi0301/TrialMatch/tree/milestone3/docs/ms3/evidence).
New run outputs belong in GCS and ignored `artifacts/`, not in the source tree.
