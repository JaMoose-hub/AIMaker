"""Build/replace the canonical per-board-model reference asset.

Used by ``POST /api/calibrate`` (see ``app/api/calibrate.py`` and
``docs/api-contract.md`` §6). The flow:

1. The frontend draws a dashed guide rectangle (sized to the board's
   ``outline_mm`` aspect ratio) over the live video and asks the user to
   align the physical board to it. On capture, the guide's on-screen corner
   pixel coordinates (TL, TR, BR, BL) are ALREADY the board-mm <-> frame-px
   correspondences -- no manual hole-clicking needed.
2. ``build_mm_to_px`` turns those 4 corners into the board-mm -> frame-px
   homography (mirrors ``tools/calibrate_reference.py``'s
   ``compute_homography``, but from a rectangle instead of 4 mounting holes).
3. ``validate_corners`` sanity-checks the corners before anything is read
   from the frame (degenerate/self-intersecting quads, or a quad that is
   implausibly small/large relative to the frame, are rejected early).
4. ``write_calibration`` extracts ORB+SIFT features from the captured frame
   (reusing ``tools/calibrate_reference.compute_features`` -- the ORB/SIFT
   extraction logic is not duplicated here), keeps only the features that
   fall within the board's footprint (+ a margin, to tolerate imprecise
   by-eye alignment), and -- only if there are enough of them -- backs up
   the previous ``board.json`` + reference image and writes the new
   reference block, reference image and ``features.npz`` feature cache.

Nothing on disk is touched when there are too few features: a bad capture
must never corrupt a working calibration.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

# tools/calibrate_reference.py already implements the ORB+SIFT reference
# feature extraction (including the board-mm projection via the inverse
# homography); reuse it here instead of duplicating the CV logic.
_TOOLS_DIR = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from calibrate_reference import compute_features  # noqa: E402
from scale_quality import (  # noqa: E402
    DEFAULT_MIN_PIN_PITCH_PX,
    DEFAULT_MIN_PX_PER_MM,
    PinGeometry,
    filter_reference_features,
    reference_scale_report,
)

__all__ = [
    "DEFAULT_MIN_PIN_PITCH_PX",
    "DEFAULT_MIN_PX_PER_MM",
    "MIN_FEATURE_COUNT",
    "build_mm_to_px",
    "reference_scale_report",
    "validate_corners",
    "write_calibration",
]

# Below this many board-region features, the captured frame is considered
# unusable as a reference (bad lighting / board not fully in frame / too far
# away) -- write_calibration() refuses to touch disk state in that case.
MIN_FEATURE_COUNT = 200

_REFERENCE_IMAGE_NAME = "reference_captured.jpg"
_BOARD_JSON_NAME = "board.json"
_FEATURES_NAME = "features.npz"


def build_mm_to_px(corners_px, outline_mm: tuple[float, float]) -> np.ndarray:
    """board-mm (0,0)/(W,0)/(W,H)/(0,H) -> the given TL/TR/BR/BL corners_px.

    Returns the 3x3 homography (cv2.getPerspectiveTransform), float64.
    """
    w, h = float(outline_mm[0]), float(outline_mm[1])
    src = np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=np.float32)
    dst = np.array(corners_px, dtype=np.float32).reshape(4, 2)
    H = cv2.getPerspectiveTransform(src, dst)
    return H.astype(np.float64)


def validate_corners(corners_px: Any, frame_shape: tuple[int, int]) -> str | None:
    """Sanity-check 4 TL/TR/BR/BL corners against the frame they were drawn on.

    Returns an error code string ("corners_invalid") when:
    - ``corners_px`` is not exactly 4 finite [x, y] pairs, or
    - the quad (in TL, TR, BR, BL order) is not simple + convex, or
    - its area is outside [1%, 95%] of the frame area,
    else None (valid).

    ``frame_shape`` is a numpy-style (height, width, ...) shape tuple.
    """
    try:
        pts = np.asarray(corners_px, dtype=np.float64)
    except (TypeError, ValueError):
        return "corners_invalid"
    if pts.shape != (4, 2) or not np.all(np.isfinite(pts)):
        return "corners_invalid"

    # Convexity: consecutive edge cross-products must all share one sign
    # (same check PoseTracker._polygon_ok uses for the detected board quad).
    edges = np.roll(pts, -1, axis=0) - pts
    next_edges = np.roll(edges, -1, axis=0)
    cross = edges[:, 0] * next_edges[:, 1] - edges[:, 1] * next_edges[:, 0]
    if not (np.all(cross > 0) or np.all(cross < 0)):
        return "corners_invalid"

    area = 0.5 * abs(
        float(np.dot(pts[:, 0], np.roll(pts[:, 1], -1))
              - np.dot(pts[:, 1], np.roll(pts[:, 0], -1)))
    )
    frame_h, frame_w = float(frame_shape[0]), float(frame_shape[1])
    frame_area = frame_w * frame_h
    if frame_area <= 0:
        return "corners_invalid"
    frac = area / frame_area
    if not (0.01 <= frac <= 0.95):
        return "corners_invalid"
    return None


def _backup(path: Path) -> Path | None:
    """Copy ``path`` to ``<name><suffix>.bak-<timestamp>`` if it exists.

    Mirrors tools/calibrate_reference.py's backup convention exactly
    (``board_json.with_suffix(f".json.bak-{stamp}")``), generalized to any
    extension so it also covers the reference image.
    """
    if not path.is_file():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(f"{path.suffix}.bak-{stamp}")
    shutil.copy2(path, backup)
    return backup


def write_calibration(
    profile_dir: Path,
    frame_bgr: np.ndarray,
    mm_to_px: np.ndarray,
    outline_mm: tuple[float, float],
    margin_frac: float = 0.08,
    min_features: int = MIN_FEATURE_COUNT,
    pin_geometry: Iterable[PinGeometry] | None = None,
    min_pin_pitch_px: float = DEFAULT_MIN_PIN_PITCH_PX,
    min_px_per_mm: float = DEFAULT_MIN_PX_PER_MM,
) -> dict:
    """Filter the captured frame's features to the board footprint and,
    if there are enough of them, install them as the new canonical
    reference (backing up the previous board.json + reference image first).

    Returns {"ok": False, "count": N} without touching disk if N < min_features,
    else {"ok": True, "count": N} after writing board.json / reference image /
    features.npz.
    """
    profile_dir = Path(profile_dir)

    # Run the scale gate before feature extraction and before any filesystem
    # operation.  This protects the existing reference even when a small
    # capture happens to contain plenty of texture/features.
    scale: dict[str, float | str] | None = None
    if pin_geometry is not None:
        scale = reference_scale_report(
            mm_to_px,
            pin_geometry,
            min_pin_pitch_px=min_pin_pitch_px,
            min_px_per_mm=min_px_per_mm,
        )
        if scale["status"] != "ok":
            return {"ok": False, "error": "insufficient_scale", **scale}

    feats = compute_features(frame_bgr, mm_to_px)
    filtered, count = filter_reference_features(
        feats, outline_mm, margin_frac=margin_frac,
    )

    if count < min_features:
        return {"ok": False, "count": count}

    board_json_path = profile_dir / _BOARD_JSON_NAME
    board_raw = json.loads(board_json_path.read_text(encoding="utf-8"))
    old_ref_name = board_raw.get("reference", {}).get("image")

    # Back up existing state before touching anything (never corrupt a
    # working calibration; the count check above already guarantees we
    # only get here with a usable capture).
    _backup(board_json_path)
    if old_ref_name:
        _backup(profile_dir / old_ref_name)

    ref_path = profile_dir / _REFERENCE_IMAGE_NAME
    ok = cv2.imwrite(str(ref_path), frame_bgr)
    if not ok:
        raise IOError(f"failed to write reference image: {ref_path}")

    height_px, width_px = frame_bgr.shape[0], frame_bgr.shape[1]
    board_raw["reference"] = {
        "image": _REFERENCE_IMAGE_NAME,
        "width_px": int(width_px),
        "height_px": int(height_px),
        "mm_to_px": [[float(v) for v in row] for row in np.asarray(mm_to_px)],
    }
    board_json_path.write_text(
        json.dumps(board_raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    np.savez_compressed(profile_dir / _FEATURES_NAME, **filtered)

    result = {"ok": True, "count": count}
    if scale is not None:
        result.update(scale)
    return result
