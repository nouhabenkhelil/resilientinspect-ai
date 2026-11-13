param([switch]$Render)
$ErrorActionPreference = 'Stop'
$reportRoot = $PSScriptRoot
$reportBuild = Join-Path $reportRoot 'build'
$reportJob = 'Rapport_MiParcours_TrackX_ResilientInspectAI'
New-Item -ItemType Directory -Force -Path $reportBuild | Out-Null
Push-Location $reportRoot
try {
    for ($reportPass = 1; $reportPass -le 2; $reportPass++) {
        & pdflatex --disable-installer -interaction=nonstopmode -halt-on-error -file-line-error -output-directory=build "-jobname=$reportJob" rapport_miparcours.tex
        if ($LASTEXITCODE -ne 0) { throw "Echec compilation LaTeX, passe $reportPass. Aucun paquet installe automatiquement." }
    }
    $reportLog = Get-Content -LiteralPath (Join-Path $reportBuild "$reportJob.log") -Raw
    if ($reportLog -match 'Overfull|Missing character|Undefined control sequence') { throw 'Controle LaTeX: debordement ou caractere manquant.' }
    Copy-Item -LiteralPath (Join-Path $reportBuild "$reportJob.pdf") -Destination (Join-Path $reportRoot "$reportJob.pdf") -Force
    & pdfinfo "$reportJob.pdf"
    if ($LASTEXITCODE -ne 0) { throw 'Echec pdfinfo.' }
    & pdftotext -layout "$reportJob.pdf" build/rapport_extracted.txt
    if ($LASTEXITCODE -ne 0) { throw 'Echec extraction PDF.' }
    & pdftotext -bbox-layout "$reportJob.pdf" build/rapport_bbox.html
    if ($LASTEXITCODE -ne 0) { throw 'Echec controle geometrique PDF.' }
    if ($Render) {
        & pdftoppm -r 140 -png "$reportJob.pdf" build/final-page
        if ($LASTEXITCODE -ne 0) { throw 'Echec rendu PNG.' }
    }
} finally { Pop-Location }
