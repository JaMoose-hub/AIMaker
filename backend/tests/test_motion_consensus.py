import cv2
import numpy as np
import pytest

from app.vision.motion_consensus import MotionConsensus
from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from app.vision.yolo_pose import BoardPoseObservation


def scene():
    frame = np.full((480, 640, 3), 25, np.uint8)
    frame[100:300, 120:400] = (180, 60, 20)
    rng = np.random.default_rng(91)
    for _ in range(180):
        x, y = rng.integers([130, 110], [390, 290])
        cv2.circle(frame, (int(x), int(y)), 3, (230, 230, 230), -1)
    quad = np.float32([[120, 100], [400, 100], [400, 300], [120, 300]])
    return frame, quad


def shifted(frame, quad, dx):
    image = cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, 0]]), (640, 480))
    return image, quad + [dx, 0]


def observation(quad):
    return BoardPoseObservation(quad, .9, np.full(4, .9), tuple(np.r_[quad.min(0), quad.max(0)]))


@pytest.mark.parametrize('cid', ['hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
def test_moving_clear_component_can_reacquire_without_stopping(cid):
    frame, quad = scene()
    profile = ComponentVisionProfile(cid, (('VCC', .2, .9), ('GND', .8, .9)))
    tracker = ComponentPoseTracker(profile, reacquire_confirm_frames=3)
    assert tracker.update(frame, observation(quad), frame_id=0, ts_ms=0).tracking == 'locked'
    for i in range(1, 4):
        moved, corners = shifted(frame, quad, 12*i)
        result = tracker.update(moved, observation(corners), frame_id=i, ts_ms=i*300)
        if i < 3:
            assert result.tracking != 'locked'
    assert result.tracking == 'locked' and result.stability == 'reacquired'
    np.testing.assert_allclose(result.outline_px, corners)
    assert result.reacquire_evidence['accepted']
    assert result.reacquire_evidence['count'] == 3


@pytest.mark.parametrize('kind', ['wrong_position', 'reordered', 'covered', 'gap', 'duplicate', 'reverse'])
def test_unverified_motion_never_counts_as_agreement(kind):
    frame, quad = scene()
    consensus = MotionConsensus()
    assert not consensus.compare(frame, quad, 1, 300, 3)
    moved, corners = shifted(frame, quad, 12)
    fid, ts = 2, 600
    if kind == 'wrong_position': corners += [20, 0]
    if kind == 'reordered': corners = np.roll(corners, 1, axis=0)
    if kind == 'covered': moved[:] = 50
    if kind == 'gap': ts = 2000
    if kind == 'duplicate': fid = 1
    if kind == 'reverse': ts = 200
    assert not consensus.compare(moved, corners, fid, ts, 3)


def test_reacquisition_diagnostics_do_not_reappear_on_missing_frame():
    frame, quad = scene()
    tracker = ComponentPoseTracker(ComponentVisionProfile('hc-sr04', (('GND', .5, .9),)))
    tracker.update(frame, observation(quad), frame_id=0, ts_ms=0)
    moved, corners = shifted(frame, quad, 20)
    candidate = tracker.update(moved, observation(corners), frame_id=1, ts_ms=300)
    assert candidate.reacquire_evidence is not None
    missing = tracker.update(moved, None, frame_id=2, ts_ms=600)
    assert missing.reacquire_evidence is None
