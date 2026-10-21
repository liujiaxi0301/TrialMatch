#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/../.."
export PYTHONUTF8=1 TRIALMATCH_MODE=offline
export TRIALMATCH_ARTIFACTS=artifacts/ovrz/rag_workflow
unset CHROMADB_HOST
uv sync --locked --python 3.12
uv run --locked python -m services.frontend.prepare
echo "Open http://127.0.0.1:8080/ . Keep this terminal open. Ctrl+C stops the server."
exec uv run --locked python -m uvicorn services.frontend.app:app --host 127.0.0.1 --port 8080
