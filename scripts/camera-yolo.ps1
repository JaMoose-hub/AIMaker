# Board Vision - physical C920 camera + YOLO/Profile hybrid mode.
[CmdletBinding()]
param(
    [ValidateSet("raspberry-pi-5", "arduino-uno-q")]
    [string]$Board = "raspberry-pi-5",
    # Device indices are backend-specific on this host: the C920 is DShow 1
    # but MSMF 0. MSMF delivers a real 30 FPS stream; DShow silently falls
    # back to 1080p YUY2, which this camera exposes at only 5 FPS.
    [int]$DeviceIndex = 1,
    [ValidateSet("dshow", "msmf")]
    [string]$CaptureApi = "dshow",
    [ValidateSet("opencv", "ffmpeg")]
    [string]$CaptureBackend = "ffmpeg",
    [string]$FfmpegDeviceName = "HD Pro Webcam C920",
    [string]$FfmpegPath = "ffmpeg",
    [int]$Width = 1920,
    [int]$Height = 1080,
    # The UI/camera stay at 1080p. Only the square tensor sent to YOLO is
    # resized. Keep the switch explicit so each trained model can retain the
    # smallest input that passes both recall and the 12 Hz runtime gate.
    [ValidateSet(640, 768, 832, 896, 928, 960)]
    [int]$YoloInputSize = 960,
    [ValidateSet("cuda", "opencv", "directml")]
    [string]$RuntimeBackend = "cuda",
    [int]$CudaDeviceId = 0,
    [int]$DirectMlDeviceId = 1,
    # 9 px/pitch remains the recommended framing target.  The live C920
    # setup sits around 8.3-8.6 px/pitch at 720p, so use a slightly lower
    # hard stop and let endpoint ambiguity checks reject unsafe assignments.
    [double]$MinPinPitchPx = 8.0,
    [double]$MinPxPerMm = 3.1,
    [string]$ModelPath = "",
    [ValidateSet("photoresistor-module", "hc-sr04", "mrd-tf240-8p-cs")]
    [string]$Component = "mrd-tf240-8p-cs",
    [string]$ComponentModelPath = "",
    [string]$ComponentProfilePath = "",
    [switch]$ElectricalVerification,
    [switch]$UsePi5EightPointPose,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
if (-not $ModelPath) {
    $ModelPath = if ($Board -eq "raspberry-pi-5") {
        "$root\models\board-pose-pi5-handheld-v2.onnx"
    } else {
        "$root\models\board-pose.onnx"
    }
}
if (-not $ComponentModelPath) {
    $ComponentModelPath = switch ($Component) {
        "hc-sr04" { "$root\models\hc-sr04-corner-pose-v3-robust.onnx" }
        "mrd-tf240-8p-cs" { "$root\models\mrd-tf240-8p-cs-pose.onnx" }
        default { "$root\models\photoresistor-pose.onnx" }
    }
}
if (-not $ComponentProfilePath) {
    $ComponentProfilePath = "$root\profiles\components\$Component\vision_profile.json"
}
$componentInputSize = switch ($Component) {
    "mrd-tf240-8p-cs" { 1280 }
    default { 768 }
}
$componentConfidence = switch ($Component) {
    "hc-sr04" { 0.25 }
    "mrd-tf240-8p-cs" { 0.20 }
    default { 0.35 }
}
$componentKeypointConfidence = switch ($Component) {
    "hc-sr04" { 0.20 }
    "mrd-tf240-8p-cs" { 0.15 }
    default { 0.25 }
}

$componentModelPaths = @{
    "photoresistor-module" = "$root\models\photoresistor-pose.onnx"
    "hc-sr04" = "$root\models\hc-sr04-corner-pose-v3-robust.onnx"
    "mrd-tf240-8p-cs" = "$root\models\mrd-tf240-8p-cs-pose.onnx"
}
$componentProfilePaths = @{
    "photoresistor-module" = "$root\profiles\components\photoresistor-module\vision_profile.json"
    "hc-sr04" = "$root\profiles\components\hc-sr04\vision_profile.json"
    "mrd-tf240-8p-cs" = "$root\profiles\components\mrd-tf240-8p-cs\vision_profile.json"
}
$componentInputSizes = @{
    "photoresistor-module" = 768
    "hc-sr04" = 768
    "mrd-tf240-8p-cs" = 1280
}
$componentConfidenceThresholds = @{
    "photoresistor-module" = 0.35
    "hc-sr04" = 0.25
    "mrd-tf240-8p-cs" = 0.20
}
$componentKeypointThresholds = @{
    "photoresistor-module" = 0.25
    "hc-sr04" = 0.20
    "mrd-tf240-8p-cs" = 0.15
}
$componentReacquireFractions = @{
    "photoresistor-module" = 0.45
    "hc-sr04" = 0.25
    "mrd-tf240-8p-cs" = 0.08
}
$componentModelPaths[$Component] = $ComponentModelPath
$componentProfilePaths[$Component] = $ComponentProfilePath
$componentTargetIds = @(
    "hc-sr04",
    "mrd-tf240-8p-cs"
)
if (
    $PSBoundParameters.ContainsKey("Component") -and
    -not ($componentTargetIds -contains $Component)
) {
    # The default component-inspection demo should not show the photoresistor
    # AO overlay.  Keep it available when explicitly launching that guide.
    $componentTargetIds = @($Component) + $componentTargetIds
}
$componentTargets = $componentTargetIds | ForEach-Object {
    [ordered]@{
        id = $_
        model_path = $componentModelPaths[$_]
        profile_path = $componentProfilePaths[$_]
        input_size = $componentInputSizes[$_]
        confidence_threshold = $componentConfidenceThresholds[$_]
        keypoint_threshold = $componentKeypointThresholds[$_]
        interval_s = 0.30
        reacquire_min_visible_fraction = $componentReacquireFractions[$_]
    }
}

$env:BOARDVISION_CAMERA__SOURCE = "device"
$env:BOARDVISION_CAMERA__DEVICE_INDEX = [string]$DeviceIndex
$env:BOARDVISION_CAMERA__CAPTURE_API = $CaptureApi
$env:BOARDVISION_CAMERA__CAPTURE_BACKEND = $CaptureBackend
$env:BOARDVISION_CAMERA__FFMPEG_DEVICE_NAME = $FfmpegDeviceName
$env:BOARDVISION_CAMERA__FFMPEG_PATH = $FfmpegPath
$env:BOARDVISION_CAMERA__WIDTH = [string]$Width
$env:BOARDVISION_CAMERA__HEIGHT = [string]$Height
$env:BOARDVISION_DETECTOR = "hybrid"
$env:BOARDVISION_BOARD = $Board
$env:BOARDVISION_YOLO_POSE__MODEL_PATH = $ModelPath
# Preserve a model for both controllers so the UI can hot-switch without
# restarting C920/FFmpeg. A caller-supplied model overrides only the selected
# board; the other controller keeps its validated default.
$boardModelPaths = @{
    "raspberry-pi-5" = "$root\models\board-pose-pi5-handheld-v2.onnx"
    "arduino-uno-q" = "$root\models\board-pose.onnx"
}
$boardModelPaths[$Board] = $ModelPath
$env:BOARDVISION_YOLO_POSE__BOARD_MODEL_PATHS = ($boardModelPaths | ConvertTo-Json -Compress)
$board8ptModelPaths = @{}
if ($UsePi5EightPointPose) {
    $board8ptModelPaths["raspberry-pi-5"] = "$root\models\board-pose-pi5-8kpt-synth-negative-pilot.onnx"
}
$env:BOARDVISION_YOLO_POSE__BOARD_8PT_MODEL_PATHS = ($board8ptModelPaths | ConvertTo-Json -Compress)
$env:BOARDVISION_YOLO_POSE__RUNTIME_BACKEND = $RuntimeBackend
$env:BOARDVISION_YOLO_POSE__CUDA_DEVICE_ID = [string]$CudaDeviceId
$env:BOARDVISION_YOLO_POSE__INPUT_SIZE = [string]$YoloInputSize
$env:BOARDVISION_YOLO_POSE__DIRECTML_DEVICE_ID = [string]$DirectMlDeviceId
$env:BOARDVISION_COMPONENT_VISION__ENABLED = "true"
$env:BOARDVISION_COMPONENT_VISION__MODEL_PATH = $ComponentModelPath
$env:BOARDVISION_COMPONENT_VISION__PROFILE_PATH = $ComponentProfilePath
$env:BOARDVISION_COMPONENT_VISION__INPUT_SIZE = [string]$componentInputSize
$env:BOARDVISION_COMPONENT_VISION__CONFIDENCE_THRESHOLD = [string]$componentConfidence
$env:BOARDVISION_COMPONENT_VISION__KEYPOINT_THRESHOLD = [string]$componentKeypointConfidence
$env:BOARDVISION_COMPONENT_VISION__PRIMARY_COMPONENT_ID = $Component
$env:BOARDVISION_COMPONENT_VISION__COMPONENTS = ($componentTargets | ConvertTo-Json -Compress)
$env:BOARDVISION_COMPONENT_VISION__RUNTIME_BACKEND = $RuntimeBackend
$env:BOARDVISION_COMPONENT_VISION__CUDA_DEVICE_ID = [string]$CudaDeviceId
$env:BOARDVISION_COMPONENT_VISION__DIRECTML_DEVICE_ID = [string]$DirectMlDeviceId
$env:BOARDVISION_COMPONENT_VISION__INTERVAL_S = "0.30"
# HC-SR04's two metal transducers cover most of its small blue PCB, so its
# normal visible-blue fraction is lower than the photoresistor module's. Keep
# the conservative tracker gate component-specific so a clear HC-SR04 can
# reacquire after being moved without weakening the photoresistor hold logic.
$componentReacquireVisibleFraction = switch ($Component) {
    "hc-sr04" { 0.25 }
    # The display covers most of the PCB inside the four mounting holes, so
    # its normal blue-fill ratio is intentionally much lower than a sensor.
    "mrd-tf240-8p-cs" { 0.08 }
    default { 0.45 }
}
$env:BOARDVISION_COMPONENT_VISION__REACQUIRE_MIN_VISIBLE_FRACTION = [string]$componentReacquireVisibleFraction
# The current teaching flow uses VLM for connector appearance and Serial for
# electrical proof. Keep the experimental color/skeleton wire recognizer off
# so it cannot add stale candidates or interfere with the guide.
$env:BOARDVISION_WIRE_TRACE__ENABLED = "false"
$env:BOARDVISION_WIRE_TRACE__MIN_PIN_PITCH_PX = [string]$MinPinPitchPx
$env:BOARDVISION_WIRE_TRACE__MIN_PX_PER_MM = [string]$MinPxPerMm
$env:BOARDVISION_VLM__ENABLED = "true"
$env:BOARDVISION_VLM__PROVIDER = "ollama"
$env:BOARDVISION_VLM__MODEL = "qwen3-vl:8b"
$env:BOARDVISION_VLM__TIMEOUT_S = "25"
$env:BOARDVISION_VLM__INSERTION_ENABLED = "true"
$env:BOARDVISION_ELECTRICAL_VERIFICATION__ENABLED = if ($ElectricalVerification) { "true" } else { "false" }
if ($CaptureApi -eq "msmf") {
    # Avoid MSMF's slow hardware-transform enumeration during camera startup.
    $env:OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS = "0"
}

if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    Write-Warning "YOLO model not found at $ModelPath; this launch will use the existing feature-pipeline fallback."
}
if (-not (Test-Path -LiteralPath $ComponentModelPath -PathType Leaf)) {
    throw "$Component pose model not found at $ComponentModelPath"
}
if (-not (Test-Path -LiteralPath $ComponentProfilePath -PathType Leaf)) {
    throw "$Component vision profile not found at $ComponentProfilePath"
}
foreach ($target in $componentTargets) {
    if (-not (Test-Path -LiteralPath $target.model_path -PathType Leaf)) {
        throw "$($target.id) pose model not found at $($target.model_path)"
    }
    if (-not (Test-Path -LiteralPath $target.profile_path -PathType Leaf)) {
        throw "$($target.id) vision profile not found at $($target.profile_path)"
    }
}
if ($CaptureBackend -eq "ffmpeg" -and -not (Get-Command $FfmpegPath -ErrorAction SilentlyContinue)) {
    throw "FFmpeg executable not found: $FfmpegPath"
}

