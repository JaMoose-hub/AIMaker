param(
    [string]$Dataset = "datasets\board-pose-pi5",
    [ValidateSet("train", "val", "test")]
    [string]$Split = "val",
    [string]$Model = "models\board-pose-pi5-handheld-v2.onnx",
    [string]$Output = "",
    [int]$Variants = 5,
    [int]$Seed = 20260828,
    [int]$MaxImages = 0,
    [ValidateSet("auto", "mask", "clean-plate")]
    [string]$ForegroundMode = "auto",
    [string]$MaskDir = "",
    [string]$CleanPlate = "",
    [string]$BackgroundDir = "",
    [switch]$GenerateOnly,
    [switch]$NoFail
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$tool = Join-Path $projectRoot "tools\pi5_robustness_test.py"

function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Board Vision Python environment not found: $python"
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $Output = "runs\robustness\pi5-$stamp"
}

$arguments = @(
    $tool,
    "--dataset", (Resolve-ProjectPath $Dataset),
    "--split", $Split,
    "--model", (Resolve-ProjectPath $Model),
    "--output", (Resolve-ProjectPath $Output),
    "--variants", $Variants,
    "--seed", $Seed,
    "--max-images", $MaxImages,
    "--foreground-mode", $ForegroundMode
)

if (-not [string]::IsNullOrWhiteSpace($MaskDir)) {
    $arguments += @("--mask-dir", (Resolve-ProjectPath $MaskDir))
}
if (-not [string]::IsNullOrWhiteSpace($CleanPlate)) {
    $arguments += @("--clean-plate", (Resolve-ProjectPath $CleanPlate))
}
if (-not [string]::IsNullOrWhiteSpace($BackgroundDir)) {
    $arguments += @("--background-dir", (Resolve-ProjectPath $BackgroundDir))
}
if ($GenerateOnly) {
    $arguments += "--generate-only"
}
if ($NoFail) {
    $arguments += "--no-fail"
}

& $python @arguments
exit $LASTEXITCODE
