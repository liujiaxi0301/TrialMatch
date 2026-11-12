FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/.venv PATH="/.venv/bin:$PATH"
ENV OPENSSL_armcap=0
RUN pip install --no-cache-dir uv==0.13.1
COPY docker/workflow/pyproject.toml docker/workflow/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY cloud/__init__.py cloud/tasks.py cloud/pipeline.py cloud/release.py ./cloud/
COPY cloud/eligibility.py ./cloud/
COPY cloud/training_inputs.py ./cloud/
COPY cloud/finetuned_retrieval.py ./cloud/
COPY cloud/retrieval_evaluation.py cloud/retrieval_benchmark.json ./cloud/
COPY cloud/train_pairs.py cloud/train_pairs_llm.py ./cloud/
COPY evaluation/ms3/run_retrieval.py evaluation/ms3/retrieval_queries.jsonl ./evaluation/ms3/
COPY evaluation/ms3/retrieval/evaluate_retrieval_complete.py evaluation/ms3/retrieval/retrieval_labels.csv evaluation/ms3/retrieval/retrieval_queries.jsonl ./evaluation/ms3/retrieval/
COPY evaluation/ms3/retrieval/reviewed_labels/ ./evaluation/ms3/retrieval/reviewed_labels/
COPY evaluation/ms3/gemini_developer_provider.py ./evaluation/ms3/
COPY evaluation/ms3/eligibility/run_eligibility.py evaluation/ms3/eligibility/eligibility_protocol.md evaluation/ms3/eligibility/cohort_manifest.json evaluation/ms3/eligibility/eligibility_cases.jsonl ./evaluation/ms3/eligibility/
COPY evaluation/ms3/eligibility/reviewed_labels/ ./evaluation/ms3/eligibility/reviewed_labels/
COPY evaluation/retrieval/__init__.py evaluation/retrieval/benchmark.py ./evaluation/retrieval/
COPY prepare_data.py ./
COPY services/trial_ingestion/scripts ./services/trial_ingestion/scripts
COPY services/rag_workflow/*.py ./services/rag_workflow/
COPY services/rag_workflow/prompts/ ./services/rag_workflow/prompts/
RUN mkdir -p artifacts
RUN python -m cloud.retrieval_evaluation --help \
    && python -c "from cloud.retrieval_evaluation import load_benchmark; load_benchmark()"
ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=$SOURCE_COMMIT
CMD ["python", "-m", "cloud.pipeline", "--help"]
