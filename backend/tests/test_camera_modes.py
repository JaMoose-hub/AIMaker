"""Mode discovery/switching tests never open physical cameras or Pi hardware."""
from types import SimpleNamespace
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
import pytest

from app.api.camera_modes import router
from app.capture import modes
from app.capture.bus import FrameBus
from app.capture.service import CaptureService
from app.capture.sources import FfmpegMjpegCameraSource
from app.config import CameraConfig
from app.vision_worker import DetectionState

OPTIONS = '''
[dshow] vcodec=mjpeg  min s=2592x1944 fps=15 max s=2592x1944 fps=15
[dshow] vcodec=mjpeg  min s=1920x1080 fps=15 max s=1920x1080 fps=30
[dshow] vcodec=mjpeg  min s=1920x1080 fps=15 max s=1920x1080 fps=30 (bt470bg)
[dshow] pixel_format=yuyv422 min s=2592x1944 fps=2 max s=2592x1944 fps=2
[dshow] vcodec=mjpeg  min s=640x480 fps=15 max s=640x480 fps=30
'''
SMALL = dict(width=64, height=48, fps=30.0)
LARGE = dict(width=96, height=72, fps=15.0)


def test_parse_only_discrete_mjpeg_deduplicated_sorted_with_real_fps():
    assert modes.parse_mjpeg_modes(OPTIONS) == [
        dict(width=2592, height=1944, fps=15), dict(width=1920, height=1080, fps=30),
        dict(width=640, height=480, fps=30)]
    assert modes.parse_mjpeg_modes('vcodec=mjpeg min s=100x100 fps=15 max s=200x200 fps=30') == []


def test_probe_nonzero_exit_is_normal_but_empty_output_is_failure(monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1, stderr=OPTIONS)
    monkeypatch.setattr(modes.subprocess, 'run', run)
    modes.advertised_modes.cache_clear()
    assert modes.advertised_modes('ffmpeg', 'USB camera')[0]['fps'] == 15
    assert modes.advertised_modes('ffmpeg', 'USB camera')[0]['width'] == 2592
    assert len(calls) == 1
    assert calls[0][0][-1] == 'video=USB camera'
    assert calls[0][1]['timeout'] == 8
    modes.advertised_modes.cache_clear()
    monkeypatch.setattr(modes.subprocess, 'run', lambda *a, **k: SimpleNamespace(stderr='busy'))
    with pytest.raises(RuntimeError):
        modes.advertised_modes('ffmpeg', 'USB camera')


def test_source_mode_retains_controls_and_requires_closed_capture():
    source = FfmpegMjpegCameraSource(1, 'USB camera', **SMALL, focus=12)
    source.configure_mode(width=2592, height=1944, fps=15)
    assert source.capture_mode == dict(width=2592, height=1944, fps=15)
    assert source._focus == 12
    command = source.command()
    assert command[command.index('-video_size') + 1] == '2592x1944'
    assert command[command.index('-framerate') + 1] == '15'
    source._closed = False
    with pytest.raises(RuntimeError):
        source.configure_mode(**SMALL)


class Worker:
    def __init__(self):
        self._thread = None
        self.resets = 0
        self.stops = []
    def start(self):
        thread = SimpleNamespace(alive=True)
        thread.is_alive = lambda: thread.alive
        self._thread = thread
    def stop(self, **kwargs):
        self.stops.append(kwargs)
        if self._thread is not None:
            self._thread.alive = False
        self._thread = None
    def reset_tracking(self):
        assert self._thread is None
        self.resets += 1


class Source(FfmpegMjpegCameraSource):
    def __init__(self):
        super().__init__(1, 'USB camera', **SMALL)
        self.fail = None
        self.mismatch = False
        self.counter = 0
        self.frozen = False
    def open(self):
        self._closed = False
    def close(self):
        self._closed = True
    def read(self):
        time.sleep(.01)
        if self.fail == 'all' or (self.fail == 'large' and self._width == LARGE['width']):
            return None
        self.counter += 1
        width = 60 if self.mismatch and self._width == LARGE['width'] else self._width
        return np.full((self._height, width, 3), 100, np.uint8), self.counter, 1 if self.frozen else time.monotonic()*1000


