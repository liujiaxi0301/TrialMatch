FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/.venv
ENV PATH="/.venv/bin:$PATH"
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV OPENSSL_armcap=0
ENV ANONYMIZED_TELEMETRY=False

RUN pip install --no-cache-dir uv==0.13.1
COPY docker/chromadb/pyproject.toml docker/chromadb/uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
RUN mkdir -p /data

EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=5s --retries=18 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v2/heartbeat', timeout=3).close()"
CMD ["chroma", "run", "--host", "0.0.0.0", "--port", "8000", "--path", "/data"]
