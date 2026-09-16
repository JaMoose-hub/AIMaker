param(
    [string]$Source = "datasets\board-pose-pi5-8kpt",
    [string]$Output = "datasets\board-pose-pi5-8kpt-synth-v4",
    [int]$Seed = 20260829,
    [int]$PreviewCount = 16
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$tool = Join-Path $projectRoot "tools\build_pi5_synthetic_training_set.py"

function Resolve-ProjectPath([string]$Value) {
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Value))
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Board Vision Python environment not found: $python"
}

& $python $tool `
    --source (Resolve-ProjectPath $Source) `
    --output (Resolve-ProjectPath $Output) `
    --seed $Seed `
    --preview-count $PreviewCount
exit $LASTEXITCODE
