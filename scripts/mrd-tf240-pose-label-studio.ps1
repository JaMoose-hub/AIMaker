[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = Join-Path $root ".venv-training\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

$arguments = @(
    "tools\pi5_pose_label_studio.py",
    "--data", "training\mrd-tf240-8p-corner-pose-v1.yaml",
    "--subject", "MRD_TF240_8P_CS",
    "--settings", "training\mrd-tf240-8p-pose-label-studio.json"
)

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "MRD_TF240_8P_CS Pose Label Studio failed" }
} finally {
    Pop-Location
}
