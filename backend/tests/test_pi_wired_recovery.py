"""A bad color contour must not prevent independent, current-image recovery."""
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.profiles.store import ProfileStore
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import BoardPoseObservation, refine_board_corners_from_pcb
from app.vision.yolo_profile_detector import YoloProfileDetector


class Locator:
    available = True

    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    def locate(self, frame):
        self.calls += 1
        return self.observation

    def close(self):
        pass


def setup_scene(turn=0):
    reference = np.full((316, 480, 3), (65, 150, 70), np.uint8)
    rng = np.random.default_rng(873)
    for _ in range(700):
        center = tuple(rng.integers([8, 8], [472, 308]).tolist())
        shade = int(rng.integers(10, 245))
        cv2.circle(reference, center, int(rng.integers(2, 7)), (shade, shade, shade), -1)
    src = np.float32([[0, 0], [479, 0], [479, 315], [0, 315]])
    quad = np.float32([[220, 180], [700, 180], [700, 496], [220, 496]])
    rotation = cv2.getRotationMatrix2D((460, 338), turn * 90, 1)
    quad = cv2.transform(quad[None], rotation)[0]
    matrix = cv2.getPerspectiveTransform(src, quad)
    frame = cv2.warpPerspective(reference, matrix, (960, 720), borderValue=(100, 100, 100))
    cv2.line(frame, (420, 0), (420, 360), (65, 150, 70), 13)
    cv2.line(frame, (0, 290), (420, 290), (180, 80, 20), 13)
    # The model sees the body but its corners are not precise board evidence.
    predicted = quad.mean(0) + .8 * (quad - quad.mean(0))
    obs = BoardPoseObservation(predicted, .8, np.full(4, .9), tuple(np.r_[quad.min(0), quad.max(0)]))
    store = ProfileStore(Path(__file__).resolve().parents[2] / 'profiles')
    profile, _ = store.load('raspberry-pi-5')
    detector = YoloProfileDetector(locator=Locator(obs), use_camera_calibration=False)
    detector.load(profile, store.board_dir('raspberry-pi-5'))
    detector._reference_board_bgr = reference
    return detector, frame, obs, quad


@pytest.mark.parametrize('turn', range(4))
@pytest.mark.parametrize('reuse_roi_matcher', [False, True])
def test_wires_recover_from_current_roi_without_new_model_or_global_search(turn, reuse_roi_matcher):
    detector, frame, obs, quad = setup_scene(turn)
    boundary = {}
    assert refine_board_corners_from_pcb(frame, obs, boundary_evidence=boundary) is None
    assert boundary['rejected'] and boundary['at_search_edge']
    if reuse_roi_matcher:
        def forbidden(frame):
            pytest.fail('A fresh primary ROI must not run another YOLO model')
        detector._reference_recovery = ReferencePoseRecovery(
            detector._reference_board_bgr, SimpleNamespace(locate=forbidden, close=lambda: None))
    detector._recover_scene_reference = lambda *args: pytest.fail('Unnecessary global search')
    result = detector.detect(frame, 7, 233.)
    assert detector._locator.calls == 1
    assert result.tracking == 'locked'
    assert len(result.pins) == 40 and result.frame_id == 7 and result.ts_ms == 233.
    assert result.pose_path == 'reference_sift'
    assert result.reference_evidence['scope'] == 'rejected_boundary_roi'
    assert result.reference_evidence['accepted']
    assert result.reference_evidence['boundary']['rejected']
    assert np.max(np.linalg.norm(np.asarray(result.outline_px) - quad, axis=1)) < 2
    assert result.body['confidence'] == .8
    detector.close()
    assert detector._boundary_reference_recovery is None


@pytest.mark.parametrize('kind', ['blank', 'green_desk', 'mirror', 'small_patch'])
def test_uncorroborated_boundary_never_returns_old_pins(kind, monkeypatch):
    detector, frame, obs, _ = setup_scene()
    assert detector.detect(frame, 1, 33.).tracking == 'locked'
    bad = np.full_like(frame, 100)
    if kind == 'green_desk':
        bad[:] = (65, 150, 70)
    elif kind == 'mirror':
        bad = frame[:, ::-1].copy()
    elif kind == 'small_patch':
        bad[220:280, 270:330] = frame[220:280, 270:330]
    # Isolate the boundary-rejection branch; the model continues reporting a
    # body box, but that cannot carry pin identity or renew an old pose.
    def reject(*args, boundary_evidence, **kwargs):
        boundary_evidence.update(rejected=True, fill=.4, at_search_edge=True)
    monkeypatch.setattr('app.vision.yolo_profile_detector.refine_board_corners_from_pcb', reject)
    result = detector.detect(bad, 2, 66.)
    assert result.tracking == 'searching' and not result.pins
    assert result.pose_stability_state == 'pcb_boundary_unverified'
    assert not result.reference_evidence['accepted']
    assert detector._last_locked_result is None
    assert result.body is not None
    detector.close()


def test_clean_contour_does_not_run_boundary_recovery(monkeypatch):
    detector, frame, obs, quad = setup_scene()
    clean = np.full_like(frame, 100)
    cv2.fillConvexPoly(clean, quad.astype(np.int32), (65, 150, 70))
    monkeypatch.setattr(detector, '_recover_boundary_reference', lambda *a: pytest.fail('Not needed'))
    assert detector.detect(clean, 1, 33.).tracking == 'locked'
    detector.close()


def test_camera_reset_and_profile_reload_discard_recovery_state():
    detector, frame, obs, quad = setup_scene()
    assert detector.detect(frame, 1, 33.).tracking == 'locked'
    recovery = detector._boundary_reference_recovery
    assert recovery.evidence['accepted']
    detector.reset_for_camera(use_camera_calibration=False)
    assert recovery.evidence == {} and recovery.last_observation is None
    detector.load(detector._profile, detector._profile_dir)
    assert detector._boundary_reference_recovery is None
    detector.close()
