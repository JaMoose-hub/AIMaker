# Isolated subprocess checks: no app.main, cameras, network or live service.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'backend-supervisor.ps1')
$taskPython = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\.venv\Scripts\python.exe'
$taskTemporary = Join-Path ([IO.Path]::GetTempPath()) ('tinkro-supervisor-test-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($taskTemporary) | Out-Null
function Assert-Check($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Read-Events([string]$Directory) { Get-ChildItem -LiteralPath $Directory -Filter '*events.jsonl' | Get-Content | ForEach-Object { $_ | ConvertFrom-Json } }
try {
    $taskFail = Join-Path $taskTemporary 'fail.py'
    [IO.File]::WriteAllText($taskFail, "import sys`nprint('stdout evidence')`nprint('stderr evidence', file=sys.stderr)`nsys.exit(17)`n")
    $taskFailLogs = Join-Path $taskTemporary 'failed'
    $taskCode = Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskFail) -WorkingDirectory $taskTemporary -LogDirectory $taskFailLogs -BeforeStart {} -MaxRestarts 2 -RestartDelaySeconds 0
    $taskEvents = @(Read-Events $taskFailLogs)
    $taskExits = @($taskEvents | Where-Object event -eq 'exited')
    Assert-Check ($taskCode -eq 17 -and $taskExits.Count -eq 3) 'Failed child must exit after exactly two restarts.'
    Assert-Check ($taskExits[0].exit_hex -eq '0x00000011' -and $taskExits[-1].reason -eq 'restart_limit_reached' -and -not $taskExits[-1].restart) 'Exit codes and restart exhaustion must remain visible.'
    Assert-Check ((Get-Content -LiteralPath $taskExits[0].stdout -Raw) -match 'stdout evidence') 'stdout was not recorded.'
    Assert-Check ((Get-Content -LiteralPath $taskExits[0].stderr -Raw) -match 'stderr evidence') 'stderr was not recorded.'
    $taskSuccess = Join-Path $taskTemporary 'success.py'
    [IO.File]::WriteAllText($taskSuccess, "print('normal stop')`n")
    $taskSuccessLogs = Join-Path $taskTemporary 'success'
    $taskCode = Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskSuccess) -WorkingDirectory $taskTemporary -LogDirectory $taskSuccessLogs -BeforeStart {} -MaxRestarts 2 -RestartDelaySeconds 0
    Assert-Check ($taskCode -eq 0 -and @((Read-Events $taskSuccessLogs) | Where-Object event -eq 'exited').Count -eq 1) 'Successful child must never restart.'
    $taskBlockedLogs = Join-Path $taskTemporary 'blocked'
    $taskBlocked = $false
    try { Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskFail) -WorkingDirectory $taskTemporary -LogDirectory $taskBlockedLogs -BeforeStart { throw 'existing backend' } -MaxRestarts 2 -RestartDelaySeconds 0 | Out-Null }
    catch { $taskBlocked = $_.Exception.Message -eq 'existing backend' }
    Assert-Check ($taskBlocked -and @(Read-Events $taskBlockedLogs).Count -eq 1 -and @(Get-ChildItem -LiteralPath $taskBlockedLogs -Filter '*.log').Count -eq 0) 'Existing backend must block launch without starting a child.'
    $taskGuardLogs = Join-Path $taskTemporary 'guard-between-restarts'
    $taskGuardState = @{ count = 0 }
    $taskGuarded = $false
    try { Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskFail) -WorkingDirectory $taskTemporary -LogDirectory $taskGuardLogs -BeforeStart { $taskGuardState.count += 1; if ($taskGuardState.count -gt 1) { throw 'backend appeared during backoff' } } -MaxRestarts 2 -RestartDelaySeconds 0 | Out-Null }
    catch { $taskGuarded = $_.Exception.Message -eq 'backend appeared during backoff' }
    Assert-Check ($taskGuarded -and @((Read-Events $taskGuardLogs) | Where-Object event -eq 'starting').Count -eq 1) 'A new existing backend must block the next restart.'
    $taskDelays = [Collections.Generic.List[int]]::new()
    function Start-Sleep { param([int]$Seconds) $taskDelays.Add($Seconds) }
    $taskBackoffLogs = Join-Path $taskTemporary 'backoff'
    $taskCode = Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskFail) -WorkingDirectory $taskTemporary -LogDirectory $taskBackoffLogs -BeforeStart {} -MaxRestarts 3 -RestartDelaySeconds 2
    Assert-Check ($taskCode -eq 17 -and ($taskDelays -join ',') -eq '2,4,8') 'Restart backoff must be bounded 2,4,8 seconds.'
    $taskInterrupted = Join-Path $taskTemporary 'interrupted.py'
    [IO.File]::WriteAllText($taskInterrupted, "import sys`nsys.exit(130)`n")
    $taskInterruptLogs = Join-Path $taskTemporary 'interrupted'
    $taskCode = Invoke-TinkroBackendSupervisor -PythonExecutable $taskPython -PythonArguments @('-u', $taskInterrupted) -WorkingDirectory $taskTemporary -LogDirectory $taskInterruptLogs -BeforeStart {} -MaxRestarts 3 -RestartDelaySeconds 2
    Assert-Check ($taskCode -eq 130 -and @((Read-Events $taskInterruptLogs) | Where-Object event -eq 'exited').Count -eq 1 -and $taskDelays.Count -eq 3) 'Interrupted child must not restart or wait.'
    Write-Host 'PASS: bounded restart, exit diagnostics, stdout/stderr, normal stop, pre-start guard, between-attempt guard, 2/4/8 backoff, interrupted stop.'
} finally {
    # Keep any failed-test diagnostics; avoid deleting computed temporary paths.
    Write-Host "測試記錄：$taskTemporary"
}
