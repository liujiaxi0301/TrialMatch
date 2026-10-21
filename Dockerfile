FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1
ENV UV_PROJECT_ENVIRONMENT=/.venv
ENV PATH="/.venv/bin:$PATH"
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV UV_NO_DEV=1
ENV OPENSSL_armcap=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.13.1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY services ./services
COPY demo ./demo
COPY prepare_data.py ./
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/artifacts \
    && chown -R app:app /app /.venv /tmp/uv-cache
USER app

CMD ["uv", "run", "--frozen", "bash"]
