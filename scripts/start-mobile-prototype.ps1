param(
    [ValidateRange(1, 65535)][int]$Port = 8100,
    [ValidateRange(0, 10)][int]$MaxRestarts = 3,
    [ValidateRange(0, 30)][int]$RestartDelaySeconds = 2,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
$taskRepo = Split-Path -Parent $PSScriptRoot
$taskBackend = Join-Path $taskRepo 'backend'
$taskPython = Join-Path $taskBackend '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '請先在 backend 執行 uv sync，並完成 frontend 的 npm run build。'
}
. (Join-Path $PSScriptRoot 'backend-supervisor.ps1')
$taskLogDirectory = Join-Path $taskBackend 'runs\mobile-backend'
$taskGuard = {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port 已有程式使用；此工具不會停止現有程式或啟動第二份相機。"
    }
    $taskExisting = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'uvicorn\s+[\x22\x27]?app\.main:app(?:\s|[\x22\x27])' }
    if ($taskExisting) {
        throw "已存在 Tinkro app.main 程式 (PID $($taskExisting.ProcessId -join ', '))，即使尚未監聽也不會啟動第二份相機。"
    }
}
if ($CheckOnly) {
    & $taskGuard
    Write-Host "啟動檢查通過：$taskPython；Port $Port；最多重啟 $MaxRestarts 次；記錄 $taskLogDirectory"
    return
}
[IO.Directory]::CreateDirectory($taskLogDirectory) | Out-Null
$taskLock = $null
try {
    # A shared lock prevents two launchers racing before either binds the port.
    $taskLock = [IO.File]::Open((Join-Path $taskLogDirectory 'supervisor.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $taskArguments = @('-u', '-X', 'faulthandler', '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', "$Port", '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1,::1', '--timeout-graceful-shutdown', '3', '--no-access-log', '--log-level', 'warning')
    $taskExitCode = Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments $taskArguments -WorkingDirectory $taskBackend -LogDirectory $taskLogDirectory -BeforeStart $taskGuard -MaxRestarts $MaxRestarts -RestartDelaySeconds $RestartDelaySeconds
    if ($taskExitCode -ne 0) { throw "Tinkro 後端退出，代碼 $taskExitCode；詳見 $taskLogDirectory。" }
} finally {
    if ($taskLock) { $taskLock.Dispose() }
}
