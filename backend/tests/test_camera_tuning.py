"""Hardware-free tuning state machine, rollback, metrics, and API regressions."""
import copy
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.camera_tuning import CameraTuner, TuneStopped, fixed_regions, is_better, quality, snap
from app.capture import control_store


class Source:
    supports_live_controls = True
    control_identity = 'fake-device'

    def __init__(self):
        self.props = {
            'focus': dict(Min=0, Max=250, Step=5, Default=0, Caps=3, Value=10, Flags=2),
            'exposure': dict(Min=-11, Max=-1, Step=1, Default=-5, Caps=3, Value=-5, Flags=2),
            'gain': dict(Min=0, Max=255, Step=1, Default=0, Caps=2, Value=0, Flags=2),
        }
        self.calls = []

    def settings(self):
        return {k: dict(value=p['Value'], flags=p['Flags']) for k, p in self.props.items()}

    def read_live_controls(self):
        return dict(controls=[dict(Name=k, **v) for k, v in self.props.items()])

    def apply_live_controls(self, settings):
        self.calls.append(copy.deepcopy(settings))
        for k, v in settings.items():
            self.props[k].update(Value=v['value'], Flags=v['flags'])
        return {'verified': True}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(control_store, 'STORE', tmp_path / 'runs' / 'camera-settings.json')
    source = Source()
    slot = SimpleNamespace(frame=np.full((80, 100, 3), 80, np.uint8), ts_ms=time.monotonic() * 1000)
    state = SimpleNamespace(source=source, config=SimpleNamespace(camera=SimpleNamespace(source='device', fps=30)),
                            frame_bus=SimpleNamespace(get_latest=lambda *a, **k: slot, latest_seq=0),
                            camera_control_lock=threading.Lock())
    tuner = CameraTuner(state, settle_s=0, samples=2)
    state.camera_tuner = tuner
    def measure(*a):
        tuner._check(source)
        value = source.props['focus']['Value']
        score = 2. if value == 20 else 1.
        return metrics(score)
    monkeypatch.setattr(tuner, '_measure', measure)
    return state, source, tuner


def metrics(score, *, sharpness=100., detected=1.):
    return dict(score=score, regions={'workspace': dict(score=score, highlight=0., sharpness=sharpness, level=90)},
                detected={'raspberry-pi-5': detected})


def finish(tuner):
    tuner._thread.join(6)
    assert not tuner._thread.is_alive()
    assert not tuner.state.camera_control_lock.locked()
    return tuner.snapshot()


def test_improvement_verified_saved_and_undo_restores_original_modes(rig):
    state, source, tuner = rig
    source.props['focus']['Flags'] = 1
    original = source.settings()
    assert tuner.start()['ok']
    result = finish(tuner)
    assert result['state'] == 'improved' and result['saved'] and result['can_restore']
    assert source.props['focus']['Value'] == 20
    assert control_store.load(source.control_identity) == source.settings()
    assert tuner.start(restore=True)['ok']
    assert finish(tuner)['state'] == 'restored'
    assert source.settings() == original
    assert not control_store.load(source.control_identity)


def test_no_improvement_rolls_back_and_never_saves(rig, monkeypatch):
    state, source, tuner = rig
    original = source.settings()
    monkeypatch.setattr(tuner, '_measure', lambda *a: metrics(1))
    tuner.start()
    result = finish(tuner)
    assert result['state'] == 'unchanged' and not result['saved']
    assert source.settings() == original
    assert not control_store.STORE.exists()


@pytest.mark.parametrize('reason', ['no_frames', 'moving', 'timeout', 'cancelled'])
def test_interrupted_trial_restores_original_and_releases_lease(rig, monkeypatch, reason):
    state, source, tuner = rig
    original = source.settings()
    count = 0
    def measure(*a):
        nonlocal count
        count += 1
        if count > 1:
            raise TuneStopped(reason)
        return metrics(1)
    monkeypatch.setattr(tuner, '_measure', measure)
    tuner.start()
    result = finish(tuner)
    assert result['reason'] == reason
    assert source.settings() == original
    assert not control_store.STORE.exists()


