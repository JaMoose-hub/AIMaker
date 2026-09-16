param(
    [ValidateSet("capture", "solve")]
    [string]$Mode = "capture",
    [string]$Source = "http://127.0.0.1:8100/video"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $projectRoot "backend"
$viewsDir = Join-Path $projectRoot "calibration\c920-views"
$outputPath = Join-Path $projectRoot "calibration\c920-1080p.json"

if ($Mode -eq "capture") {
    & (Join-Path $backendDir ".venv\Scripts\python.exe") `
        (Join-Path $projectRoot "tools\capture_camera_calibration.py") `
        --source $Source --out $viewsDir --min-views 20 --width 1920 --height 1080
    exit $LASTEXITCODE
}

& (Join-Path $backendDir ".venv\Scripts\python.exe") `
    (Join-Path $projectRoot "tools\calibrate_camera.py") $viewsDir `
    --output $outputPath --pattern-cols 9 --pattern-rows 6 --square-mm 25 `
    --min-views 20 --max-rms-px 1.2 --max-view-rms-px 2.5 --min-coverage 0.30
exit $LASTEXITCODE
