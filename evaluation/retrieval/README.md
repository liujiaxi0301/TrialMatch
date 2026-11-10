# Embedding retrieval experiment

Compare the existing Gemini retriever with a frozen BioClinical-ModernBERT encoder on the actual Part 1/2 data. The experiment is based on `origin/yixiao/ms3-infra` at `e95c2bb` and lives on `rag-workflow`. Shared deployment defaults, source datasets, the original Gemini index and eligibility guards are preserved.

## Read the findings first

- [Recorded results](results/2026-10-29/REPORT.md): retrieval metrics and limitations.
- [Run receipts](results/2026-10-29/summary.json): model settings, hashes, software versions and paired integration checks.
- Local full detail: `artifacts/embedding_eval/REPORT.md` and `artifacts/embedding_eval/results/*.json`.
- Human review worksheet: `artifacts/embedding_eval/dataset/human_review.csv`.

**These are provisional silver-label topic diagnostics, not human-reviewed gold labels or clinical eligibility accuracy.** Six English topic questions repeat across five official synthetic Synthea patients, producing 30 cases. Topic rules label the entire fixed corpus, but can favor lexical retrieval. Do not interpret the sample as 30 independent topics or use it as a held-out test after tuning on it.

## What changed

| File | Responsibility |
| --- | --- |
| `services/rag_workflow/embedding_providers.py` | Independent retrieval encoder factory and local BioClinical implementation |
| `services/rag_workflow/providers.py` | Existing Gemini embeddings and structured generation, preserved |
| `services/rag_workflow/config.py` | Optional provider, exact revision, token limit and device |
| `services/rag_workflow/index.py` | Encoder-aware collection identity and batched local encoding |
| `services/rag_workflow/index_versions.py` | Optional encoder identity in portable snapshots; old Gemini snapshots remain readable |
| `services/rag_workflow/cli.py` | Build a configured embedding index without requiring Gemini for local encoding |
| `services/rag_workflow/workflow.py` | Select the retrieval encoder while retaining Gemini judgments and current guards |
| `evaluation/retrieval/benchmark.py` | Freeze inputs, prepare transparent topic labels, run controlled retrieval and produce reports |
| `evaluation/retrieval/screen_smoke.py` | Paired full-workflow integration check on one synthetic case |
| `services/rag_workflow/tests/test_embedding_providers.py` | Pooling, token-budget, encoder separation and snapshot compatibility checks |
| `evaluation/retrieval/test_benchmark.py` | Recall/MRR/nDCG and rank-fusion checks using known rankings |

## Encoder protocol