def test_partial_write_failure_is_rolled_back(rig, monkeypatch):
    state, source, tuner = rig
    original = source.settings()
    apply = source.apply_live_controls
    calls = 0
    def fail(settings):
        nonlocal calls
        calls += 1
        apply(settings)
        if calls == 2:
            raise RuntimeError('partial write')
    monkeypatch.setattr(source, 'apply_live_controls', fail)
    tuner.start()
    assert finish(tuner)['reason'] == 'control_failed'
    assert source.settings() == original


def test_rollback_failure_remains_visible_and_retryable(rig, monkeypatch):
    state, source, tuner = rig
    monkeypatch.setattr(source, 'apply_live_controls', lambda *a: (_ for _ in ()).throw(RuntimeError('refused')))
    tuner.start()
    status = finish(tuner)
    assert status['reason'] == 'restore_failed' and status['can_restore']
    assert not status['saved']


def test_save_failure_reverts_hardware(rig, monkeypatch):
    state, source, tuner = rig
    before = source.settings()
    monkeypatch.setattr(control_store, 'save', lambda *a: (_ for _ in ()).throw(OSError('full disk')))
    tuner.start()
    assert finish(tuner)['reason'] == 'control_failed'
    assert source.settings() == before


def test_eye_and_unsupported_devices_do_not_touch_camera(rig):
    state, source, tuner = rig
    state.config.camera.source = 'xreal'
    assert not tuner.snapshot()['available']
    assert tuner.start() == {'ok': False, 'reason': 'unsupported'}
    assert not source.calls


def test_busy_lease_blocks_duplicate_tuning_and_other_camera_mutations(rig):
    from app.api.camera_tuning import camera_mutation_guard, router
    from fastapi import Depends
    state, source, tuner = rig
    app = FastAPI()
    app.state = state
    app.include_router(router)
    @app.post('/other', dependencies=[Depends(camera_mutation_guard)])
    def other():
        return {'ok': True}
    state.camera_control_lock.acquire()
    try:
        with TestClient(app) as client:
            assert client.post('/api/camera/auto-tune').json()['reason'] == 'busy'
            assert client.post('/other').status_code == 409
            assert client.get('/api/camera/auto-tune').status_code == 200
    finally:
        state.camera_control_lock.release()
    assert not source.calls


def test_native_focus_is_live_and_does_not_restart_ffmpeg(monkeypatch):
    from app.capture.sources import FfmpegMjpegCameraSource
    from app.capture import windows_uvc
    source = FfmpegMjpegCameraSource(1, 'mock', 64, 48, 30, native_uvc_controls=True, focus=10)
    monkeypatch.setattr(source, '_stop_process_locked', lambda: pytest.fail('stream stopped'))
    monkeypatch.setattr(source, '_ensure_started', lambda **kw: pytest.fail('stream restarted'))
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *a: pytest.fail('second handle opened'))
    monkeypatch.setattr(windows_uvc, 'read_controls', lambda *a: Source().read_live_controls())
    monkeypatch.setattr(windows_uvc, 'apply_controls', lambda name, settings: {
        'verified': True, 'controls': [dict(Name=k, Value=v['value'], Flags=v['flags']) for k, v in settings.items()]})
    assert source.set_focus(20) == (True, 20)
    assert source._live_control_overrides['focus'] == {'value': 20, 'flags': 2}
    assert source.set_focus(None)[0]
    assert source._live_control_overrides['focus']['flags'] == 1


