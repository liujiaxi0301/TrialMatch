#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

mkdir -p artifacts/ms4

docker compose run --rm --no-deps -T \
  -e TRIALMATCH_MODE=offline \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD/demo:/app/demo:ro" \
  rag-api sh -ec '
    uv pip install --target /tmp/ms4-tools coverage==7.10.7

    export PYTHONPATH=/tmp/ms4-tools
    export COVERAGE_FILE=/tmp/ms4.coverage

    python -m coverage erase

    python -m coverage run \
      --source=services/rag_workflow,services/frontend \
      --omit="*/tests/*" \
      -m unittest discover -s services/rag_workflow/tests -v

    python -m coverage run --append \
      --source=services/rag_workflow,services/frontend \
      --omit="*/tests/*" \
      -m unittest discover -s services/frontend/tests -v

    python -m coverage xml \
      -o /app/artifacts/ms4/coverage.xml

    python -m coverage html \
      -d /app/artifacts/ms4/coverage_html

    python -m coverage report \
      --show-missing --fail-under=50
  '
