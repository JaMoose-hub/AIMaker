from copy import deepcopy
import numpy as np
from app.vision.motion_tracking import MotionTrack
from test_motion_tracking import scene, pose


def test_pi_image_anchor_corroborates_without_raw_corner_tug():
    gray, quad = scene()
    track = MotionTrack()
    track.observe(pose(quad), gray, 1.)
    for i in range(1, 85):
        output = track.update(gray, i, i * 33.)
        msg = pose(quad, i, i * 33.)
        msg['motion_outline'] = (quad + [52, 0]).tolist()
        msg['pose_quality'] = {'image_confirmed': True, 'stability': 'deadband'}
        track.observe(msg, gray, 1.)
        assert output['tracking'] == 'locked'
    assert track.confirmation_debug['evidence'] == 'image_confirmed_outline'
    assert track.confirmed_ts == 84 * 33.
    np.testing.assert_allclose(track.message['outline'], quad, atol=.01)


def test_unconfirmed_or_stale_outline_cannot_override_raw_disagreement():
    gray, quad = scene()
    for status, confirmed in [('locked', False), ('stale', True)]:
        track = MotionTrack()
        track.observe(pose(quad), gray, 1.)
        track.update(gray, 1, 33.)
        msg = pose(quad, 1, 33.)
        msg.update(tracking=status, motion_outline=(quad + [52, 0]).tolist(),
                   pose_quality={'image_confirmed': confirmed})
        track.observe(msg, gray, 1.)
        assert track.confirmed_ts == 0


def test_absent_pi_without_any_local_pin_support_revokes_background_track():
    gray, quad = scene()
    track = MotionTrack()
    track.observe(pose(quad), gray, 1.)
    absent = pose(quad, 1, 33.)
    absent.update(tracking='searching', outline=None, pins=[])
    track.observe(absent, gray, 1.)
    # Isolate the removal decision from LK: static textured background can
    # track perfectly, but no pin patch and no fresh object support remain.
    track.pin_regions.check = lambda *args: {'J8:11': {'supported': False}}
    assert track.update(gray, 1, 33.) is None
    assert track.failure_reason == 'source_absent_no_pin_support'
    assert track.message is None


def test_absent_model_alone_does_not_revoke_visible_pin_regions():
    gray, quad = scene()
    track = MotionTrack()
    track.observe(pose(quad), gray, 1.)
    absent = pose(quad, 1, 33.)
    absent.update(tracking='searching', outline=None, pins=[])
    track.observe(absent, gray, 1.)
    assert track.update(gray, 1, 33.) is not None
