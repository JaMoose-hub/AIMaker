[CmdletBinding()]
param(
    [string]$Source = "http://127.0.0.1:8100/video"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

Push-Location $root
try {
    & $python "tools\calibrate_photoresistor_profile.py" `
        --source $Source `
        --out "profiles\components\photoresistor-module"
    if ($LASTEXITCODE -ne 0) { throw "photoresistor profile calibration failed" }
} finally {
    Pop-Location
}
