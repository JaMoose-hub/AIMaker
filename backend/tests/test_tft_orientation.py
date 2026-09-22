from dataclasses import replace

import cv2
import numpy as np
import pytest

from app.vision import tft_ring_geometry as geometry
from test_motion_consensus import observation


def panel(color=(210, 210, 210), top=.09, bottom=.16):
    frame = np.full((900, 900, 3), 110, np.uint8)
    mounts = np.float32([[300, 200], [600, 200], [600, 700], [300, 700]])
    cv2.rectangle(frame, (280, 180), (620, 720), (180, 65, 20), -1)
    cv2.rectangle(frame, (295, 220), (605, 680), (25, 25, 25), -1)
    cv2.rectangle(frame, (300, round(200+500*top)), (600, round(700-500*bottom)), color, -1)
    for p in mounts.astype(int):
        cv2.circle(frame, tuple(p), 11, (230, 230, 230), -1)
        cv2.circle(frame, tuple(p), 7, (45, 45, 45), -1)
    return frame, mounts


@pytest.mark.parametrize('angle', [0, 37, 90, 180, 270])
@pytest.mark.parametrize('reversed_order', [False, True])
def test_full_panel_inset_selects_physical_header_not_image_top(angle, reversed_order):
    frame, mounts = panel()
    matrix = cv2.getRotationMatrix2D((450, 450), angle, 1)
    frame = cv2.warpAffine(frame, matrix, (900, 900))
    mounts = cv2.transform(mounts[None], matrix)[0]
    pose = observation(np.roll(mounts, 2 if reversed_order else 0, axis=0))
    pose = replace(pose, keypoint_confidences=np.array([.6, .7, .8, .9]), landmarks_px=pose.corners_px.copy())
    evidence = {}
    result = geometry.orient_tft_from_panel_inset(frame, pose, evidence)
    assert evidence['verified'], evidence
    assert evidence['corrected'] == reversed_order
    np.testing.assert_allclose(result.corners_px, mounts, atol=.001)
    np.testing.assert_array_equal(result.landmarks_px, result.corners_px)
    np.testing.assert_array_equal(result.keypoint_confidences, np.roll(pose.keypoint_confidences, 2 if reversed_order else 0))
    assert result.confidence == pose.confidence


@pytest.mark.parametrize('color', [(240, 240, 240), (20, 20, 230), (20, 230, 20), (230, 20, 20)])
def test_header_order_does_not_depend_on_display_color(color):
    frame, mounts = panel(color)
    evidence = {}
    result = geometry.orient_tft_from_panel_inset(frame, observation(np.roll(mounts, 2, axis=0)), evidence)
    assert evidence['verified'], evidence
    np.testing.assert_allclose(result.corners_px, mounts)


@pytest.mark.parametrize('kind', ['symmetric', 'blank', 'covered', 'clipped'])
def test_no_independent_inset_does_not_invent_a_flip(kind):
    frame, mounts = panel(top=.12, bottom=.12) if kind == 'symmetric' else panel()
    if kind == 'blank':
        frame[:] = 110
    if kind == 'covered':
        frame[150:450] = 110
    if kind == 'clipped':
        mounts -= [400, 0]
    pose = observation(np.roll(mounts, 2, axis=0))
    evidence = {}
    result = geometry.orient_tft_from_panel_inset(frame, pose, evidence)
    assert not evidence['verified'], evidence
    assert result is pose


def test_recent_orientation_bridges_only_current_nearby_geometry_and_expires(monkeypatch):
    frame, mounts = panel()
    acquirer = geometry.TftRingAcquirer()
    reverse = observation(np.roll(mounts, 2, axis=0))
    measured = reverse
    monkeypatch.setattr(geometry, 'refine_tft_rings', lambda frame, pose, evidence: measured)
    result = acquirer.locate(frame, reverse, 1, 100)
    np.testing.assert_allclose(result.corners_px, mounts)
    assert acquirer.evidence['orientation']['verified']
    blank = np.full_like(frame, 110)
    moved = replace(reverse, corners_px=reverse.corners_px+[4, 2])
    measured = moved
    result = acquirer.locate(blank, moved, 2, 200)
    np.testing.assert_allclose(result.corners_px, mounts+[4, 2])
    assert acquirer.evidence['orientation']['carried']
    assert not acquirer.evidence['orientation']['verified']
    acquirer.locate(blank, moved, 3, 600)
    result = acquirer.locate(blank, moved, 4, 750)
    assert not acquirer.evidence['orientation'].get('carried')
    np.testing.assert_allclose(result.corners_px, moved.corners_px)


@pytest.mark.parametrize('change', ['reset', 'gap', 'duplicate', 'reverse', 'resize', 'distant'])
def test_invalid_history_cannot_force_a_header_direction(monkeypatch, change):
    frame, mounts = panel()
    acquirer = geometry.TftRingAcquirer()
    pose = observation(np.roll(mounts, 2, axis=0))
    monkeypatch.setattr(geometry, 'refine_tft_rings', lambda frame, seed, evidence: pose)
    acquirer.locate(frame, pose, 2, 200)
    if change == 'reset': acquirer.reset()
    blank = np.full_like(frame, 110)
    if change == 'resize': blank = blank[:800]
    if change == 'distant': pose = replace(pose, corners_px=pose.corners_px+[90, 0])
    result = acquirer.locate(blank, pose, 2 if change == 'duplicate' else 1 if change == 'reverse' else 3, 1000 if change == 'gap' else 300)
    assert not acquirer.evidence['orientation'].get('carried')
    np.testing.assert_allclose(result.corners_px, pose.corners_px)


def test_verified_anchor_measures_current_holes_before_a_new_model_order(monkeypatch):
    frame, mounts = panel()
    acquirer = geometry.TftRingAcquirer()
    calls = []
    def measure(image, seed, evidence):
        calls.append((image, seed.corners_px.copy()))
        return seed
    monkeypatch.setattr(geometry, 'refine_tft_rings', measure)
    acquirer.locate(frame, observation(mounts), 1, 100)
    current = frame.copy()
    result = acquirer.locate(current, observation(np.roll(mounts, 2, axis=0)), 2, 200)
    assert len(calls) == 2
    assert calls[-1][0] is current
    np.testing.assert_allclose(calls[-1][1], mounts)
    np.testing.assert_allclose(result.corners_px, mounts)
    assert acquirer.evidence['search'] == 'recent_header_verified_rings'
