param(
    [string]$Port,
    [switch]$Once,
    [switch]$Json,
    [switch]$AnalogA0
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$arguments = @(
    "run",
    "--project", (Join-Path $projectRoot "backend"),
    "python", (Join-Path $projectRoot "tools\test_serial_gpio.py")
)

if ($Port) {
    $arguments += @("--port", $Port)
}
if ($Once) {
    $arguments += "--once"
}
if ($Json) {
    $arguments += "--json"
}
if ($AnalogA0) {
    $arguments += "--analog-a0"
}

& uv @arguments
exit $LASTEXITCODE
