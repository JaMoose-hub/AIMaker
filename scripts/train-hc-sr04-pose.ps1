[CmdletBinding()]
param(
    [int]$Epochs = 180,
    [int]$ImageSize = 768,
    [int]$Batch = 12,
    [string]$Device = "0",
    [switch]$Pilot,
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
$baseModel = Join-Path $root "yolo11n-pose.pt"
$dataYaml = Join-Path $root "training\hc-sr04-pose.yaml"
$dataset = Join-Path $root "datasets\hc-sr04-pose"
$suffix = if ($Pilot) { "-pilot" } else { "" }
$outputModel = Join-Path $root "models\hc-sr04-pose$suffix.onnx"
$checkpoint = Join-Path $root "models\hc-sr04-pose$suffix.pt"
$runName = "hc-sr04-pose$suffix"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if (-not (Test-Path -LiteralPath $baseModel -PathType Leaf)) {
    throw "YOLO11 Pose base model not found: $baseModel"
}

$auditArguments = @(
    "tools\audit_yolo_pose_dataset.py",
    "--data", $dataYaml,
    "--require-reviewed"
)
if ($Pilot) {
    $auditArguments += @(
        "--min-train", "20",
        "--min-val", "5"
    )
} else {
    $auditArguments += @(
        "--min-train", "280",
        "--min-val", "70",
        "--min-test", "40",
        "--min-negative", "80"
    )
}

Push-Location $root
try {
    & $python @auditArguments
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 pose dataset audit failed" }

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
        "--project", (Join-Path $root "runs\hc-sr04-pose"),
        "--name", $runName,
        "--augmentation", "handheld",
        "--pose-weight", "30",
        "--accept-ultralytics-license"
    )
    if ($Overwrite) { $arguments += "--overwrite" }

    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 pose training failed" }
} finally {
    Pop-Location
}
