"""Cold-path DirectShow controls; never opens a second video stream."""
import base64
import json
import os
from pathlib import Path
import subprocess


def apply_controls(device_name: str, settings: dict) -> dict:
    if os.name != 'nt':
        raise RuntimeError('DirectShow controls require Windows')
    encoded = base64.b64encode(json.dumps(settings).encode('utf-8')).decode('ascii')
    completed = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
         str(Path(__file__).with_suffix('.ps1')), '-DeviceName', device_name,
         '-SettingsBase64', encoded],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if completed.returncode:
        raise RuntimeError(f'DirectShow control helper failed: {completed.stderr[-1200:]}')
    report = json.loads(completed.stdout)
    if not report.get('verified'):
        raise RuntimeError(f'DirectShow control read-back mismatch: {report}')
    return report
