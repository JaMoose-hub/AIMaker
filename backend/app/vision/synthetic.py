"""Synthetic camera scene: desk background + board rendered under a smooth
time-varying 6-DoF pose, plus exact ground truth for the same instant.

Shared contract (capture layer + MockDetector):
- capture stamps frames with ts_ms = time.monotonic() * 1000 and calls
  ``frame_at(t_s = ts_ms / 1000)``;
- MockDetector receives the same ts_ms in detect() and calls
  ``truth_at(ts_ms / 1000, frame_id)`` — both sides derive from the same
  clock so overlay and video agree.

Rendering/ground-truth consistency note: the board is drawn by warping the
*orthographic* reference image (a plane at z=0), so the drawn pin holes are
planar, while ``truth_at`` projects the profile's 3D pin positions with
z = header_top_z_mm (~8.5 mm above the PCB). At the <= 12 degree tilts of
the built-in trajectory the difference is small, and the truth is the
physically-correct answer — do NOT change truth to match the drawn holes.

Everything is deterministic: same (profile, video_size, seed, t_s) => same
frame and same truth.
"""
from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np

from app.vision.camera_model import (
    CameraModel,
    default_camera,
    plane_homography,
    project_board,
    project_wire_exclusion,
)
from app.vision.interface import DetectionResult

__all__ = ["trajectory_pose", "SyntheticScene"]


# ---------------------------------------------------------------------------
# Canned smooth trajectory (also used by MockDetector without a scene).
# All terms are smooth sinusoids of t; no files or state needed.
# ---------------------------------------------------------------------------

_YAW_PERIOD_S = 60.0      # full 360 degree spin
_TILT_PERIOD_S = 17.0     # tilt amplitude oscillates 0..12 degrees
_TILT_AXIS_PERIOD_S = 23.0
_Z0_MM = 200.0            # nominal camera distance


def _rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rot_axis(axis: np.ndarray, a: float) -> np.ndarray:
    r, _ = cv2.Rodrigues(np.asarray(axis, np.float64).reshape(3) * a)
    return r


