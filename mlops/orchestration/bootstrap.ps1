$ErrorActionPreference = 'Stop'
$prefectProject = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $prefectProject
if (-not (Test-Path '.venv-prefect/Scripts/python.exe')) {
    py -3.11 -m venv .venv-prefect
    if ($LASTEXITCODE) { throw 'Unable to create the isolated Prefect environment.' }
}
& ./.venv-prefect/Scripts/python.exe -m pip install -r "$PSScriptRoot/requirements-lock.txt"
if ($LASTEXITCODE) { throw 'Prefect dependency installation failed.' }
& ./.venv-prefect/Scripts/python.exe -m pip check
if ($LASTEXITCODE) { throw 'Prefect dependency validation failed.' }