Write-Host "[1/4] Building frontend..."
Push-Location "$root\frontend"
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "frontend build failed" }
Pop-Location

Write-Host "[2/4] Stopping existing Board Vision backend (if any)..."
$listener = Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($null -ne $listener) {
    $existingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
    $commandLine = [string]$existingProcess.CommandLine
    if ($commandLine -notlike "*board-vision*" -or $commandLine -notlike "*uvicorn*8100*") {
        throw "Port 8100 is occupied by an unexpected process; refusing to stop it: $commandLine"
    }
    Stop-Process -Id $listener.OwningProcess -Force
    $waitUntil = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $waitUntil -and (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue)) {
        Start-Sleep -Milliseconds 200
    }
    if (Get-NetTCPConnection -LocalPort 8100 -State Listen -ErrorAction SilentlyContinue) {
        throw "Existing Board Vision backend did not release port 8100"
    }
}

Write-Host "[3/4] Starting $Board hybrid detector with camera index $DeviceIndex ($CaptureBackend/$CaptureApi, ${Width}x${Height}) ..."
$runtimeGroupArgs = switch ($RuntimeBackend) {
    "directml" { "--no-group cuda --group directml" }
    "opencv" { "--no-group cuda" }
    default { "--group cuda" }
}
Start-Process -WindowStyle Hidden -WorkingDirectory "$root\backend" powershell.exe -ArgumentList @(
    "-NoProfile", "-Command",
    "uv run $runtimeGroupArgs uvicorn app.main:app --host 127.0.0.1 --port 8100 --timeout-graceful-shutdown 3"
)

