$ErrorActionPreference = 'Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..'))
$script:localChecks = [System.Collections.Generic.List[object]]::new()
$env:DVC_SITE_CACHE_DIR = Join-Path (Get-Location).Path '.dvc/site-cache'
$env:MLFLOW_DISABLE_TELEMETRY = 'true'
$env:MLFLOW_DISABLE_AGENT_HINT = '1'

function Invoke-Checked {
    param([string]$Name, [string]$Program, [string[]]$Arguments)
    Write-Host "Checking: $Name"
    $started = [datetime]::UtcNow
    & $Program @Arguments
    $exitCode = $LASTEXITCODE
    $script:localChecks.Add([pscustomobject]@{ name=$Name; exit_code=$exitCode; seconds=([datetime]::UtcNow-$started).TotalSeconds })
    if ($exitCode -ne 0) { throw "$Name failed with exit code $exitCode" }
}

# Requires restored artifacts, registered models, and already running local services.
# Does not stop/recreate services, train, export, benchmark, or regenerate portability.
Invoke-Checked 'DVC release SHA256' '.\.venv-mlops\Scripts\python.exe' @('mlops/dvc_release.py','verify')
Invoke-Checked 'DVC workspace status' '.\.venv-mlops\Scripts\python.exe' @('-m','dvc','status')
Invoke-Checked 'DVC remote status' '.\.venv-mlops\Scripts\python.exe' @('-m','dvc','status','--cloud')
Invoke-Checked 'Historical MLflow provenance' '.\.venv-mlops\Scripts\python.exe' @('mlops/tracking.py','verify')
Invoke-Checked 'Registry URI retrieval and real val inference' '.\.venv-mlops\Scripts\python.exe' @('mlops/registry.py','verify')
Invoke-Checked 'Frozen Docker scientific inputs' '.\.venv\Scripts\python.exe' @('scripts/prepare_compose.py','--check')

$composeState = docker compose ps --format json
if ($LASTEXITCODE) { throw 'docker compose ps failed' }
$containers = @($composeState | ForEach-Object { $_ | ConvertFrom-Json })
if ($containers.Count -ne 2 -or @($containers | Where-Object { $_.State -ne 'running' -or $_.Health -ne 'healthy' }).Count) {
    throw 'Both application containers must already be running and healthy.'
}
Invoke-Checked 'Real FastAPI engines and refusals' '.\.venv\Scripts\python.exe' @('scripts/check_onnx_api.py')
Invoke-Checked 'Frontend layouts comparison and history browser path' 'node' @('frontend/scripts/browser-qa.mjs')
Invoke-Checked 'ONNX application browser path' 'node' @('frontend/scripts/onnx-qa.mjs')
Invoke-Checked 'MLflow browser path' 'node' @('mlops/browser-qa.mjs')
Invoke-Checked 'Final 15/14 models, proofs and metadata' '.\.venv-mlops\Scripts\python.exe' @('mlops/verify.py')
Invoke-Checked 'Official aggregate source verification' '.\.venv\Scripts\python.exe' @('frontend/scripts/export-analytics.py','--check')
Invoke-Checked 'Official aggregate regression tests' '.\.venv\Scripts\python.exe' @('-m','pytest','frontend/scripts/tests','-q')

New-Item -ItemType Directory -Path 'scripts/ci/local' -Force | Out-Null
[pscustomobject]@{ status='passed'; checked_at_utc=[datetime]::UtcNow.ToString('o'); checks=$script:localChecks; containers=@($containers | Select-Object Service,State,Health,Ports) } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath 'scripts/ci/local/full-validation.json' -Encoding UTF8
Write-Host 'Full local artifact-backed validation passed; original models and services preserved.'
