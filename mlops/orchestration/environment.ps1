$ErrorActionPreference = 'Stop'
$orchestrationRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:PREFECT_HOME = Join-Path $orchestrationRoot 'mlops/local/prefect'
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PREFECT_SERVER_ALLOW_EPHEMERAL_MODE = 'false'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
$env:PREFECT_CLI_PROMPT = 'false'
$env:PYTHONIOENCODING = 'utf-8'
