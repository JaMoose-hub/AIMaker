"""Physical launch defaults only; never starts a server, camera, model or Pi."""
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("script", ["camera.ps1", "camera-yolo.ps1"])
def test_physical_launch_defaults_to_mx_brio_and_keeps_explicit_overrides(script):
    text = (ROOT / "scripts" / script).read_text(encoding="utf-8-sig")
    assert re.search(r'\[string\]\$FfmpegDeviceName\s*=\s*"MX Brio"', text)
    assert re.search(r'\[int\]\$DeviceIndex\s*=\s*0\b', text)
    assert "$env:BOARDVISION_CAMERA__FFMPEG_DEVICE_NAME = $FfmpegDeviceName" in text
    assert "$env:BOARDVISION_CAMERA__DEVICE_INDEX = [string]$DeviceIndex" in text
    assert 'Start-Process -WindowStyle Hidden' in text