def trajectory_pose(t_s: float, board_wh_mm: tuple[float, float],
                    yaw0_deg: float = 0.0
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Ground-truth (rvec, tvec) in the vision frame at time t_s (seconds).

    Gentle xy/z drift + full 360-degree yaw over ~60 s + tilt oscillating
    between 0 and 12 degrees about a slowly precessing horizontal axis.
    The board centre stays near the image centre for any camera made by
    ``camera_model.default_camera`` (the trajectory is intrinsics-free).
    """
    t = float(t_s)
    yaw = math.radians(yaw0_deg) + 2.0 * math.pi * t / _YAW_PERIOD_S
    tilt = math.radians(6.0) * (1.0 - math.cos(2.0 * math.pi * t / _TILT_PERIOD_S))
    phi = 2.0 * math.pi * t / _TILT_AXIS_PERIOD_S
    tilt_axis = np.array([math.cos(phi), math.sin(phi), 0.0])

    R = _rot_axis(tilt_axis, tilt) @ _rot_z(yaw)

    # Where the board centre sits in camera coordinates (mm).
    cx = 15.0 * math.sin(2.0 * math.pi * t / 29.0)
    cy = 8.0 * math.sin(2.0 * math.pi * t / 31.0 + 1.0)
    cz = _Z0_MM + 15.0 * math.sin(2.0 * math.pi * t / 37.0)
    centre_cam = np.array([cx, cy, cz])

    centre_board = np.array([board_wh_mm[0] / 2.0, board_wh_mm[1] / 2.0, 0.0])
    tvec = centre_cam - R @ centre_board
    rvec, _ = cv2.Rodrigues(R)
    return rvec.reshape(3), tvec.reshape(3)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------

class SyntheticScene:
    """Deterministic synthetic desk + board scene (see module docstring).

    Extra keyword arguments beyond the shared contract:
    - yaw0_deg: initial in-plane rotation of the trajectory (tests use 180).
    - seed: RNG seed for the desk background.
    """

    def __init__(self, profile, profile_dir: Path,
                 video_size: tuple[int, int], *, yaw0_deg: float = 0.0,
                 seed: int = 1234,
                 horizontal_fov_deg: float | None = None) -> None:
        self.profile = profile
        self.video_size = (int(video_size[0]), int(video_size[1]))
        self.camera: CameraModel = default_camera(
            self.video_size, horizontal_fov_deg=horizontal_fov_deg
        )
        self.yaw0_deg = float(yaw0_deg)

        ref_path = Path(profile_dir) / profile.reference.image
        ref = cv2.imread(str(ref_path), cv2.IMREAD_COLOR)
        if ref is None:
            raise FileNotFoundError(f"reference image not found: {ref_path}")

        mm_to_px = np.asarray(profile.reference.mm_to_px, dtype=np.float64)
        if mm_to_px.shape != (3, 3):
            raise ValueError("reference.mm_to_px must be 3x3")

        # Pre-shrink the reference towards ~2x the expected on-screen scale
        # (INTER_AREA once) so per-frame warps do not alias.
        ref_px_per_mm = float(np.linalg.norm(mm_to_px[:2, 0]))
        screen_px_per_mm = float(self.camera.K[0, 0]) / _Z0_MM
        s = min(1.0, 2.0 * screen_px_per_mm / max(ref_px_per_mm, 1e-9))
        if s < 0.999:
            ref = cv2.resize(ref, None, fx=s, fy=s,
                             interpolation=cv2.INTER_AREA)
            mm_to_px = np.diag([s, s, 1.0]) @ mm_to_px
        self._ref = ref
        self._px_to_mm = np.linalg.inv(mm_to_px)
        self._background = self._make_background(seed)

    # -- pose ---------------------------------------------------------------

    def pose_at(self, t_s: float) -> tuple[np.ndarray, np.ndarray]:
        return trajectory_pose(t_s, self.profile.board.outline_mm,
                               yaw0_deg=self.yaw0_deg)

    def homography_at(self, t_s: float) -> np.ndarray:
        """Board-mm plane -> video px homography for the pose at t_s."""
        rvec, tvec = self.pose_at(t_s)
        return plane_homography(self.camera, rvec, tvec)

    # -- rendering ----------------------------------------------------------

    def _make_background(self, seed: int) -> np.ndarray:
        w, h = self.video_size
        rng = np.random.default_rng(seed)
        yy = np.linspace(0.0, 1.0, h)[:, None]
        xx = np.linspace(0.0, 1.0, w)[None, :]
        base = 95.0 + 30.0 * (0.6 * yy + 0.4 * xx)          # soft gradient
        bg = np.stack([base * 0.92, base * 1.0, base * 1.06], axis=-1)
        bg += rng.normal(0.0, 3.0, size=bg.shape)            # desk grain
        bg = np.clip(bg, 0, 255).astype(np.uint8)
        # A few fake desk items for realism (deterministic placement).
        cv2.rectangle(bg, (int(w * 0.04), int(h * 0.62)),
                      (int(w * 0.22), int(h * 0.95)), (196, 203, 208), -1)
        cv2.rectangle(bg, (int(w * 0.04), int(h * 0.62)),
                      (int(w * 0.22), int(h * 0.95)), (150, 155, 160), 3)
        cv2.circle(bg, (int(w * 0.88), int(h * 0.18)), int(h * 0.09),
                   (60, 90, 140), -1)                        # mug
        cv2.circle(bg, (int(w * 0.88), int(h * 0.18)), int(h * 0.06),
                   (35, 55, 90), -1)
        pen = np.array([[w * 0.70, h * 0.86], [w * 0.94, h * 0.78],
                        [w * 0.945, h * 0.80], [w * 0.705, h * 0.88]],
                       dtype=np.int32)
        cv2.fillPoly(bg, [pen], (70, 70, 200))               # pen
        bg = cv2.GaussianBlur(bg, (3, 3), 0)
        return bg

    def frame_at(self, t_s: float) -> np.ndarray:
        """BGR uint8 frame (H, W, 3) of video_size at time t_s."""
        w, h = self.video_size
        H_total = self.homography_at(t_s) @ self._px_to_mm
        warped = cv2.warpPerspective(self._ref, H_total, (w, h),
                                     flags=cv2.INTER_LINEAR)
        mask = np.full(self._ref.shape[:2], 255, dtype=np.uint8)
        mask = cv2.warpPerspective(mask, H_total, (w, h),
                                   flags=cv2.INTER_LINEAR)
        alpha = (mask.astype(np.float32) / 255.0)[:, :, None]
        out = (self._background.astype(np.float32) * (1.0 - alpha)
               + warped.astype(np.float32) * alpha)
        return np.clip(out, 0, 255).astype(np.uint8)

    # -- ground truth ---------------------------------------------------------

    def truth_at(self, t_s: float, frame_id: int) -> DetectionResult:
        """Exact DetectionResult ground truth for the same t_s as frame_at."""
        rvec, tvec = self.pose_at(t_s)
        pins, outline = project_board(self.profile, self.camera, rvec, tvec,
                                      pin_confidence=1.0)
        wire_exclusion = project_wire_exclusion(
            self.profile, self.camera, rvec, tvec)
        return DetectionResult(
            board_id=self.profile.board.id,
            frame_id=int(frame_id),
            ts_ms=float(t_s) * 1000.0,
            tracking="locked",
            confidence=1.0,
            pins=pins,
            outline_px=outline,
            wire_exclusion_px=wire_exclusion,
            rvec=[float(v) for v in np.asarray(rvec).reshape(3)],
            tvec=[float(v) for v in np.asarray(tvec).reshape(3)],
        )
