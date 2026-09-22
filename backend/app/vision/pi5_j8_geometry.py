"""Conservative image alignment of a projected Pi 5 J8 lattice.

This locates the header housing, not electrical contacts or wire continuity.
The board model supplies identity, pin numbering and perspective. No fixed
screen-space offset is learned or retained by this module.
"""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np

from app.vision.interface import PinDetection


def align_pi5_j8(
    frame_bgr: np.ndarray,
    profile,
    pins: list[PinDetection],
    video_size: tuple[int, int],
) -> list[PinDetection]:
    """Return a corrected lattice only for an unambiguous full-length housing.

    A connected dark contour can include chips, silkscreen shadows and screws.
    Rectify with the existing pin projection, then require a continuous narrow
    strip across most of all 20 columns. Short attached objects cannot pull
    its centre or endpoints. Missing/ambiguous evidence leaves pins untouched.
    """
    if (frame_bgr is None or frame_bgr.size == 0
            or getattr(getattr(profile, 'board', None), 'id', None) != 'raspberry-pi-5'):
        return pins
    width, height = video_size
    if frame_bgr.shape[:2] != (height, width):
        return pins
    j8 = [p for p in pins if p.header == 'J8']
    indexed = {p.index: p for p in j8}
    # Never stretch a visible fragment to represent all 40 pins.
    if len(j8) != 40 or set(indexed) != set(range(1, 41)):
        return pins
    source = np.float32([[indexed[i].x, indexed[i].y] for i in (1, 39, 40, 2)])
    if (not all(p.visible for p in j8) or not np.isfinite(source).all()
            or not np.isfinite([[p.x, p.y] for p in j8]).all()
            or not cv2.isContourConvex(source)
            or np.any(source < 0) or np.any(source >= [width, height])):
        return pins
    long_edges = np.linalg.norm(source[[1, 2]] - source[[0, 3]], axis=1)
    row_edges = np.linalg.norm(source[[3, 2]] - source[[0, 1]], axis=1)
    if min(long_edges) < 76 or min(row_edges) < 4:
        return pins

    # Fixed-size, perspective-normalized ROI: one pin pitch = 12 pixels.
    # The inverse mapping preserves rotations, row order and foreshortening.
    pitch = 12
    target = np.float32([[24, 36], [252, 36], [252, 48], [24, 48]])
    matrix = cv2.getPerspectiveTransform(source, target)
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1e-12:
        return pins
    inverse = np.linalg.inv(matrix)
    housing_prior = cv2.perspectiveTransform(
        np.float32([[[18, 30], [258, 30], [258, 54], [18, 54]]]), inverse)[0]
    if (not np.isfinite(housing_prior).all() or np.any(housing_prior < 1)
            or np.any(housing_prior >= [width - 1, height - 1])):
        return pins
    patch = cv2.warpPerspective(frame_bgr, matrix, (276, 84),
                                borderValue=(255, 255, 255))
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    # Dark green PCB must not join the neutral plastic housing. Saturation is
    # unreliable near black, so retain very dark pixels independently of hue.
    dark = ((hsv[:, :, 2] <= 105)
            & ((hsv[:, :, 1] <= 60) | (hsv[:, :, 2] <= 35))).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Remove branches shorter than 14 pin pitches, then bridge only the small
    # reflective seam between the two rows. Not the neighbouring PCB/chips.
    core = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 169), np.uint8))
    core = cv2.morphologyEx(core, cv2.MORPH_CLOSE, np.ones((7, 1), np.uint8))
    contours, _ = cv2.findContours(core, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if (x <= 1 or y <= 1 or x + w >= 275 or y + h >= 83
                or not 17.5 * pitch <= w <= 22 * pitch
                or not 1.1 * pitch <= h <= 2.8 * pitch):
            continue
        selected = np.zeros_like(core)
        cv2.drawContours(selected, [contour], -1, 255, cv2.FILLED)
        # Robust edge consensus across the housing, rather than percentiles of
        # all contour points (a textured chip contributes far more points).
        lateral = [np.flatnonzero(selected[:, col])
                   for col in range(x + w // 10, x + w - w // 10)]
        lateral = [s for s in lateral if len(s)]
        if not lateral:
            continue
        top, bottom = np.median([(s[0], s[-1]) for s in lateral], axis=0)
        centre_y = (top + bottom) / 2
        spans = [np.flatnonzero(selected[row]) for row in
                 range(int(top + .25 * (bottom - top)), int(top + .75 * (bottom - top)) + 1)]
        spans = [s for s in spans if len(s)]
        if not spans:
            continue
        left, right = np.median([(s[0], s[-1]) for s in spans], axis=0)
        if (abs(centre_y - 42) > 1.5 * pitch
                or abs((left + right) / 2 - 138) > pitch
                or right - left < 17.5 * pitch):
            continue
        candidates.append((left - .5, right + .5, centre_y))
    # Two plausible parallel strips are ambiguous: never pick by dark area.
    if len(candidates) != 1:
        return pins
    left, right, centre_y = candidates[0]
    canonical = np.float32([
        [left + ((p.index - 1) // 2 + .5) * (right - left) / 20,
         centre_y + (-.5 if p.index % 2 else .5) * pitch]
        for p in j8
    ])
    corrected = cv2.perspectiveTransform(canonical.reshape(-1, 1, 2), inverse).reshape(-1, 2)
    old = np.asarray([[p.x, p.y] for p in j8])
    if (not np.isfinite(corrected).all() or np.any(corrected < 0)
            or np.any(corrected >= [width, height])
            or np.median(np.linalg.norm(corrected - old, axis=1)) > 2 * np.mean(long_edges) / 19):
        return pins
    by_id = {p.pin_id: xy for p, xy in zip(j8, corrected)}
    return [replace(p, x=float(by_id[p.pin_id][0]), y=float(by_id[p.pin_id][1]))
            if p.pin_id in by_id else p for p in pins]
