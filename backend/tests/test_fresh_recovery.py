import numpy as np
import pytest
from test_motion_tracking import scene, pose
from app.vision.motion_tracking import MotionTrack


def recovering():
    gray, quad=scene(); track=MotionTrack(); track.fresh_recovery_enabled=True
    track.observe(pose(quad),gray,1)
    assert track.update(np.full_like(gray,40),1,33,search_budget=lambda:False) is None
    return track,gray,quad


def test_fresh_recovery_requires_paired_pixels_then_current_flow():
    track,gray,quad=recovering()
    seed=pose(quad,2,40)
    track.last_seen_ts=66
    assert track.needs_source_image(seed)
    track.observe(seed,gray,1)
    assert not track.recovering and track.confirmed_ts==40
    assert track.update(gray,3,99)['frame_id']==3


def test_bad_candidate_does_not_erase_old_anchor():
    track,gray,quad=recovering(); old=track.flow
    track.last_seen_ts=66
    track.observe(pose(quad,2,40),np.full_like(gray,40),1)
    assert track.flow is old and track.recovering
    assert track.confirmed_ts==0


def test_stale_or_wrong_context_not_reseeded():
    track,gray,quad=recovering()
    for change in [dict(tracking='stale'),dict(runtime_revision=2),dict(ts_ms=-1),dict(ts_ms=999)]:
        seed=pose(quad,2,20);seed.update(change)
        assert not track._can_reseed(seed)


def test_normal_tracking_not_reseeded():
    track,gray,quad=recovering()
    assert track.update(gray,2,66) is not None
    assert not track._can_reseed(pose(quad,3,80))


@pytest.mark.parametrize('component,enabled', [('hc-sr04',True),('mrd-tf240-8p-cs',True),('hw-123',False)])
def test_component_recovery_scope(component, enabled):
    gray,quad=scene(); track=MotionTrack();track.fresh_recovery_enabled=True
    seed=pose(quad);seed.pop('board_id');seed['component_id']=component
    track.observe(seed,gray,1)
    assert track.update(np.full_like(gray,40),1,33,search_budget=lambda:False) is None
    next_seed=dict(seed,frame_id=2,ts_ms=20)
    assert track._can_reseed(next_seed) is enabled
    if enabled:
        assert track.needs_source_image(next_seed)
        track.observe(next_seed,gray,1)
        assert track.update(gray,3,66)['component_id']==component


def test_component_identity_mismatch_cannot_reseed():
    track,gray,quad=recovering()
    seed=pose(quad,2,20);seed.pop('board_id');seed['component_id']='hc-sr04'
    assert not track._can_reseed(seed)
