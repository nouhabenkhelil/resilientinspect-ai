$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Prepare the validated scientific .venv first.' }
if (-not (Test-Path '.venv-mlops/Scripts/python.exe')) {
    & .\.venv\Scripts\python.exe -m venv .venv-mlops
    if ($LASTEXITCODE) { throw 'venv failed' }
}
@'
from pathlib import Path
import subprocess
r = Path.cwd()
p = r / '.venv-mlops/Lib/site-packages/resilientinspect_scientific.pth'
p.write_text('import site; site.addsitedir(' + repr(str(r / '.venv/Lib/site-packages')) + ')\n' + str(r) + '\n', encoding='utf-8')
freeze = subprocess.check_output([str(r / '.venv/Scripts/python.exe'), '-m', 'pip', 'freeze'], text=True)
(r / 'mlops/scientific-constraints.txt').write_text('\n'.join(x for x in freeze.splitlines() if not x.startswith(('-e', '#', 'resilientinspect'))) + '\n')
'@ | & .\.venv\Scripts\python.exe -
if ($LASTEXITCODE) { throw 'constraints failed' }
& .\.venv-mlops\Scripts\python.exe -m pip install -r mlops/requirements.txt -r mlops/requirements-lock.txt -c mlops/scientific-constraints.txt
if ($LASTEXITCODE) { throw 'install failed' }
