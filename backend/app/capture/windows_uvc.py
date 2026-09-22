"""Bounded DirectShow property controls; never opens a second video stream."""
import base64
import json
import os
from pathlib import Path
import subprocess


def apply_controls(device_name: str, settings: dict) -> dict:
    encoded = base64.b64encode(json.dumps(settings).encode('utf-8')).decode('ascii')
    report = _run(device_name, ['-SettingsBase64', encoded])
    if not report.get('verified'):
        raise RuntimeError(f'DirectShow control read-back mismatch: {report}')
    return report


def read_controls(device_name: str) -> dict:
    return _run(device_name, ['-ReadOnly'])


def supports_tuning(report: dict) -> bool:
    """At least one control that the tuner can actually vary and restore."""
    for prop in report.get('controls', []):
        if not isinstance(prop, dict) or prop.get('Name') not in {'exposure', 'focus', 'gain', 'white_balance'}:
            continue
        if not all(type(prop.get(k)) is int for k in ('Min', 'Max', 'Step', 'Caps', 'Value', 'Flags')):
            continue
        if (prop['Flags'] not in (1, 2) or not prop['Caps'] & prop['Flags']
                or not prop['Caps'] & 2 or prop['Max'] <= prop['Min']
                or prop['Step'] < 0 or not prop['Min'] <= prop['Value'] <= prop['Max']):
            continue
        # White balance is only adjusted via auto-settle then manual lock.
        if prop['Name'] != 'white_balance' or prop['Caps'] & 1:
            return True
    return False


def _run(device_name: str, arguments: list[str]) -> dict:
    if os.name != 'nt':
        raise RuntimeError('DirectShow controls require Windows')
    completed = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
         str(Path(__file__).with_suffix('.ps1')), '-DeviceName', device_name,
         *arguments],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=12, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if completed.returncode:
        raise RuntimeError(f'DirectShow control helper failed: {completed.stderr[-1200:]}')
    return json.loads(completed.stdout)
