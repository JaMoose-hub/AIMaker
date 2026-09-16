# Board Vision - physical UVC camera mode.
# Default index 1 is the current 1920x1080 UVC camera on this workstation.
[CmdletBinding()]
param(
    [int]$DeviceIndex = 1
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

# Keep the checked-in demo configuration synthetic/mock. These overrides are
# inherited by the backend child process and select the physical CV path only
# for this launch.
$env:BOARDVISION_CAMERA__SOURCE = "device"
$env:BOARDVISION_CAMERA__DEVICE_INDEX = [string]$DeviceIndex
$env:BOARDVISION_DETECTOR = "pipeline"

Write-Host "[1/3] Building frontend..."
Push-Location "$root\frontend"
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }
Pop-Location

Write-Host "[2/3] Starting physical camera index $DeviceIndex on http://127.0.0.1:8100 ..."
Start-Process -WorkingDirectory "$root\backend" powershell.exe -ArgumentList @(
    "-NoProfile", "-Command",
    "uv run uvicorn app.main:app --host 127.0.0.1 --port 8100 --timeout-graceful-shutdown 3"
)

Write-Host "[3/3] Waiting for backend, then opening app window..."
$deadline = (Get-Date).AddSeconds(30)
$config = $null
while ((Get-Date) -lt $deadline) {
    try {
        $config = Invoke-RestMethod "http://127.0.0.1:8100/api/config" -TimeoutSec 2
        if ($config.camera_source -eq "device" -and $config.detector -eq "pipeline") { break }
    } catch { Start-Sleep -Milliseconds 500 }
}

if ($null -eq $config -or $config.camera_source -ne "device" -or $config.detector -ne "pipeline") {
    throw "physical camera backend did not become ready"
}

Write-Host "Camera mode ready: source=$($config.camera_source), detector=$($config.detector), index=$DeviceIndex"
Start-Process msedge "--app=http://127.0.0.1:8100"
