"""Camera changes must discard old geometry without unloading ONNX sessions."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.body_worker import BodyVisionWorker
from app.capture.bus import FrameBus
from app.component_worker import ComponentPoseResult, ComponentPoseState, ComponentPoseWorker
from app.motion_worker import MotionFrameState, MotionOverlayWorker
from app.vision.camera_model import default_camera
from app.vision.factory import create_detector
from app.vision.interface import DetectionResult
from app.vision.pipeline_detector import PipelineDetector
from app.vision.yolo_profile_detector import HybridBoardDetector, YoloProfileDetector
from app.vision_worker import DetectionState
from vision_fixtures.make_fixture import build_fixture


ROOT = Path(__file__).resolve().parents[2]
FRAME = np.zeros((480, 640, 3), np.uint8)


class Locator:
    available = True

    def __init__(self):
        self.closed = False

    def locate(self, frame):
        assert not self.closed
        return None

    def close(self):
        self.closed = True


def calibration(path, focal):
    path.write_text(json.dumps({
        'fx': focal, 'fy': focal, 'cx': 320, 'cy': 240,
        'dist': [0.01] * 5, 'quality_status': 'ok', 'image_size': [640, 480],
    }), encoding='utf-8')
    return path


@pytest.mark.parametrize('use_calibration', [True, False])
@pytest.mark.parametrize('shared_file', [True, False])
def test_eye_bypasses_shared_and_profile_calibration_and_c920_fov(tmp_path, use_calibration, shared_file):
    profile, directory = build_fixture(tmp_path / 'profile')
    calibration(directory / 'camera.json', 600)
    shared = calibration(tmp_path / 'shared.json', 900) if shared_file else None
    settings = dict(camera_calibration_path=shared, horizontal_fov_deg=70.42,
                    use_camera_calibration=use_calibration)
    primary = YoloProfileDetector(locator=Locator(), **settings)
    fallback = PipelineDetector(**settings)
    primary.load(profile, directory)
    fallback.load(profile, directory)
    primary._ensure_camera(FRAME)
    fallback.detect(FRAME, 1, 1000)
    for camera in (primary._camera, fallback.tracker._camera):
        assert camera.calibrated is use_calibration
        if use_calibration:
            assert camera.K[0, 0] == (900 if shared_file else 600)
        else:
            np.testing.assert_array_equal(camera.K, default_camera((640, 480)).K)
            np.testing.assert_array_equal(camera.dist, np.zeros(5))
    primary.close()


def test_factory_routes_eye_calibration_flag_to_both_detectors(tmp_path, monkeypatch):
    from app.vision import yolo_profile_detector as module
    monkeypatch.setattr(module, 'create_yolo_pose_locator', lambda *args, **kwargs: Locator())
    profile, directory = build_fixture(tmp_path / 'profile')
    calibration(directory / 'camera.json', 600)
    detector = create_detector('hybrid', profile, directory, yolo_model_path='unused',
                               use_camera_calibration=False, horizontal_fov_deg=70.42)
    detector.primary._ensure_camera(FRAME)
    detector.fallback.detect(FRAME, 1, 1000)
    assert not detector.primary._camera.calibrated
    assert not detector.fallback.tracker._camera.calibrated
    detector.close()


def test_same_resolution_camera_reset_clears_hybrid_holds_and_preserves_locator(tmp_path):
    profile, directory = build_fixture(tmp_path / 'profile')
    shared = calibration(tmp_path / 'shared.json', 900)
    locator = Locator()
    primary = YoloProfileDetector(locator=locator, camera_calibration_path=shared)
    fallback = PipelineDetector(camera_calibration_path=shared)
    detector = HybridBoardDetector(primary, fallback)
    detector.load(profile, directory)
    primary._ensure_camera(FRAME)
    fallback.detect(FRAME, 10, 1000)
    reference_features = fallback.tracker._ref_desc
    old_result = DetectionResult(profile.board.id, 10, 1000., 'locked', .9, [])
    primary._last_locked_result = old_result
    primary._visibility_baseline = .8
    primary._pending_outline = np.zeros((4, 2))
    fallback.tracker._last_locked_result = old_result
    fallback.tracker._prev_gray = FRAME[:, :, 0]
    fallback.tracker.sm.state = 'locked'
    detector.reset_for_camera(use_camera_calibration=False)
    assert primary._locator is locator and not locator.closed
    assert primary._last_locked_result is None and primary._visibility_baseline is None
    assert primary._pending_outline is None
    assert fallback.tracker._last_locked_result is None
    assert fallback.tracker._prev_gray is None
    assert fallback.tracker.sm.state == 'searching'
    assert fallback.tracker._ref_desc is reference_features
    primary._ensure_camera(FRAME)
    assert not primary._camera.calibrated
    assert primary.detect(FRAME, 11, 1100).tracking == 'searching'
    detector.reset_for_camera(camera_calibration_path=shared, horizontal_fov_deg=70.42)
    primary._ensure_camera(FRAME)
    fallback.detect(FRAME, 12, 1200)
    assert primary._camera.calibrated and fallback.tracker._camera.calibrated
    detector.close()


def test_component_reset_drops_same_size_state_without_closing_model():
    state = ComponentPoseState()
    locator = Locator()
    worker = ComponentPoseWorker(bus=FrameBus(), state=state, model_path='unused',
        profile_path=ROOT / 'profiles/components/hc-sr04/vision_profile.json',
        publish=lambda _: None, locator=locator)
    old = ComponentPoseResult('hc-sr04', 10, 1000., 'locked', .9, (640, 480),
                              np.zeros((4, 2)), (), 'tracking')
    state.set(old)
    worker._tracker._last_good = old
    worker._tracker._last_result = old
    worker._tracker._last_input = (10, 1000., (640, 480))
    worker.stop(close_models=False)
    worker.reset_tracking()
    assert state.get() is None and state.all() == ()
    assert worker._tracker._last_good is None and worker._tracker._last_input is None
    result = worker._tracker.update(FRAME, None, frame_id=11, ts_ms=1100.)
    assert result.tracking == 'searching' and not result.pins
    assert not locator.closed
    worker.start()
    assert worker._thread.is_alive() and not worker._stop.is_set()
    worker.stop()
    assert locator.closed


def test_motion_and_body_restart_clear_source_packets_and_keep_body_model():
    bus, state = FrameBus(), MotionFrameState()
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1))
    body_locator = Locator()
    demand = SimpleNamespace(requested=lambda: False)
    body = BodyVisionWorker(bus, runtime, demand, body_locator)
    body._pair = ('old-frame', 'old-body')
    body.stop(close_models=False)
    body.start()
    assert body._thread.is_alive() and not body._stop.is_set()
    body.stop(close_models=False)
    assert body.get_synchronized() is None and not body_locator.closed
    motion = MotionOverlayWorker(bus, DetectionState(), ComponentPoseState(), runtime, state)
    motion.tracks['old'] = object()
    motion.body_tracks['old'] = object()
    state.set({'seq': 20}, 'old-frame')
    motion.reset_tracking()
    assert not motion.tracks and not motion.body_tracks
    assert state._packet is None and state._source is None
    motion.set_target_fps(60)
    assert motion.interval == pytest.approx(1 / 60)
    motion.stop()
    motion.start()
    assert motion._thread.is_alive() and not motion._stop.is_set()
    motion.stop()
    body.stop()
    assert body_locator.closed


@pytest.mark.parametrize('hz', [0, -1, 61, float('nan'), float('inf')])
def test_invalid_display_rate_does_not_poison_timing(hz):
    worker = MotionOverlayWorker(None, None, None, None, MotionFrameState())
    with pytest.raises(ValueError):
        worker.set_target_fps(hz)
    assert worker.interval == pytest.approx(1 / 30)
