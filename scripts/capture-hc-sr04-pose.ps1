[CmdletBinding()]
param(
    [ValidateSet("train", "val", "test")]
    [string]$Split = "train",
    [double]$Duration = 60.0,
    [double]$Interval = 0.7,
    [int]$MaxFrames = 100,
    [double]$MinMeanDiff = 0.05,
    [switch]$NoPreview,
    [string]$Source = "http://127.0.0.1:8100/video"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

$arguments = @(
    "tools\capture_pose_stream.py",
    "--source", $Source,
    "--out", (Join-Path $root "datasets\hc-sr04-pose"),
    "--split", $Split,
    "--duration", $Duration,
    "--interval", $Interval,
    "--max-frames", $MaxFrames,
    "--min-mean-diff", $MinMeanDiff
)
if (-not $NoPreview) {
    $arguments += @(
        "--preview",
        "--guide", "hc-sr04-train",
        "--countdown", "4"
    )
}

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 live capture failed" }
} finally {
    Pop-Location
}
