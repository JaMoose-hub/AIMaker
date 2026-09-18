"""Local-only per-device control profiles; never rewrites config.yaml/secrets."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

STORE = Path(__file__).resolve().parents[2] / 'runs' / 'camera-settings.json'
_LOCK = threading.RLock()
NAMES = {'exposure', 'focus', 'gain', 'white_balance'}


def identity(name: str, width: int, height: int, fps: float) -> str:
    return hashlib.sha256(f'{name.casefold()}|{width}|{height}|{fps:g}'.encode()).hexdigest()


def valid_settings(settings) -> dict:
    if not isinstance(settings, dict):
        raise ValueError('invalid control profile')
    result = {}
    for key, entry in settings.items():
        if (key not in NAMES or not isinstance(entry, dict)
                or type(entry.get('value')) is not int or entry.get('flags') not in (1, 2)):
            raise ValueError('invalid control profile')
        result[key] = {'value': entry['value'], 'flags': entry['flags']}
    return result


def _read() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding='utf-8'))
        return data if data.get('version') == 1 and isinstance(data.get('devices'), dict) else {'version': 1, 'devices': {}}
    except (OSError, ValueError, AttributeError):
        return {'version': 1, 'devices': {}}


def load(key: str) -> dict:
    with _LOCK:
        try:
            return valid_settings(_read()['devices'].get(key, {}))
        except ValueError:
            return {}


def save(key: str, settings: dict) -> None:
    settings = valid_settings(settings)
    with _LOCK:
        data = _read()
        data['devices'][key] = settings
        STORE.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=STORE.parent,
                                             prefix='camera-settings-', suffix='.tmp', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, STORE)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
