"""Lit LCDs and collapsed model keypoints: current geometry, never cached pins."""
from dataclasses import replace

import cv2
import numpy as np
import pytest

from app.vision.tft_ring_geometry import (
    TftRingAcquirer, _independent_panel_edges, orient_tft_from_panel_inset,
    refine_tft_rings,
)
from test_motion_consensus import observation


def lit_panel():
    image = np.full((720, 1080, 3), (185, 170, 155), np.uint8)
    mounts = np.float32([[340, 140], [540, 140], [540, 500], [340, 500]])
    cv2.rectangle(image, (325, 125), (555, 515), (180, 70, 20), -1)
    cv2.rectangle(image, (333, 161), (547, 449), (230, 230, 230), -1)
    cv2.rectangle(image, (336, 164), (544, 446), (15, 15, 15), -1)
    # Interrupt the closed edge contour but leave >70% of every real rail.
    cv2.rectangle(image, (424, 147), (436, 195), (15, 15, 15), -1)
    cv2.rectangle(image, (430, 425), (442, 466), (15, 15, 15), -1)
    cv2.putText(image, 'TFT', (355, 320), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 210, 170), 3)
    for p in mounts.astype(int):
        cv2.circle(image, tuple(p), 11, (230, 230, 230), -1)
        cv2.circle(image, tuple(p), 7, (45, 45, 45), -1)
    return image, mounts


@pytest.mark.parametrize('angle', [0, 37, 90, 180])
def test_separate_lcd_edges_restore_header_with_connected_text_contours(angle):
    image, mounts = lit_panel()
    transform = cv2.getRotationMatrix2D((450, 350), angle, 1)
    image = cv2.warpAffine(image, transform, (1080, 720))
    mounts = cv2.transform(mounts[None], transform)[0]
    assert _independent_panel_edges(image, mounts)
    evidence = {}
    result = orient_tft_from_panel_inset(image, observation(np.roll(mounts, 2, axis=0)), evidence)
    assert evidence['verified'], evidence
    np.testing.assert_allclose(result.corners_px, mounts, atol=.001)


def test_expanded_search_recovers_real_mounts_not_collapsed_model_corners():
    image, mounts = lit_panel()
    predicted = (mounts-mounts.mean(0))*.35+mounts.mean(0)+[55, 0]
    pose = replace(observation(predicted), box_xyxy=(400., 180., 550., 460.))
    evidence = {}
    result = refine_tft_rings(image, pose, evidence, expanded=True)
    assert result is not None, evidence
    np.testing.assert_allclose(result.corners_px, mounts, atol=3)
    assert evidence['expanded_search']


@pytest.mark.parametrize('kind', ['blank', 'no_lcd', 'covered_side', 'missing_hole', 'symmetric'])
def test_wider_search_never_invents_missing_mounts_or_panel_evidence(kind):
    image, mounts = lit_panel()
    if kind == 'blank':
        image[:] = 100
    elif kind == 'no_lcd':
        image[150:475, 328:553] = (180, 70, 20)
    elif kind == 'covered_side':
        image[150:475, 325:380] = 100
    elif kind == 'missing_hole':
        image[125:155, 325:355] = 100
    else:
        image[150:475, 328:553] = (180, 70, 20)
        cv2.rectangle(image, (336, 183), (544, 457), (15, 15, 15), -1)
    assert refine_tft_rings(image, observation(mounts), {}, expanded=True) is None


def test_expanded_search_is_bounded_and_needs_current_identity():
    image, mounts = lit_panel()
    evidence = {}
    huge = replace(observation(mounts), box_xyxy=(0., 0., 1000., 700.))
    assert refine_tft_rings(image, huge, evidence, expanded=True) is None
    assert evidence['reason'] == 'expanded_search_not_bounded'
    assert TftRingAcquirer().locate(image, None, 1, 100) is None


def test_acquired_lit_panel_moves_then_disappears_without_reusing_old_pixels():
    image, mounts = lit_panel()
    predicted = (mounts-mounts.mean(0))*.35+mounts.mean(0)+[55, 0]
    pose = replace(observation(predicted), box_xyxy=(400., 180., 550., 460.))
    acquirer = TftRingAcquirer()
    first = acquirer.locate(image, pose, 1, 100)
    assert first is not None, acquirer.evidence
    moved = cv2.warpAffine(image, np.float32([[1, 0, 8], [0, 1, 4]]), (1080, 720))
    result = acquirer.locate(moved, None, 2, 200)
    assert result is not None, acquirer.evidence
    np.testing.assert_allclose(result.corners_px, mounts+[8, 4], atol=3)
    assert acquirer.locate(np.full_like(image, 100), None, 3, 300) is None
    assert acquirer.locate(moved, None, 4, 901) is None
