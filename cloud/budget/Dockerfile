FROM python:3.12-slim-bookworm
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/.venv PATH="/.venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache
COPY main.py ./
USER 65534
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "1", "--timeout", "280", "main:app"]
