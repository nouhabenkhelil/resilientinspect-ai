$ErrorActionPreference = 'Stop'
$monitorRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $monitorRoot
try {
    if (-not (Test-Path '.venv-monitoring/Scripts/python.exe')) {
        & .venv-prefect/Scripts/python.exe -m venv .venv-monitoring
        if ($LASTEXITCODE) { throw 'Monitoring venv creation failed' }
    }
    & .venv-monitoring/Scripts/python.exe -m pip install -r mlops/monitoring/requirements-lock.txt
    if ($LASTEXITCODE) { throw 'Monitoring dependencies failed' }
    & .venv-monitoring/Scripts/python.exe -m mlops.monitoring.configure provision
    if ($LASTEXITCODE) { throw 'Monitoring provisioning failed' }
    & docker compose -f mlops/monitoring/compose.yml up -d
    if ($LASTEXITCODE) { throw 'Monitoring collector failed' }
    $monitorReady = $false
    for ($monitorAttempt = 0; $monitorAttempt -lt 30; $monitorAttempt++) {
        try {
            $monitorHealth = Invoke-WebRequest http://127.0.0.1:19108/health -UseBasicParsing -TimeoutSec 3
            if ($monitorHealth.StatusCode -eq 200) { $monitorReady = $true; break }
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $monitorReady) { throw 'Monitoring health timeout' }
    & .venv-monitoring/Scripts/python.exe -m mlops.monitoring.configure connect
    if ($LASTEXITCODE) { throw 'Monitoring connection failed' }
    & .venv-prefect/Scripts/python.exe -m mlops.monitoring.flow
    if ($LASTEXITCODE) { throw 'Initial monitoring measurement failed' }
} finally { Pop-Location }
