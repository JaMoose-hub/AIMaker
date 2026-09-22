"""Windows camera inventory without opening streams; explicit identity-bound switching."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import subprocess
import sys
import time

from . import modes
from .sources import DeviceCameraSource, FfmpegMjpegCameraSource, frame_has_signal


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    selector: str

    @property
    def id(self):
        return hashlib.sha256(self.selector.casefold().encode()).hexdigest()[:24]

    @property
    def selectable(self):
        # The dedicated Eye source must never be opened as a webcam.
        return not ('vid_0b05' in self.selector.lower() and 'pid_1d9d' in self.selector.lower())


def parse_devices(output: str) -> list[CameraDevice]:
    devices = []
    pending = None
    for line in output.splitlines():
        match = re.search(r'"(.*)" \((video|audio)\)', line)
        if match:
            pending = match[1] if match[2] == 'video' else None
            continue
        match = re.search(r'Alternative name "(.*)"', line)
        if match and pending is not None:
            devices.append(CameraDevice(len(devices), pending, match[1]))
            pending = None
    return devices


def inventory(ffmpeg: str) -> list[CameraDevice]:
    # No cache: indices/names can change on every USB plug. This lists metadata
    # only, unlike VideoCapture probes which can hold a busy driver after timeout.
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-list_devices', 'true',
                             '-f', 'dshow', '-i', 'dummy'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if 'DirectShow video devices' not in result.stderr and 'Alternative name' not in result.stderr:
        if 'Could not enumerate video devices' not in result.stderr:
            raise RuntimeError('camera_inventory_unavailable')
    return parse_devices(result.stderr)


def supports_inventory(state):
    return (sys.platform == 'win32' and state.config.camera.source == 'device'
            and isinstance(state.source, (FfmpegMjpegCameraSource, DeviceCameraSource)))


def current_device(source, devices):
    identity = getattr(source, 'device_identity', None)
    if identity:
        return next((d for d in devices if d.id == identity), None)
    if isinstance(source, FfmpegMjpegCameraSource):
        matches = [d for d in devices if source.device_name in (d.name, d.selector)]
        return matches[0] if len(matches) == 1 else None
    return next((d for d in devices if d.index == source.current_index), None)


def fresh_slot(state):
    slot = state.frame_bus.get_latest(timeout=0)
    return slot if (slot is not None and 0 <= time.monotonic()*1000 - slot.ts_ms < 2000
                    and frame_has_signal(slot.frame)) else None


def choose_mode(options, camera):
    # Prefer the previous size when supported; otherwise a nearby <=1080p mode.
    # Never send the last camera's 5MP@30 request to a different device.
    usable = [m for m in options if m['width'] <= 1920 and m['height'] <= 1080] or options
    exact = [m for m in options if (m['width'], m['height']) == (camera.width, camera.height)]
    return dict(min(exact or usable, key=lambda m: (
        abs(m['width']*m['height'] - camera.width*camera.height), -m['fps'])))


def switch_device(state, device: CameraDevice, *, timeout=10):
    camera = state.config.camera
    try:
        options = modes.advertised_modes(camera.ffmpeg_path, device.selector)
    except Exception:
        return dict(ok=False, error='camera_modes_unavailable')
    mode = choose_mode(options, camera)
    source = FfmpegMjpegCameraSource(device.index, device.selector, **mode,
                                    ffmpeg_path=camera.ffmpeg_path)
    source.device_identity = device.id
    source.device_display_name = device.name
    source.allow_camera_calibration = False
    # Defaults leave driver controls alone; never copy C920 controls or lens
    # calibration to a different camera. Saved config on disk is not overwritten.
    config = camera.model_copy(update={**mode, 'device_index': device.index,
        'capture_backend': 'ffmpeg', 'capture_api': 'dshow', 'ffmpeg_device_name': device.selector,
        'native_uvc_controls': False, 'uvc_image_controls': {}, 'lock_auto_focus': False,
        'focus': None, 'lock_auto_exposure': False, 'exposure': None, 'gain': None,
        'lock_auto_white_balance': False, 'white_balance_temperature': None,
        'horizontal_fov_deg': None, 'calibration_path': None})
    result = modes.change_mode(state, mode, timeout=timeout, replacement=(source, config))
    if not result['ok']:
        result['error'] = {'camera_mode_failed': 'open_failed',
                           'camera_restore_failed': 'camera_restore_failed'}.get(result['error'], result['error'])
        return result
    # Do not confuse "leave this camera's settings alone" with "unsupported".
    # The mutation lease is still held. Only read this device's capabilities;
    # no saved profile is loaded, no property is written, no stream is reopened.
    state.config.camera.native_uvc_controls = source.discover_live_controls()
    return dict(ok=True, index=device.index, device_id=device.id, name=device.name,
                width=mode['width'], height=mode['height'])