- Model: [`thomas-sounack/BioClinical-ModernBERT-base`](https://huggingface.co/thomas-sounack/BioClinical-ModernBERT-base).
- Exact model/tokenizer revision: `c3648aa87af95837c809e6f0c5f85d08160db437`.
- `AutoModel` token representations, attention-mask-aware mean pooling (including special tokens), L2 normalization, 768 dimensions, float32, SDPA attention, evaluation/inference mode. No remote model code or retrieval training.
- Default CPU execution, maximum 2,048 tokens. Oversized inputs fail explicitly instead of silently truncating. Change the token limit only as a separately recorded experiment.
- Query and document use the same encoder. `RETRIEVAL_QUERY`/`RETRIEVAL_DOCUMENT` select actual Gemini task types for Gemini, but do not add synthetic text prefixes to BioClinical.
- Collection and cache identities include revision, pooling, normalization, dtype and token budget. Existing Gemini identities remain unchanged. Never search Gemini document vectors with BioClinical query vectors.

The model card describes a masked language model and recommends downstream adaptation for retrieval. Mean pooling is an experimental baseline, not evidence that the checkpoint is already a trained clinical retriever.

## Run from the repository root

```bash
uv sync --locked --group embeddings
export HF_HOME="$PWD/artifacts/embedding_eval/huggingface"
uv run --locked --group embeddings python -m evaluation.retrieval.benchmark prepare
uv run --locked --group embeddings python -m evaluation.retrieval.benchmark run \
  --encoder bioclinical --query-mode patient
```

The first run downloads the pinned public model weights and builds a separate index. Repeated builds verify/reuse the collection and text cache. A Gemini baseline requires the existing local `services/rag_workflow/index_snapshots/current.json`; recover it with the team's documented DVC procedure if absent. The runner validates its source hashes, trial IDs and dimensions before restoring it into the experiment store. It does not re-embed the 607 Gemini document fragments.

Use the existing local `.env` that points to valid GCP/ADC credentials. The commands below use `services/rag_workflow/.env`, matching this checkout; replace that path with `.env` if your configuration lives at the repository root. Never copy credentials into results or commit them.

```bash
uv run --locked --group embeddings --env-file services/rag_workflow/.env \
  python -m evaluation.retrieval.benchmark run --encoder gemini --query-mode patient

# Question-only ablation. This does not change the production patient_query function.
uv run --locked --group embeddings python -m evaluation.retrieval.benchmark run \
  --encoder bioclinical --query-mode question
uv run --locked --group embeddings --env-file services/rag_workflow/.env \
  python -m evaluation.retrieval.benchmark run --encoder gemini --query-mode question

uv run --locked --group embeddings python -m evaluation.retrieval.benchmark report
```

Both question and patient modes reuse exactly the same frozen topic labels. `patient` uses the unmodified production query builder. `question` tests whether patient context obscures the question; it is a distinct ablation, not a replacement deployed by this change.

## What the benchmark measures

1. Criterion retrieval: rank fragments by cosine similarity, deduplicate criterion IDs, compute Recall@10, nDCG@10, MRR@10, precision and hit rate. Save both exhaustive cosine and real Chroma rankings to separate encoder behavior from approximate-search behavior.
2. Trial retrieval: take each trial's best criterion hit, compute dense trial metrics at 5, then fuse the trial ranking with the unchanged BM25 ranking using `sum(1 / (60 + rank))`. Verify the hybrid top five matches the actual production `Retriever`.
3. Compare Gemini dense vs BioClinical dense, and Gemini hybrid vs BioClinical hybrid. BM25-only results are also retained as a diagnostic.
4. Save query text/hash, corpus/query/label hashes, exact model revision, index hash, device, package versions, raw rankings, top-ten source excerpts, per-query metrics and cache counts.

Binary nDCG uses `DCG = sum(relevance / log2(rank + 1))`, normalized by the best possible ordering at the cutoff. Recall divides retrieved relevant unique IDs by all relevant IDs under the declared labeling rule. Relevance here means **topic relevance**, not eligibility. A pregnancy exclusion can be relevant even when a patient's pregnancy status is unknown.

Restore time is not document-embedding time. Query timing includes cache and database/verification overhead, and question-only queries share cache entries across patients. These timings cannot establish which encoder is intrinsically faster.

## Full workflow smoke check

After the two experiment indexes exist:

```bash
uv run --locked --group embeddings --env-file services/rag_workflow/.env \
  python -m evaluation.retrieval.screen_smoke --encoder bioclinical
uv run --locked --group embeddings --env-file services/rag_workflow/.env \
  python -m evaluation.retrieval.screen_smoke --encoder gemini
```

This uses one official synthetic patient and the question `What requirements concern kidney function?`, with `top_k=1` and unchanged generation model, rules and inference budget. It calls Gemini for interpretation/explanation even with local BioClinical retrieval. It checks every criterion is assessed once and citations belong to the patient. `OK` means workflow completion, not correct clinical eligibility. Outputs are in `artifacts/embedding_eval/screening/`.

## Next evaluation stage

Have reviewers label criterion relevance independently of model rankings using the CSV worksheet. Keep review decisions, reviewer identity and a fixed dataset version. Report incomplete judgments as incomplete; do not assume unreviewed criteria are irrelevant. Freeze a held-out set before selecting pooling, prompts, reranking parameters or fine-tuning checkpoints, grouping paraphrases and repeated patient cases to avoid leakage. Then rerun the same retrieval metrics against reviewed references. The existing patient verification package addresses grounding/eligibility and is not automatically a retrieval relevance gold set.

If BioClinical is subsequently fine-tuned, training pairs should be query/positive criterion and appropriate negatives, with separate training, validation and test groups. Do not treat higher match scores or fewer UNKNOWN decisions as evidence of better embeddings.

## Local storage and Part 4 handoff

- Gemini experiment store: `artifacts/embedding_eval/gemini/chroma/`.
- BioClinical experiment store: `artifacts/embedding_eval/bioclinical/chroma/`.
- Portable BioClinical export, when created: `artifacts/embedding_eval/bioclinical.snapshot.json`.
- Model weights and text caches stay ignored under `artifacts/embedding_eval/`.
- Torch/Transformers are an optional locked dependency group, so the default cloud image remains unchanged. Part 4 must explicitly install the group and budget model memory/startup time before deploying this provider. A copied readiness file alone does not restore a collection.
- Existing Gemini deployment defaults remain active. This experiment does not automatically promote BioClinical, change the shared Compose environment, or push a branch.

## Checks

```bash
uv run --locked --group embeddings python -m unittest discover -s services/rag_workflow/tests -v
uv run --locked --group embeddings python -m unittest evaluation.retrieval.test_benchmark -v
uv run --locked --group embeddings ruff check services/rag_workflow evaluation/retrieval
```
