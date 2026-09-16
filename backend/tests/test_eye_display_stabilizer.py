"""Fresh YOLO-only display correction; synthetic geometry, no image/GPU work."""
from dataclasses import replace

import cv2
import numpy as np
import pytest

from app.component_worker import ComponentPinPosition, ComponentPoseResult
from app.eye_display_stabilizer import EyeYoloDisplayStabilizer
from app.vision.interface import DetectionResult, PinDetection


BASE = np.array([[220., 150.], [380., 150.], [380., 250.], [220., 250.]])
PINS = np.array([[250., 155.], [280., 155.], [310., 155.], [340., 155.]])
SIZE = (1920, 1080)


def result(frame_id, quad=BASE, *, component=False):
    quad = np.asarray(quad, np.float64)
    matrix = cv2.getPerspectiveTransform(BASE.astype(np.float32), quad.astype(np.float32))
    points = cv2.perspectiveTransform(PINS.reshape(-1, 1, 2), matrix).reshape(-1, 2)
    body = {'box': [*quad.min(axis=0), *quad.max(axis=0)], 'confidence': .8, 'source': 'yolo'}
    if component:
        pins = tuple(ComponentPinPosition(str(i), *point, .8) for i, point in enumerate(points))
        return ComponentPoseResult('hc-sr04', frame_id, 1000. + 33.3 * frame_id,
            'locked', .8, SIZE, quad.copy(), pins, 'yolo_direct', body=body,
            motion_outline_px=quad.copy(), tracking_reason='yolo_direct')
    pins = [PinDetection(str(i), *point, .8) for i, point in enumerate(points)]
    return DetectionResult('raspberry-pi-5', frame_id, 1000. + 33.3 * frame_id,
        'locked', .8, pins, quad.tolist(), pose_stability_state='yolo_direct',
        body=body, motion_outline_px=quad.tolist())


def apply(stabilizer, value, revision=1, size=SIZE):
    return stabilizer.apply(value, video_size=size, runtime_revision=revision)


@pytest.mark.parametrize('component', [False, True])
def test_stationary_corner_noise_is_reduced_without_altering_confidence_or_identity(component):
    stabilizer = EyeYoloDisplayStabilizer()
    random = np.random.default_rng(71)
    raw_errors, shown_errors = [], []
    for frame_id in range(1, 61):
        quad = BASE + random.normal(0, 2.2, BASE.shape)
        current = result(frame_id, quad, component=component)
        original = np.array(current.outline_px).copy()
        shown = apply(stabilizer, current)
        assert shown.frame_id == frame_id and shown.ts_ms == current.ts_ms
        assert shown.confidence == current.confidence and shown.tracking == 'locked'
        assert [getattr(pin, 'pin_id', getattr(pin, 'id', None)) for pin in shown.pins] == ['0', '1', '2', '3']
        np.testing.assert_array_equal(current.outline_px, original)
        if frame_id > 5:
            raw_errors.append(quad - BASE)
            shown_errors.append(np.asarray(shown.outline_px) - BASE)
    assert np.std(shown_errors) < .80 * np.std(raw_errors)
    assert abs(np.mean(shown_errors)) < .8


def test_common_box_jitter_is_reduced_even_when_all_corners_move_together():
    stabilizer = EyeYoloDisplayStabilizer()
    raw, displayed = [], []
    for frame_id in range(1, 41):
        shift = 3. if frame_id % 2 else -3.
        current = result(frame_id, BASE + [shift, 0])
        shown = apply(stabilizer, current)
        raw.append(shift)
        displayed.append(np.asarray(shown.outline_px).mean(axis=0)[0] - 300.)
    assert np.std(displayed[5:]) < .6 * np.std(raw[5:])


def test_real_translation_and_direction_change_follow_without_frozen_old_points():
    stabilizer = EyeYoloDisplayStabilizer()
    centers, errors = [], []
    for frame_id in range(1, 15):
        shift = [3. * frame_id, frame_id]
        shown = apply(stabilizer, result(frame_id, BASE + shift))
        centers.append(np.asarray(shown.outline_px).mean(axis=0))
        errors.append(np.max(np.linalg.norm(np.asarray(shown.outline_px) - (BASE + shift), axis=1)))
    assert np.min(np.diff(np.asarray(centers)[:, 0])) > 0
    assert max(errors[3:]) < 1.
    current = result(15, BASE + [20., 14.])
    changed = apply(stabilizer, current)
    assert np.asarray(changed.outline_px).mean(axis=0)[0] < centers[-1][0]
    assert np.max(np.linalg.norm(np.asarray(changed.outline_px) - current.outline_px, axis=1)) < 4.


def test_gradual_rotation_follows_promptly_without_reordering_semantic_corners():
    stabilizer = EyeYoloDisplayStabilizer()
    for frame_id in range(1, 16):
        angle = np.deg2rad(4. * frame_id)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        quad = (BASE - [300., 200.]) @ rotation.T + [300., 200.]
        shown = apply(stabilizer, result(frame_id, quad))
        assert shown.tracking == 'locked'
        edge = np.asarray(shown.outline_px)[1] - np.asarray(shown.outline_px)[0]
        error = abs(np.rad2deg(np.arctan2(edge[1], edge[0]) - angle))
        if frame_id > 3:
            assert error < 1.
        assert [pin.pin_id for pin in shown.pins] == ['0', '1', '2', '3']


