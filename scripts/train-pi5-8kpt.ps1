param(
    [int]$Epochs = 180,
    [int]$Batch = 8,
    [string]$Device = "0",
    [switch]$Pilot,
    [switch]$RobustnessTest,
    [ValidateSet("val", "test")]
    [string]$RobustnessSplit = "test",
    [int]$RobustnessVariants = 5
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv-training\Scripts\python.exe"
$baseModel = Join-Path $projectRoot "yolo11n-pose.pt"
$dataset = Join-Path $projectRoot "datasets\board-pose-pi5-8kpt"
$outputModel = if ($Pilot) {
    Join-Path $projectRoot "models\board-pose-pi5-8kpt-pilot.onnx"
} else {
    Join-Path $projectRoot "models\board-pose-pi5-8kpt.onnx"
}
$runName = if ($Pilot) { "pi5-8kpt-pilot" } else { "pi5-8kpt" }

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if (-not (Test-Path -LiteralPath $baseModel -PathType Leaf)) {
    throw "YOLO11 Pose base model not found: $baseModel"
}

$auditArguments = @(
    (Join-Path $projectRoot "tools\audit_pi5_8kpt_dataset.py"),
    "--dataset", $dataset
)
if (-not $Pilot) { $auditArguments += "--strict" }
& $python @auditArguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python (Join-Path $projectRoot "tools\train_yolo_board_pose.py") `
    --data (Join-Path $projectRoot "training\board-pose-pi5-8kpt.yaml") `
    --model $baseModel `
    --output $outputModel `
    --epochs $Epochs --imgsz 960 --batch $Batch --device $Device `
    --project (Join-Path $projectRoot "runs\board-pose") --name $runName `
    --augmentation handheld --pose-weight 30 --accept-ultralytics-license
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($RobustnessTest) {
    & (Join-Path $projectRoot "scripts\test-pi5-robustness.ps1") `
        -Dataset $dataset `
        -Split $RobustnessSplit `
        -Model $outputModel `
        -Variants $RobustnessVariants
    exit $LASTEXITCODE
}

exit 0
