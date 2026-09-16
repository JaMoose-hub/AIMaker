"""Small, display-only smoothing of fresh Eye YOLO geometry.

There is no image analysis, optical flow or prediction here. Missing detections
clear immediately. Every displayed pin starts from this frame's model output;
one shared homography applies the same small correction as the displayed quad.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np


@dataclass
class _Sample:
    raw: np.ndarray
    shown: np.ndarray
    delta: np.ndarray | None
    frame_id: int
    ts_ms: float
    context: tuple
    pending: bool = False


def _quad(value):
    if value is None:
        return None
    try:
        points = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if (points.shape != (4, 2) or not np.isfinite(points).all()
            or not cv2.isContourConvex(points.astype(np.float32))
            or abs(cv2.contourArea(points.astype(np.float32))) < 1.):
        return None
    return points.copy()


def _box_quad(body):
    if body is None:
        return None
    box = body.get('box')
    if not isinstance(box, (tuple, list)) or len(box) != 4:
        return None
    x1, y1, x2, y2 = box
    return _quad([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])


def _rms(delta):
    return float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))


def _discontinuity(previous, current):
    diagonal = max(1., float(np.linalg.norm(np.ptp(previous, axis=0))))
    ordered = _rms(current - previous)
    alternatives = [np.roll(current, shift, axis=0) for shift in (1, 2, 3)]
    alternatives.extend(np.roll(current[::-1], shift, axis=0) for shift in range(4))
    reordered = min(_rms(points - previous) for points in alternatives)
    if ordered > diagonal * .18 and reordered < min(ordered * .35, diagonal * .12):
        return 'semantic_flip'
    area = abs(cv2.contourArea(current.astype(np.float32)))
    old_area = max(1., abs(cv2.contourArea(previous.astype(np.float32))))
    if ordered > max(40., diagonal * .60) or not .45 <= area / old_area <= 2.2:
        return 'large_jump'
    return None


def _transform(points, matrix):
    values = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(values, matrix).reshape(-1, 2)


class EyeYoloDisplayStabilizer:
    """One Eye group owns this helper; no webcam worker calls it.

    apply() preserves frame IDs, timestamps, confidences and pin identities.
    diagnostics() describes the display correction separately from model data.
    reset() clears every object at a camera/runtime transition.
    """

    def __init__(self):
        self._samples = {}
        self._diagnostics = {}

    def reset(self):
        self._samples.clear()
        self._diagnostics.clear()

    def diagnostics(self):
        return {key: dict(value) for key, value in self._diagnostics.items()}

    def _hide(self, result, reason):
        changes = dict(tracking='searching', confidence=0., outline_px=None,
                       pins=() if isinstance(result.pins, tuple) else [],
                       motion_outline_px=None, body=None)
        if hasattr(result, 'tracking_reason'):
            detail = result.tracking_reason if reason == 'missing' else None
            changes.update(tracking_reason=detail or 'yolo_' + reason, diagnostic_pins=(),
                           diagnostic_box_px=None, diagnostic_reason=None)
        else:
            detail = result.pose_path if reason == 'missing' else None
            changes.update(pose_path=detail or 'yolo_' + reason, wire_exclusion_px=None)
        return replace(result, **changes)

    def apply(self, result, *, video_size, runtime_revision):
        identifier = getattr(result, 'component_id', None) or result.board_id
        stale = result.tracking == 'stale'
        outline = _quad(result.outline_px) if result.tracking == 'locked' else None
        body_quad = _box_quad(result.body)
        raw = outline if outline is not None else body_quad
        mode = 'pose' if outline is not None else 'body'
        if outline is None:
            changes = dict(tracking='searching', outline_px=None,
                           pins=() if isinstance(result.pins, tuple) else [],
                           motion_outline_px=None)
            if hasattr(result, 'wire_exclusion_px'):
                changes['wire_exclusion_px'] = None
            result = replace(result, **changes)
        context = (tuple(video_size), runtime_revision, mode)
        if raw is None or stale:
            self._samples.pop(identifier, None)
            self._diagnostics[identifier] = {'reason': 'missing', 'correction_px': 0.}
            return self._hide(result, 'missing')
        sample = self._samples.get(identifier)
        if (sample is not None and (sample.context != context
                or result.frame_id <= sample.frame_id
                or not 0 < result.ts_ms - sample.ts_ms <= 250.)):
            sample = None
        delta = None if sample is None else raw - sample.raw
        reason = None if sample is None else _discontinuity(sample.raw, raw)
        if reason is not None:
            # Keep only an undisplayed candidate. A second coherent fresh
            # observation may seed the new geometry, never blend across it.
            self._samples[identifier] = _Sample(raw, raw.copy(), None,
                result.frame_id, result.ts_ms, context, pending=True)
            self._diagnostics[identifier] = {'reason': reason, 'correction_px': 0.}
            return self._hide(result, reason)
        if sample is None or sample.pending:
            self._samples[identifier] = _Sample(raw, raw.copy(), None,
                result.frame_id, result.ts_ms, context)
            self._diagnostics[identifier] = {'reason': 'fresh_seed', 'correction_px': 0.}
            return result

        diagonal = max(1., float(np.linalg.norm(np.ptp(raw, axis=0))))
        quiet = max(3., diagonal * .012)
        distance = _rms(raw - sample.shown)
        alpha = .35 + .65 * float(np.clip((distance - quiet) / max(6., diagonal * .05), 0., 1.))
        # Consistent consecutive model displacements indicate real movement;
        # independent corner jitter tends to reverse direction instead.
        if sample.delta is not None:
            norm = float(np.linalg.norm(delta) * np.linalg.norm(sample.delta))
            alignment = float(np.sum(delta * sample.delta)) / norm if norm > 0 else 0.
            if alignment > .65 and _rms(delta) > 1. and _rms(sample.delta) > 1.:
                alpha = max(alpha, .90)
        shown = sample.shown + alpha * (raw - sample.shown)
        # Bound geometric lag even on a sudden direction change. No point is
        # held frozen and no extrapolated point lies beyond the current input.
        maximum_correction = max(3., min(8., diagonal * .018))
        correction = float(np.max(np.linalg.norm(shown - raw, axis=1)))
        if correction > maximum_correction:
            shown = raw + (shown - raw) * (maximum_correction / correction)
        if _quad(shown) is None:
            shown = raw.copy()
        matrix = cv2.getPerspectiveTransform(raw.astype(np.float32), shown.astype(np.float32))
        changes = {}
        if outline is not None:
            changes['outline_px'] = shown.copy() if isinstance(result.outline_px, np.ndarray) else shown.tolist()
            changes['motion_outline_px'] = changes['outline_px']
            if result.pins:
                points = _transform([(pin.x, pin.y) for pin in result.pins], matrix)
                if not np.isfinite(points).all():
                    self._samples.pop(identifier, None)
                    return self._hide(result, 'invalid_projection')
                pins = [replace(pin, x=float(x), y=float(y), visible=pin.visible and
                        0 <= x < video_size[0] and 0 <= y < video_size[1])
                        for pin, (x, y) in zip(result.pins, points)]
                changes['pins'] = tuple(pins) if isinstance(result.pins, tuple) else pins
            exclusion = getattr(result, 'wire_exclusion_px', None)
            if exclusion is not None:
                projected = _transform(exclusion, matrix)
                changes['wire_exclusion_px'] = projected.tolist() if np.isfinite(projected).all() else None
        if body_quad is not None:
            projected = _transform(body_quad, matrix)
            if not np.isfinite(projected).all():
                projected = body_quad
            changes['body'] = {**result.body, 'box': [float(value) for value in
                (*projected.min(axis=0), *projected.max(axis=0))]}
        self._samples[identifier] = _Sample(raw, shown.copy(), delta,
            result.frame_id, result.ts_ms, context)
        self._diagnostics[identifier] = {'reason': 'following' if alpha >= .90 else 'smoothed',
            'alpha': round(alpha, 3),
            'correction_px': round(float(np.max(np.linalg.norm(shown - raw, axis=1))), 3)}
        return replace(result, **changes)
