. "$PSScriptRoot/environment.ps1"
Set-Location $orchestrationRoot
& ./.venv-prefect/Scripts/python.exe -m prefect server start --host 127.0.0.1 --port 4200
if ($LASTEXITCODE) { throw 'Prefect server failed; existing services were not restarted.' }
