# Helper only: dot-sourcing this file never starts a process.
function Invoke-TinkroBackendSupervisor {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$PythonExecutable,
        [Parameter(Mandatory)][string[]]$PythonArguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string]$LogDirectory,
        [Parameter(Mandatory)][scriptblock]$BeforeStart,
        [ValidateRange(0, 10)][int]$MaxRestarts = 3,
        [ValidateRange(0, 30)][int]$RestartDelaySeconds = 2
    )
    [IO.Directory]::CreateDirectory($LogDirectory) | Out-Null
    $taskRun = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
    $taskEvents = Join-Path $LogDirectory "$taskRun-events.jsonl"
    $taskAttempt = 0
    while ($true) {
        $taskStdout = Join-Path $LogDirectory "$taskRun-attempt-$taskAttempt.stdout.log"
        $taskStderr = Join-Path $LogDirectory "$taskRun-attempt-$taskAttempt.stderr.log"
        try { & $BeforeStart | Out-Null }
        catch {
            $taskEvent = [ordered]@{ time = [DateTimeOffset]::Now.ToString('o'); event = 'start_blocked'; attempt = $taskAttempt; error = $_.Exception.Message }
            [IO.File]::AppendAllText($taskEvents, (($taskEvent | ConvertTo-Json -Compress) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
            throw
        }
        $taskEvent = [ordered]@{ time = [DateTimeOffset]::Now.ToString('o'); event = 'starting'; attempt = $taskAttempt; stdout = $taskStdout; stderr = $taskStderr }
        [IO.File]::AppendAllText($taskEvents, (($taskEvent | ConvertTo-Json -Compress) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
        Write-Host "Tinkro 啟動：第 $($taskAttempt + 1) 次；診斷 $taskEvents"
        # Run in this terminal so Ctrl+C reaches Python. Keep raw stdout/stderr
        # separate, and preserve the caller's environment and camera settings.
        $taskOriginalPreference = $ErrorActionPreference
        Push-Location -LiteralPath $WorkingDirectory
        try {
            $ErrorActionPreference = 'Continue'
            & $PythonExecutable @PythonArguments 1> $taskStdout 2> $taskStderr
            $taskExitCode = [int]$LASTEXITCODE
        } finally {
            $ErrorActionPreference = $taskOriginalPreference
            Pop-Location
        }
        $taskExitHex = '0x{0:X8}' -f [BitConverter]::ToUInt32([BitConverter]::GetBytes($taskExitCode), 0)
        $taskNormalStop = $taskExitCode -in @(0, 130, -1073741510)
        $taskRestart = -not $taskNormalStop -and $taskAttempt -lt $MaxRestarts
        $taskDelay = if ($taskRestart) { [int][Math]::Min(30, $RestartDelaySeconds * [Math]::Pow(2, $taskAttempt)) } else { 0 }
        $taskReason = if ($taskNormalStop) { 'normal_or_interrupted_stop' } elseif ($taskRestart) { 'unexpected_exit' } else { 'restart_limit_reached' }
        $taskEvent = [ordered]@{ time = [DateTimeOffset]::Now.ToString('o'); event = 'exited'; attempt = $taskAttempt; exit_code = $taskExitCode; exit_hex = $taskExitHex; restart = $taskRestart; delay_seconds = $taskDelay; reason = $taskReason; stdout = $taskStdout; stderr = $taskStderr }
        [IO.File]::AppendAllText($taskEvents, (($taskEvent | ConvertTo-Json -Compress) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
        Write-Host "Tinkro 退出：$taskExitCode ($taskExitHex)；$taskReason；stderr: $taskStderr"
        if (-not $taskRestart) { return $taskExitCode }
        Write-Host "$taskDelay 秒後重啟；Ctrl+C 結束監督。工作階段會因後端重啟失效，聊天與照片保存不變。"
        if ($taskDelay -gt 0) { Start-Sleep -Seconds $taskDelay }
        $taskAttempt += 1
    }
}
