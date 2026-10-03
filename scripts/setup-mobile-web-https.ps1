param(
    [string]$LanAddress = '',
    [int]$Port = 8443,
    [int]$BackendPort = 8100,
    [string]$CertificateDirectory = ''
)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskBackend = Join-Path $taskRepo 'backend'
$taskPython = Join-Path $taskBackend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw '請先在 backend 執行 uv sync。' }
if ($Port -lt 1 -or $Port -gt 65535 -or $BackendPort -lt 1 -or $BackendPort -gt 65535) { throw '無效的 TCP 埠。' }
if (-not $LanAddress) {
    $taskNetworks = @(Get-NetIPConfiguration | Where-Object {
        $_.IPv4DefaultGateway -and $_.IPv4Address -and $_.NetAdapter.Status -eq 'Up'
    })
    $taskNetwork = $taskNetworks | Where-Object { $_.InterfaceAlias -match 'Wi-Fi|WLAN|Wireless' } | Select-Object -First 1
    if (-not $taskNetwork) { $taskNetwork = $taskNetworks | Select-Object -First 1 }
    if ($taskNetwork) { $LanAddress = [string]($taskNetwork.IPv4Address | Select-Object -First 1).IPAddress }
}
$taskAddress = $null
if (-not [Net.IPAddress]::TryParse($LanAddress, [ref]$taskAddress) -or
    $taskAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
    [Net.IPAddress]::IsLoopback($taskAddress)) { throw '找不到 Wi-Fi IPv4；請用 -LanAddress 指定，例如 192.168.50.141。' }
if (-not $CertificateDirectory) { $CertificateDirectory = Join-Path $taskBackend 'runs\mobile-web-https' }
$taskCertificateDirectory = [IO.Path]::GetFullPath($CertificateDirectory)
Push-Location -LiteralPath $taskBackend
try {
    & $taskPython -m app.mobile_https certificates --directory $taskCertificateDirectory --lan-host $LanAddress
    if ($LASTEXITCODE -ne 0) { throw '建立本機 HTTPS 憑證失敗。' }
} finally { Pop-Location }
$taskConnection = @{
    base_url = "https://${LanAddress}:$Port"
    backend_url = "http://127.0.0.1:$BackendPort"
    port = $Port
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
}
$taskConnectionPath = Join-Path $taskCertificateDirectory 'connection.json'
[IO.File]::WriteAllText($taskConnectionPath, ($taskConnection | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
Write-Host "手機網址：$($taskConnection.base_url)/mobile"
Write-Host "iPhone 首次安裝憑證：http://${LanAddress}:$BackendPort/api/mobile/web-ca-profile"
Write-Host '請在 iPhone 安裝 Tinkro LAN Development CA 描述檔，再到「設定 > 一般 > 關於本機 > 憑證信任設定」啟用完全信任。'
Write-Host '只有 rootCA.der / rootCA.mobileconfig 是給手機的公開憑證；不要傳送任何 *-key.pem。'
Write-Host '此工具沒有安裝 Windows 根憑證、修改防火牆或啟動第二份 Tinkro 後端。'
