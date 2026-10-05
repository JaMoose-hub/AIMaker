$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'Run these isolated tests with pwsh 7.' }
. (Join-Path $PSScriptRoot 'mobile-web-network.ps1')
$passed = 0
function Assert-True($value, $message) { if (-not $value) { throw $message }; $script:passed++ }
function Assert-Throws([scriptblock]$action, $message) {
    $threw = $false
    try { & $action | Out-Null } catch { $threw = $true }
    Assert-True $threw $message
}
function New-FakeChild {
    $child = [pscustomobject]@{ HasExited = $false; Disposed = $false; KilledTree = $false; ExitCode = 9 }
    $child | Add-Member ScriptMethod Kill { param($tree) $this.KilledTree = $tree; $this.HasExited = $true }
    $child | Add-Member ScriptMethod WaitForExit { param($timeout) return $this.HasExited }
    $child | Add-Member ScriptMethod Dispose { $this.Disposed = $true }
    return $child
}

$adapters = @(
    [pscustomobject]@{ Name='Ethernet'; InterfaceIndex=1; Status='Up'; HardwareInterface=$true; Virtual=$false; NdisPhysicalMedium=14 },
    [pscustomobject]@{ Name='Wi-Fi'; InterfaceIndex=2; Status='Up'; HardwareInterface=$true; Virtual=$false; NdisPhysicalMedium=9 },
    [pscustomobject]@{ Name='VPN'; InterfaceIndex=3; Status='Up'; HardwareInterface=$false; Virtual=$true; NdisPhysicalMedium=0 })
$networks = foreach ($index in 1..3) { [pscustomobject]@{ InterfaceIndex=$index; IPv4DefaultGateway='gateway'; IPv4Address=@([pscustomobject]@{IPAddress="192.168.$index.20"}) } }
Assert-True ((Get-TinkroMobileLanAddress $networks $adapters) -eq '192.168.2.20') 'Wi-Fi must take priority over Ethernet/VPN.'
$networks[1].IPv4DefaultGateway = $null
Assert-True ((Get-TinkroMobileLanAddress $networks $adapters) -eq '192.168.1.20') 'A physical Ethernet default route is the fallback.'
$networks[0].IPv4DefaultGateway = $null
Assert-True ($null -eq (Get-TinkroMobileLanAddress $networks $adapters)) 'VPN alone must not advertise a phone address.'
$networks[1].IPv4DefaultGateway = 'gateway'
$networks[1].IPv4Address[0].IPAddress = '169.254.3.4'
Assert-True ($null -eq (Get-TinkroMobileLanAddress $networks $adapters)) 'APIPA is not usable LAN.'

$state = New-TinkroMobileNetworkState
$starts = [Collections.Generic.List[string]]::new()
$children = [Collections.Generic.List[object]]::new()
$start = { param($address) $starts.Add($address); $child=New-FakeChild; $children.Add($child); return $child }
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.138' $start) -eq 'confirming') 'First observation must wait.'
Assert-True ($starts.Count -eq 0) 'Warmup must not start.'
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.138' $start) -eq 'started') 'Second stable observation starts.'
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.138' $start) -eq 'unchanged') 'Same IP cannot duplicate gateway.'
$ownerBefore = $state.Process
$probeFailure = Invoke-TinkroMobileNetworkPoll -State $state -GetAddress { throw 'synthetic temporary adapter failure' } -StartGateway $start
Assert-True ($probeFailure.Event -eq 'probe_failed' -and $state.Process -eq $ownerBefore -and -not $ownerBefore.HasExited) 'Probe exceptions preserve the healthy owned gateway.'
Assert-True ($starts.Count -eq 1 -and $state.ActiveAddress -eq '192.168.50.138') 'Probe failure does not consume or restart network state.'
$probeRecovery = Invoke-TinkroMobileNetworkPoll -State $state -GetAddress { '192.168.50.138' } -StartGateway $start
Assert-True ($probeRecovery.Event -eq 'unchanged') 'Successful same-address probe resumes without reconnecting.'
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.139' $start) -eq 'confirming') 'IP change is debounced.'
Assert-True (-not $children[0].KilledTree) 'One changed observation retains current owned gateway.'
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.139' $start) -eq 'started') 'Stable changed IP restarts.'
Assert-True ($children[0].KilledTree -and $children[0].Disposed -and $starts.Count -eq 2) 'Old entire owned tree must be closed before replacement.'
Assert-True ((Update-TinkroMobileNetwork $state $null $start) -eq 'offline') 'Network loss stops only owned gateway.'
Assert-True ($children[1].KilledTree -and $null -eq $state.Process -and $starts.Count -eq 2) 'Offline must not start or issue certificates.'
Assert-True ((Update-TinkroMobileNetwork $state '192.168.50.139' $start) -eq 'confirming') 'Restored network needs confirmation again.'
Assert-Throws { Update-TinkroMobileNetwork $state '192.168.50.139' { throw 'synthetic launch failure' } } 'Launch failure must propagate.'
Assert-True ($null -eq $state.Process -and $null -eq $state.ActiveAddress) 'Failure cannot publish a false active owner.'
Update-TinkroMobileNetwork $state '192.168.50.139' $start | Out-Null
Stop-TinkroOwnedGateway $state.Process
Assert-True ($state.Process.KilledTree -and $state.Process.Disposed) 'The finally cleanup primitive terminates descendants.'
Assert-Throws { Assert-TinkroMobilePortFree 48443 { param($port) @([pscustomobject]@{OwningProcess=99999}) } } 'A foreign listener is never taken over.'
Assert-TinkroMobilePortFree 48443 { param($port) @() }
$lock = Enter-TinkroMobilePortLock 48443
try { Assert-Throws { Enter-TinkroMobilePortLock 48443 } 'Concurrent watchers cannot own the same port.' }
finally { $lock.Dispose() }
$lock = Enter-TinkroMobilePortLock 48443
$lock.Dispose()
Assert-True $true 'Released lock can be reacquired.'

$tempBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temp = [IO.Path]::GetFullPath((Join-Path $tempBase ('tinkro-network-test-'+[Guid]::NewGuid().ToString('N'))))
[IO.Directory]::CreateDirectory($temp) | Out-Null
$repo = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $repo 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
try {
    $connection = Join-Path $temp 'connection.json'
    Write-TinkroMobileConnection $connection @{base_url='https://192.168.50.138:8443'; port=8443; backend_url='http://127.0.0.1:8100'}
    Assert-True ((Get-Content $connection -Raw | ConvertFrom-Json).port -eq 8443) 'Connection JSON roundtrips atomically.'
    Assert-True (@(Get-ChildItem $temp -Filter '*.tmp').Count -eq 0) 'Atomic writer leaves no temporary data.'
    Push-Location -LiteralPath $backend
    try {
        & $python -m app.mobile_https certificates --directory $temp --lan-host '192.168.50.138' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic certificate setup failed.' }
        $caHash = (Get-FileHash (Join-Path $temp 'rootCA.pem')).Hash
        $leafHash = (Get-FileHash (Join-Path $temp 'server.pem')).Hash
        Assert-True (Test-TinkroMobileCertificate $python $temp '192.168.50.138') 'Matching unexpired SAN is reused.'
        Assert-True (-not (Test-TinkroMobileCertificate $python $temp '192.168.50.139')) 'New IP requires new leaf.'
        Assert-True ((Get-FileHash (Join-Path $temp 'server.pem')).Hash -eq $leafHash) 'Read-only certificate check never reissues leaf.'
        & $python -m app.mobile_https certificates --directory $temp --lan-host '192.168.50.139' | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Synthetic leaf update failed.' }
        Assert-True ((Get-FileHash (Join-Path $temp 'rootCA.pem')).Hash -eq $caHash) 'Updating LAN leaf must preserve the trusted CA.'
        Assert-True (Test-TinkroMobileCertificate $python $temp '192.168.50.139') 'Renewed leaf matches new IP.'
    } finally { Pop-Location }
    # Replace only this test scope's process/network primitives; no native process,
    # listener, gateway or real phone is started by this failure/rollback test.
    & {
        function Assert-TinkroMobilePortFree { param($Port) }
        function Test-TinkroMobileCertificate { param($Python,$Directory,$Address) return $true }
        $failedChild = New-FakeChild
        $failedChild.HasExited = $true
        function Start-Process { return $failedChild }
        $owner = New-TinkroMobileNetworkState
        $before = (Get-Content $connection -Raw | ConvertFrom-Json).base_url
        Assert-Throws { Start-TinkroOwnedGateway -Python $python -Backend $backend -Frontend $temp -Directory $temp -Address '192.168.50.139' -Port 8443 -Upstream 'http://127.0.0.1:8100' -Owner $owner } 'Failed child must not report TLS success.'
        Assert-True ($failedChild.Disposed -and $null -eq $owner.Process) 'Failed child is disposed and ownership cleared after cleanup.'
        Assert-True ((Get-Content $connection -Raw | ConvertFrom-Json).base_url -eq $before) 'Failed start rolls back the previous connection URL.'
    }
    & {
        function Assert-TinkroMobilePortFree { param($Port) }
        function Test-TinkroMobileCertificate { param($Python,$Directory,$Address) return $true }
        $failedChild = New-FakeChild
        $tlsCalls = [Collections.Generic.List[string]]::new()
        function Start-Process { return $failedChild }
        function Start-Sleep { }
        function Test-TinkroMobileGatewayTls {
            param($Python,$Directory,$Address,$Port)
            $tlsCalls.Add($Address)
            $failedChild.HasExited = $true
            return $false
        }
        $owner = New-TinkroMobileNetworkState
        $before = (Get-Content $connection -Raw | ConvertFrom-Json).base_url
        Assert-Throws { Start-TinkroOwnedGateway -Python $python -Backend $backend -Frontend $temp -Directory $temp -Address '192.168.50.139' -Port 8443 -Upstream 'http://127.0.0.1:8100' -Owner $owner } 'Unverified TLS cannot be accepted as healthy.'
        Assert-True ($tlsCalls.Count -eq 1 -and $tlsCalls[0] -eq '192.168.50.139') 'TLS verifies the new LAN host, not just localhost.'
        Assert-True ($failedChild.Disposed -and $null -eq $owner.Process) 'TLS failure cleans up only the owned gateway.'
        Assert-True ((Get-Content $connection -Raw | ConvertFrom-Json).base_url -eq $before) 'TLS failure rolls back the advertised connection.'
    }
} finally {
    # Verify the fully resolved recursive-delete target is our unique test folder.
    if (-not $temp.StartsWith($tempBase, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFileName($temp).StartsWith('tinkro-network-test-'))) { throw 'Unexpected test cleanup path.' }
    Remove-Item -LiteralPath $temp -Recurse -Force
}
Write-Host "$passed assertions passed; synthetic adapters/processes/certificates only."
