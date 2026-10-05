# Dot-sourcing defines helpers only; no processes or network changes.
function Get-TinkroMobileLanAddress {
    param([object[]]$Configurations, [object[]]$Adapters)
    if (-not $PSBoundParameters.ContainsKey('Configurations')) { $Configurations = @(Get-NetIPConfiguration) }
    if (-not $PSBoundParameters.ContainsKey('Adapters')) { $Adapters = @(Get-NetAdapter -Physical) }
    $candidates = foreach ($adapter in $Adapters) {
        if ($adapter.Status -ne 'Up' -or -not $adapter.HardwareInterface -or $adapter.Virtual) { continue }
        foreach ($network in $Configurations) {
            if ($network.InterfaceIndex -ne $adapter.InterfaceIndex -or -not $network.IPv4DefaultGateway) { continue }
            foreach ($entry in $network.IPv4Address) {
                $address = $null
                if (-not [Net.IPAddress]::TryParse([string]$entry.IPAddress, [ref]$address)) { continue }
                if ($address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or
                    [Net.IPAddress]::IsLoopback($address) -or $address.ToString().StartsWith('169.254.') -or
                    $address.GetAddressBytes()[0] -eq 0 -or $address.GetAddressBytes()[0] -ge 224) { continue }
                [pscustomobject]@{ Address = $address.ToString(); Priority = $(if ($adapter.NdisPhysicalMedium -eq 9 -or $adapter.Name -match 'Wi-Fi|WLAN|Wireless') { 0 } else { 1 }); Index = [int]$adapter.InterfaceIndex }
            }
        }
    }
    $selected = $candidates | Sort-Object Priority, Index, Address | Select-Object -First 1
    if ($selected) { return [string]$selected.Address }
    return $null
}

function New-TinkroMobileNetworkState {
    return @{ Candidate = $null; Samples = 0; ActiveAddress = $null; Process = $null }
}

function Stop-TinkroOwnedGateway {
    param([Parameter(Mandatory)]$Process)
    # The venv launcher can own another Python process. Keep this exact handle;
    # never locate/kill an arbitrary process by its port, name or recycled PID.
    if (-not $Process.HasExited) {
        $Process.Kill($true)
        if (-not $Process.WaitForExit(5000)) { throw '自有 HTTPS gateway 未結束；不會啟動第二份。' }
    }
    $Process.Dispose()
}

function Update-TinkroMobileNetwork {
    param([Parameter(Mandatory)][hashtable]$State, [AllowNull()][string]$Address,
        [Parameter(Mandatory)][scriptblock]$StartGateway,
        [scriptblock]$StopGateway = { param($child) Stop-TinkroOwnedGateway $child })
    if (-not $Address) {
        $State.Candidate = $null; $State.Samples = 0
        if ($State.Process) { & $StopGateway $State.Process; $State.Process = $null }
        $State.ActiveAddress = $null
        return 'offline'
    }
    if ($State.Candidate -eq $Address) { $State.Samples = [Math]::Min(2, $State.Samples + 1) }
    else { $State.Candidate = $Address; $State.Samples = 1 }
    if ($State.Samples -lt 2) { return 'confirming' }
    if ($State.Process -and -not $State.Process.HasExited -and $State.ActiveAddress -eq $Address) { return 'unchanged' }
    if ($State.Process) { & $StopGateway $State.Process; $State.Process = $null }
    $State.ActiveAddress = $null
    # StartGateway must clean up a failed/partially started child before throwing.
    $State.Process = & $StartGateway $Address
    if (-not $State.Process) { throw 'HTTPS gateway 沒有回傳自有程序。' }
    $State.ActiveAddress = $Address
    return 'started'
}

