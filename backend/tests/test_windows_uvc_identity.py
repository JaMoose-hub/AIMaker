"""Control capability / identity tests; never enumerate or change real cameras."""
import os
from pathlib import Path
import subprocess

import pytest

from app.capture import windows_uvc


@pytest.mark.parametrize('name,caps,expected', [
    ('focus', 3, True), ('exposure', 2, True), ('gain', 2, True),
    ('focus', 1, False), ('white_balance', 3, True), ('white_balance', 2, False),
    ('brightness', 3, False), ('unknown', 3, False),
])
def test_only_controls_the_tuner_can_vary_enable_button(name, caps, expected):
    prop = dict(Name=name, Min=0, Max=100, Step=1, Value=20, Flags=2 if caps & 2 else 1, Caps=caps)
    assert windows_uvc.supports_tuning({'controls': [prop]}) == expected


@pytest.mark.parametrize('change', [dict(Max=0), dict(Step=-1), dict(Value=101),
                                    dict(Flags=0), dict(Min=None), dict(Caps='manual')])
def test_bad_capability_cannot_enable_button(change):
    prop = dict(Name='focus', Min=0, Max=100, Step=1, Value=20, Flags=2, Caps=3)
    prop.update(change)
    assert not windows_uvc.supports_tuning({'controls': [prop]})
    assert not windows_uvc.supports_tuning({'controls': []})


@pytest.mark.skipif(os.name != 'nt', reason='PowerShell C# compilation is Windows-only')
def test_exact_moniker_and_ffmpeg_alias_match_without_name_fallback():
    # Compile only the helper's C# library. Do not invoke Read/Apply/FindFilter.
    script = Path(windows_uvc.__file__).with_suffix('.ps1').read_text(encoding='utf-8')
    library = script.split("Add-Type -TypeDefinition @'", 1)[1].split("'@", 1)[0]
    checks = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
LIBRARY
'@
$tests = @(
  @('@device_pnp_usb-a', '@device:pnp:usb-a', 'USB camera', $true),
  @('@device:pnp:usb-a', '@device:pnp:usb-a', 'USB camera', $true),
  @('@DEVICE_PNP_USB-A', '@device:pnp:usb-a', 'USB camera', $true),
  @('@device_pnp_usb-a', '@device:pnp:usb-b', '@device_pnp_usb-a', $false),
  @('@device_pnp_usb-a', '@device:pnp:usb-ab', 'USB camera', $false),
  @('@device_pnp_usb-a', $null, '@device_pnp_usb-a', $false),
  @('HD Pro Webcam C920', '@device:pnp:usb-a', 'HD Pro Webcam C920', $true),
  @('HD Pro Webcam C920', '@device:pnp:usb-a', 'USB camera', $false)
)
foreach ($test in $tests) {
  if ([BoardVisionUvc.Controls]::MatchesDevice($test[0], $test[1], $test[2]) -ne $test[3]) {
    throw 'Incorrect camera identity match'
  }
}
Write-Output 'identity checks passed'
'''.replace('LIBRARY', library)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', checks],
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr
    assert 'identity checks passed' in result.stdout
