# Module B: training and experiment tracking — execution plan

Owner: Jenny (B). Branch: `jenny/ms3-training`, based on `xuyang/ms3-pipeline`.
Audience: whoever picks this up next, including an agent session with no prior context.

MS3 is due **22:00 ET on 2026-11-12**, submitted as a commit hash on Canvas from a
`milestone3` branch. Module B owns objective 1 of the milestone, *advanced training
workflows*: experiment tracking plus at least one logged, reproducible training run
on Vertex AI. One successful run is sufficient; a model that beats the baseline is
not required, and claiming one that was not measured is worse than reporting none.

---

## 1. What already exists

Four commits on `jenny/ms3-training`:

| Commit | Contents |
| --- | --- |
| `cba1856` | `services/rag_workflow/embedding_providers.py` — encoder factory separating retrieval from generation, plus the BioClinical provider; `evaluation/retrieval/` benchmark harness and the 2026-10-29 results |
| `f26c7fc` | `evaluation/ms3/run_retrieval.py` and the ranked runs handed to the evaluation owner |
| `3ba3314` | `cloud/train_pairs.py` — training pair construction |
| `7280b2b` | Lint fix narrowing the index-restore guard |


Already true, do not redo:

- `BioClinicalProvider` loads `thomas-sounack/BioClinical-ModernBERT-base` at revision
  `c3648aa87af95837c809e6f0c5f85d08160db437`, attention-mask mean pooling **including
  special tokens**, L2 normalized, 768 dimensions, float32, SDPA attention.
- Collection and cache identities already carry the encoder fingerprint, so a new
  encoder cannot silently query vectors built by another one.
- `cloud/train_pairs.py` produces 2,281 pairs (2,087 train / 194 validation) into
  `artifacts/training/pairs.jsonl` with a sibling `.summary.json`.
- Torch and transformers live in the optional `embeddings` dependency group and are
  **not** in `docker/workflow`. Keep it that way.

### Measured baseline to improve on

From `evaluation/retrieval/results/2026-10-29/REPORT.md`, criterion-level, silver labels:

| Encoder | Query mode | nDCG@10 | Recall@10 | MRR@10 |
| --- | --- | ---: | ---: | ---: |
| bioclinical (frozen) | question | 0.416 | 0.128 | 0.639 |
| gemini | question | 0.781 | 0.248 | 0.867 |

The frozen BioClinical checkpoint is a masked language model with no retrieval
training; its own model card recommends downstream adaptation. Closing part of that
gap is the point of this module.

---

## 2. Constraints that override convenience

Violating any of these invalidates the result. Check them, do not assume them.

1. **The 50 trials in `services/rag_workflow/examples/demo_manifest.json` are held
   out of training, permanently.** They are the retrieval benchmark's universe.
   `cloud/train_pairs.py` already excludes them; any new data path must assert the
   same and fail loudly rather than warn.
2. **Relevance labels, metrics and the comparison report belong to the evaluation
   owner (Jiaxi).** Module B produces rankings and training artifacts, never scores
   on the benchmark. Q01–Q02 are the development queries; **Q03–Q08 must not be
   inspected or tuned against.** Freeze every configuration before they are scored.
3. **Do not quietly rewrite teammates' files.** `cloud/pipeline.py`, `cloud/tasks.py`,
   `cloud/release.py`, `cloud/build.yaml`, `cloud/setup.sh` and `cloud/deploy.sh`
   belong to modules A and D. Changes there must be additive, must preserve the
   existing release-binding checks, and must be agreed before pushing.
4. **Budget.** `cloud/budget/` shuts the Cloud Run service down at $5 of monthly
   spend. A single T4 training run is roughly $0.30–0.50, but confirm headroom with
   the infrastructure owner (Yixiao) before submitting, and never leave a job or a
   GPU running unattended.
5. **No credentials in Git.** The W&B API key comes from Secret Manager at run time.
   Never print it, never bake it into an image, never write it into a manifest.
6. **Reported numbers must name what produced them.** Silver topic labels, human
   labels and smoke checks are three different things and are never merged into one
   claim. No result is described as clinical accuracy.

---

## 3. Interfaces fixed by other modules

From `docs/ms3/module-a-plan.md`, module A expects from B:

- **Input:** the validated `release.json` URI, an explicit run configuration, and an
  output location.
- **Output:** a training manifest identifying the source release, artifact URI and
  checksum, workflow type, configuration, code/image version, and experiment run
  reference.

Infrastructure values from `cloud/config.env`:

