"""Shared reference-image scale checks for calibration and preflight tools."""
from __future__ import annotations

from typing import Iterable

import numpy as np

DEFAULT_MIN_PIN_PITCH_PX = 18.0
DEFAULT_MIN_PX_PER_MM = 8.0
DEFAULT_MARGIN_FRAC = 0.08

# (header id, index, x_mm, y_mm)
PinGeometry = tuple[str, int, float, float]
_ORB_ALIGNED_KEYS = (
    "xy_mm", "desc", "orb_pts", "orb_size", "orb_angle", "orb_response",
    "orb_octave", "orb_desc",
)


def _apply_h(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    homogeneous = np.c_[points, np.ones(len(points))]
    projected = (np.asarray(h, dtype=np.float64) @ homogeneous.T).T
    denominator = projected[:, 2:3]
    if np.any(np.abs(denominator) < 1e-12):
        raise ValueError("mm_to_px projects a pin at infinity")
    return projected[:, :2] / denominator


def reference_scale_report(
    mm_to_px: np.ndarray,
    pin_geometry: Iterable[PinGeometry],
    *,
    min_pin_pitch_px: float = DEFAULT_MIN_PIN_PITCH_PX,
    min_px_per_mm: float = DEFAULT_MIN_PX_PER_MM,
) -> dict[str, float | str]:
    """Measure the projected header scale used by a reference capture.

    Adjacent pins are measured within each header row.  Pixel/mm is derived
    from each pair's actual board geometry rather than assuming a fixed board
    pitch, so the same check can be reused for another profile.
    """
    if min_pin_pitch_px <= 0 or min_px_per_mm <= 0:
        raise ValueError("scale thresholds must be positive")

    by_header: dict[str, list[tuple[int, float, float]]] = {}
    for header, index, x_mm, y_mm in pin_geometry:
        by_header.setdefault(str(header), []).append(
            (int(index), float(x_mm), float(y_mm))
        )

    pitch_samples: list[float] = []
    px_per_mm_samples: list[float] = []
    h = np.asarray(mm_to_px, dtype=np.float64)
    if h.shape != (3, 3) or not np.all(np.isfinite(h)):
        raise ValueError("mm_to_px must be a finite 3x3 matrix")

    for row in by_header.values():
        row.sort(key=lambda item: item[0])
        if len(row) < 2:
            continue
        board_points = np.asarray([[item[1], item[2]] for item in row], dtype=np.float64)
        projected = _apply_h(h, board_points)
        for i in range(len(row) - 1):
            px_distance = float(np.linalg.norm(projected[i + 1] - projected[i]))
            mm_distance = float(np.linalg.norm(board_points[i + 1] - board_points[i]))
            if px_distance > 0.0 and mm_distance > 0.0:
                pitch_samples.append(px_distance)
                px_per_mm_samples.append(px_distance / mm_distance)

    if pitch_samples:
        pitch_px = float(np.median(np.asarray(pitch_samples)))
        px_per_mm = float(np.median(np.asarray(px_per_mm_samples)))
    else:
        pitch_px = 0.0
        px_per_mm = 0.0

    status = (
        "ok"
        if pitch_px >= float(min_pin_pitch_px)
        and px_per_mm >= float(min_px_per_mm)
        else "reject"
    )
    return {
        "pitch_px": pitch_px,
        "px_per_mm": px_per_mm,
        "min_pitch_px": float(min_pin_pitch_px),
        "min_px_per_mm": float(min_px_per_mm),
        "status": status,
    }


def profile_pin_geometry(board: dict) -> list[PinGeometry]:
    """Extract the common geometry tuple from a raw board.json payload."""
    return [
        (str(pin["header"]), int(pin["index"]), float(pin["pos_mm"][0]), float(pin["pos_mm"][1]))
        for pin in board.get("pins", [])
    ]


def filter_reference_features(
    features: dict[str, np.ndarray],
    outline_mm: tuple[float, float],
    *,
    margin_frac: float = DEFAULT_MARGIN_FRAC,
) -> tuple[dict[str, np.ndarray], int]:
    """Keep aligned ORB/cache features inside the board footprint."""
    if margin_frac < 0:
        raise ValueError("margin_frac must be non-negative")
    w_mm, h_mm = float(outline_mm[0]), float(outline_mm[1])
    xy_mm = np.asarray(
        features.get("xy_mm", np.zeros((0, 2))), dtype=np.float64
    ).reshape(-1, 2)
    lo_x, hi_x = -margin_frac * w_mm, w_mm + margin_frac * w_mm
    lo_y, hi_y = -margin_frac * h_mm, h_mm + margin_frac * h_mm
    keep = (
        (xy_mm[:, 0] >= lo_x) & (xy_mm[:, 0] <= hi_x)
        & (xy_mm[:, 1] >= lo_y) & (xy_mm[:, 1] <= hi_y)
    )
    filtered: dict[str, np.ndarray] = {
        key: np.asarray(features[key])[keep]
        for key in _ORB_ALIGNED_KEYS
        if key in features
    }
    # SIFT and image-shape arrays are diagnostic metadata, not runtime cache
    # arrays aligned with xy_mm, so preserve them unfiltered.
    for key in (
        "sift_pts", "sift_size", "sift_angle", "sift_response",
        "sift_octave", "sift_desc", "image_shape",
    ):
        if key in features:
            filtered[key] = np.asarray(features[key])
    return filtered, int(keep.sum())


__all__ = [
    "DEFAULT_MIN_PIN_PITCH_PX",
    "DEFAULT_MIN_PX_PER_MM",
    "DEFAULT_MARGIN_FRAC",
    "PinGeometry",
    "filter_reference_features",
    "profile_pin_geometry",
    "reference_scale_report",
]
