# TrialMatch MS3 — Retrieval Evaluation

## Benchmark

- Fixed search universe: 50 trials from the milestone2 demo manifest.
- Development queries: Q01–Q02.
- Reporting queries: Q03–Q08.
- Relevance: 0 = irrelevant, 1 = partially relevant, 2 = directly relevant.
- Task: topical relevance, NOT individual patient eligibility.

The original benchmark definition is in `retrieval_protocol.md`. Some historical paths in that document predate the move into `retrieval/`.

## Gold labels

- `retrieval_labels.csv`: 182 unique query-trial judgments.
- `reviewed_labels/Q01.json` through `Q08.json`: decisions, reasons, and evidence references.
- 107 original judgments preserved; 75 newly reviewed.
- All 166 distinct pairs returned by Jenny's ten methods are judged.
- 16 historical judgments outside that ranking pool are retained.

Additional reviews used method-blind packets and AI-assisted, non-clinician assessment. These are not independent clinical-expert annotations.

## Retrieval methods

- `retrieval_runs.jsonl`: 80 rankings, ten methods x eight queries.
- `retrieval_runs.config.json`: method configurations.
- `runs_handoff.md`: Jenny's training and retrieval provenance.
- `results/*_rankings.jsonl`: four legacy baselines.

Methods include BM25, frozen BioClinical dense/hybrid, and fine-tuned dense/hybrid, with question-only and patient-aware variants.

The original generation runner is on branch `jenny/ms3-training`. The transferred ranking outputs and configuration are preserved without modification.

The legacy BM25 rankings exactly match Jenny's BM25 rankings, so they are not treated as independent experiments.

## Reproduce scoring

From the TrialMatch repository root:

    PYTHONDONTWRITEBYTECODE=1 uv run --locked python evaluation/ms3/retrieval/evaluate_retrieval_complete.py --output-dir /tmp/trialmatch-retrieval-check

Use a new output directory. Existing output files cannot be overwritten.

P@3 counts relevance >= 1 in the first three results.

nDCG@5 uses graded gain (2^relevance - 1), with IDCG calculated from all judged pooled candidates for each query.

Official results:

- `results/ms3_retrieval_all14_per_query.csv`
- `results/ms3_retrieval_all14_summary.csv`
- `results/ms3_retrieval_finetune_deltas.csv`
- `results/ms3_retrieval_evaluation_manifest.json`

See `RETRIEVAL_EVALUATION_REPORT.md` for the full comparison, fine-tuning ablation, and failure analysis.

## Tests

    PYTHONDONTWRITEBYTECODE=1 uv run --locked python -m unittest discover -s evaluation/ms3/retrieval/tests -p 'test_*.py' -v

## Limitations

This benchmark contains only six reporting queries and uses a pooled judgment set over a fixed 50-trial universe. It does not establish full-corpus recall, statistical significance, patient eligibility accuracy, or clinical readiness. Historical trial and patient reference dates also differ.
