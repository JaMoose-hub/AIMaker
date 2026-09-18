"""Narrow Webcam identity veto: an HC candidate on a visible TFT panel.

This is negative evidence, not a new detector. Missing rings alone never reject
an HC, and confidence scores from independent models are never compared.
"""
import cv2
import numpy as np


def _quad(value):
    if value is None:
        return None
    q = np.asarray(value, np.float32)
    if (q.shape != (4, 2) or not np.isfinite(q).all()
            or not cv2.isContourConvex(q) or abs(cv2.contourArea(q)) < 64):
        return None
    return q


def tft_panel_visible(frame, outline):
    """Require a large inset LCD rectangle AND blue end strips in current pixels.

    Uses the displayed outer PCB outline, not mounting-hole coordinates. An
    unlit LCD is sufficient evidence; a bright/occluded LCD conservatively
    returns false, leaving the ordinary detectors unchanged.
    """
    mapping = cv2.getPerspectiveTransform(outline,
        np.float32([[0, 0], [159, 0], [159, 239], [0, 239]]))
    patch = cv2.warpPerspective(frame, mapping, (160, 240))
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.uint8([75, 50, 20]), np.uint8([145, 255, 255]))
    # The two blue strips disambiguate LCDs from a uniform black/blue surface.
    if min(np.mean(blue[:24] > 0), np.mean(blue[-24:] > 0)) < .12:
        return False
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    mask = cv2.bitwise_and(cv2.inRange(gray, 0, 80), cv2.bitwise_not(blue))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if not .48 <= cv2.contourArea(contour) / (160 * 240) <= .88:
            continue
        q = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True).reshape(-1, 2)
        if len(q) != 4 or not cv2.isContourConvex(q):
            continue
        if q[:, 1].min() < 8 or q[:, 1].max() > 231:
            continue
        if np.max(np.abs(q.mean(0) / [160, 240] - .5)) > .12:
            continue
        edges = np.abs(q - np.roll(q, -1, axis=0))
        if np.all(edges.min(1) / np.maximum(edges.max(1), 1) < .30):
            return True
    return False


def hc_tft_conflict(frame, hc_outline, tft_outline, *, hc_visible,
                    reference_confirmed=False):
    """Return diagnostic evidence only for a positively corroborated conflict.

    Callers must provide synchronized/current poses. hc_visible is lazy: the
    existing transducer test is only needed for the rare overlapping candidate.
    Real HC-on-TFT cases with current ring/reference evidence remain eligible.
    """
    hc, tft = _quad(hc_outline), _quad(tft_outline)
    if hc is None or tft is None or reference_confirmed:
        return None
    area = abs(cv2.contourArea(hc))
    ratio = area / abs(cv2.contourArea(tft))
    if not .04 <= ratio <= .65:
        return None
    overlap = cv2.intersectConvexConvex(hc, tft)[0] / area
    if overlap < .70 or not tft_panel_visible(frame, tft):
        return None
    if hc_visible(frame, hc, 1.0):
        return None
    return dict(rejected=True, reason='component_identity_conflict',
                conflicts_with='mrd-tf240-8p-cs', overlap_fraction=round(overlap, 3),
                area_ratio=round(ratio, 3), tft_panel_visible=True,
                hc_transducers_visible=False)
