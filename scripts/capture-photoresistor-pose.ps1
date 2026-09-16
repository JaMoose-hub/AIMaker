[CmdletBinding()]
param(
    [ValidateSet("train", "val", "test")]
    [string]$Split = "train",
    [string]$Source = "http://127.0.0.1:8100/video",
    [int]$MaxSamples = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

Push-Location $root
try {
    & $python "tools\capture_yolo_photoresistor_pose.py" `
        --source $Source `
        --out "datasets\photoresistor-pose" `
        --split $Split `
        --max-samples $MaxSamples
    if ($LASTEXITCODE -ne 0) { throw "photoresistor pose capture failed" }
} finally {
    Pop-Location
}
