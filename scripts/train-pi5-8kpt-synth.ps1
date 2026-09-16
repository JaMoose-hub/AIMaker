param(
    [int]$Epochs = 80,
    [int]$Batch = 8,
    [string]$Device = "0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv-training\Scripts\python.exe"
$dataset = Join-Path $projectRoot "datasets\board-pose-pi5-8kpt-synth-v4"
$dataConfig = Join-Path $projectRoot "training\board-pose-pi5-8kpt-synth-v4.yaml"
$baseModel = Join-Path $projectRoot "runs\board-pose\pi5-8kpt-pilot\weights\best.pt"
$outputModel = Join-Path $projectRoot "models\board-pose-pi5-8kpt-synth-pilot.onnx"
$runName = "pi5-8kpt-synth-pilot"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if (-not (Test-Path -LiteralPath $baseModel -PathType Leaf)) {
    throw "8-keypoint pilot checkpoint not found: $baseModel"
}

& $python (Join-Path $projectRoot "tools\audit_pi5_8kpt_dataset.py") --dataset $dataset
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $python (Join-Path $projectRoot "tools\train_yolo_board_pose.py") `
    --data $dataConfig `
    --model $baseModel `
    --output $outputModel `
    --epochs $Epochs --imgsz 960 --batch $Batch --device $Device `
    --project (Join-Path $projectRoot "runs\board-pose") --name $runName `
    --augmentation handheld --pose-weight 30 --patience 30 `
    --accept-ultralytics-license
exit $LASTEXITCODE
