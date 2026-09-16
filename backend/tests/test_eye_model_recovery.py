"""Fresh identity and bounded zoom recovery retain the existing model contract."""
from pathlib import Path
from dataclasses import replace

import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPoseState, ComponentPoseWorker
from app.profiles.store import ProfileStore
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.scale_recovery import ComponentScaleRecovery
from app.vision.yolo_pose import BoardPoseObservation
from app.vision.yolo_profile_detector import HybridBoardDetector, YoloProfileDetector
from test_yolo_identity import MissingFeatures

ROOT = Path(__file__).resolve().parents[2]


def observation():
    return BoardPoseObservation(np.array([[2., 3.], [8., 3.], [8., 9.], [2., 9.]]),
                                .8, np.full(4, .9), (1., 2., 10., 12.),
                                landmarks_px=np.array([[2., 3.], [8., 3.], [8., 9.], [2., 9.], [5., 6.]]))


class Locator:
    available = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.shapes = []

    def locate(self, frame):
        self.shapes.append(frame.shape[:2])
        return next(self.outputs)


def test_reference_identity_survives_missing_sift_but_clears_every_call():
    candidate = observation()
    recovery = ReferencePoseRecovery(None, Locator([candidate, None]))
    frame = np.zeros((100, 200, 3), np.uint8)
    assert recovery.locate(frame) is None
    assert recovery.last_observation is candidate
    assert recovery.evidence['reason'] == 'missing_reference_features'
    assert recovery.locate(frame) is None
    assert recovery.last_observation is None
    recovery.last_observation = candidate
    assert recovery.locate(None) is None
    assert recovery.last_observation is None


@pytest.mark.parametrize('hybrid', [False, True])
def test_pi_reference_yolo_is_only_identity_when_sift_fails(hybrid):
    primary = YoloProfileDetector(locator=Locator([None, None]), use_camera_calibration=False)
    profile = ProfileStore(ROOT / 'profiles').profile('raspberry-pi-5')
    detector = HybridBoardDetector(primary, MissingFeatures()) if hybrid else primary
    detector.load(profile, ROOT / 'profiles/boards/raspberry-pi-5')
    candidate = replace(observation(), box_xyxy=(10., 20., 100., 90.))
    primary._reference_recovery = ReferencePoseRecovery(None, Locator([candidate, None]))
    frame = np.zeros((100, 200, 3), np.uint8)
    result = detector.detect(frame, 10, 1000.)
    assert result.body == {'box': [10., 20., 100., 90.], 'confidence': .8, 'source': 'pi_reference_model'}
    assert result.tracking == 'searching' and result.pins == []
    assert detector.detect(frame, 11, 1100.).body is None


def test_tile_remaps_all_geometry_and_reuses_successful_tile_until_miss():
    recovery = ComponentScaleRecovery()
    candidate = observation()
    locator = Locator([None, candidate, candidate, None, candidate])
    frame = np.zeros((100, 200, 3), np.uint8)
    assert recovery.locate(frame, locator) is None
    for _ in range(2):
        recovered = recovery.locate(frame, locator)
        np.testing.assert_array_equal(recovered.corners_px, candidate.corners_px + [100, 0])
        np.testing.assert_array_equal(recovered.landmarks_px, candidate.landmarks_px + [100, 0])
        assert recovered.box_xyxy == (101., 2., 110., 12.)
        assert recovered.confidence == candidate.confidence
    assert recovery.locate(frame, locator) is None
    recovered = recovery.locate(frame, locator)
    np.testing.assert_array_equal(recovered.corners_px, candidate.corners_px + [0, 50])
    assert locator.shapes == [(50, 100)] * 5
    recovery.reset()
    assert recovery._cursor == 0


def test_source_shape_change_resets_tile_before_inference():
    recovery = ComponentScaleRecovery()
    locator = Locator([None, observation()])
    assert recovery.locate(np.zeros((100, 200, 3), np.uint8), locator) is None
    result = recovery.locate(np.zeros((200, 400, 3), np.uint8), locator)
    np.testing.assert_array_equal(result.corners_px, observation().corners_px)


@pytest.mark.parametrize('component', ['hc-sr04', 'hw-123'])
def test_scale_recovery_is_eye_hc_only_and_never_runs_on_full_success(component):
    candidate = observation()
    locator = Locator([None, candidate, None, candidate] if component == 'hc-sr04'
                      else [None, candidate, None])
    worker = ComponentPoseWorker(bus=FrameBus(), state=ComponentPoseState(),
        model_path='unused', profile_path=ROOT / f'profiles/components/{component}/vision_profile.json',
        publish=lambda _: None, locator=locator)
    frame = np.zeros((100, 200, 3), np.uint8)
    assert worker._locate(frame) is None  # disabled has exactly one call
    worker.set_scale_recovery(True)
    assert worker._locate(frame) is candidate  # full success has exactly one call
    result = worker._locate(frame)
    assert len(locator.shapes) == (4 if component == 'hc-sr04' else 3)
    assert (result is not None) is (component == 'hc-sr04')
    worker._scale_recovery._cursor = 2
    worker.set_scale_recovery(False)
    assert worker._scale_recovery._cursor == 0
    worker._scale_recovery._cursor = 2
    worker.reset_tracking()
    assert worker._scale_recovery._cursor == 0


