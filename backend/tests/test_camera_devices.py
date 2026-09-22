"""Hot-plug regression tests: no real webcam handles, FFmpeg or Pi calls."""
from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.api.cameras import router
from app.capture import devices, modes, windows_uvc, control_store
from app.camera_tuning import CameraTuner
from app.capture.sources import FfmpegMjpegCameraSource
from test_camera_modes import state, Source, SMALL, LARGE

OUTPUT = '''
[dshow] "USB camera" (video)
[dshow] Alternative name "@device_pnp_usb-a"
[dshow] "Microphone" (audio)
[dshow] Alternative name "@device_cm_audio"
[dshow] "USB camera" (video)
[dshow] Alternative name "@device_pnp_usb-b"
[dshow] "Eye" (video)
[dshow] Alternative name "@device_pnp_vid_0b05&pid_1d9d"
'''
A = devices.CameraDevice(0, 'USB camera', '@device_pnp_usb-a')
B = devices.CameraDevice(1, 'HD Pro Webcam C920', '@device_pnp_usb-b')


@pytest.fixture(autouse=True)
def no_physical_controls(monkeypatch):
    monkeypatch.setattr(windows_uvc, 'read_controls', lambda _: {'controls': []})
    monkeypatch.setattr(windows_uvc, 'apply_controls', lambda *a: pytest.fail('switch must not write controls'))


def client_for(state, monkeypatch, inventory=None):
    monkeypatch.setattr(devices, 'supports_inventory', lambda _: True)
    monkeypatch.setattr(devices, 'inventory', lambda _: inventory if inventory is not None else [A, B])
    app = FastAPI()
    for key, value in vars(state).items():
        setattr(app.state, key, value)
    app.include_router(router)
    return TestClient(app)


def test_metadata_keeps_duplicate_names_separate_ignores_audio_and_excludes_eye():
    result = devices.parse_devices(OUTPUT)
    assert len(result) == 3
    assert result[0].id != result[1].id
    assert result[0].name == result[1].name
    assert not result[2].selectable
    assert devices.CameraDevice(5, A.name, A.selector).id == A.id
    source = FfmpegMjpegCameraSource(0, 'USB camera', **SMALL)
    assert devices.current_device(source, result) is None  # ambiguous names
    source.device_identity = result[1].id
    assert devices.current_device(source, result) == result[1]


def test_inventory_is_fresh_bounded_and_never_opens_video(monkeypatch):
    calls = []
    def run(command, **kw):
        calls.append((command, kw))
        return SimpleNamespace(stderr=OUTPUT)
    monkeypatch.setattr(devices.subprocess, 'run', run)
    assert len(devices.inventory('ffmpeg')) == 3
    assert len(devices.inventory('ffmpeg')) == 3
    assert len(calls) == 2
    assert calls[0][0][-1] == 'dummy'
    assert '-list_devices' in calls[0][0]
    assert calls[0][1]['timeout'] == 5


def test_get_lists_present_unopened_devices_and_does_not_assume_old_index_is_current(state, monkeypatch):
    # Runtime still says USB camera at index 1, but that index now belongs to C920.
    client = client_for(state, monkeypatch, [B])
    data = client.get('/api/cameras').json()
    assert data['refreshable']
    assert data['cameras'][0]['name'] == B.name
    assert data['cameras'][0]['selectable']
    assert not data['cameras'][0]['available']
    assert not data['cameras'][0]['is_current']
    assert 'thumbnail_b64' not in data['cameras'][0]


def test_old_frame_is_not_live_or_a_reason_to_block_reconnect(state, monkeypatch):
    state.capture_service.stop()
    state.frame_bus.put(np.full((48, 64, 3), 100, np.uint8), 999, time.monotonic()*1000-4000)
    client = client_for(state, monkeypatch)
    data = client.get('/api/cameras').json()['cameras'][0]
    assert data['is_current'] and not data['available'] and data['selectable']
    calls = []
    monkeypatch.setattr(devices, 'switch_device', lambda _, target: calls.append(target) or dict(ok=True))
    assert client.post('/api/cameras/select', json=dict(index=0, device_id=A.id)).json()['ok']
    assert calls == [A]


