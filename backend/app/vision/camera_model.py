"""Camera intrinsics + shared projection helpers for the vision pipeline.

Both PoseTracker (real CV) and SyntheticScene (renderer / ground truth) MUST
use the same intrinsics from this module so that synthetic tests are
self-consistent.

Intrinsics for an uncalibrated webcam use a caller-provided horizontal FOV
when available; callers without hardware information retain the historical
fallback ``fx = fy = 0.9 * W, cx = W / 2, cy = H / 2`` with zero distortion.

Optional calibration file ``camera.json`` (searched by callers, typically in
the profile folder or next to config.yaml) with the format::

    { "fx": 1234.5, "fy": 1234.5, "cx": 640.0, "cy": 360.0,
      "dist": [k1, k2, p1, p2, k3] }

``dist`` may have 0..14 entries (OpenCV order). Sizes below 5 are padded to
5, sizes 6/7 to 8; anything that still is not a valid OpenCV distortion
length (4, 5, 8, 12, 14) falls back to the default (zero-distortion) camera.

Coordinate-frame note (important, read this once)
-------------------------------------------------
The board profile frame (models.py) is: origin = top-left PCB corner seen
from above, x -> right, y -> down, z -> UP from the PCB plane.  As specified
that triple is LEFT-handed (x cross y points *into* the desk, not up), so no
proper rotation (OpenCV rvec) can map it onto the right-handed camera frame
while showing the top of the board un-mirrored.

Internally the vision code therefore works in the "vision frame":

    (x_v, y_v, z_v) = (x_mm, y_mm, -z_mm)

which is right-handed (z into the desk).  Consequences:
- Points on the PCB plane (z_mm = 0) are unchanged.
- Header pin openings (z_mm = +header_top_z_mm above the PCB, i.e. towards
  the camera) become z_v = -header_top_z_mm, which OpenCV correctly projects
  *closer* to the camera. This is the physically-correct parallax.
- A nominal top-down view (USB-C left, board matching the reference image)
  has rvec ~= 0.
- The board's outward normal (up out of the PCB) is (0, 0, -1) in the vision
  frame; a plausible pose must have (R @ [0,0,-1])[2] < 0 (normal towards
  the camera).

All rvec/tvec produced and consumed inside app.vision (including the
rvec/tvec debug fields of DetectionResult) use this vision frame.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.vision.interface import PinDetection

__all__ = [
    "CameraModel",
    "default_camera",
    "load_camera",
    "board_to_vision",
    "board_outline_mm",
    "project_wire_exclusion",
    "plane_homography",
    "project_points",
    "project_board",
]


@dataclass(frozen=True)
class CameraModel:
    """Pinhole camera: 3x3 K, distortion vector, image size (W, H)."""

    K: np.ndarray            # (3,3) float64
    dist: np.ndarray         # (N,) float64, OpenCV order (k1 k2 p1 p2 k3 ...)
    size: tuple[int, int]    # (W, H)
    calibrated: bool = False
    calibration_path: str | None = None


def default_camera(video_size: tuple[int, int],
                   horizontal_fov_deg: float | None = None) -> CameraModel:
    """Approximate intrinsics for an uncalibrated webcam.

    ``horizontal_fov_deg`` is a hardware-specific fallback. If omitted, the
    historical generic estimate (``0.9 * width``) is retained for synthetic
    fixtures and callers that do not know their lens. Production callers
    should provide a measured/spec FOV or a checkerboard calibration file.
    """
    w, h = int(video_size[0]), int(video_size[1])
    if horizontal_fov_deg is not None and 1.0 < float(horizontal_fov_deg) < 179.0:
        f = (w / 2.0) / np.tan(np.deg2rad(float(horizontal_fov_deg)) / 2.0)
    else:
        f = 0.9 * w
    K = np.array([[f, 0.0, w / 2.0],
                  [0.0, f, h / 2.0],
                  [0.0, 0.0, 1.0]], dtype=np.float64)
    return CameraModel(K=K, dist=np.zeros(5, dtype=np.float64), size=(w, h))


def load_camera(video_size: tuple[int, int],
                camera_json: Path | str | None = None,
                horizontal_fov_deg: float | None = None) -> CameraModel:
    """Load intrinsics from camera.json when present, else defaults.

    Any parse/shape problem silently falls back to :func:`default_camera`
    (an uncalibrated camera must never break the pipeline).

    A calibration is tied to the pixel dimensions at which it was captured.
    When the same camera is opened at another *same-aspect-ratio* resolution
    (for example 1280x720 -> 1920x1080), scale the intrinsic matrix into the
    live pixel space.  Leaving ``K`` in calibration pixels is a subtle but
    severe error: pose solving still succeeds, while every projected GPIO
    point is displaced by a resolution-dependent amount.

    A calibration with a materially different aspect ratio is not silently
    stretched.  Without crop/letterbox metadata there is no safe way to know
    whether the driver resized or cropped the sensor image, so the loader
    falls back to the uncalibrated model instead of returning confidently
    wrong geometry.
    """
    cam = default_camera(video_size, horizontal_fov_deg)
    if camera_json is None:
        return cam
    p = Path(camera_json)
    if not p.is_file():
        return cam
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        # New calibration tools record an explicit quality decision.  A
        # rejected file must never be used merely because its numeric fields
        # happen to parse; fall back to the known FOV/default model instead.
        quality_status = raw.get("quality_status")
        # The physical accuracy gate requires evidence that the calibration
        # itself passed its view/RMS/coverage checks. Loading a legacy file
        # with no quality metadata would make an unverified projection look
        # authoritative, so it follows the same safe fallback as rejection.
        if quality_status != "ok":
            return cam
        fx = float(raw["fx"])
        fy = float(raw["fy"])
        cx = float(raw["cx"])
        cy = float(raw["cy"])
        d = np.asarray(raw.get("dist", []), dtype=np.float64).reshape(-1)
        if d.size < 5:
            d = np.concatenate([d, np.zeros(5 - d.size)])
        elif 5 < d.size < 8:
            # 6/7-element vectors are not a valid OpenCV distortion shape;
            # pad to the 8-element rational model (extra terms zero).
            d = np.concatenate([d, np.zeros(8 - d.size)])
        if d.size not in (4, 5, 8, 12, 14):
            # Any other size would crash every cv2 call downstream.
            return cam
        K = np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]],
                     dtype=np.float64)
        calibration_size = raw.get("image_size")
        if calibration_size is not None:
            if (not isinstance(calibration_size, (list, tuple))
                    or len(calibration_size) != 2):
                return cam
            calibrated_w = float(calibration_size[0])
            calibrated_h = float(calibration_size[1])
            live_w, live_h = float(cam.size[0]), float(cam.size[1])
            if calibrated_w <= 0.0 or calibrated_h <= 0.0:
                return cam
            calibrated_aspect = calibrated_w / calibrated_h
            live_aspect = live_w / live_h if live_h > 0.0 else 0.0
            # A small tolerance allows integer rounding between modes but
            # rejects a real 4:3 vs 16:9 change, whose crop origin is unknown.
            if live_aspect <= 0.0 or abs(live_aspect / calibrated_aspect - 1.0) > 0.01:
                return cam
            sx = live_w / calibrated_w
            sy = live_h / calibrated_h
            K[0, 0] *= sx
            K[0, 2] *= sx
            K[1, 1] *= sy
            K[1, 2] *= sy
        return CameraModel(
            K=K,
            dist=d,
            size=cam.size,
            calibrated=True,
            calibration_path=str(p),
        )
    except Exception:
        return cam


# ---------------------------------------------------------------------------
# Frame conversion + projection helpers (shared by tracker / synthetic / mock)
# ---------------------------------------------------------------------------

def board_to_vision(pts_mm: np.ndarray) -> np.ndarray:
    """Profile board-mm points (N,3) -> right-handed vision frame (negate z).

    Accepts (N,2) as z=0 plane points and returns (N,3).
    """
    pts = np.asarray(pts_mm, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts[None, :]
    if pts.shape[1] == 2:
        out = np.zeros((pts.shape[0], 3), dtype=np.float64)
        out[:, :2] = pts
        return out
    out = pts.copy()
    out[:, 2] = -out[:, 2]
    return out


def board_outline_mm(outline_wh: tuple[float, float]) -> np.ndarray:
    """Board corner points (4,3) at z=0, order (0,0),(W,0),(W,H),(0,H)."""
    w, h = float(outline_wh[0]), float(outline_wh[1])
    return np.array([[0.0, 0.0, 0.0],
                     [w, 0.0, 0.0],
                     [w, h, 0.0],
                     [0.0, h, 0.0]], dtype=np.float64)


def project_wire_exclusion(profile, camera: CameraModel, rvec: np.ndarray,
                           tvec: np.ndarray, *,
                           inset_header_mm: float = 1.5,
                           inset_side_mm: float = 1.0,
                           ) -> list[tuple[float, float]]:
    """Project the board area to exclude from wire segmentation.

    The PCB outline is at z=0, while the useful wire/body boundary is the
    header-pin plane.  Under an oblique camera those two silhouettes have a
    visible parallax offset, so the inset is built in board-mm and projected
    as 3-D points instead of shrinking the already projected PCB polygon.
    """
    width, height = (float(v) for v in profile.board.outline_mm)
    header_z = float(profile.board.header_top_z_mm)
    side = max(0.0, min(float(inset_side_mm), width / 2.0))
    header = max(0.0, min(float(inset_header_mm), height / 2.0))
    pts = np.array([
        [side, header, header_z],
        [width - side, header, header_z],
        [width - side, height - header, header_z],
        [side, height - header, header_z],
    ], dtype=np.float64)
    px = project_points(board_to_vision(pts), camera, rvec, tvec)
    return [(float(x), float(y)) for x, y in px]


def plane_homography(camera: CameraModel, rvec: np.ndarray,
                     tvec: np.ndarray) -> np.ndarray:
    """Homography mapping board-mm plane points (x, y, 1) -> image px.

    H = K @ [r1 | r2 | t].  Valid for z = 0 points only and only when the
    camera distortion is zero (the synthetic camera).
    """
    R, _ = cv2.Rodrigues(np.asarray(rvec, dtype=np.float64).reshape(3, 1))
    t = np.asarray(tvec, dtype=np.float64).reshape(3, 1)
    return camera.K @ np.hstack([R[:, 0:1], R[:, 1:2], t])


def project_points(pts_vision: np.ndarray, camera: CameraModel,
                   rvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    """cv2.projectPoints wrapper: (N,3) vision-frame mm -> (N,2) px."""
    pts = np.ascontiguousarray(np.asarray(pts_vision, np.float64).reshape(-1, 3))
    px, _ = cv2.projectPoints(pts,
                              np.asarray(rvec, np.float64).reshape(3, 1),
                              np.asarray(tvec, np.float64).reshape(3, 1),
                              camera.K, camera.dist)
    return px.reshape(-1, 2)


def project_board(profile, camera: CameraModel, rvec: np.ndarray,
                  tvec: np.ndarray, pin_confidence: float = 1.0,
                  ) -> tuple[list[PinDetection], list[tuple[float, float]]]:
    """Project every profile pin (pos_mm WITH z) + the z=0 board outline.

    Returns (pins, outline_px).  Pin ``visible`` is True when the projected
    point lies inside the frame bounds.
    """
    w, h = camera.size
    pin_pts = np.array([p.pos_mm for p in profile.pins], dtype=np.float64)
    px = project_points(board_to_vision(pin_pts), camera, rvec, tvec)
    pins: list[PinDetection] = []
    for p, (x, y) in zip(profile.pins, px):
        visible = bool(0.0 <= x < w and 0.0 <= y < h)
        pins.append(PinDetection(pin_id=p.id, x=float(x), y=float(y),
                                 confidence=float(pin_confidence),
                                 visible=visible, header=p.header,
                                 index=p.index))
    outline = project_points(board_outline_mm(profile.board.outline_mm),
                             camera, rvec, tvec)
    outline_px = [(float(x), float(y)) for x, y in outline]
    return pins, outline_px
