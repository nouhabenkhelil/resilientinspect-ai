# Recurring maintenance was explicitly approved for this local Sprint 3 deployment.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$statePath = Join-Path $repoRoot 'deployment/industrial/local/observability/daemon.json'
if (Test-Path -LiteralPath $statePath) {
    $daemonState = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
    $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($daemonState.pid)"
    if ($existing -and $existing.CommandLine -like '*deployment/operations/backup.py*daemon*') {
        Write-Output 'Backup daemon already running.'
        exit 0
    }
}
Start-Process -FilePath (Join-Path $repoRoot '.venv-ops/Scripts/python.exe') -ArgumentList @('deployment/operations/backup.py','daemon','--approved-maintenance') -WorkingDirectory $repoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $repoRoot 'deployment/industrial/local/observability/daemon.stdout.log') -RedirectStandardError (Join-Path $repoRoot 'deployment/industrial/local/observability/daemon.stderr.log')
Write-Output 'Backup daemon started; private status records its PID and schedule.'
