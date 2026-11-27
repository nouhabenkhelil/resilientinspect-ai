param(
    [string]$Python = 'python',
    [ValidateSet('repro','recompute','dag','metrics','track','verify','tests','regression')]
    [string]$Action = 'repro'
)
$ErrorActionPreference = 'Stop'
$pipelineRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$pipelineOldPath = $env:PATH
$pipelineOldSiteCache = $env:DVC_SITE_CACHE_DIR
$pipelineOldAnalytics = $env:DVC_NO_ANALYTICS
$pipelineOldTelemetry = $env:MLFLOW_DISABLE_TELEMETRY
Push-Location $pipelineRoot
try {
    $pipelineExecutable = (& $Python -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE) { throw 'Python executable unavailable' }
    $env:PATH = (Split-Path $pipelineExecutable -Parent) + [IO.Path]::PathSeparator + $env:PATH
    $env:DVC_SITE_CACHE_DIR = Join-Path $pipelineRoot '.dvc/site-cache'
    $env:DVC_NO_ANALYTICS = 'true'
    $env:MLFLOW_DISABLE_TELEMETRY = 'true'
    & $pipelineExecutable -c 'from mlops.dvc_pipeline.common import environment; environment()'
    if ($LASTEXITCODE) { throw 'Environment does not match the declared versions' }
    switch ($Action) {
        'repro' { & $pipelineExecutable -m dvc repro }
        'recompute' { & $pipelineExecutable -m dvc repro --force --no-run-cache }
        'dag' { & $pipelineExecutable -m dvc dag dvc.yaml }
        'metrics' { & $pipelineExecutable -m dvc metrics show mlops/dvc_pipeline/work/evaluation/metrics.json }
        'track' { & $pipelineExecutable -m mlops.dvc_pipeline.track }
        'verify' { & $pipelineExecutable -m mlops.dvc_pipeline.verify }
        'tests' { & $pipelineExecutable -m pytest mlops/dvc_pipeline/tests -q }
        'regression' { & $pipelineExecutable -m mlops.dvc_pipeline.regression }
    }
    if ($LASTEXITCODE) { throw "Pipeline command failed: $Action" }
} finally {
    $env:PATH = $pipelineOldPath
    $env:DVC_SITE_CACHE_DIR = $pipelineOldSiteCache
    $env:DVC_NO_ANALYTICS = $pipelineOldAnalytics
    $env:MLFLOW_DISABLE_TELEMETRY = $pipelineOldTelemetry
    Pop-Location
}
