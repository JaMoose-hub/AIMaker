"""Geometry and reflective-chroma regressions; no claim of physical accuracy."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from app.vision.motion_tracking import PlanarFlow
from app.vision.pose_tracker import PoseTracker, TrackerParams
from app.vision.yolo_pose import BoardPoseObservation

ROOT = Path(__file__).resolve().parents[2]


def test_partial_offscreen_seed_does_not_poison_valid_template():
    gray = np.random.default_rng(9).integers(0, 256, (300, 400), dtype=np.uint8)
    quad = np.float32([[50, 50], [250, 50], [250, 200], [50, 200]])
    flow = PlanarFlow()
    assert flow.seed(gray, quad)
    assert not flow.seed(gray, quad + [-100, 0])
    assert flow.failure_reason == 'seed_outside_frame'
    np.testing.assert_array_equal(flow.quad, quad)
    assert flow.step(gray) is not None


@pytest.mark.parametrize('delta,expected', [(0, True), (-100, False), (300, False)])
def test_feature_pose_polygon_requires_inframe_geometry(delta, expected):
    tracker = object.__new__(PoseTracker)
    tracker.params = TrackerParams()
    tracker._video_size = (400, 300)
    quad = np.array([[50, 50], [250, 50], [250, 200], [50, 200]], dtype=float)
    quad[:, 0] += delta
    assert bool(tracker._polygon_ok(quad)) is expected


def test_sparse_skin_colored_noise_is_not_a_hand_but_contiguous_skin_is():
    frame = np.full((160, 200, 3), 120, dtype=np.uint8)
    quad = np.float64([[10, 10], [190, 10], [190, 150], [10, 150]])
    frame[::3, ::3] = (80, 130, 190)
    assert ComponentPoseTracker._hand_fraction(frame, quad) < .01
    frame[30:120, 50:140] = (80, 130, 190)
    assert ComponentPoseTracker._hand_fraction(frame, quad) > .25


def test_saved_hc_reflection_recovers_after_expiry_without_lowering_threshold():
    path = ROOT / 'runs/acceptance/2026-09-11/S02-HC-dark-center-quick-01/scene-after-sample.jpg'
    if not path.exists():
        pytest.skip('optional on-site image unavailable')
    frame = cv2.imread(str(path))
    corners = np.float64([[1162.93494,593.35925], [838.87604,600.79175],
                          [835.73102,463.67130], [1159.78992,456.23874]])
    profile = ComponentVisionProfile.load(ROOT / 'profiles/components/hc-sr04/vision_profile.json')
    tracker = ComponentPoseTracker(profile, reacquire_min_visible_fraction=.25)
    obs = BoardPoseObservation(corners, .4139, np.ones(4),
                               (*corners.min(0), *corners.max(0)))
    assert tracker._hand_fraction(frame, corners) < tracker.hand_fraction_threshold
    tracker.update(frame, None, frame_id=0, ts_ms=0)
    for i in range(1, 9):
        result = tracker.update(frame, obs, frame_id=i, ts_ms=i*300)
    assert result.tracking == 'locked'
    assert len(result.pins) == 4
