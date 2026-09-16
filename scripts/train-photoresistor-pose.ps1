[CmdletBinding()]
param(
    [int]$Epochs = 150,
    [int]$ImageSize = 768,
    [int]$Batch = 12,
    [string]$Device = "0",
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
$model = Join-Path $root "yolo11n-pose.pt"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if (-not (Test-Path -LiteralPath $model -PathType Leaf)) {
    throw "pose base model not found: $model"
}

$arguments = @(
    "tools\train_yolo_photoresistor_pose.py",
    "--model", $model,
    "--data", "training\photoresistor-pose.yaml",
    "--output", "models\photoresistor-pose.onnx",
    "--epochs", $Epochs,
    "--imgsz", $ImageSize,
    "--batch", $Batch,
    "--device", $Device,
    "--accept-ultralytics-license"
)
if ($Overwrite) { $arguments += "--overwrite" }

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "photoresistor pose training failed" }
} finally {
    Pop-Location
}
