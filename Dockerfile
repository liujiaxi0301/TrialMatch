FROM python:3.12-slim-bookworm

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/.venv

RUN pip install --no-cache-dir uv==0.13.1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

CMD ["uv", "run", "--frozen", "bash"]
