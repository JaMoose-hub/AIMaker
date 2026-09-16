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

$arguments = @("tools\pi5_pose_label_studio.py")
if ($Data.Trim().Length -gt 0) {
    $arguments += @("--data", $Data)
}

Push-Location $root
try {
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Pi 5 Pose Label Studio failed" }
} finally {
    Pop-Location
}

