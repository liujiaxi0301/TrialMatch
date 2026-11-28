# Serving encoder and training

The app's fine-tuned retrieval option uses the evaluated checkpoint
`train-20261110-t4-r3`, not the last model produced by any later pipeline.
[training_manifest.json](training_manifest.json) preserves its original model
files, hashes, training inputs, configuration, image digest and W&B run.

| Item | Value |
| --- | --- |
| Base encoder | `thomas-sounack/BioClinical-ModernBERT-base` |
| Revision | `c3648aa87af95837c809e6f0c5f85d08160db437` |
| Output | 768 dimensions, masked mean pooling, L2 normalization |
| Checkpoint | `gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model` |
| SHA256 | `7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c` |
| Vertex job | `8919501313956380672`, `us-east1` |
| Training | One T4, 3 epochs, batch 8, learning rate 2e-5, seed 0, FP16 |
| Loss | InfoNCE; in-batch positives and up to four mined hard negatives |
| Pairs | 5,137 training / 476 validation; all 50 benchmark trials excluded |

Pairs combine corpus templates and LLM-generated questions. They are not expert
labels. [W&B](https://forge.coreweave.com/wandb/jennyyang-harvard-university/trialmatch-ms3/runs/26xhkrre)
tracks the successful run. The internal validation set contains 386 queries and
1,046 training-corpus passages; it is separate from the retrieval benchmark.

| Checkpoint | Validation loss | Recall@10 | MRR@10 |
| --- | ---: | ---: | ---: |
| Frozen base encoder | 3.348 | 0.249 | 0.147 |
| Epoch 1 | 0.964 | 0.782 | 0.477 |
| Epoch 2 | 0.948 | 0.802 | 0.514 |
| Epoch 3 (saved) | 0.999 | 0.802 | 0.488 |

The saved model is the last epoch, not the best validation epoch. External retrieval
results and limitations are in the [benchmark report](../../evaluation/ms3/retrieval/RETRIEVAL_EVALUATION_REPORT.md).
Neither benchmark establishes clinical accuracy.

## Reproduce the original run

Use the frozen pair files and original trainer digest. Current pair generators
may differ, so regenerating inputs is a new experiment.

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/secrets/google-credentials.json"
export GOOGLE_CLOUD_QUOTA_PROJECT=trialmatch-ac215-yixiao
uv run --project docker/workflow --locked python -m cloud.train_job \
  --image us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch/trainer@sha256:97c872638eabbf681d020d6bb1c1f534a707e3798b997d57ad435d7bd964fea9 \
  --pairs gs://trialmatch-ac215-yixiao-ms3/training/pairs/20261110/pairs.jsonl gs://trialmatch-ac215-yixiao-ms3/training/pairs/20261110/pairs_llm.jsonl \
  --batch-size 8 --evidence artifacts/training/reproduction
```

Run from the repository root with uv, ADC credentials and T4 quota. A new run ID
is generated automatically. Add `--dry-run` to inspect the job without submitting.
The pipeline service account needs access to the `wandb-api-key` secret; check
`experiment.mode=online` in the manifest, since missing W&B access can fall back
to offline tracking. The historical image does not support newer pipeline input
hash flags; use current images for the [integrated pipeline](../../cloud/README.md).

Original screenshots, failed-attempt records and the independent reproduction
remain in the [MS3 archive](https://github.com/liujiaxi0301/TrialMatch/tree/milestone3/docs/ms3/evidence/module-b/2026-11-10).
