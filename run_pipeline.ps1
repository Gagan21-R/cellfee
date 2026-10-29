# Re-runs the full pipeline: XGBoost || AQSVC, QpiAI Opt decisions for 5,000 batteries, QAOA, market (~60 min).
# Add "--reuse-cv" after cellfee.pipeline to redo only the decision stage.
# The first run also fetches the dataset's per-cycle summaries (~11 MB, about 30 s).
$py = Join-Path $env:USERPROFILE ".venvs\cellfee\Scripts\python.exe"
$env:PYTHONUTF8 = "1"
Push-Location (Join-Path $PSScriptRoot "backend")
if (-not (Test-Path (Join-Path $PSScriptRoot "data\raw\severson_summary.json"))) { & $py -m cellfee.fetch_severson }
& $py -m cellfee.pipeline
Pop-Location
