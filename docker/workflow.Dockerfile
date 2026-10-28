FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/.venv PATH="/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group cloud
COPY cloud ./cloud
COPY prepare_data.py ./
COPY services/trial_ingestion/scripts ./services/trial_ingestion/scripts
COPY services/rag_workflow ./services/rag_workflow
RUN mkdir -p artifacts
CMD ["python", "-m", "cloud.pipeline", "--help"]
