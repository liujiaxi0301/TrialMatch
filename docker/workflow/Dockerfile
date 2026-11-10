FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/.venv PATH="/.venv/bin:$PATH"
ENV OPENSSL_armcap=0
RUN pip install --no-cache-dir uv==0.13.1
COPY docker/workflow/pyproject.toml docker/workflow/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY cloud/__init__.py cloud/tasks.py cloud/pipeline.py cloud/release.py ./cloud/
COPY cloud/train_pairs.py cloud/train_pairs_llm.py ./cloud/
COPY evaluation/ms3/run_retrieval.py evaluation/ms3/retrieval_queries.jsonl ./evaluation/ms3/
COPY evaluation/retrieval/__init__.py evaluation/retrieval/benchmark.py ./evaluation/retrieval/
COPY prepare_data.py ./
COPY services/trial_ingestion/scripts ./services/trial_ingestion/scripts
COPY services/rag_workflow/*.py ./services/rag_workflow/
COPY services/rag_workflow/prompts/ ./services/rag_workflow/prompts/
RUN mkdir -p artifacts
ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=$SOURCE_COMMIT
CMD ["python", "-m", "cloud.pipeline", "--help"]
