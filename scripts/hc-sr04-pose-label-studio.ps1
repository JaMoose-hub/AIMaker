[CmdletBinding()]
param(
    [string]$Data = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = Join-Path $root ".venv-training\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}
if ($Data.Trim().Length -eq 0) {
    $Data = Join-Path $root "training\hc-sr04-pose.yaml"
}

$arguments = @(
    "tools\pi5_pose_label_studio.py",
    "--data", $Data,
    "--subject", "HC-SR04",
    "--settings", (Join-Path $root "training\hc-sr04-pose-label-studio.json"),
    "--default-model", (Join-Path $root "models\hc-sr04-pose.pt")
)

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "HC-SR04 Pose Label Studio failed" }
} finally {
    Pop-Location
}
