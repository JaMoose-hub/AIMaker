from dataclasses import replace
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.interface import PinDetection
from app.vision.pi5_j8_geometry import align_pi5_j8

PROFILE = SimpleNamespace(board=SimpleNamespace(id='raspberry-pi-5'))
SIZE = (560, 340)


def scene():
    frame = np.full((340, 560, 3), (65, 125, 70), np.uint8)
    cv2.rectangle(frame, (81, 132), (441, 164), (30, 30, 30), -1)
    expected = [PinDetection(str(i + 1), 90. + 18 * (i // 2),
                            140. + 16 * (i % 2), .9, True, 'J8', i + 1)
                for i in range(40)]
    return frame, expected


def xy(pins):
    return np.array([[p.x, p.y] for p in pins])


def moved(pins, matrix):
    points = cv2.perspectiveTransform(xy(pins).astype(np.float32).reshape(-1, 1, 2), matrix).reshape(-1, 2)
    return [replace(p, x=float(q[0]), y=float(q[1])) for p, q in zip(pins, points)]


@pytest.mark.parametrize('angle', [0, 37, 90, 180, 270])
def test_connected_chips_and_dark_green_shadow_do_not_shift_header(angle):
    frame, expected = scene()
    # Components touch the body; ordinary contour percentiles centre between
    # these objects instead of between the physical rows.
    cv2.rectangle(frame, (100, 84), (220, 134), (28, 28, 28), -1)
    cv2.rectangle(frame, (310, 162), (410, 205), (28, 28, 28), -1)
    cv2.rectangle(frame, (225, 98), (310, 134), (30, 85, 35), -1)
    matrix = np.vstack([cv2.getRotationMatrix2D((280, 170), angle, .70), [0, 0, 1]])
    frame = cv2.warpPerspective(frame, matrix, SIZE, borderValue=(150, 150, 150))
    prior = moved([replace(p, y=p.y + 10) for p in expected], matrix)
    truth = moved(expected, matrix)
    result = align_pi5_j8(frame, PROFILE, prior, SIZE)
    assert result is not prior
    assert np.max(np.linalg.norm(xy(result) - xy(truth), axis=1)) < 2.0
    assert [p.pin_id for p in result] == [p.pin_id for p in prior]
    assert [p.confidence for p in result] == [p.confidence for p in prior]


def test_perspective_spacing_is_preserved_not_replaced_with_uniform_screen_grid():
    frame, expected = scene()
    matrix = cv2.getPerspectiveTransform(
        np.float32([[0, 0], [559, 0], [559, 339], [0, 339]]),
        np.float32([[35, 30], [510, 75], [540, 325], [70, 295]]))
    frame = cv2.warpPerspective(frame, matrix, SIZE, borderValue=(150, 150, 150))
    prior = moved([replace(p, y=p.y + 7) for p in expected], matrix)
    truth = moved(expected, matrix)
    result = align_pi5_j8(frame, PROFILE, prior, SIZE)
    assert result is not prior
    assert np.max(np.linalg.norm(xy(result) - xy(truth), axis=1)) < 2.0


@pytest.mark.parametrize('kind', ['blank', 'black', 'short', 'occluded', 'wide', 'ambiguous'])
def test_rejects_missing_partial_wide_or_ambiguous_housing(kind):
    frame, prior = scene()
    if kind == 'blank':
        frame[:] = 160
    elif kind == 'black':
        frame[:] = 20
    elif kind == 'short':
        frame[:, 330:] = 160
    elif kind == 'occluded':
        frame[:, 230:310] = 160
    elif kind == 'wide':
        cv2.rectangle(frame, (81, 102), (441, 194), (30, 30, 30), -1)
    else:
        frame[:] = 160
        cv2.rectangle(frame, (81, 116), (441, 140), (30, 30, 30), -1)
        cv2.rectangle(frame, (81, 156), (441, 180), (30, 30, 30), -1)
    assert align_pi5_j8(frame, PROFILE, prior, SIZE) is prior


def test_cropped_header_and_incomplete_or_invalid_pin_metadata_are_not_stretched():
    frame, prior = scene()
    for bad in (prior[:-1], [replace(p, visible=False) if p.index == 20 else p for p in prior],
                [replace(p, x=float('nan')) if p.index == 1 else p for p in prior],
                [replace(p, y=float('inf')) if p.index == 20 else p for p in prior]):
        assert align_pi5_j8(frame, PROFILE, bad, SIZE) is bad
    shift = np.float32([[1, 0, -100], [0, 1, 0], [0, 0, 1]])
    cropped = moved(prior, shift)
    assert align_pi5_j8(cv2.warpPerspective(frame, shift, SIZE), PROFILE, cropped, SIZE) is cropped
    # All contact centres remain visible, but the housing end is clipped.
    shift[0, 2] = -84
    cropped = moved(prior, shift)
    assert align_pi5_j8(cv2.warpPerspective(frame, shift, SIZE), PROFILE, cropped, SIZE) is cropped
    other = SimpleNamespace(board=SimpleNamespace(id='arduino-uno-q'))
    assert align_pi5_j8(frame, other, prior, SIZE) is prior
