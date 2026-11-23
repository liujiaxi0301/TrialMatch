#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

if [[ "${1:-}" != "--container" ]]; then
  mkdir -p artifacts/ms4
  export LOCAL_UID="${LOCAL_UID:-$(id -u)}"
  export LOCAL_GID="${LOCAL_GID:-$(id -g)}"
  exec docker compose -f docker-compose.yml -f docker-compose.test.yml \
    run --build --rm --no-deps -T -e "COVERAGE_MIN=${COVERAGE_MIN:-50}" api-tests
fi

# Always produce reports, including when a test fails. Either a test failure or
# coverage below the threshold must fail the command and therefore the CI job.
failed=0
python -m coverage erase
python -m coverage run \
  --source=services/rag_workflow,services/frontend --omit="*/tests/*" \
  -m pytest -ra -p no:cacheprovider --import-mode=importlib services/rag_workflow/tests \
  --junitxml=artifacts/ms4/backend-tests.xml \
  2>&1 | tee artifacts/ms4/backend-tests.txt || failed=1
python -m coverage run --append \
  --source=services/rag_workflow,services/frontend --omit="*/tests/*" \
  -m pytest -ra -p no:cacheprovider --import-mode=importlib services/frontend/tests \
  --junitxml=artifacts/ms4/frontend-api-tests.xml \
  2>&1 | tee artifacts/ms4/frontend-api-tests.txt || failed=1
python -m coverage xml -o artifacts/ms4/coverage.xml || failed=1
python -m coverage html -d artifacts/ms4/coverage_html || failed=1
python -m coverage report --show-missing --fail-under="${COVERAGE_MIN:-50}" \
  | tee artifacts/ms4/coverage.txt || failed=1
exit "$failed"
