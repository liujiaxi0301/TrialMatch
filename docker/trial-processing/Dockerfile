FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV UV_PROJECT_ENVIRONMENT=/.venv
ENV PATH="/.venv/bin:$PATH"
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV OPENSSL_armcap=0

RUN pip install --no-cache-dir uv==0.13.1
COPY docker/trial-processing/pyproject.toml docker/trial-processing/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/artifacts /tmp/uv-cache \
    && chown -R app:app /app /tmp/uv-cache
COPY --chown=app:app services/trial_ingestion/scripts/*.py ./services/trial_ingestion/scripts/
COPY --chown=app:app prepare_data.py ./

USER app
# Pull the committed DVC pointers without mounting the host Git checkout.
RUN dvc config --global core.no_scm true
CMD ["python", "prepare_data.py"]