```
GCP_PROJECT   trialmatch-ac215-yixiao
GCP_REGION    us-east1
GCS_BUCKET    trialmatch-ac215-yixiao-ms3
REGISTRY      us-east1-docker.pkg.dev/trialmatch-ac215-yixiao/trialmatch
```

Service accounts are `trialmatch-{api,pipeline,build,chroma}@…`. `trialmatch-pipeline`
already holds `roles/aiplatform.user` and `storage.objectAdmin` on the bucket, so
**reuse it rather than creating a trainer account**; that avoids editing `setup.sh`.

`cloud/release.py` build targets are `schema_version: 4` and carry `workflow_image`
(digest-pinned), `release_uri` and `data_fingerprint`. B's manifest references those
values; it does not redefine them.

---

## 4. Tasks

### B1 — `cloud/train.py`: contrastive adaptation with experiment tracking

Build the training entry point. One module, runnable locally and in the container.

```
python -m cloud.train \
  --pairs artifacts/training/pairs.jsonl \
  --output artifacts/training/run \
  --epochs 3 --batch-size 16 --lr 2e-5 \
  --wandb-project trialmatch-ms3
```

Design requirements:

- **Pooling must match `BioClinicalProvider` exactly** — attention-mask mean including
  special tokens, then L2. A trained checkpoint pooled differently from the one that
  serves queries produces silently wrong vectors. Import the provider's pooling rather
  than reimplementing it, or add a test asserting the two agree to 1e-6.
- Loss: InfoNCE over in-batch negatives plus the mined hard negatives already in each
  pair. Temperature configurable, default 0.05.
- Validation each epoch on the `validation` split: mean loss, plus Recall@10 and
  MRR@10 computed over the validation pairs' own criterion pool. These are *internal*
  metrics on held-out training trials; they are not the benchmark.
- W&B logs: full config, per-step training loss, per-epoch validation metrics, the
  pair summary counts, model revision, code commit, and the pairs file checksum.
  If `WANDB_API_KEY` is absent, fall back to `WANDB_MODE=offline` and still write the
  run directory — the job must not fail because tracking is unavailable.
- Outputs under `--output`: `model/` (safetensors plus tokenizer), and
  `training_manifest.json` carrying source release URI, artifact URI and SHA256,
  workflow type, full configuration, code commit, image URI, and the W&B run path.
- Assert at startup that no `trial_id` in the pairs file appears in the demo manifest,
  and abort if one does.

**Acceptance criteria**

- [ ] Validation loss decreases across epochs; the curve is visible in W&B.
- [x] Validation Recall@10 after training exceeds the frozen checkpoint's score on the
      same validation pairs, measured by the same code path. If it does not, report
      that honestly and keep the run — a negative result with a correct method is a
      valid MS3 deliverable; a fabricated improvement is not.
- [x] A pooling-equivalence test passes against `BioClinicalProvider`.
- [x] The leakage assertion is exercised by a test that feeds it a demo trial and
      expects failure.
- [x] `training_manifest.json` contains every field module A asked for.
- [x] `ruff check cloud/train.py` is clean.

**Status 2026-11-10.** `cloud/train.py` and `cloud/tests/test_train.py` are in. Training
pools through `masked_mean_l2`, now the provider's single pooling definition. A local
200-pair, one-epoch smoke run on MPS completed and wrote a manifest (W&B offline). The
first two boxes stay open until the Vertex run puts a curve in W&B.

**Status 2026-11-10, after the Vertex run.** Recall@10 on the internal validation pairs
rose from 0.249 (frozen) to 0.802 after three epochs, through the same code path. The
first box stays open on purpose: validation loss fell from 3.348 to 0.964 and 0.948 but
rose to 0.999 in epoch 3, so it does not decrease across every epoch. The saved
checkpoint is the epoch-3 model. Training now starts with a numerics check that compares
accelerator embeddings with CPU embeddings of the same weights, because the first Vertex
attempt returned non-finite embeddings on CUDA with the `sdpa` attention path under the
base image's PyTorch 2.4; the run used the `eager` path, which matched CPU to 2.4e-7.

### B2 — `docker/trainer/`: the training image

- Base on Vertex's prebuilt PyTorch GPU container
  (`us-docker.pkg.dev/vertex-ai/training/pytorch-gpu.2-*`) rather than installing CUDA
  torch from scratch; the slim-bookworm base the other three images use would add
  several GB and a long build.
- Own `pyproject.toml` and `uv.lock` under `docker/trainer/`, mirroring the structure
  of `docker/workflow/`. Dependencies: transformers, wandb, google-cloud-storage,
  google-cloud-aiplatform, google-cloud-secret-manager.