@pytest.mark.parametrize('change', ['semantic_flip', 'large_jump'])
def test_discontinuity_hides_then_reseeds_from_next_coherent_fresh_detection(change):
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    changed = np.roll(BASE, 2, axis=0) if change == 'semantic_flip' else BASE + [300., 0.]
    hidden = apply(stabilizer, result(2, changed))
    assert hidden.frame_id == 2 and hidden.tracking == 'searching'
    assert hidden.pins == [] and hidden.body is None and hidden.outline_px is None
    assert stabilizer.diagnostics()['raspberry-pi-5']['reason'] == change
    latest = result(3, changed + [1., 0.])
    reseeded = apply(stabilizer, latest)
    np.testing.assert_array_equal(reseeded.outline_px, latest.outline_px)
    assert reseeded.pins == latest.pins


def test_alternating_semantic_flips_do_not_freeze_or_reuse_previous_gpio():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    for frame_id in range(2, 7):
        quad = np.roll(BASE, 2, axis=0) if frame_id % 2 == 0 else BASE
        hidden = apply(stabilizer, result(frame_id, quad))
        assert hidden.pins == [] and hidden.outline_px is None


@pytest.mark.parametrize('component', [False, True])
def test_missing_clears_immediately_and_returning_detection_has_no_old_history(component):
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1, component=component))
    current = result(2, component=component)
    current = replace(current, tracking='searching', outline_px=None,
                      pins=() if component else [], body=None)
    missing = apply(stabilizer, current)
    assert not missing.pins and missing.body is None and missing.outline_px is None
    returned = result(3, BASE + [2., 1.], component=component)
    shown = apply(stabilizer, returned)
    np.testing.assert_array_equal(shown.outline_px, returned.outline_px)
    assert shown.pins == returned.pins


@pytest.mark.parametrize('change', ['revision', 'shape', 'explicit_reset', 'time_gap', 'clock_reset'])
def test_camera_context_changes_seed_fresh_geometry(change):
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(10))
    current = result(11, BASE + [2., 0.])
    revision, size = 1, SIZE
    if change == 'revision':
        revision = 2
    elif change == 'shape':
        size = (2048, 1512)
    elif change == 'explicit_reset':
        stabilizer.reset()
    elif change == 'time_gap':
        current.ts_ms += 1000.
    else:
        current.frame_id = 1
        current.ts_ms = 100.
    shown = apply(stabilizer, current, revision=revision, size=size)
    np.testing.assert_array_equal(shown.outline_px, current.outline_px)
    assert shown.pins == current.pins


def test_pins_and_body_receive_same_current_quad_transform_and_keep_raw_input_untouched():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    current = result(2, BASE + [[2., 1.], [-1., 2.], [1., -2.], [-2., -1.]])
    original_pins = [(pin.x, pin.y) for pin in current.pins]
    shown = apply(stabilizer, current)
    homography = cv2.getPerspectiveTransform(np.asarray(current.outline_px, np.float32),
                                            np.asarray(shown.outline_px, np.float32))
    expected = cv2.perspectiveTransform(np.array(original_pins).reshape(-1, 1, 2), homography).reshape(-1, 2)
    np.testing.assert_allclose([(pin.x, pin.y) for pin in shown.pins], expected)
    assert original_pins == [(pin.x, pin.y) for pin in current.pins]
    assert shown.body is not current.body and shown.body['confidence'] == current.body['confidence']


def test_body_only_output_never_invents_a_pin_or_pose():
    stabilizer = EyeYoloDisplayStabilizer()
    for frame_id in (1, 2, 3):
        current = result(frame_id, BASE + [frame_id, 0.])
        current = replace(current, tracking='searching', pins=[], outline_px=None, motion_outline_px=None)
        shown = apply(stabilizer, current)
        assert shown.tracking == 'searching' and shown.pins == [] and shown.outline_px is None
        assert shown.body is not None and shown.frame_id == frame_id


def test_one_component_missing_never_resets_another_object():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    apply(stabilizer, result(1, component=True))
    missing = replace(result(2), tracking='searching', pins=[], outline_px=None, body=None)
    apply(stabilizer, missing)
    assert 'raspberry-pi-5' not in stabilizer._samples and 'hc-sr04' in stabilizer._samples


def test_individually_missing_or_invisible_pins_are_never_recovered_from_history():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    current = result(2, BASE + [2., 0.])
    current.pins = [replace(current.pins[0], visible=False), current.pins[2]]
    shown = apply(stabilizer, current)
    assert [pin.pin_id for pin in shown.pins] == ['0', '2']
    assert shown.pins[0].visible is False


def test_invalid_pose_can_only_keep_fresh_body_without_old_or_invalid_pins():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    invalid = result(2)
    invalid.outline_px = [[float('nan'), 0.]] * 4
    shown = apply(stabilizer, invalid)
    assert shown.pins == [] and shown.outline_px is None
    assert shown.tracking == 'searching' and shown.body == invalid.body


def test_stale_result_cannot_keep_body_or_pins():
    stabilizer = EyeYoloDisplayStabilizer()
    apply(stabilizer, result(1))
    stale = replace(result(2), tracking='stale')
    shown = apply(stabilizer, stale)
    assert shown.pins == [] and shown.outline_px is None and shown.body is None
    assert 'raspberry-pi-5' not in stabilizer._samples
