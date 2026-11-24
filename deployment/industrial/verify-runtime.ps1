# Read-only local runtime/log inspection. Never print environments, credentials or raw logs.
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location -LiteralPath $repoRoot
try {
    $dc = @('compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml')
    $secrets = @()
    foreach ($line in Get-Content -LiteralPath 'deployment/industrial/local/.env') {
        $pair = $line -split '=', 2
        if ($pair.Count -eq 2 -and $pair[0] -match 'PASSWORD|SECRET' -and $pair[1].Length -ge 20) { $secrets += $pair[1] }
    }
    $accounts = Get-Content -Raw -LiteralPath 'deployment/industrial/local/accounts.json' | ConvertFrom-Json
    foreach ($entry in $accounts.accounts.PSObject.Properties) { $secrets += $entry.Value.password }
    $ErrorActionPreference = 'Continue'
    $logs = (& docker @dc logs --no-color --no-log-prefix 2>&1 | Out-String)
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw 'Unable to inspect container logs' }
    $secretMatches = @($secrets | Where-Object { $logs.Contains($_) }).Count
    $jwtMatches = [regex]::Matches($logs, 'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}').Count
    if ($secretMatches -ne 0 -or $jwtMatches -ne 0) { throw 'Sensitive content detected in logs; values withheld' }
    $services = @()
    foreach ($service in @('postgres', 'science', 'portal', 'web', 'idp')) {
        $containerId = (& docker @dc ps -q $service | Out-String).Trim()
        if (-not $containerId) { throw "Missing industrial service: $service" }
        $details = (& docker inspect $containerId | Out-String | ConvertFrom-Json)[0]
        $ports = @($details.HostConfig.PortBindings.PSObject.Properties | Where-Object { $_.Value } | ForEach-Object { foreach ($binding in $_.Value) { "$($binding.HostIp):$($binding.HostPort)" } })
        if ($service -in @('science', 'postgres') -and $ports.Count -ne 0) { throw 'A private service publishes a host port' }
        if ($service -eq 'science' -and @($details.Mounts | Where-Object { $_.Type -eq 'bind' -and $_.RW }).Count) { throw 'A scientific bind mount is writable' }
        $services += [ordered]@{ service = $service; status = $details.State.Status; health = $details.State.Health.Status;
            image_id = $details.Image; published_ports = $ports; read_only_root = $details.HostConfig.ReadonlyRootfs;
            user = $details.Config.User; bind_mounts = @($details.Mounts | Where-Object { $_.Type -eq 'bind' }).Count }
    }
    $live = Invoke-RestMethod 'http://localhost:18180/api/health'
    $legacy = Invoke-RestMethod 'http://localhost:8001/health'
    $denied = @()
    foreach ($route in @('auth/session', 'status', 'model/metadata', 'inspections', 'admin/users', 'audit', 'readiness')) {
        $status = 0
        try { $status = (Invoke-WebRequest -UseBasicParsing "http://localhost:18180/api/$route").StatusCode }
        catch { if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode } else { throw 'Unable to reach industrial gateway' } }
        if ($status -ne 401) { throw "Anonymous endpoint not denied: $route" }
        $denied += [ordered]@{ route = $route; status = $status }
    }
    $oracleListening = @(Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue).Count -gt 0
    $trafficScope = 'Startup and unauthenticated traffic only; real OIDC/inference QA not run'
    $browserEvidence = 'deployment/industrial/local/browser-verification.json'
    if (Test-Path -LiteralPath $browserEvidence) {
        $browserResult = Get-Content -Raw -LiteralPath $browserEvidence | ConvertFrom-Json
        if ($browserResult.passed) { $trafficScope = 'Startup, anonymous requests and real authenticated OIDC/inference QA traffic' }
    }
    $result = [ordered]@{ services = $services; health = $live; anonymous_http = $denied;
        legacy_models = $legacy.ready_models_by_engine; legacy_frontend_status = (Invoke-WebRequest -UseBasicParsing 'http://localhost:18080').StatusCode;
        oracle_8080_listening = $oracleListening; configured_secret_matches_in_logs = $secretMatches;
        jwt_matches_in_logs = $jwtMatches; log_scan_scope = $trafficScope }
    $result | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath 'deployment/industrial/local/runtime-verification.json'
    $result | ConvertTo-Json -Depth 8
}
finally { Pop-Location }
