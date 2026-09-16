import cv2
import numpy as np
import pytest

from app.vision.pose_continuity import PoseContinuity
from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from test_motion_consensus import scene, shifted, observation


@pytest.mark.parametrize('cid', ['hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
def test_visual_continuity_tracks_movement_without_waiting_for_stationary_model(cid):
    frame, quad = scene()
    tracker = ComponentPoseTracker(ComponentVisionProfile(cid, (('GND', .5, .9),)), visual_continuity=True)
    assert tracker.update(frame, observation(quad), frame_id=0, ts_ms=0).tracking == 'locked'
    for i in range(1, 6):
        moved, corners = shifted(frame, quad, 8*i)
        # Raw model jitter is NOT used as the returned GPIO geometry.
        raw = corners + np.float32([[4, 0], [0, -4], [-4, 0], [0, 4]])
        result = tracker.update(moved, observation(raw), frame_id=i, ts_ms=i*150)
        assert result.tracking == 'locked'
        assert result.visual_continuity['accepted']
        np.testing.assert_allclose(result.outline_px, corners, atol=1.)


@pytest.mark.parametrize('kind', ['covered', 'reordered', 'wrong_object', 'missing', 'gap', 'reverse', 'resize'])
def test_continuity_requires_current_image_and_semantics(kind):
    frame, quad = scene()
    flow = PoseContinuity()
    flow.seed(frame, quad, 1, 100)
    moved, corners = shifted(frame, quad, 8)
    ts, fid = 250, 2
    if kind == 'covered': moved[:] = 50
    if kind == 'reordered': corners = np.roll(corners, 1, axis=0)
    if kind == 'wrong_object': corners += [80, 0]
    if kind == 'gap': ts = 1000
    if kind == 'reverse': fid = 0
    if kind == 'resize': moved = cv2.resize(moved, (320, 240))
    obs = None if kind == 'missing' else observation(corners)
    assert flow.propose(moved, obs, fid, ts) is None


def test_coarse_model_agreement_cannot_renew_semantic_lease_forever():
    frame, quad = scene()
    flow = PoseContinuity(lease_ms=500)
    flow.seed(frame, quad, 0, 0)
    for i in range(1, 4):
        moved, corners = shifted(frame, quad, 8*i)
        result = flow.propose(moved, observation(corners + [5, 0]), i, i*200)
        assert (result is not None) == (i < 3)


def test_partial_hand_color_does_not_override_distributed_board_matches():
    frame, quad = scene()
    tracker = ComponentPoseTracker(ComponentVisionProfile('hw-123', (('GND', .5, .9),)), visual_continuity=True)
    tracker.update(frame, observation(quad), frame_id=0, ts_ms=0)
    moved, corners = shifted(frame, quad, 8)
    # Skin-coloured vertical strip obscures part, not the complete board.
    moved[100:300, 240:275] = (100, 150, 200)
    result = tracker.update(moved, observation(corners), frame_id=1, ts_ms=150)
    assert result.hand_fraction >= tracker.hand_fraction_threshold
    assert result.visual_continuity['accepted']
    assert result.tracking == 'locked'
    np.testing.assert_allclose(result.outline_px, corners, atol=1.)


def test_reset_discards_previous_camera_visual_anchor():
    frame, quad = scene()
    tracker = ComponentPoseTracker(ComponentVisionProfile('hc-sr04', (('GND', .5, .9),)), visual_continuity=True)
    tracker.update(frame, observation(quad), frame_id=0, ts_ms=0)
    tracker.reset_tracking()
    assert tracker.visual_continuity.flow is None
