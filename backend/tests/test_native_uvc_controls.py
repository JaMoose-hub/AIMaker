"""No real device/helper is opened by these camera lifecycle regressions."""
import base64
import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.capture.sources import FfmpegMjpegCameraSource, create_frame_source
from app.capture import windows_uvc
from app.config import AppConfig, CameraConfig


def source():
    return FfmpegMjpegCameraSource(1, 'HD Pro Webcam C920', 64, 48, 30,
        native_uvc_controls=True, focus=10, lock_auto_focus=True,
        exposure=-5, lock_auto_exposure=True, gain=0,
        uvc_image_controls={'saturation': 128, 'sharpness': 128})


def fake_report(settings):
    return {'verified': True, 'controls': [dict(Name=key, Value=data['value'],
        Flags=data['flags'], Verified=True) for key, data in settings.items()]}


def test_native_preflight_does_not_open_opencv_or_reset_unconfigured_controls(monkeypatch):
    calls = []
    def apply(name, settings):
        calls.append((name, settings))
        return fake_report(settings)
    monkeypatch.setattr(windows_uvc, 'apply_controls', apply)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a, **k: pytest.fail('second capture stream'))
    camera = source()
    camera._apply_controls_before_ffmpeg_locked()
    assert len(calls) == 1
    settings = calls[0][1]
    assert settings == {name: {'value': value, 'flags': 2} for name, value in
        [('saturation', 128), ('sharpness', 128), ('focus', 10), ('exposure', -5), ('gain', 0)]}
    assert camera.focus_state()['read_back'] == 10
    assert camera.focus_state()['uvc_controls']['verified']


def test_helper_failure_is_not_reported_as_success(monkeypatch):
    def fail(*args):
        raise RuntimeError('read-back mismatch')
    monkeypatch.setattr(windows_uvc, 'apply_controls', fail)
    camera = source()
    camera._focus_read_back = 10
    camera._apply_controls_before_ffmpeg_locked()
    assert camera.focus_state()['read_back'] is None
    assert camera.focus_state()['uvc_controls']['verified'] is False


@pytest.mark.parametrize('black_first', [False, True])
def test_controls_reapplied_once_after_each_stream_start_before_publishing(monkeypatch, black_first):
    calls = []
    monkeypatch.setattr(windows_uvc, 'apply_controls',
        lambda name, settings: calls.append(settings) or fake_report(settings))
    camera = source()
    camera._closed = False
    before = cv2.imencode('.jpg', np.full((48, 64, 3), 230, np.uint8))[1].tobytes()
    after = cv2.imencode('.jpg', np.full((48, 64, 3), 70, np.uint8))[1].tobytes()
    black = cv2.imencode('.jpg', np.zeros((48, 64, 3), np.uint8))[1].tobytes()
    for restart in range(2):
        chunks = iter(([black] if black_first else []) + [before, after, after, b''])
        process = SimpleNamespace(stdout=SimpleNamespace(read=lambda _: next(chunks)), poll=lambda: None)
        camera._process = process
        camera._apply_controls_before_ffmpeg_locked()
        camera._reader_loop(process)
        assert len(calls) == 2 * (restart + 1)
        assert camera._latest[0].mean() == pytest.approx(70, abs=1)
        assert camera._frame_id == 2 * (restart + 1)  # pre-restoration frame discarded


def test_config_wires_only_ffmpeg_native_path():
    config = AppConfig(camera=CameraConfig(source='device', capture_backend='ffmpeg',
        native_uvc_controls=True, uvc_image_controls={'sharpness': 128}))
    camera, _ = create_frame_source(config)
    assert camera._native_uvc_controls
    assert camera._uvc_image_controls == {'sharpness': 128}
    with pytest.raises(ValueError):
        CameraConfig(uvc_image_controls={'unsupported': 1})


def test_explicit_autofocus_request_preserves_other_configured_properties(monkeypatch):
    camera = source()
    camera._focus = None
    camera._native_autofocus_requested = True
    camera._focus_read_back = 10
    calls = []
    monkeypatch.setattr(windows_uvc, 'apply_controls',
        lambda name, settings: calls.append(settings) or fake_report(settings))
    camera._apply_native_uvc_controls()
    assert calls[0]['focus'] == {'value': 10, 'flags': 1}
    assert calls[0]['gain'] == {'value': 0, 'flags': 2}


@pytest.mark.parametrize('failure', [None, 'process', 'readback'])
def test_helper_is_bounded_hidden_and_uses_literal_argv(monkeypatch, failure):
    monkeypatch.setattr(windows_uvc.os, 'name', 'nt')
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=1 if failure == 'process' else 0,
            stderr='failure', stdout=json.dumps({'verified': failure != 'readback'}))
    monkeypatch.setattr(windows_uvc.subprocess, 'run', run)
    if failure:
        with pytest.raises(RuntimeError):
            windows_uvc.apply_controls('camera with spaces', {'gain': {'value': 0, 'flags': 2}})
    else:
        windows_uvc.apply_controls('camera with spaces', {'gain': {'value': 0, 'flags': 2}})
    argv, kwargs = calls[0]
    assert argv[argv.index('-DeviceName') + 1] == 'camera with spaces'
    assert json.loads(base64.b64decode(argv[-1])) == {'gain': {'value': 0, 'flags': 2}}
    assert kwargs['timeout'] == 12 and 'shell' not in kwargs
    assert 'creationflags' in kwargs
