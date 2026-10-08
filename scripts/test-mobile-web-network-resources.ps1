param([string]$Scenario = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'mobile-web-network.ps1')
$passed = 0
$scenarios = @('success', 'config-error', 'adapter-error', 'create-error', 'supplied-config', 'supplied-adapter', 'supplied-both')
foreach ($case in $scenarios) {
    if ($Scenario -and $Scenario -ne $case) { continue }
    & {
        $created = [Collections.Generic.List[object]]::new()
        $removed = [Collections.Generic.List[object]]::new()
        $queried = [Collections.Generic.List[object]]::new()
        # This unrelated session must never be queried or removed by the helper.
        $unrelated = [pscustomobject]@{ Name = 'caller-owned' }
        $config = [pscustomobject]@{ InterfaceIndex=1; IPv4DefaultGateway='gateway'; IPv4Address=@([pscustomobject]@{IPAddress='192.168.50.141'}) }
        $adapter = [pscustomobject]@{ Name='Wi-Fi'; InterfaceIndex=1; Status='Up'; HardwareInterface=$true; Virtual=$false; NdisPhysicalMedium=9 }
        function New-CimSession {
            [CmdletBinding()] param()
            if ($case -eq 'create-error') { Write-Error 'synthetic create failure'; return }
            $session = [pscustomobject]@{ Name = 'probe-owned' }
            $created.Add($session)
            return $session
        }
        function Get-NetIPConfiguration {
            [CmdletBinding()] param($CimSession)
            $queried.Add($CimSession)
            if ($case -eq 'config-error') { Write-Error 'synthetic config failure'; return }
            return $config
        }
        function Get-NetAdapter {
            [CmdletBinding()] param([switch]$Physical, $CimSession)
            $queried.Add($CimSession)
            if ($case -eq 'adapter-error') { Write-Error 'synthetic adapter failure'; return }
            return $adapter
        }
        function Remove-CimSession {
            [CmdletBinding()] param($CimSession)
            $removed.Add($CimSession)
        }
        $arguments = @{}
        if ($case -in @('supplied-config', 'supplied-both')) { $arguments.Configurations = @($config) }
        if ($case -in @('supplied-adapter', 'supplied-both')) { $arguments.Adapters = @($adapter) }
        $failure = $null
        $address = $null
        try { $address = Get-TinkroMobileLanAddress @arguments } catch { $failure = $_.Exception.Message }
        $expectedQueries = switch ($case) { 'create-error' {0} 'supplied-both' {0} 'config-error' {1} 'supplied-config' {1} 'supplied-adapter' {1} default {2} }
        $expectedSessions = if ($case -in @('create-error', 'supplied-both')) {0} else {1}
        $expectsError = $case.EndsWith('-error')
        $valid = $created.Count -eq $expectedSessions -and $removed.Count -eq $expectedSessions -and $queried.Count -eq $expectedQueries
        if ($expectedSessions) {
            $valid = $valid -and [object]::ReferenceEquals($removed[0], $created[0])
            foreach ($session in $queried) { $valid = $valid -and [object]::ReferenceEquals($session, $created[0]) }
        }
        $valid = $valid -and -not ($removed -contains $unrelated)
        $valid = $valid -and $(if ($expectsError) { $failure -like 'synthetic * failure' -and $null -eq $address } else { $null -eq $failure -and $address -eq '192.168.50.141' })
        if (-not $valid) { throw "CIM resource ownership failed: $case (created=$($created.Count), removed=$($removed.Count), queries=$($queried.Count), error=$failure)" }
    }
    $passed++
}
if (-not $passed) { throw "Unknown scenario: $Scenario" }
Write-Host "$passed CIM resource scenarios passed; mocked queries only."
