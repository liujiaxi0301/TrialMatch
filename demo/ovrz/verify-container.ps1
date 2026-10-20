$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$evidenceRoot = Join-Path (Get-Location) 'artifacts/ovrz/container-evidence'
New-Item -ItemType Directory -Force -Path $evidenceRoot | Out-Null
& docker version 2>&1 | Tee-Object -FilePath "$evidenceRoot/docker-version.txt"
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable.' }
& docker compose -f demo/ovrz/compose.yml config 2>&1 | Tee-Object -FilePath "$evidenceRoot/compose.txt"
if ($LASTEXITCODE -ne 0) { throw 'Compose validation failed.' }
& docker compose -f demo/ovrz/compose.yml up --build --wait --wait-timeout 300 2>&1 | Tee-Object -FilePath "$evidenceRoot/startup.txt"
if ($LASTEXITCODE -ne 0) { throw 'Container startup failed.' }
& docker compose -f demo/ovrz/compose.yml ps -a 2>&1 | Tee-Object -FilePath "$evidenceRoot/services.txt"
& docker compose -f demo/ovrz/compose.yml exec -T rag-api python demo/ovrz/verify_http.py --output /app/artifacts/ovrz/container-http 2>&1 | Tee-Object -FilePath "$evidenceRoot/http-checks.txt"
if ($LASTEXITCODE -ne 0) { throw 'HTTP verification failed.' }
& docker compose -f demo/ovrz/compose.yml logs --no-color 2>&1 | Tee-Object -FilePath "$evidenceRoot/services-log.txt"
& docker compose -f demo/ovrz/compose.yml cp rag-api:/app/artifacts/ovrz/container-http "$evidenceRoot/http"
if ($LASTEXITCODE -ne 0) { throw 'Evidence export failed.' }
Write-Host "PASS. Evidence: $evidenceRoot . Capture the running containers and browser."
