[CmdletBinding()]
param(
    [string]$Source = "http://127.0.0.1:8100/video",
    [string]$WebSocketUrl = "ws://127.0.0.1:8100/ws/detections",
    [string]$Out = "datasets\pi5-occlusion-inbox",
    [string]$Session = "",
    [int]$MaxSamples = 160,
    [double]$MaxRuntimeSeconds = 0,
    [double]$CooldownSeconds = 0.8,
    [double]$ConfidenceDrop = 0.18,
    [double]$MotionPitch = 0.45,
    [double]$MinVisibleFraction = 0.75,
    [double]$VisibleFractionDrop = 0.18,
    [double]$MinMeanDiff = 4.0,
    [bool]$AutoCapture = $true,
    [switch]$Headless
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "backend Python not found: $python"
}

$argsList = @(
    "tools\capture_pi5_occlusion_cases.py",
    "--source", $Source,
    "--ws-url", $WebSocketUrl,
    "--out", $Out,
    "--max-samples", "$MaxSamples",
    "--max-runtime-s", "$MaxRuntimeSeconds",
    "--cooldown-s", "$CooldownSeconds",
    "--confidence-drop", "$ConfidenceDrop",
    "--motion-pitch", "$MotionPitch",
    "--min-visible-fraction", "$MinVisibleFraction",
    "--visible-fraction-drop", "$VisibleFractionDrop",
    "--min-mean-diff", "$MinMeanDiff"
)

if ($Session.Trim().Length -gt 0) {
    $argsList += @("--session", $Session)
}
if (-not $AutoCapture) {
    $argsList += "--no-auto"
}
if ($Headless) {
    $argsList += "--headless"
}

Push-Location $root
try {
    & $python @argsList
    if ($LASTEXITCODE -ne 0) { throw "Pi 5 occlusion capture failed" }
} finally {
    Pop-Location
}
