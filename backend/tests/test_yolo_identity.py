"""Wiring-model identity must survive a rejected pin solve, never a new frame."""
from pathlib import Path

import numpy as np
import pytest

from app.profiles.store import ProfileStore
from app.vision.interface import DetectionResult
from app.vision.yolo_pose import BoardPoseObservation
from app.vision.yolo_profile_detector import HybridBoardDetector, YoloProfileDetector


class Locator:
    available = True

    def __init__(self):
        self.observation = BoardPoseObservation(
            corners_px=np.array([[200, 150], [600, 150], [600, 400], [200, 400.]]),
            confidence=.89, keypoint_confidences=np.full(4, .9),
            box_xyxy=(200., 150., 600., 400.),
        )

    def locate(self, frame):
        return self.observation


class MissingFeatures:
    def load(self, profile, directory):
        self.board_id = profile.board.id

    def detect(self, frame, frame_id, ts_ms):
        return DetectionResult(self.board_id, frame_id, ts_ms, 'searching', 0)


@pytest.mark.parametrize('hybrid', [False, True])
def test_fresh_yolo_identity_survives_pcb_rejection_but_never_survives_missing_model(monkeypatch, hybrid):
    import app.vision.yolo_profile_detector as module

    def reject_boundary(frame, observation, *, boundary_evidence=None, **kwargs):
        boundary_evidence.update(rejected=True, fill=.42)
        return None

    monkeypatch.setattr(module, 'refine_board_corners_from_pcb', reject_boundary)
    root = Path(__file__).resolve().parents[2] / 'profiles'
    profile = ProfileStore(root).profile('raspberry-pi-5')
    locator = Locator()
    primary = YoloProfileDetector(locator=locator)
    detector = HybridBoardDetector(primary, MissingFeatures()) if hybrid else primary
    detector.load(profile, root / 'boards/raspberry-pi-5')
    frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
    result = detector.detect(frame, 10, 1000.)
    assert result.tracking == 'searching'
    assert result.pins == []
    assert result.pose_stability_state == 'pcb_boundary_unverified'
    assert result.body == {'box': [200., 150., 600., 400.], 'confidence': .89, 'source': 'pose_model'}

    locator.observation = None
    next_result = detector.detect(frame, 11, 1050.)
    assert next_result.frame_id == 11
    assert next_result.body is None
    assert next_result.pins == []


@pytest.mark.parametrize('use_existing_roi_model', [False, True])
def test_eye_yolo_immediately_projects_gpio_without_feature_or_stability_judges(monkeypatch, use_existing_roi_model):
    import app.vision.yolo_profile_detector as module
    from app.vision.reference_recovery import ReferencePoseRecovery

    def forbidden(*args, **kwargs):
        raise AssertionError('Eye must run YOLO and profile projection only')

    root = Path(__file__).resolve().parents[2] / 'profiles'
    profile = ProfileStore(root).profile('raspberry-pi-5')
    primary_locator, roi_locator = Locator(), Locator()
    primary = YoloProfileDetector(locator=primary_locator)
    fallback = MissingFeatures()
    detector = HybridBoardDetector(primary, fallback)
    detector.load(profile, root / 'boards/raspberry-pi-5')
    primary._reference_recovery = ReferencePoseRecovery(None, roi_locator)
    primary._reference_recovery.locate = forbidden
    fallback.detect = forbidden
    monkeypatch.setattr(module, 'refine_board_corners_from_pcb', forbidden)
    monkeypatch.setattr(module, 'solve_landmark_pose', forbidden)
    if use_existing_roi_model:
        primary_locator.observation = None
    detector.set_yolo_only(True)
    frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
    if use_existing_roi_model:
        # Eye budgets one YOLO forward per frame, so the reference model is
        # tried on the next frame after the primary model misses.
        searching = detector.detect(frame, 20, 2067.)
        assert searching.pins == [] and searching.body is None
    result = detector.detect(frame, 21, 2100.)
    if use_existing_roi_model:
        assert result.tracking == 'searching' and result.pins == []
        assert result.body is not None and result.pose_path == 'yolo_body_only'
    else:
        assert result.tracking == 'locked' and len(result.pins) == 40
    assert result.frame_id == 21 and result.ts_ms == 2100.
    assert result.pose_stability_state == 'yolo_direct'
    assert result.reference_evidence is None
    assert all(np.isfinite([pin.x, pin.y]).all() for pin in result.pins)
    primary_locator.observation = roi_locator.observation = None
    missing = detector.detect(frame, 22, 2133.)
    assert missing.pins == [] and missing.body is None
    assert missing.tracking == 'searching'