@pytest.fixture
def state(monkeypatch):
    source, bus = Source(), FrameBus()
    holder = SimpleNamespace(clears=0)
    def clear():
        holder.clears += 1
    holder.clear = clear
    revisions = []
    state = SimpleNamespace(
        source=source, config=SimpleNamespace(camera=CameraConfig(source='device', **SMALL)),
        frame_bus=bus, capture_service=CaptureService(source, bus),
        vision_worker=Worker(), motion_worker=Worker(), body_worker=Worker(),
        component_workers=[Worker(), Worker()], component_worker=None,
        wire_worker=Worker(), component_pose_state=holder, motion_frame_state=holder,
        wire_state=holder, verification_state=holder, guidance_color_preview=holder,
        detection_state=DetectionState(), detector=SimpleNamespace(reset_for_camera=lambda **kw: None),
        runtime_manager=SimpleNamespace(camera_changed=lambda _: revisions.append(1)),
        camera_control_lock=threading.Lock(), revisions=revisions,
    )
    state.vision_worker.start()
    state.component_workers[0].start()
    state.wire_worker.start()
    state.capture_service.start()
    assert bus.get_latest(timeout=1) is not None
    monkeypatch.setattr(modes, 'advertised_modes', lambda *args: (SMALL, LARGE))
    yield state
    state.capture_service.stop()


def test_success_verifies_real_size_clears_geometry_preserves_models_and_running_workers(state):
    seq = state.frame_bus.latest_seq
    assert modes.change_mode(state, LARGE, timeout=.2) == {'ok': True}
    assert state.frame_bus.latest_seq > seq
    assert state.frame_bus.get_latest(timeout=0).frame.shape == (72, 96, 3)
    assert state.config.camera.width == 96
    assert state.revisions == [1]
    assert state.component_pose_state.clears == 5
    assert state.vision_worker._thread is not None
    assert state.component_workers[0].stops == [{'close_models': False}]
    assert state.component_workers[0]._thread is not None
    assert state.component_workers[1]._thread is None
    assert state.wire_worker._thread is not None


@pytest.mark.parametrize('failure', ['no_frames', 'wrong_size'])
def test_rollback_requires_fresh_frames_at_old_size(state, failure):
    state.source.fail = 'large' if failure == 'no_frames' else None
    state.source.mismatch = failure == 'wrong_size'
    result = modes.change_mode(state, LARGE, timeout=.12)
    assert result == dict(ok=False, error='camera_mode_failed', restored=True)
    assert state.source.capture_mode == SMALL
    assert state.config.camera.width == 64
    assert modes.mode_info(state)['actual'] == dict(width=64, height=48)
    assert state.revisions == [1, 1]


def test_disconnected_camera_does_not_report_rollback_success(state):
    state.source.fail = 'all'
    result = modes.change_mode(state, LARGE, timeout=.06)
    assert result == dict(ok=False, error='camera_restore_failed', restored=False)
    assert modes.mode_info(state)['actual'] is None


def test_repeated_timestamp_cannot_verify_new_stream(state):
    state.source.frozen = True
    result = modes.change_mode(state, LARGE, timeout=.07)
    assert result['ok'] is False
    assert result['restored'] is False


def test_api_device_binding_capabilities_and_exclusive_camera_lease(state):
    app = FastAPI()
    for name, value in vars(state).items():
        setattr(app.state, name, value)
    app.include_router(router)
    client = TestClient(app)
    info = client.get('/api/camera/modes').json()
    assert info['supported'] and info['actual']['width'] == 64
    body = dict(device_id=info['device_id'], **LARGE)
    assert client.post('/api/camera/modes', json={**body, 'device_id': 'stale'}).status_code == 409
    assert client.post('/api/camera/modes', json={**body, 'fps': 30}).status_code == 422
    assert client.post('/api/camera/modes', json={**body, 'fps': -1}).status_code == 422
    state.camera_control_lock.acquire()
    try:
        assert client.get('/api/camera/modes').json()['busy']
        assert client.post('/api/camera/modes', json=body).status_code == 409
    finally:
        state.camera_control_lock.release()
    result = client.post('/api/camera/modes', json=body)
    assert result.status_code == 200 and result.json()['ok']
    assert result.json()['actual'] == dict(width=96, height=72)
    assert not state.camera_control_lock.locked()
    app.state.config.camera.source = 'synthetic'
    assert client.get('/api/camera/modes').json()['supported'] is False