def test_selection_binds_identity_not_index_and_rejects_removed_devices(state, monkeypatch):
    reordered = devices.CameraDevice(8, B.name, B.selector)
    client = client_for(state, monkeypatch, [reordered])
    calls = []
    monkeypatch.setattr(devices, 'switch_device', lambda _, target: calls.append(target) or dict(ok=True))
    for body in [dict(index=8), dict(index=8, device_id=A.id)]:
        assert client.post('/api/cameras/select', json=body).json()['error'] == 'camera_changed'
    assert not calls
    assert client.post('/api/cameras/select', json=dict(index=1, device_id=B.id)).json()['ok']
    assert calls == [reordered]
    state.camera_control_lock.acquire()
    try:
        assert client.post('/api/cameras/select', json=dict(index=1, device_id=B.id)).status_code == 409
        assert len(calls) == 1
    finally:
        state.camera_control_lock.release()


def test_source_replacement_verifies_new_frames_resets_geometry_and_does_not_copy_controls(state, monkeypatch):
    old = state.source
    state.config.camera.focus = 25
    state.config.camera.native_uvc_controls = True
    calls = []
    def make(index, name, **kwargs):
        calls.append(kwargs)
        new = Source()
        new._index, new._device_name = index, name
        return new
    monkeypatch.setattr(devices, 'FfmpegMjpegCameraSource', make)
    result = devices.switch_device(state, B, timeout=.3)
    assert result['ok'] and result['name'] == B.name
    assert old._closed
    assert state.source is not old and state.source.device_identity == B.id
    assert state.config.camera.focus is None
    assert state.config.camera.calibration_path is None
    assert not state.source._native_uvc_controls
    assert not state.source.allow_camera_calibration
    assert 'focus' not in calls[0]
    assert state.component_workers[0]._thread.is_alive()
    assert state.revisions == [1]


def test_new_camera_failure_restores_old_source_only_if_it_produces_new_frames(state, monkeypatch):
    old, previous = state.source, state.config.camera
    def make(*args, **kwargs):
        broken = Source()
        broken.fail = 'all'
        return broken
    monkeypatch.setattr(devices, 'FfmpegMjpegCameraSource', make)
    result = devices.switch_device(state, B, timeout=.07)
    assert result == dict(ok=False, error='open_failed', restored=True)
    assert state.source is old and state.config.camera == previous
    old.fail = 'all'
    result = devices.switch_device(state, B, timeout=.07)
    assert result == dict(ok=False, error='camera_restore_failed', restored=False)
    assert devices.fresh_slot(state) is None


@pytest.mark.parametrize('capability', ['supported', 'unsupported', 'busy'])
def test_switch_discovers_tuning_without_importing_old_settings_or_writing(state, monkeypatch, capability):
    queried = []
    def read(selector):
        queried.append(selector)
        if capability == 'busy':
            raise RuntimeError('property query busy')
        return {'controls': [dict(Name='focus', Min=0, Max=250, Step=5, Caps=3,
                                  Value=25, Flags=1)] if capability == 'supported' else []}
    monkeypatch.setattr(windows_uvc, 'read_controls', read)
    monkeypatch.setattr(control_store, 'load', lambda _: pytest.fail('switch must not load saved settings'))
    def make(index, name, **kwargs):
        new = Source()
        new._index, new._device_name = index, name
        return new
    monkeypatch.setattr(devices, 'FfmpegMjpegCameraSource', make)
    assert devices.switch_device(state, B, timeout=.3)['ok']
    assert queried == [B.selector]
    assert state.config.camera.native_uvc_controls == (capability == 'supported')
    tuner = CameraTuner(state)
    assert tuner.snapshot()['available'] == (capability == 'supported')
    assert not tuner.snapshot()['busy']
    assert not state.source._controls_requested()
    assert not state.source._live_control_overrides
    assert devices.fresh_slot(state) is not None


def test_supported_mode_selected_instead_of_previous_cameras_5mp(state):
    state.config.camera.width, state.config.camera.height = 2592, 1944
    options = [dict(width=1920, height=1080, fps=30), dict(width=640, height=480, fps=30)]
    assert devices.choose_mode(options, state.config.camera) == options[0]


def test_unreadable_formats_do_not_stop_current_stream(state, monkeypatch):
    old = state.source
    monkeypatch.setattr(modes, 'advertised_modes', lambda *args: (_ for _ in ()).throw(RuntimeError('busy')))
    assert devices.switch_device(state, B)['error'] == 'camera_modes_unavailable'
    assert state.source is old and not old._closed
    assert state.revisions == []
