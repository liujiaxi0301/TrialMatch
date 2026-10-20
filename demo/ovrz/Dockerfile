FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV UV_CACHE_DIR=/tmp/uv-cache

RUN pip install --no-cache-dir uv==0.13.1

COPY demo/ovrz/pyproject.toml demo/ovrz/uv.lock ./
RUN uv sync --frozen

COPY services ./services
COPY demo/ovrz ./demo/ovrz
RUN useradd --create-home --uid 1000 app && mkdir -p /app/artifacts && chown -R app:app /app/artifacts
USER app
CMD ["python", "-m", "uvicorn", "services.frontend.app:app", "--host", "0.0.0.0", "--port", "8080"]
