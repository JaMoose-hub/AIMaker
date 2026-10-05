param(
    [int]$Port = 0,
    [string]$CertificateDirectory = ''
)
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw '此網路監測器需要 PowerShell 7；請用 pwsh -File .\scripts\start-mobile-web.ps1 重新開啟。尚未啟動 gateway。' }
. (Join-Path $PSScriptRoot 'mobile-web-network.ps1')
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskBackend = Join-Path $taskRepo 'backend'
$taskPython = Join-Path $taskBackend '.venv\Scripts\python.exe'
$taskFrontend = Join-Path $taskRepo 'frontend\dist'
if (-not $CertificateDirectory) { $CertificateDirectory = Join-Path $taskBackend 'runs\mobile-web-https' }
$taskCertificateDirectory = [IO.Path]::GetFullPath($CertificateDirectory)
$taskConnectionPath = Join-Path $taskCertificateDirectory 'connection.json'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '請先在 backend 執行 uv sync。' }
if (-not (Test-Path -LiteralPath $taskConnectionPath)) { throw '請先執行 .\scripts\setup-mobile-web-https.ps1。' }
$taskConnection = Get-Content -LiteralPath $taskConnectionPath -Raw | ConvertFrom-Json
if ($Port -eq 0) { $Port = [int]$taskConnection.port }
if ($Port -lt 1 -or $Port -gt 65535) { throw '無效的 HTTPS 埠。' }
Assert-TinkroMobilePortFree $Port
if (-not (Test-Path -LiteralPath (Join-Path $taskFrontend 'index.html'))) { throw '請先在 frontend 執行 npm run build。' }
try {
    $taskApi = Invoke-RestMethod "$($taskConnection.backend_url)/openapi.json" -TimeoutSec 5
    if (-not $taskApi.paths.PSObject.Properties['/api/mobile/pair']) { throw '目前後端尚未載入手機 API，請重新啟動現有 8100 後端。' }
} catch { throw "現有 Tinkro 後端無法使用：$($_.Exception.Message)" }
Write-Host '每 5 秒偵測 Wi-Fi（其次實體 Ethernet），IP 連續兩次一致才啟動 HTTPS gateway。'
Write-Host 'Ctrl+C 只結束此監測器及其自有 gateway；不會關閉 8100 後端或相機。'
$taskLock = $null
$taskNetworkState = New-TinkroMobileNetworkState
$taskLastEvent = ''
try {
    $taskLock = Enter-TinkroMobilePortLock $Port
    Assert-TinkroMobilePortFree $Port
    while ($true) {
        $taskObservation = Invoke-TinkroMobileNetworkPoll -State $taskNetworkState -GetAddress { Get-TinkroMobileLanAddress } -StartGateway {
                param($address)
                Start-TinkroOwnedGateway -Python $taskPython -Backend $taskBackend -Frontend $taskFrontend -Directory $taskCertificateDirectory -Address $address -Port $Port -Upstream $taskConnection.backend_url -Owner $taskNetworkState
        }
        $taskEvent = $taskObservation.Event
        $taskAddress = $taskObservation.Address
        $taskEventKey = "$taskEvent|$($taskObservation.Error)"
        if ($taskEventKey -ne $taskLastEvent) {
            Write-TinkroMobileNetworkEvent $taskCertificateDirectory $taskEvent $taskAddress
            if ($taskEvent -eq 'started') { Write-Host "手機用 Safari 開啟：https://${taskAddress}:$Port/mobile" }
            elseif ($taskEvent -eq 'offline') { Write-Host '沒有可用的實體 LAN；已停止自有 gateway，等待網路恢復。' }
            elseif ($taskEvent -eq 'probe_failed') { Write-Host '暫時無法讀取網路狀態；保留自有 gateway，5 秒後重試。' }
            elseif ($taskEvent -eq 'start_failed') { Write-Host "手機 HTTPS 尚未可用：$($taskObservation.Error)" }
            $taskLastEvent = $taskEventKey
        }
        Limit-TinkroMobileGatewayLogs $taskCertificateDirectory
        Start-Sleep -Seconds 5
    }
} finally {
    try { if ($taskNetworkState.Process) { Stop-TinkroOwnedGateway $taskNetworkState.Process } }
    finally { if ($taskLock) { $taskLock.Dispose() } }
}
