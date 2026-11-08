[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$SkipInstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $projectRoot '.venv'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'

function Test-SupportedPython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )

    # Probe the interpreter itself; do not infer its version from its file name.
    $probe = "import sys, struct; print('%d.%d;%d' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P') * 8))"
    try {
        $probeOutput = & $Executable @PrefixArguments -c $probe 2>&1
        $probeExitCode = $LASTEXITCODE
        $details = (@($probeOutput) -join "`n").Trim()
        return [pscustomobject]@{
            IsValid = ($probeExitCode -eq 0 -and $details -match '^3\.(11|12|13);64$')
            Details = $details
        }
    }
    catch {
        return [pscustomobject]@{
            IsValid = $false
            Details = $_.Exception.Message
        }
    }
}

function Invoke-CheckedPython {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PythonArguments = @()
    )

    & $Executable @PythonArguments
    $nativeExitCode = $LASTEXITCODE
    if ($nativeExitCode -ne 0) {
        throw "Python command failed with exit code $nativeExitCode."
    }
}

if (Test-Path -LiteralPath $venvPath) {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "An existing .venv has no Scripts\python.exe. It was preserved. Repair it or choose another workspace before retrying."
    }
    $existingProbe = Test-SupportedPython -Executable $venvPython
    if (-not $existingProbe.IsValid) {
        throw "Existing .venv must use 64-bit Python 3.11, 3.12 or 3.13. It was preserved. Probe result: $($existingProbe.Details)"
    }
    Write-Host "Using the existing supported Python environment ($($existingProbe.Details))."
}
else {
    $selectedPython = $null
    $selectedPrefix = @()

    if ($PythonPath) {
        $explicitProbe = Test-SupportedPython -Executable $PythonPath
        if (-not $explicitProbe.IsValid) {
            throw "-PythonPath must identify a working 64-bit Python 3.11, 3.12 or 3.13 interpreter. Probe result: $($explicitProbe.Details)"
        }
        $selectedPython = $PythonPath
    }
    else {
        $candidates = @()
        $launcher = Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        foreach ($pythonMinor in @('3.11', '3.12', '3.13')) {
            if ($null -ne $launcher) {
                $candidates += [pscustomobject]@{ Executable = $launcher.Source; Prefix = @("-$pythonMinor") }
            }
            if ($env:LOCALAPPDATA) {
                $pythonDirectory = 'Programs\Python\Python' + $pythonMinor.Replace('.', '') + '\python.exe'
                $localPython = Join-Path $env:LOCALAPPDATA $pythonDirectory
                if (Test-Path -LiteralPath $localPython -PathType Leaf) {
                    $candidates += [pscustomobject]@{ Executable = $localPython; Prefix = @() }
                }
            }
        }
        $pathPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $pathPython) {
            $candidates += [pscustomobject]@{ Executable = $pathPython.Source; Prefix = @() }
        }

        foreach ($candidate in $candidates) {
            $candidateProbe = Test-SupportedPython -Executable $candidate.Executable -PrefixArguments $candidate.Prefix
            if ($candidateProbe.IsValid) {
                $selectedPython = $candidate.Executable
                $selectedPrefix = @($candidate.Prefix)
                break
            }
        }
    }

    if ($null -eq $selectedPython) {
        throw 'No working 64-bit Python 3.11, 3.12 or 3.13 interpreter was found. Install a supported version, then retry with -PythonPath pointing to its python.exe.'
    }

    Write-Host 'Creating .venv with a supported 64-bit Python (3.11 to 3.13).'
    Invoke-CheckedPython -Executable $selectedPython -PythonArguments ($selectedPrefix + @('-m', 'venv', $venvPath))
    $createdProbe = Test-SupportedPython -Executable $venvPython
    if (-not $createdProbe.IsValid) {
        throw 'The new .venv failed validation. It was preserved for inspection.'
    }
}

if ($SkipInstall) {
    Write-Host 'Dependency installation skipped (-SkipInstall).'
}
else {
    # Use an explicit interpreter instead of activation; resolve the editable project from its own root.
    Push-Location -LiteralPath $projectRoot
    try {
        Invoke-CheckedPython -Executable $venvPython -PythonArguments @('-m', 'pip', 'install', '--disable-pip-version-check', '-e', '.[dev]')
    }
    finally {
        Pop-Location
    }
}

Write-Host 'Bootstrap complete. No dataset was downloaded and no model was trained.'
Write-Host 'Run from the project root:'
Write-Host '  & .\.venv\Scripts\python.exe .\scripts\smoke_test.py'
Write-Host '  & .\.venv\Scripts\python.exe -m pytest'
