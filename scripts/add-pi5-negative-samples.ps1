param(
    [string]$Source = "datasets\board-pose-pi5-8kpt-synth-v4",
    [string]$Output = "datasets\board-pose-pi5-8kpt-synth-v5",
    [int]$UnoCount = 20,
    [int]$SensorCount = 15,
    [int]$WiringCount = 15
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "backend\.venv\Scripts\python.exe"
$tool = Join-Path $projectRoot "tools\add_pi5_negative_samples.py"

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
    --uno-source (Resolve-ProjectPath "datasets\board-pose\images\train") `
    --sensor-source (Resolve-ProjectPath "datasets\photoresistor-pose\images\train") `
    --wiring-source (Resolve-ProjectPath "datasets\live-captures\powered_led\20260807-092815-powered_led\images") `
    --uno-count $UnoCount `
    --sensor-count $SensorCount `
    --wiring-count $WiringCount
exit $LASTEXITCODE
