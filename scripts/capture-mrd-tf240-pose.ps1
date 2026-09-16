[CmdletBinding()]
param(
    [ValidateSet("train", "val", "test")]
    [string]$Split = "train",
    [double]$Duration = 70,
    [int]$MaxFrames = 80,
    [string]$Source = "http://127.0.0.1:8100/video"
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "backend Python not found: $python"
}

$dataset = Join-Path $root "datasets\mrd-tf240-8p-corner-pose-v1"
$arguments = @(
    "tools\capture_pose_stream.py",
    "--source", $Source,
    "--out", $dataset,
    "--split", $Split,
    "--duration", [string]$Duration,
    "--interval", "0.7",
    "--max-frames", [string]$MaxFrames,
    "--min-mean-diff", "0.8",
    "--prefix", "mrd_tf240_$Split",
    "--display-name", "MRD_TF240_8P_CS",
    "--guide", "component-train",
    "--countdown", "5",
    "--preview"
)

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "MRD_TF240_8P_CS capture failed" }
} finally {
    Pop-Location
}
