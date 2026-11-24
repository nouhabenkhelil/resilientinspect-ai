# Run only after explicit approval. No restore, data reset, volume removal or Keycloak action.
param([switch]$ApprovedRestart)
if (-not $ApprovedRestart) { throw 'Explicit approval required; review docs/industrial/postgres-restart-review.md' }
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location -LiteralPath $repoRoot
try {
    $dc = @('compose', '--env-file', 'deployment/industrial/local/.env', '-f', 'deployment/industrial/compose.yml')
    function Check-Exit { if ($LASTEXITCODE -ne 0) { throw 'Docker/PostgreSQL operation failed; no further action taken' } }
    $containerId = (& docker @dc ps -q postgres | Out-String).Trim()
    if ($containerId -notmatch '^[a-f0-9]{12,64}$') { throw 'Unexpected PostgreSQL container identity' }
    $initial = (& docker inspect $containerId | Out-String | ConvertFrom-Json)[0]
    $volume = @($initial.Mounts | Where-Object { $_.Destination -eq '/var/lib/postgresql/data' })
    if ($volume.Count -ne 1 -or $volume[0].Name -ne 'resilientinspect-industrial_postgres-data') { throw 'Unexpected PostgreSQL volume' }
    $busy = (& docker @dc exec -T postgres psql -U ri_migrator -d portal -qAtc 'SELECT count(*) FROM work_leases;' | Out-String).Trim()
    Check-Exit
    if ($busy -ne '0') { throw 'Active inference leases; do not restart' }
    $sql = "SELECT jsonb_build_object('revision',(SELECT version_num FROM alembic_version),'inspections',(SELECT jsonb_agg(to_jsonb(i) ORDER BY i.id) FROM inspections i),'model_releases',(SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM model_releases r),'grants',(SELECT jsonb_agg(to_jsonb(g) ORDER BY g.inspection_id,g.user_id) FROM inspection_grants g),'users',(SELECT jsonb_agg(jsonb_build_object('id',u.id,'role',u.role,'enabled',u.enabled) ORDER BY u.id) FROM users u));"
    $before = (& docker @dc exec -T postgres psql -U ri_migrator -d portal -qAtc $sql | Out-String).Trim()
    Check-Exit
    $snapshot = $before | ConvertFrom-Json
    if (@($snapshot.inspections).Count -lt 11) { throw 'Expected inspection data missing before backup' }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path (Resolve-Path 'deployment/industrial/local').Path "backups/$stamp"
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    $before | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $backupDir 'before.json')
    $archives = @()
    foreach ($databaseName in @('portal', 'portal_tests')) {
        $archive = "/tmp/ri-$stamp-$databaseName.dump"
        & docker @dc exec -T postgres pg_dump -U ri_migrator -d $databaseName -Fc -f $archive
        Check-Exit
        $target = Join-Path $backupDir "$databaseName.dump"
        & docker cp "${containerId}:$archive" $target
        Check-Exit
        & docker @dc exec -T postgres pg_restore --list $archive | Out-Null
        Check-Exit
        if ((Get-Item -LiteralPath $target).Length -eq 0) { throw 'Empty backup; do not restart' }
        $archives += [ordered]@{ database = $databaseName; sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLower(); bytes = (Get-Item -LiteralPath $target).Length; archive_readable = $true }
    }
    $globals = "/tmp/ri-$stamp-globals.sql"
    & docker @dc exec -T postgres pg_dumpall -U ri_migrator --globals-only --file $globals
    Check-Exit
    $globalsTarget = Join-Path $backupDir 'globals.sql'
    & docker cp "${containerId}:$globals" $globalsTarget
    Check-Exit
    if ((Get-Item -LiteralPath $globalsTarget).Length -eq 0) { throw 'Empty global-role backup; do not restart' }
    $globalsHash = (Get-FileHash -LiteralPath $globalsTarget -Algorithm SHA256).Hash.ToLower()
    # The one interruption explicitly approved by the user:
    & docker @dc restart postgres
    Check-Exit
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker @dc exec -T postgres pg_isready -U ri_migrator -d portal | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'PostgreSQL did not become ready; backups retained, no automatic restore' }
    $after = (& docker @dc exec -T postgres psql -U ri_migrator -d portal -qAtc $sql | Out-String).Trim()
    Check-Exit
    $after | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $backupDir 'after.json')
    if ($before -cne $after) { throw 'Business snapshot changed after restart; backups retained, no automatic restore' }
    $final = (& docker inspect $containerId | Out-String | ConvertFrom-Json)[0]
    $finalVolume = @($final.Mounts | Where-Object { $_.Destination -eq '/var/lib/postgresql/data' })[0].Name
    if ($finalVolume -ne $volume[0].Name -or $initial.State.StartedAt -eq $final.State.StartedAt) { throw 'Unexpected restart or volume identity' }
    $result = [ordered]@{ date = (Get-Date).ToUniversalTime().ToString('o'); passed = $true; explicit_user_approval = $true;
        postgres_restarted = $true; volume = $finalVolume; volume_preserved = $true; inspections_preserved = @($snapshot.inspections).Count;
        exact_business_snapshot_match = $true; revision = $snapshot.revision; backups = $archives; global_roles_sha256 = $globalsHash;
        backup_directory = "deployment/industrial/local/backups/$stamp"; full_restore_tested = $false; no_data_deletion = $true }
    $result | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath 'deployment/industrial/local/restart-verification.json'
    $result | ConvertTo-Json -Depth 8
}
finally { Pop-Location }
