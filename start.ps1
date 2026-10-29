# Starts CELLFEE: story at http://127.0.0.1:8000  ·  dashboard at http://127.0.0.1:8000/dashboard/
$py = Join-Path $env:USERPROFILE ".venvs\cellfee\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
Push-Location (Join-Path $PSScriptRoot "frontend")
if (-not (Test-Path "dist")) { npm install; npx vite build }
Pop-Location
Push-Location (Join-Path $PSScriptRoot "backend")
Write-Host "CELLFEE running: http://127.0.0.1:8000  (dashboard: /dashboard/)  - keep this window open"
& $py -m uvicorn cellfee.api:app --host 127.0.0.1 --port 8000
Pop-Location