def test_local_profiles_are_device_specific_and_reject_invalid_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(control_store, 'STORE', tmp_path / 'camera-settings.json')
    key = control_store.identity('C920', 1920, 1080, 30)
    settings = {'focus': {'value': 20, 'flags': 2}}
    control_store.save(key, settings)
    assert control_store.load(key) == settings
    assert not control_store.load(control_store.identity('C920', 1280, 720, 30))
    with pytest.raises(ValueError):
        control_store.save(key, {'password': {'value': 20, 'flags': 2}})
    assert not list(tmp_path.glob('*.tmp'))


def test_quality_penalizes_blur_and_clipping_and_works_without_detections():
    rng = np.random.default_rng(9)
    texture = np.repeat(rng.integers(40, 170, (120, 160, 1), dtype=np.uint8), 3, axis=2)
    regions = fixed_regions(texture, {})
    normal, _ = quality(texture, regions)
    blur, _ = quality(cv2.GaussianBlur(texture, (15, 15), 5), regions)
    clip, _ = quality(np.full_like(texture, 255), regions)
    assert normal['workspace']['score'] > blur['workspace']['score'] > clip['workspace']['score']


def test_average_cannot_hide_loss_of_other_component():
    baseline = metrics(1)
    assert not is_better(metrics(2, detected=0), baseline)
    assert not is_better(metrics(2, sharpness=20), baseline)
    assert is_better(metrics(1.5), baseline)


def test_snap_respects_driver_increment():
    prop = dict(Min=0, Max=250, Step=5)
    assert snap(prop, 13) == 15
    assert snap(prop, -100) == 0
    assert snap(prop, 500) == 250


def test_measure_requires_fresh_frames_and_never_reuses_cached_image(rig):
    state, source, tuner = rig
    tuner._deadline = time.monotonic() + 5
    state.frame_bus = SimpleNamespace(latest_seq=20, get_latest=lambda *a, **kw: None)
    with pytest.raises(TuneStopped, match='no_frames'):
        CameraTuner._measure(tuner, source, {'workspace': (0,0,100,80)}, (80,100,3))
    old = SimpleNamespace(frame=np.zeros((80,100,3),np.uint8), seq=21, ts_ms=0)
    state.frame_bus.get_latest = lambda *a, **kw: old
    with pytest.raises(TuneStopped, match='no_frames'):
        CameraTuner._measure(tuner, source, {'workspace': (0,0,100,80)}, (80,100,3))


def test_device_profile_reapplied_on_start_without_new_stream(rig, monkeypatch):
    from app.capture.sources import FfmpegMjpegCameraSource
    from app.capture import windows_uvc
    key = control_store.identity('mock startup', 1920,1080,30)
    control_store.save(key, {'focus':dict(value=30,flags=2), 'exposure':dict(value=-6,flags=2)})
    writes=[]
    monkeypatch.setattr(windows_uvc, 'apply_controls', lambda device,settings: writes.append(copy.deepcopy(settings)) or {
        'verified':True,'controls':[dict(Name=k,Value=v['value'],Flags=v['flags']) for k,v in settings.items()]})
    source = FfmpegMjpegCameraSource(1,'mock startup',1920,1080,30,native_uvc_controls=True,focus=10)
    source._apply_native_uvc_controls()
    assert writes[-1]['focus']['value'] == 30
    assert writes[-1]['exposure']['value'] == -6
    assert source.focus_state()['configured_focus'] == 30
    # A saved profile must also be applied when config has no explicit values.
    unconfigured = FfmpegMjpegCameraSource(1,'mock startup',1920,1080,30,native_uvc_controls=True)
    assert unconfigured._controls_requested()


def test_read_only_helper_never_writes(monkeypatch):
    from app.capture import windows_uvc
    monkeypatch.setattr(windows_uvc.os, 'name', 'nt')
    calls=[]
    def run(argv,**kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0,stdout='{"controls":[]}',stderr='')
    monkeypatch.setattr(windows_uvc.subprocess,'run',run)
    windows_uvc.read_controls('mock')
    assert '-ReadOnly' in calls[0] and '-SettingsBase64' not in calls[0]