Write-Host "[4/4] Waiting for backend, then opening app window..."
$deadline = (Get-Date).AddSeconds(30)
$config = $null
while ((Get-Date) -lt $deadline) {
    try {
        $config = Invoke-RestMethod "http://127.0.0.1:8100/api/config" -TimeoutSec 2
        if ($config.camera_source -eq "device" -and $config.detector -eq "hybrid" -and $config.camera_capture_backend -eq $CaptureBackend) { break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if ($null -eq $config -or $config.detector -ne "hybrid" -or $config.camera_capture_backend -ne $CaptureBackend) {
    throw "hybrid camera backend did not become ready"
}
Write-Host "Hybrid mode ready: profile=$Board, camera=$DeviceIndex, capture=$CaptureBackend/$CaptureApi, video=${Width}x${Height}, YOLO=${YoloInputSize}x${YoloInputSize}, requestedRuntime=$RuntimeBackend, CUDA=$CudaDeviceId, DirectML=$DirectMlDeviceId, gate=${MinPinPitchPx}px/${MinPxPerMm}px-mm, model=$ModelPath, component=$Component, componentModel=$ComponentModelPath, componentProfile=$ComponentProfilePath. Actual providers: /api/inference/status"
if (-not $NoOpen) {
    Start-Process msedge "--app=http://127.0.0.1:8100"
}
