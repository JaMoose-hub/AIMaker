[CmdletBinding()]
param(
    [int]$Epochs = 150,
    [int]$ImageSize = 960,
    [int]$Batch = 8,
    [string]$Device = "0",
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
$photoresistorCheckpoint = Join-Path $root "runs\pose\runs\photoresistor-pose\photoresistor-pose\weights\best.pt"
$baseModel = if (Test-Path -LiteralPath $photoresistorCheckpoint -PathType Leaf) {
    $photoresistorCheckpoint
} else {
    Join-Path $root "yolo11n-pose.pt"
}
$sourceData = Join-Path $root "training\hc-sr04-pose.yaml"
$dataYaml = Join-Path $root "training\hc-sr04-corner-pose.yaml"
$dataset = Join-Path $root "datasets\hc-sr04-corner-pose"
$outputModel = Join-Path $root "models\hc-sr04-corner-pose.onnx"
$checkpoint = Join-Path $root "models\hc-sr04-corner-pose.pt"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if (-not (Test-Path -LiteralPath $baseModel -PathType Leaf)) {
    throw "YOLO11 Pose base model not found: $baseModel"
}

Push-Location $root
try {
    if (-not (Test-Path -LiteralPath (Join-Path $dataset ".corner-pose-derived.json") -PathType Leaf)) {
        & $python "tools\derive_component_corner_pose_dataset.py" `
            "--source-data" $sourceData `
            "--destination" $dataset
        if ($LASTEXITCODE -ne 0) { throw "HC-SR04 corner dataset derivation failed" }
    }

    & $python "tools\audit_yolo_pose_dataset.py" `
        "--data" $dataYaml `
        "--min-train" "20" `
        "--min-val" "5" `
        "--min-test" "0" `
        "--min-negative" "0" `
        "--require-reviewed"
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 corner dataset audit failed" }

    $arguments = @(
        "tools\train_yolo_board_pose.py",
        "--data", $dataYaml,
        "--model", $baseModel,
        "--output", $outputModel,
        "--checkpoint-output", $checkpoint,
        "--epochs", $Epochs,
        "--imgsz", $ImageSize,
        "--batch", $Batch,
        "--device", $Device,
        "--project", (Join-Path $root "runs\hc-sr04-corner-pose"),
        "--name", "hc-sr04-corner-pose",
        "--augmentation", "component-profile",
        "--pose-weight", "20",
        "--patience", "60",
        "--accept-ultralytics-license"
    )
    if ($Overwrite) { $arguments += "--overwrite" }

    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 corner pose training failed" }
} finally {
    Pop-Location
}
