# MS3 Submission Evidence

Decision recorded November 12, 2026 (ET): present C's completed retrieval
evaluation using its original saved rankings, 182 reviewed judgments and model
provenance. Keep the later seven-task cloud run as a separate integration record.
No additional training or labeling is required to reproduce the selected report.

The [Vertex screenshot gallery](evidence/module-a/screenshots.md) contains the
three original console images supplied on November 12, with run IDs, captions
and links to the corresponding exported records.

## Selected evidence

| Component | Evidence to open | What it establishes |
| --- | --- | --- |
| Encoder training | [Jenny's November 10 evidence](evidence/module-b/2026-11-10/README.md), [W&B run](https://forge.coreweave.com/wandb/jennyyang-harvard-university/trialmatch-ms3/runs/26xhkrre) | Successful Vertex training with its recorded configuration and checkpoint; the reproduction run is archived separately in the same directory. |
| Retrieval evaluation | [C's report](../../evaluation/ms3/retrieval/RETRIEVAL_EVALUATION_REPORT.md), [scorer and README](../../evaluation/ms3/retrieval/README.md) | 14 saved methods, eight queries and 182 judgments; P@3, nDCG@5 and four fine-tuning comparisons for those saved inputs. |
| Automated workflow | [November 10 four-task Vertex evidence](evidence/module-a/gcp-20261110/README.md) | Successful fixed-data reproduction, validation and BM25/Gemini ranking generation at its recorded source/image version. |
| Failure handling | [Checksum rejection evidence](evidence/module-a/negative-20261110/README.md) | Corrupted input fails at fetch and blocks the three downstream tasks. |
| Deployed API | [Cloud app](https://trialmatch-15733748057.us-east1.run.app), [response screenshot](evidence/cloud-screening.jpg), [API and monitoring guide](API_MONITORING.md) | November 12 revision `trialmatch-b7738f4`: Gemini and Fine-tuned BioClinical each returned three candidates with OK and no recorded errors. |
| Later integration | [November 12 seven-task evidence](evidence/module-a/gcp-20261112/README.md) | Six tasks succeeded; evaluation rejected ten unjudged pairs. The overall run is FAILED and has no retrieval scores. |

The app now offers Gemini and the evaluated November 10 encoder for retrieval;
Gemini handles criterion assessment in both choices. The online response above is
separate from benchmark reproduction. Staff need an approved IAP Google account
or an agreed authenticated demonstration; team access alone does not establish TF access.

## Model and result identities

The fine-tuned methods in the selected report use:

```text
gs://trialmatch-ac215-yixiao-ms3/training/train-20261110-t4-r3/model
SHA256: 7dcec7d9c8ca3697ee60091346723130ebb37263254e81a69a0aff038dbc931c
```

The checkpoint URI and digest match both Jenny's archived training manifest and
C's saved `retrieval_runs.config.json`. C's bundle was imported unchanged from
`jiaxi/ms3-evaluation` commit `da3129766e77e35a646740ad0753bd90ebc6b0c4`.
Its 14 methods consist of ten Jenny handoff methods and four legacy baselines;
the report preserves the different source groups and historical provenance.

The November 12 checkpoint has aggregate SHA256
`7dd900ba458da9156de2fdac75e9bce934839e7169d81135f4225cc4aae18f98`.
Do not associate the selected report's metrics with this checkpoint or with
pipeline `trialmatch-data-pipeline-20261112172151`.

## Reproduce the selected report without cloud access

From the repository root, with Python 3.12 available:

```bash
MS3_REPORT_DIR="$(mktemp -d)"
python3 evaluation/ms3/retrieval/evaluate_retrieval_complete.py \
  --output-dir "$MS3_REPORT_DIR/results"
python3 -m unittest discover \
  -s evaluation/ms3/retrieval/tests -p 'test_*.py' -v
```

The scorer uses only the Python standard library and committed files. It does
not download a model, call an LLM, train, or submit a cloud job. Use a fresh output
directory on each invocation; the scorer refuses to overwrite existing outputs.
Do not run `cloud.pipeline` or regenerate rankings to reproduce this report.

Expected files in the new `results` directory:

| File | Expected contents |
| --- | --- |
| `ms3_retrieval_all14_per_query.csv` | 112 method/query rows |
| `ms3_retrieval_all14_summary.csv` | 42 method/scope rows |
| `ms3_retrieval_finetune_deltas.csv` | Four frozen/fine-tuned comparisons |
| `ms3_retrieval_evaluation_manifest.json` | Input hashes, label version and scoring protocol |

[Reproduction verification](evidence/module-a/retrieval-reproduction-20261112.json)
records all four files matching the committed originals byte-for-byte, all 30 C
files unchanged from the source commit, matching historical checkpoint identities,
and six passing C tests. The check compared bytes and schemas automatically; it
did not manually inspect held-out scores or assign new labels.

## Presentation scope

Show the historical model's W&B record with its matching evaluation report, and
the successful four-task Vertex run with its own run ID. The later seven-task
run is separate: training and ranking succeeded, but scoring intentionally
stopped because ten pairs were outside the judged pool. No missing judgment was
converted to relevance zero, and historical rankings were not substituted into
that run to make it pass.

The ten-pair review package remains available outside the submission code for
future completion. Reusing the November 12 rankings after reviewed labeling would
require a new frozen label version and scoring provenance. Comparisons across
models must use the same label version because nDCG's ideal ranking may change.
The earlier failed Vertex run must retain its original status.

The course requires documented training, a running service/API, an automated
Vertex workflow and monitoring. This document selects the existing evaluation
evidence; it does not certify that every team deliverable or TF access check is
complete. Preserve each contributor's commits in the final `milestone3` branch.
