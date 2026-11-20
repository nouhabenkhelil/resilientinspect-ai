param([int]$Port = 5000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$rootPath = (Get-Location).Path.Replace('\', '/')
if (-not (Test-Path 'mlops/local/mlflow/tracking.db')) { throw 'Run mlops/tracking.py track first.' }
$env:MLFLOW_DISABLE_AGENT_HINT = '1'
$env:MLFLOW_DISABLE_TELEMETRY = 'true'
& .\.venv-mlops\Scripts\python.exe -m mlflow server `
    --backend-store-uri "sqlite:///$rootPath/mlops/local/mlflow/tracking.db" `
    --default-artifact-root "file:///$rootPath/mlops/local/mlflow/artifacts" `
    --no-serve-artifacts --host 127.0.0.1 --port $Port --workers 1
if ($LASTEXITCODE) { throw 'MLflow server failed' }
