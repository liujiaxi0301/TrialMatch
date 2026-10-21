param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:PYTHONUTF8 = '1'
$env:TRIALMATCH_MODE = 'offline'
$env:TRIALMATCH_ARTIFACTS = 'artifacts/ovrz/rag_workflow'
Remove-Item Env:CHROMADB_HOST -ErrorAction SilentlyContinue
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv and Python 3.12, then rerun this script.'
}
& uv sync --locked --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& uv run --locked python -m services.frontend.prepare
if ($LASTEXITCODE -ne 0) { throw 'Preparation failed. For source hash errors, see docs/ovrz-ms2/README.md.' }
Write-Host "Open http://127.0.0.1:$Port/ . Keep this terminal open. Ctrl+C stops the server."
& uv run --locked python -m uvicorn services.frontend.app:app --host 127.0.0.1 --port $Port
if ($LASTEXITCODE -ne 0) { throw 'Server exited with an error.' }
