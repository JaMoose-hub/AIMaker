param(
    [int]$Port = 0,
    [string]$CertificateDirectory = ''
)
$ErrorActionPreference = 'Stop'
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
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "HTTPS Port $Port 已有程式使用；此工具不會停止現有程式。" }
if (-not (Test-Path -LiteralPath (Join-Path $taskFrontend 'index.html'))) { throw '請先在 frontend 執行 npm run build。' }
try {
    $taskApi = Invoke-RestMethod "$($taskConnection.backend_url)/openapi.json" -TimeoutSec 5
    if (-not $taskApi.paths.PSObject.Properties['/api/mobile/pair']) { throw '目前後端尚未載入手機 API，請重新啟動現有 8100 後端。' }
} catch { throw "現有 Tinkro 後端無法使用：$($_.Exception.Message)" }
if ($Port -ne [int]$taskConnection.port) {
    $taskBase = [UriBuilder]::new([string]$taskConnection.base_url)
    $taskBase.Port = $Port
    $taskConnection.base_url = $taskBase.Uri.GetLeftPart([UriPartial]::Authority)
    $taskConnection.port = $Port
    [IO.File]::WriteAllText($taskConnectionPath, ($taskConnection | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
Write-Host "手機用 Safari 開啟：$($taskConnection.base_url)/mobile"
Write-Host 'HTTPS proxy 只提供手機介面與手機 API；Ctrl+C 只關閉 proxy，不會關閉 8100 後端或相機。'
Push-Location -LiteralPath $taskBackend
try {
    & $taskPython -m app.mobile_https serve --directory $taskCertificateDirectory --frontend $taskFrontend --upstream $taskConnection.backend_url --port $Port
    if ($LASTEXITCODE -ne 0) { throw "HTTPS proxy 退出，代碼 $LASTEXITCODE" }
} finally { Pop-Location }
