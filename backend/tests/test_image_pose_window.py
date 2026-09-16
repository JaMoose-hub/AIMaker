import numpy as np
import pytest

from app.vision.image_pose_window import ImagePoseWindow
from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from test_motion_consensus import scene, shifted, observation


def test_motion_compensation_averages_jitter_without_waiting_for_stationary_board():
    frame, quad = scene()
    window = ImagePoseWindow()
    for i, noise in enumerate((-4., 4., -4., 4.)):
        moved, corners = shifted(frame, quad, 10*i)
        result = window.update(moved, corners+[noise, 0], i, i*125)
        if i < 3:
            assert result is None
    assert window.evidence['accepted']
    np.testing.assert_allclose(result, corners, atol=.7)


@pytest.mark.parametrize('kind', ['missing_texture','reordered','wrong_region','gap','duplicate','reverse','shape'])
def test_unverified_motion_cannot_complete_acquisition(kind):
    frame, quad = scene()
    window = ImagePoseWindow()
    for i in range(3):
        moved, corners = shifted(frame, quad, 10*i)
        assert window.update(moved, corners, i, i*125) is None
    moved, corners = shifted(frame, quad, 30)
    fid, ts = 3, 375
    if kind == 'missing_texture': moved[:] = 50
    if kind == 'reordered': corners = np.roll(corners, 1, axis=0)
    if kind == 'wrong_region': corners += [30,0]
    if kind == 'gap': ts = 2000
    if kind == 'duplicate': fid = 2
    if kind == 'reverse': ts = 100
    if kind == 'shape': moved = moved[:400]
    assert window.update(moved, corners, fid, ts) is None
    assert not window.evidence['accepted']


@pytest.mark.parametrize('cid', ['hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
def test_worker_reacquires_in_motion_with_jitter_and_retains_original_semantics(cid):
    frame, quad = scene()
    profile = ComponentVisionProfile(cid, (('VCC', .2, .9), ('GND', .8, .9)))
    tracker = ComponentPoseTracker(profile, motion_handoff=True)
    tracker._needs_reacquire = True
    for i, noise in enumerate((-4.,4.,-4.,4.)):
        moved, corners = shifted(frame, quad, i*10)
        result = tracker.update(moved, observation(corners+[noise,0]), frame_id=i, ts_ms=i*125)
    assert result.tracking == 'locked'
    assert result.reacquire_evidence['source'] == 'image_aligned_pose_window'
    np.testing.assert_allclose(result.outline_px, corners, atol=.7)
    assert tuple(p.id for p in result.pins) == ('VCC', 'GND')
