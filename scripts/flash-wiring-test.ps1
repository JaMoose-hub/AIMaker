param(
    [string]$Port = "COM3",
    [switch]$CompileOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sketchPath = Join-Path $projectRoot "firmware\wiring-test-fw"
$buildPath = Join-Path ([System.IO.Path]::GetTempPath()) "board-vision-wiring-test-fw"
$arduinoConfig = Join-Path $projectRoot "firmware\arduino-cli-board-vision.yaml"
$projectLibraries = Join-Path $projectRoot ".arduino-user\libraries"
$bundledCli = "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"

$cliCommand = Get-Command arduino-cli -ErrorAction SilentlyContinue
if ($cliCommand) {
    $arduinoCli = $cliCommand.Source
} elseif (Test-Path -LiteralPath $bundledCli) {
    $arduinoCli = $bundledCli
} else {
    throw "arduino-cli was not found. Install Arduino IDE 2 first."
}

$libraryArguments = @()
if (Test-Path -LiteralPath $projectLibraries) {
    $libraryArguments = @("--libraries", $projectLibraries)
}

Write-Host "Compiling UNO Q electrical verification firmware..."
& $arduinoCli --config-file $arduinoConfig compile --fqbn arduino:zephyr:unoq --build-path $buildPath @libraryArguments $sketchPath
if ($LASTEXITCODE -ne 0) {
    throw "Firmware compilation failed."
}

if ($CompileOnly) {
    Write-Host "Compile check complete; nothing was uploaded."
    exit 0
}

Write-Host "Uploading to Arduino UNO Q ($Port)..."
$boardList = & $arduinoCli --config-file $arduinoConfig board list --format json | ConvertFrom-Json
$detectedPort = @($boardList.detected_ports | Where-Object { $_.port.address -eq $Port }) | Select-Object -First 1
$serialNumber = [string]$detectedPort.port.properties.serialNumber
if ([string]::IsNullOrWhiteSpace($serialNumber)) {
    throw "UNO Q ADB serial number was not found for $Port. Reconnect the board, then try again."
}

# UNO Q uploads travel over the board's ADB channel, not the Windows COM
# monitor alone. Arduino CLI does not preserve discovery properties when an
# explicit COM port is supplied, so provide the detected device serial here.
& $arduinoCli --config-file $arduinoConfig upload --port $Port --upload-property "serialNumber=$serialNumber" --fqbn arduino:zephyr:unoq --build-path $buildPath $sketchPath
if ($LASTEXITCODE -ne 0) {
    throw "Firmware upload failed."
}

Write-Host "Upload complete."
