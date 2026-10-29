FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV UV_PROJECT_ENVIRONMENT=/.venv
ENV PATH="/.venv/bin:$PATH"
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV OPENSSL_armcap=0

RUN pip install --no-cache-dir uv==0.13.1
COPY docker/rag-api/pyproject.toml docker/rag-api/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/artifacts /tmp/uv-cache \
    && chown -R app:app /app /tmp/uv-cache
COPY --chown=app:app cloud/__init__.py cloud/tasks.py ./cloud/
COPY --chown=app:app services/rag_workflow/*.py ./services/rag_workflow/
COPY --chown=app:app services/rag_workflow/prompts/ ./services/rag_workflow/prompts/
COPY --chown=app:app services/frontend/__init__.py services/frontend/app.py services/frontend/vector_demo.py ./services/frontend/
COPY --chown=app:app services/frontend/static/ ./services/frontend/static/
COPY --chown=app:app demo/ovrz/verify_http.py ./demo/ovrz/

USER app
CMD ["python", "-m", "uvicorn", "services.frontend.app:app", "--host", "0.0.0.0", "--port", "8080"]