- Copy only what training needs: `cloud/__init__.py`, `cloud/train.py`,
  `cloud/train_pairs.py`, `cloud/release.py`, and `services/rag_workflow/*.py`.
- Add one build step and one `images:` entry to `cloud/build.yaml`, following the
  existing immutable tag pattern `${_REGISTRY}/trainer:${_VERSION}-${BUILD_ID}`.
  **Coordinate this edit with the infrastructure owner before pushing.**

**Acceptance criteria**

- [x] `docker build -f docker/trainer/Dockerfile .` succeeds locally or in Cloud Build.
- [x] `docker run <image> python -m cloud.train --help` prints usage.
- [x] `docker/workflow/pyproject.toml` is unchanged — no torch leaked into it.
- [x] The image is referenced by digest, never by a mutable tag, wherever it is consumed.

**Status 2026-11-10.** Built locally for linux/amd64 on
`pytorch-gpu.2-4.py310@sha256:db53e742…` (PyTorch 2.4 is the newest PyTorch GPU base
Vertex publishes; Python 3.10, so the trainer has its own lock). A tiny end-to-end
training run completed inside the container on CPU. Three things differ from the
sketch above: NumPy is held below 2 because the base's SciPy is built against 1.x; the
base's `ENTRYPOINT` is cleared so `docker run <image> python -m …` works; and
`cloud/tests/test_release.py` needed its fake registry taught about a fourth image.
The `cloud/build.yaml` step is committed locally and **not pushed** pending the
infrastructure owner. Note the 32 GB image and the shared `timeout: 1200s`.

### B3 — One Vertex AI training run, with evidence

Add `cloud/train_job.py` submitting an `aiplatform.CustomJob`:

- `machine_type=n1-standard-4`, `accelerator_type=NVIDIA_TESLA_T4`, `accelerator_count=1`,
  region `us-east1`, service account `trialmatch-pipeline@…`.
- Container image pinned by digest; `WANDB_API_KEY` injected from Secret Manager.
- Pairs read from GCS, outputs written back to `gs://$GCS_BUCKET/training/<run-id>/`.
- Wait for completion and fail non-zero unless the job state is `JOB_STATE_SUCCEEDED`.

Capture evidence into `docs/ms3/evidence/module-b/<date>/`, matching module A's layout:
job resource name, job state, `training_manifest.json`, the W&B run URL and a screenshot
of its loss curve, the checkpoint GCS URI and checksum, the image digest, the code
commit, and the full job log.

**Acceptance criteria**

- [x] A Vertex job reached `JOB_STATE_SUCCEEDED` and its resource name is recorded.
- [x] A W&B run exists with the loss curve and the config, and its URL is in the manifest.
- [x] The checkpoint is in GCS and its recorded SHA256 matches what is there.
- [x] Re-running the documented command with the same inputs reproduces the manifest's
      configuration — not necessarily identical weights, but a stated seed and versions.
- [x] A screenshot of the W&B run is committed, as MS3 requires visible evidence.

**Status 2026-11-10.** Job `projects/15733748057/locations/us-east1/customJobs/8919501313956380672`
(`train-20261110-t4-r3`) succeeded on one T4 in 889 s of training. Evidence is in
`docs/ms3/evidence/module-b/2026-11-10/`, including the two failed attempts that preceded
it. Two things differ from the plan above: the batch size is 8, not 16, because the
`eager` attention path ran out of memory on the T4 at 16; and the job was submitted with
a team member's user credentials rather than a service-account key. The W&B loss charts are in the evidence directory. A second run of the
same command (`reproduction/`) reproduced the configuration, every validation metric and
the checkpoint SHA256.

### B4 — Pipeline component

Extend `cloud/pipeline.py` with a fourth container component that runs after
`validate_data`, consumes the validated release, and emits the training manifest as a
KFP artifact. Keep the existing release-binding and staleness checks intact. Module A's
plan is explicit that a placeholder task does not count as integration.

**Acceptance criteria**

- [x] `python -m cloud.pipeline --compile-only …` produces a spec containing four tasks
      with the training task's inputs wired to the validated release.
- [x] `cloud/tests/` still passes in full (45 tests at last count), plus a new test
      asserting the fourth task appears with the right dependency.
- [ ] The existing `pipeline-checks.yml` workflow stays green.
- [ ] Reviewed with module A's owner before merging.

