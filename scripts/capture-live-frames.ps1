[CmdletBinding()]
param(
    [string]$Scenario = "powered_led",
    [string]$Source = "http://127.0.0.1:8100/video",
    [string]$Out = "datasets\live-captures",
    [string]$Session = "",
    [int]$MaxSamples = 60,
    [double]$IntervalSeconds = 0.75,
    [double]$MinMeanDiff = 0.8,
    [int]$MaxSimilarSkip = 4,
    [double]$MaxRuntimeSeconds = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

$argsList = @(
    "tools\capture_live_frames.py",
    "--source", $Source,
    "--out", $Out,
    "--scenario", $Scenario,
    "--max-samples", "$MaxSamples",
    "--interval-s", "$IntervalSeconds",
    "--min-mean-diff", "$MinMeanDiff",
    "--max-similar-skip", "$MaxSimilarSkip",
    "--max-runtime-s", "$MaxRuntimeSeconds"
)

if ($Session.Trim().Length -gt 0) {
    $argsList += @("--session", $Session)
}

Push-Location $root
try {
    & $python @argsList
    if ($LASTEXITCODE -ne 0) { throw "live frame capture failed" }
} finally {
    Pop-Location
}
