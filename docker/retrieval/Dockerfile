FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/.venv PATH="/.venv/bin:$PATH"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EMBEDDING_DEVICE=cpu ANONYMIZED_TELEMETRY=False
RUN pip install --no-cache-dir uv==0.13.1
COPY docker/retrieval/pyproject.toml docker/retrieval/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY cloud/__init__.py cloud/tasks.py cloud/release.py cloud/training_inputs.py cloud/finetuned_retrieval.py ./cloud/
COPY services/rag_workflow/*.py ./services/rag_workflow/
COPY evaluation/retrieval/__init__.py evaluation/retrieval/benchmark.py ./evaluation/retrieval/
COPY evaluation/ms3/run_retrieval.py evaluation/ms3/retrieval_queries.jsonl ./evaluation/ms3/
RUN python -m cloud.finetuned_retrieval --help \
    && python -m evaluation.ms3.run_retrieval --help
ARG SOURCE_COMMIT
ENV SOURCE_COMMIT=$SOURCE_COMMIT
CMD ["python", "-m", "cloud.finetuned_retrieval", "--help"]