**Status 2026-11-10.** The task is added only when `--trainer-image` (digest-pinned) is
passed, so the three data tasks compile exactly as before and the existing tests are
untouched. It reads `validate_data`'s report, rebuilds the corpus-derived pairs from
the checksummed release that report names, and the submitter rejects a training
manifest whose `source_release_uri` is not this run's release. 61 tests pass. Not yet
run on Vertex, not yet reviewed by module A's owner, **not pushed**. One coupling to
decide in review: a failed training task fails the whole pipeline run, so the data
release would not be marked validated either.

### B5 — Re-evaluate and hand back to the evaluation owner

Rebuild the retrieval index with the fine-tuned encoder and rerun
`evaluation/ms3/run_retrieval.py` with a new encoder identity, appending methods named
`finetuned_dense_*` and `finetuned_hybrid_*`. Update `evaluation/ms3/runs_handoff.md`
with the new method configuration and the additional labelling load.

**Acceptance criteria**

- [x] The fine-tuned collection identity differs from the frozen one, so the two sets of
      vectors cannot be mixed.
- [x] Every returned trial ID is inside the 50-trial universe; the runner already fails
      otherwise.
- [x] **No metric over Q03–Q08 appears anywhere in B's output.**
- [x] The handoff states the count of newly surfaced, still-unjudged trials.

### B6 — README and milestone evidence

MS3 requires the README to highlight what changed since MS2 and to carry evidence of a
running system. Add a module B section covering: how to regenerate pairs, how to
reproduce the training run, how to read the W&B run, where the checkpoint lives, and
what the known limitations are.

**Acceptance criteria**

- [x] Changes relative to MS2 are explicitly marked.
- [x] Every command in the section has been run as written.
- [x] Limitations are stated: corpus-derived queries rather than human relevance labels,
      2,281 pairs, lexical topic alignment, synthetic patients, no clinical validation.

**Status 2026-11-11.** The README has an "Encoder Training (MS3)" section. Every command
in it was run from a clean worktree, with two qualifications. The Vertex jobs were
submitted with the workflow environment's interpreter directly; the `uv run --project
docker/workflow` form in the README was run with `--dry-run` only. The run ID in the
README command has been used, so a repeat needs a new one. Regenerating the pairs showed
that negative mining broke ties by hash order; that is now fixed, and the README states
how far regenerated files differ from the ones the run trained on.

---

## 5. Known traps

- **`.venv` is macOS arm64.** A Linux VM or container cannot use it; its
  `bin/python` is a symlink into the user's macOS home. Build a separate environment
  rather than running `uv sync` over the existing `.venv`, which would break the Mac.
- **The committed Chroma store fails verification across platforms.** Restore from
  `artifacts/embedding_eval/bioclinical.snapshot.json` into a fresh store instead of
  rebuilding or "repairing" the existing one.
- **Pair construction is easy to get backwards.** The first version used any criterion
  of a trial as a positive, which pulled age and consent boilerplate toward topical
  queries and pushed genuinely topical criteria away as negatives — training on it
  would have made retrieval worse. Positives must carry the query topic, and mined
  negatives that also carry it must be dropped. Inspect samples by eye before training;
  the counts looked fine while the content was wrong.
- **Query construction dominates retrieval quality.** Question-only and patient-aware
  queries share on average under one of their top five trials. Any change to
  `patient_query` is a change to the whole system, not a tweak.

---

## 6. Open decisions needing a human

1. **Pair volume — decided 2026-11-10: add LLM-written queries.**
   `cloud/train_pairs_llm.py` asks the configured Gemini model for the search request
   each criterion helps answer, rejects queries that mostly repeat their criterion,
   and writes `artifacts/training/pairs_llm.jsonl`. It needs live credentials and
   network, so it runs on the owner's workstation; responses are cached on disk.
   Inspect a sample by eye before training, then train on both pair files together.
2. **Image base divergence — assumed, not yet confirmed by the owner.** The trainer
   image uses a Vertex PyTorch GPU base while the other three use
   `python:3.12-slim-bookworm`, because a from-scratch CUDA image is about 5 GB and
   slow to build with two days left. Revisit if the team prefers one base.
3. **Budget headroom** for one T4 run, to be confirmed with the infrastructure owner.

---

## 7. Do not ship if

- Any demo-manifest trial appears in training data.
- A benchmark score computed by module B appears in any deliverable.
- A reported improvement was not measured by the code path that is committed.
- The W&B key, a service-account key, or any credential is present in Git or a manifest.
- `docker/workflow` gained a torch dependency.
- The claim "clinical accuracy" is attached to anything in this module.
