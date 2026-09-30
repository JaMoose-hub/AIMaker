import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.vision.pi_pin_visibility import PiPinVisibility
from app.vision.motion_tracking import MotionTrack, transform
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


def test_ambiguous_blur_preserves_prior_hidden_state_without_learning_it():
    policy = PiPinVisibility()
    pins = [{'id': 'covered'}, {'id': 'clear'}]
    regions = {'clear': {'supported': True}}
    for _ in range(3):
        visible = policy.supported(pins, regions, True)
    assert visible == {'clear'}
    for _ in range(5):
        assert policy.supported(pins, {}, True, ambiguous_blur=True) == {'clear'}
    restored = {'covered': {'supported': True}, 'clear': {'supported': True}}
    assert policy.supported(pins, restored, False) == {'clear'}
    assert policy.supported(pins, restored, False) == {'clear'}
    assert policy.supported(pins, restored, False) == {'covered', 'clear'}


def _synthetic_pi_pose(quad):
    message = pose(quad)
    message['pins'] = [
        {'id': str(i), 'x': 135. + (i//2)*10, 'y': 150. + (i%2)*15, 'v': True}
        for i in range(40)
    ]
    return message


def test_moving_pi_motion_blur_does_not_masquerade_as_gpio_occlusion():
    clear, quad = scene()
    track = MotionTrack()
    message = _synthetic_pi_pose(quad)
    track.observe(message, clear, 1)
    for i in range(1, 6):
        matrix = np.float32([[1, 0, i*5], [0, 1, i*2], [0, 0, 1]])
        moving = cv2.warpPerspective(clear, matrix, (640, 400), borderValue=40)
        blurred = cv2.filter2D(moving, -1, np.ones((1, 9), np.float32)/9)
        result = track.update(blurred, i, i*33)
        assert result is not None and result['tracking'] == 'locked'
        assert len(result['pins']) == 40
        assert result['pose_quality']['motion_blur_ambiguous']
        assert result['pose_quality']['pin_visibility_policy'] == 'pi_geometry_motion_blur_provisional'
        np.testing.assert_allclose(result['outline'], transform(quad, matrix), atol=1.5)
        expected = transform([[p['x'], p['y']] for p in message['pins']], matrix)
        actual = np.float32([[p['x'], p['y']] for p in result['pins']])
        assert np.max(np.linalg.norm(actual-expected, axis=1)) < 1.5


def test_local_hand_on_gpio_is_not_misclassified_as_global_blur():
    clear, quad = scene()
    track = MotionTrack()
    track.observe(_synthetic_pi_pose(quad), clear, 1)
    covered = clear.copy()
    covered[139:178, 129:240] = 100
    for i in range(1, 5):
        result = track.update(covered, i, i*33)
        assert result is not None
        assert not result['pose_quality']['motion_blur_ambiguous']
    assert 0 < len(result['pins']) < 40
    assert result['pose_quality']['hidden_pin_count'] > 0


def test_brief_model_search_during_blur_does_not_erase_pi_but_grace_expires():
    clear, quad = scene()
    track = MotionTrack()
    track.observe(_synthetic_pi_pose(quad), clear, 1)
    for i in range(1, 12):
        searching = pose(quad, i, i*33)
        searching.update(tracking='searching', outline=None, pins=[])
        track.observe(searching, clear, 1)
        matrix = np.float32([[1, 0, i*5], [0, 1, i*2]])
        moving = cv2.warpAffine(clear, matrix, (640, 400), borderValue=40)
        blurred = cv2.filter2D(moving, -1, np.ones((1, 9), np.float32)/9)
        result = track.update(blurred, i, i*33)
        if i <= 10:
            assert result is not None and len(result['pins']) == 40
        else:
            assert result is None
            assert track.failure_reason == 'source_absent_no_pin_support'


def test_model_search_and_local_gpio_occlusion_still_revokes_pi():
    clear, quad = scene()
    track = MotionTrack()
    track.observe(_synthetic_pi_pose(quad), clear, 1)
    searching = pose(quad, 1, 33)
    searching.update(tracking='searching', outline=None, pins=[])
    track.observe(searching, clear, 1)
    covered = clear.copy()
    covered[139:178, 129:338] = 100
    assert track.update(covered, 1, 33) is None
    assert track.failure_reason == 'source_absent_no_pin_support'


def test_recorded_pi_movement_and_directional_blur_keeps_gpio_projected():
    from app.motion_worker import tracking_gray

    root = Path(__file__).resolve().parents[2] / 'runs/diagnostics/component-recovery-20260909-restart2'
    if not (root / 'raspberry-pi-5-source.jpg').exists():
        pytest.skip('Optional recorded Pi camera fixture is not installed')
    image = cv2.imread(str(root / 'raspberry-pi-5-source.jpg'))
    message = json.loads((root / 'raspberry-pi-5-pose.json').read_text())
    message.update(frame_id=0, ts_ms=0)
    gray, scale = tracking_gray(image)
    track = MotionTrack()
    track.observe(message, gray, scale)
    assert len(message['pins']) == 40
    for i in range(1, 7):
        matrix = np.float32([[1, 0, i*15], [0, 1, i*4.5], [0, 0, 1]])
        moving = cv2.warpPerspective(image, matrix, (image.shape[1], image.shape[0]), borderValue=40)
        blurred = cv2.filter2D(moving, -1, np.ones((1, 15), np.float32)/15)
        current, _ = tracking_gray(blurred)
        result = track.update(current, i, i*33)
        assert result is not None and len(result['pins']) == 40
        assert result['pose_quality']['motion_blur_ambiguous']
        np.testing.assert_allclose(result['outline'], transform(message['outline'], matrix), atol=1.5)
        expected = transform([[p['x'], p['y']] for p in message['pins']], matrix)
        actual = np.float32([[p['x'], p['y']] for p in result['pins']])
        assert np.max(np.linalg.norm(actual-expected, axis=1)) < 1.5


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