function Invoke-TinkroMobileNetworkPoll {
    param([hashtable]$State, [scriptblock]$GetAddress, [scriptblock]$StartGateway,
        [scriptblock]$StopGateway = { param($child) Stop-TinkroOwnedGateway $child })
    try { $address = & $GetAddress }
    catch {
        # Unknown is not offline: a transient Windows adapter-query failure must
        # not close a healthy stream or consume a new-address confirmation.
        return @{ Event='probe_failed'; Address=$State.ActiveAddress; Error=$_.Exception.Message }
    }
    try {
        return @{ Event=(Update-TinkroMobileNetwork -State $State -Address $address -StartGateway $StartGateway -StopGateway $StopGateway); Address=$address; Error=$null }
    } catch { return @{ Event='start_failed'; Address=$address; Error=$_.Exception.Message } }
}

function Enter-TinkroMobilePortLock {
    param([int]$Port)
    $directory = Join-Path ([IO.Path]::GetTempPath()) 'tinkro-mobile-gateway-locks'
    [IO.Directory]::CreateDirectory($directory) | Out-Null
    try { return [IO.File]::Open((Join-Path $directory "$Port.lock"), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None) }
    catch { throw "HTTPS Port $Port 已有另一個監測啟動器；不會建立第二份。" }
}

function Assert-TinkroMobilePortFree {
    param([int]$Port, [scriptblock]$GetListeners = { param($p) @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) })
    if (@(& $GetListeners $Port).Count) { throw "HTTPS Port $Port 已有程式使用；不會停止不屬於此啟動器的程式。" }
}

function Write-TinkroMobileConnection {
    param([string]$Path, $Value)
    $temporary = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        [IO.File]::Move($temporary, $Path, $true)
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}

function Test-TinkroMobileCertificate {
    param([string]$Python, [string]$Directory, [string]$Address)
    $code = @'
import sys, ipaddress
from pathlib import Path
from datetime import datetime, timezone, timedelta
from cryptography import x509
try:
 p=Path(sys.argv[1]); leaf=x509.load_pem_x509_certificate((p/'server.pem').read_bytes()); ca=x509.load_pem_x509_certificate((p/'rootCA.pem').read_bytes())
 leaf.verify_directly_issued_by(ca)
 valid=ipaddress.ip_address(sys.argv[2]) in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
 now=datetime.now(timezone.utc)
 valid=valid and leaf.not_valid_before_utc <= now and leaf.not_valid_after_utc > now+timedelta(days=1)
 valid=valid and ca.not_valid_before_utc <= now and ca.not_valid_after_utc > now+timedelta(days=1)
 print('valid' if valid else 'renew')
except Exception:
 print('renew')
'@
    $result = & $Python -c $code $Directory $Address
    if ($LASTEXITCODE -ne 0) { throw '無法檢查手機 HTTPS 憑證。' }
    return ($result -eq 'valid')
}

function ConvertTo-TinkroProcessArgument {
    param([string]$Value)
    $escaped = [regex]::Replace($Value, '(\\*)"', '$1$1\"')
    $escaped = [regex]::Replace($escaped, '(\\+)$', '$1$1')
    return '"' + $escaped + '"'
}

function Test-TinkroMobileGatewayTls {
    param([string]$Python, [string]$Directory, [string]$Address, [int]$Port)
    $code = @'
import hashlib, http.client, ssl, sys
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
ready=False
connection=None
try:
 p=Path(sys.argv[1])
 context=ssl.create_default_context(cafile=str(p/'rootCA.pem'))
 connection=http.client.HTTPSConnection(sys.argv[2],int(sys.argv[3]),context=context,timeout=1)
 connection.connect()
 expected=x509.load_pem_x509_certificate((p/'server.pem').read_bytes()).public_bytes(Encoding.DER)
 if hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()==hashlib.sha256(expected).digest():
  connection.request('GET','/mobile')
  ready=connection.getresponse().status==200
except Exception:
 pass
finally:
 if connection is not None: connection.close()
print('ready' if ready else 'waiting')
'@
    $result = & $Python -c $code $Directory $Address "$Port"
    return ($LASTEXITCODE -eq 0 -and $result -eq 'ready')
}

