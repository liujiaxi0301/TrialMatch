FROM python:3.12-slim
RUN pip install --no-cache-dir uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
COPY services/rag_workflow/pyproject.toml services/rag_workflow/uv.lock /app/services/rag_workflow/
RUN uv sync --project /app/services/rag_workflow --frozen --no-dev
COPY services /app/services
RUN useradd --create-home app && mkdir -p /app/artifacts/rag_workflow && chown -R app:app /app
USER app
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "services.rag_workflow.api:app", "--host", "0.0.0.0", "--port", "8080"]
