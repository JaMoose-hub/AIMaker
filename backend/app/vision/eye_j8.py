"""Current-image Pi J8 row correction for Eye; no models or temporal state.

YOLO and the profile retain identity, orientation, column spacing and row pitch.
Only a common translation perpendicular to the row is estimated from visible
contact contrast. An ambiguous/unsupported image keeps this frame's projection.
"""
from __future__ import annotations

from dataclasses import replace

import cv2
import numpy as np


def correct_eye_j8_from_image(frame, profile, pins, video_size, *, diagnostic=None):
    if diagnostic is not None:
        diagnostic.clear()

    def fallback(reason):
        if diagnostic is not None:
            diagnostic.update(accepted=False, reason=reason)
        return pins

    if (frame is None or frame.size == 0 or frame.ndim != 3
            or getattr(getattr(profile, 'board', None), 'id', None) != 'raspberry-pi-5'):
        return fallback('unsupported_input')
    ordered = sorted((pin for pin in pins if pin.header == 'J8' and pin.index is not None),
                     key=lambda pin: pin.index)
    if ([pin.index for pin in ordered] != list(range(1, 41))
            or not all(pin.visible for pin in ordered)):
        return fallback('incomplete_lattice')
    xy = np.asarray([[pin.x, pin.y] for pin in ordered], np.float32).reshape(20, 2, 2)
    if not np.isfinite(xy).all():
        return fallback('invalid_lattice')
    centres = xy.mean(axis=1)
    along = centres[-1] - centres[0]
    length = float(np.linalg.norm(along))
    if length < 30.:
        return fallback('small_lattice')
    along /= length
    normal = np.array([-along[1], along[0]], np.float32)
    row_vector = np.median(xy[:, 1] - xy[:, 0], axis=0)
    if normal @ row_vector < 0:
        normal = -normal
    row_gap = float(normal @ row_vector)
    pitch = float(np.median(np.linalg.norm(np.diff(centres, axis=0), axis=1)))
    if row_gap < 4. or pitch < 4.:
        return fallback('small_lattice')

    radius = 2. * row_gap
    pad = int(np.ceil(radius + pitch))
    height, width = frame.shape[:2]
    if tuple(video_size) != (width, height):
        return fallback('frame_size_mismatch')
    left, top = np.maximum(0, np.floor(xy.reshape(-1, 2).min(0)).astype(int) - pad)
    right, bottom = np.minimum([width, height], np.ceil(xy.reshape(-1, 2).max(0)).astype(int) + pad + 1)
    if right <= left or bottom <= top:
        return fallback('off_image')
    gray = cv2.cvtColor(frame[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), .8)
    kernel = max(3, int(round(.75 * pitch)) | 1)
    contrast = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel, kernel)))
    shifts = np.unique(np.r_[np.arange(-radius, radius + .25, .5, dtype=np.float32), np.float32(0)])
    # Search contact evidence within each column's vicinity; the selected
    # longitudinal sample never moves or reassigns an output pin.
    along_samples = np.linspace(-.4 * pitch, .4 * pitch, 9, dtype=np.float32)
    flat = xy.reshape(40, 2)
    sample_x = (flat[None, :, 0, None] + shifts[:, None, None] * normal[0]
                + along_samples[None, None, :] * along[0] - np.float32(left))
    sample_y = (flat[None, :, 1, None] + shifts[:, None, None] * normal[1]
                + along_samples[None, None, :] * along[1] - np.float32(top))
    sampled = cv2.remap(contrast, sample_x.reshape(len(shifts), -1),
        sample_y.reshape(len(shifts), -1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    cells = sampled.reshape(len(shifts), 20, 2, 9).max(axis=3)
    # Broad support in both rows prevents a few highlights from authorizing
    # a shift. Competing peaks must be distinct from the selected pair.
    trimmed = np.sort(cells, axis=1)[:, 4:16].mean(axis=1)
    scores = trimmed.min(axis=1) + .25 * trimmed.sum(axis=1)
    best = int(scores.argmax())
    delta = float(shifts[best])
    threshold = max(5., float(np.percentile(contrast, 90)) * .2)
    support = (cells[best] >= threshold).sum(axis=0)
    far = abs(shifts - delta) > .45 * row_gap
    margin = float(scores[best] - scores[far].max()) if far.any() else float(scores[best])
    boundary = abs(delta) > radius - .75
    if diagnostic is not None:
        diagnostic.update(shift_px=delta, support=support.tolist(), peak=float(scores[best]),
            distant_peak_margin=margin, boundary_optimum=boundary, row_gap_px=row_gap,
            pitch_px=pitch, roi=[int(left), int(top), int(right), int(bottom)])
    if min(support) < 12:
        return fallback('insufficient_contacts')
    if margin < max(1.5, .06 * float(scores[best])):
        return fallback('ambiguous_rows')
    if boundary:
        return fallback('search_boundary')
    if diagnostic is not None:
        diagnostic.update(accepted=True, reason='contact_rows')
    if delta == 0.:
        return pins
    offset_x, offset_y = float(normal[0]) * delta, float(normal[1]) * delta
    identities = {pin.pin_id for pin in ordered}
    return [replace(pin, x=pin.x + offset_x, y=pin.y + offset_y,
                    visible=pin.visible and 0 <= pin.x + offset_x < width
                    and 0 <= pin.y + offset_y < height)
            if pin.pin_id in identities else pin for pin in pins]