function Start-TinkroOwnedGateway {
    param([string]$Python, [string]$Backend, [string]$Frontend, [string]$Directory,
        [string]$Address, [int]$Port, [string]$Upstream, [hashtable]$Owner)
    Assert-TinkroMobilePortFree $Port
    foreach ($name in @('rootCA.pem', 'rootCA-key.pem')) {
        if (-not [IO.File]::Exists((Join-Path $Directory $name))) { throw '缺少現有 CA；請先執行 setup-mobile-web-https.ps1。監測器不會建立新 CA。' }
    }
    if (-not (Test-TinkroMobileCertificate $Python $Directory $Address)) {
        Push-Location -LiteralPath $Backend
        try {
            & $Python -m app.mobile_https certificates --directory $Directory --lan-host $Address | Out-Null
            if ($LASTEXITCODE -ne 0) { throw '更新手機 HTTPS leaf 憑證失敗；保留原 CA。' }
        } finally { Pop-Location }
    }
    $connectionPath = Join-Path $Directory 'connection.json'
    $previous = Get-Content -LiteralPath $connectionPath -Raw | ConvertFrom-Json
    $next = @{ base_url = "https://${Address}:$Port"; backend_url = $Upstream; port = $Port; generated_at = [DateTimeOffset]::UtcNow.ToString('o') }
    $child = $null; $success = $false
    try {
        # Publish while the port is still closed. A newly listening gateway must
        # never advertise the previous IP through backend web-config.
        Write-TinkroMobileConnection $connectionPath $next
        $arguments = @('-m', 'app.mobile_https', 'serve', '--directory', $Directory, '--frontend', $Frontend, '--upstream', $Upstream, '--port', "$Port")
        $quoted = ($arguments | ForEach-Object { ConvertTo-TinkroProcessArgument $_ }) -join ' '
        $child = Start-Process -FilePath $Python -ArgumentList $quoted -WorkingDirectory $Backend -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Directory 'gateway.stdout.log') -RedirectStandardError (Join-Path $Directory 'gateway.stderr.log')
        if ($Owner) { $Owner.Process = $child }
        $deadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            if ($child.HasExited) { throw "HTTPS gateway 退出，代碼 $($child.ExitCode)。" }
            # Verify chain + current LAN hostname + exact prepared leaf, not
            # merely that something (possibly foreign) answers on this port.
            if (Test-TinkroMobileGatewayTls $Python $Directory $Address $Port) { $success = $true; return $child }
            Start-Sleep -Milliseconds 200
        } while ([DateTime]::UtcNow -lt $deadline)
        throw 'HTTPS gateway TLS 健康檢查逾時。'
    } finally {
        if (-not $success) {
            if ($child) { Stop-TinkroOwnedGateway $child; if ($Owner) { $Owner.Process = $null } }
            Write-TinkroMobileConnection $connectionPath $previous
        }
    }
}

function Write-TinkroMobileNetworkEvent {
    param([string]$Directory, [string]$Event, [string]$Address)
    $path = Join-Path $Directory 'network-watcher.jsonl'
    if ([IO.File]::Exists($path) -and (Get-Item -LiteralPath $path).Length -gt 262144) {
        [IO.File]::Copy($path, "$path.1", $true)
        [IO.File]::WriteAllText($path, '')
    }
    $value = @{ time = [DateTimeOffset]::UtcNow.ToString('o'); event = $Event; address = $Address }
    [IO.File]::AppendAllText($path, (($value | ConvertTo-Json -Compress) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
}

function Limit-TinkroMobileGatewayLogs {
    param([string]$Directory)
    foreach ($name in @('gateway.stdout.log', 'gateway.stderr.log')) {
        $log = Join-Path $Directory $name
        if ([IO.File]::Exists($log) -and (Get-Item -LiteralPath $log).Length -gt 1048576) {
            try {
                $file = [IO.File]::Open($log, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
                try { $file.SetLength(0) } finally { $file.Dispose() }
            } catch { } # Log rotation must not interrupt an otherwise healthy gateway.
        }
    }
}
