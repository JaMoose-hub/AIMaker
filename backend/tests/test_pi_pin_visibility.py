import numpy as np

from app.vision.pi_pin_visibility import PiPinVisibility
from app.vision.motion_tracking import MotionTrack
from test_motion_tracking import scene, pose


def test_appearance_alone_does_not_hide_gpio():
    policy = PiPinVisibility()
    pins = [{'id': str(i)} for i in range(40)]
    for _ in range(10):
        assert len(policy.supported(pins, {}, False)) == 40


def test_partial_support_requires_consistent_loss_and_recovery():
    policy = PiPinVisibility()
    pins = [{'id': 'a'}, {'id': 'b'}]
    regions = {'b': {'supported': True}}
    assert policy.supported(pins, regions, True) == {'a', 'b'}
    assert policy.supported(pins, regions, True) == {'a', 'b'}
    assert policy.supported(pins, regions, True) == {'b'}
    assert policy.supported(pins, regions, False) == {'b'}
    assert policy.supported(pins, regions, False) == {'b'}
    assert policy.supported(pins, regions, False) == {'a', 'b'}


def test_flickering_partial_support_does_not_hide_pins():
    policy = PiPinVisibility()
    for partial in [True, False]*10:
        assert policy.supported([{'id': 'a'}], {}, partial) == {'a'}


def test_full_pi_geometry_survives_appearance_change_but_not_expiry(monkeypatch):
    gray, quad = scene()
    msg = pose(quad)
    msg['pins'] = [{'id': str(i), 'x': 135.+(i//2)*10, 'y': 150.+(i%2)*15, 'v': True}
                   for i in range(40)]
    track = MotionTrack(lease_ms=200)
    track.observe(msg, gray, 1)
    monkeypatch.setattr(track.pin_regions, 'check', lambda *a: {p['id']: {'supported': False} for p in msg['pins']})
    output = track.update(gray, 1, 33)
    assert len(output['pins']) == 40
    assert output['pose_quality']['pin_visibility_policy'] == 'pi_geometry_debounced_partial_support'
    assert output['pose_quality']['pin_evidence'] == 'projected_geometry_not_contact_verification'
    assert track.update(gray, 2, 250)['pins'] == []
    assert track.update(np.full_like(gray, 100), 3, 283) is None
