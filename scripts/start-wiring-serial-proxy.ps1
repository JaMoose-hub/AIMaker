$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$localProxy = Join-Path $projectRoot "firmware\uno-q-serial-proxy\serial_proxy.py"
$remoteProxy = "/home/arduino/board-vision-serial-proxy.py"
$bundledAdb = Join-Path $env:LOCALAPPDATA "Arduino15\packages\arduino\tools\adb\32.0.0\adb.exe"

$adbCommand = Get-Command adb -ErrorAction SilentlyContinue
if ($adbCommand) {
    $adb = $adbCommand.Source
} elseif (Test-Path -LiteralPath $bundledAdb) {
    $adb = $bundledAdb
} else {
    throw "adb was not found. Install the Arduino UNO Q board package first."
}

& $adb push $localProxy $remoteProxy
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy the serial proxy to UNO Q."
}

& $adb shell 'if [ -f /tmp/board-vision-serial-proxy.pid ]; then kill $(cat /tmp/board-vision-serial-proxy.pid) 2>/dev/null || true; fi'
& $adb shell 'nohup python3 /home/arduino/board-vision-serial-proxy.py >/tmp/board-vision-serial-proxy.log 2>&1 </dev/null & echo $! >/tmp/board-vision-serial-proxy.pid'
Start-Sleep -Milliseconds 500
& $adb shell 'cat /tmp/board-vision-serial-proxy.log; ps -p $(cat /tmp/board-vision-serial-proxy.pid) -o pid=,cmd='
if ($LASTEXITCODE -ne 0) {
    throw "UNO Q serial proxy did not start."
}
