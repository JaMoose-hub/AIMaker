"""Actual current-image row evidence; no inference or camera needed."""
from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.eye_j8 import correct_eye_j8_from_image
from app.vision.interface import PinDetection


PROFILE = SimpleNamespace(board=SimpleNamespace(id='raspberry-pi-5'))
SIZE = (600, 600)


def lattice(angle=0.):
    radians = np.deg2rad(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)],
                         [np.sin(radians), np.cos(radians)]])
    points = np.array([[167. + 14. * (i // 2), 300. + 13. * (i % 2)] for i in range(40)])
    points = (points - [300., 306.5]) @ rotation.T + [300., 306.5]
    pins = [PinDetection(str(i + 1), float(x), float(y), .85, True, 'J8', i + 1)
            for i, (x, y) in enumerate(points)]
    return pins, rotation @ [0., 1.]


def contacts(pins, normal, offset, *, columns=20):
    image = np.full((*SIZE[::-1], 3), 150, np.uint8)
    for pin in pins[:columns * 2]:
        point = np.rint([pin.x, pin.y] + normal * offset).astype(int)
        cv2.circle(image, tuple(point), 3, (240, 240, 240), -1)
    return image


@pytest.mark.parametrize('angle', [0., 25., 90., 180.])
@pytest.mark.parametrize('offset', [8., -6.])
def test_visible_shifted_rows_correct_normal_only_and_preserve_spacing(angle, offset):
    pins, normal = lattice(angle)
    original = np.array([[pin.x, pin.y] for pin in pins])
    image = contacts(pins, normal, offset)
    diagnostic = {}
    result = correct_eye_j8_from_image(image, PROFILE, pins, SIZE, diagnostic=diagnostic)
    assert diagnostic['accepted']
    assert result is not pins
    actual = np.array([[pin.x, pin.y] for pin in result])
    displacement = actual - original
    # Rounded synthetic circles and their blurred intensity plateaus allow
    # about one source pixel of centre ambiguity; the full shift is recovered.
    assert np.max(np.linalg.norm(displacement - normal * offset, axis=1)) <= 1.6
    along = np.array([normal[1], -normal[0]])
    np.testing.assert_allclose(displacement @ along, 0., atol=2e-5)
    np.testing.assert_allclose(np.diff(actual, axis=0), np.diff(original, axis=0), atol=1e-6)
    assert [(p.pin_id, p.index, p.header, p.confidence) for p in result] == [
        (p.pin_id, p.index, p.header, p.confidence) for p in pins]
    np.testing.assert_array_equal([[pin.x, pin.y] for pin in pins], original)


@pytest.mark.parametrize('kind', ['flat', 'occluded', 'noise', 'ambiguous_repeated_rows'])
def test_unsupported_current_image_keeps_current_projection(kind):
    pins, normal = lattice()
    if kind == 'flat':
        image = np.full((*SIZE[::-1], 3), 150, np.uint8)
    elif kind == 'occluded':
        image = contacts(pins, normal, 8., columns=5)
    elif kind == 'noise':
        image = np.random.default_rng(112).integers(130, 171, (*SIZE[::-1], 3), dtype=np.uint8)
    else:
        image = np.full((*SIZE[::-1], 3), 150, np.uint8)
        for y in (287, 300, 313, 326):
            for column in range(20):
                cv2.circle(image, (167 + column * 14, y), 3, (240, 240, 240), -1)
    diagnostic = {}
    assert correct_eye_j8_from_image(image, PROFILE, pins, SIZE, diagnostic=diagnostic) is pins
    assert diagnostic['accepted'] is False


def test_no_correction_history_survives_missing_pixels_or_opposite_motion():
    pins, normal = lattice()
    first = correct_eye_j8_from_image(contacts(pins, normal, 8.), PROFILE, pins, SIZE)
    assert first is not pins
    current_pins = [replace(pin, x=pin.x + 12.) for pin in pins]
    blank = np.full((*SIZE[::-1], 3), 150, np.uint8)
    assert correct_eye_j8_from_image(blank, PROFILE, current_pins, SIZE) is current_pins
    fresh = correct_eye_j8_from_image(contacts(current_pins, normal, -6.), PROFILE, current_pins, SIZE)
    assert fresh is not current_pins
    assert all(abs(pin.y - original.y + 6.) <= 1.6 for pin, original in zip(fresh, current_pins))


def test_unrelated_profile_and_incomplete_lattice_are_unchanged():
    pins, normal = lattice()
    image = contacts(pins, normal, 8.)
    other = SimpleNamespace(board=SimpleNamespace(id='arduino-uno-q'))
    assert correct_eye_j8_from_image(image, other, pins, SIZE) is pins
    incomplete = pins[:-1]
    assert correct_eye_j8_from_image(image, PROFILE, incomplete, SIZE) is incomplete
    invisible = [replace(pin, visible=False) if pin.index == 4 else pin for pin in pins]
    assert correct_eye_j8_from_image(image, PROFILE, invisible, SIZE) is invisible
    assert correct_eye_j8_from_image(image, PROFILE, pins, (300, 300)) is pins