def test_vertical_strips_start_center_and_reject_artificial_boundary_crossing():
    recovery = ComponentScaleRecovery(vertical_strips=True)
    candidate = observation()
    locator = Locator([candidate, None,
        replace(candidate, box_xyxy=(10., 2., 110., 12.)),
        replace(candidate, box_xyxy=(-5., 2., 20., 12.))])
    frame = np.zeros((100, 200, 3), np.uint8)
    first = recovery.locate(frame, locator)
    np.testing.assert_array_equal(first.corners_px, candidate.corners_px + [50, 0])
    assert locator.shapes == [(100, 100)]
    assert recovery.locate(frame, locator) is None  # center missing
    assert recovery.locate(frame, locator) is None  # left box crosses right crop edge
    assert recovery.locate(frame, locator) is None  # right box crosses left crop edge
    assert recovery._cursor == 0


@pytest.mark.parametrize('component,pin_count', [('hc-sr04', 4), ('hw-123', 8), ('mrd-tf240-8p-cs', 8)])
def test_eye_yolo_projects_immediate_same_frame_pins_without_other_judges(component, pin_count, monkeypatch):
    import app.component_worker as module

    def forbidden(*args, **kwargs):
        raise AssertionError('Eye direct YOLO must not invoke another pose judge')

    candidate = replace(observation(), corners_px=np.array([[40., 20.], [140., 20.], [140., 80.], [40., 80.]]),
                        box_xyxy=(35., 15., 145., 85.), landmarks_px=None)
    locator = Locator([candidate, None] if component == 'hw-123' else [candidate, None, None])
    state = ComponentPoseState()
    worker = ComponentPoseWorker(bus=FrameBus(), state=state, model_path='unused',
        profile_path=ROOT / f'profiles/components/{component}/vision_profile.json',
        publish=forbidden, locator=locator)
    worker._tracker.update = forbidden
    if worker._reference_recovery is not None:
        worker._reference_recovery.locate = forbidden
    for name in ['refine_component_corners_from_pcb', 'orient_component_corners_from_pin_row']:
        monkeypatch.setattr(module, name, forbidden)
    # Eye's optional current-image mounting-hole adjustment retains the model
    # immediately when unavailable; it never calls another identity model.
    monkeypatch.setattr(module, 'refine_component_corners_from_mounting_holes', lambda *_, **__: None)
    worker.set_yolo_only(True)
    frame = np.zeros((100, 200, 3), np.uint8)
    first = worker.detect_yolo_frame(FrameSlot(frame, 20, 2000., 1))
    assert first.frame_id == 20 and first.ts_ms == 2000.
    assert first.tracking == 'locked' and first.stability == 'yolo_direct'
    assert len(first.pins) == pin_count
    assert all(np.isfinite([pin.x, pin.y]).all() for pin in first.pins)
    assert first.reference_evidence is None and first.reacquire_evidence is None
    assert state.get() is None  # caller owns same-frame publication
    missing = worker.detect_yolo_frame(FrameSlot(frame, 21, 2300., 2))
    assert missing.frame_id == 21 and missing.pins == () and missing.body is None
    worker.set_yolo_only(False)
    assert not worker._yolo_only and not worker._scale_recovery_enabled


def test_tft_scale_miss_preserves_original_yolo_for_direct_pin_projection():
    # Real Eye fixture: full-frame TFT keypoints are inside the display. A crop
    # is scheduled for the next frame; current direct YOLO is still displayed.
    candidate = BoardPoseObservation(np.array([[1150.9, 588.5], [1140., 537.3],
        [1227.6, 555.9], [1232.7, 608.1]]), .6186, np.full(4, .85),
        (1044.25, 435.98, 1361.89, 686.57))
    worker = ComponentPoseWorker(bus=FrameBus(), state=ComponentPoseState(), model_path='unused',
        profile_path=ROOT / 'profiles/components/mrd-tf240-8p-cs/vision_profile.json',
        publish=lambda _: None, locator=Locator([candidate, None]))
    worker.set_yolo_only(True)
    result = worker.detect_yolo_frame(FrameSlot(np.zeros((1080, 1920, 3), np.uint8), 30, 3000., 1))
    assert result.tracking == 'locked' and len(result.pins) == 8
    assert result.body['confidence'] == .6186
    assert len(worker._locator.shapes) == 1
    missing = worker.detect_yolo_frame(FrameSlot(np.zeros((1080, 1920, 3), np.uint8), 31, 3033., 2))
    assert missing.frame_id == 31 and missing.pins == () and missing.body is None
    assert len(worker._locator.shapes) == 2
