[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,
    [ValidateSet("train", "val", "test")]
    [string]$Split = "train",
    [string]$Scenario = "powered_led",
    [int]$MaxSamples = 30,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$python = Join-Path $root ".venv-training\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "training Python not found: $python"
}

$argsList = @(
    "tools\label_live_photoresistor_captures.py",
    $SourceDir,
    "--split", $Split,
    "--scenario", $Scenario,
    "--max-samples", "$MaxSamples"
)

if ($DryRun) {
    $argsList += "--dry-run"
}

Push-Location $root
try {
    & $python @argsList
    if ($LASTEXITCODE -ne 0) { throw "live photoresistor labeling failed" }
} finally {
    Pop-Location
}
