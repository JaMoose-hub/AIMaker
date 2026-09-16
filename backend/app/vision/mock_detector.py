"""MockDetector: ground-truth / canned-trajectory BoardDetector.

Two modes:
- with a SyntheticScene: detect() returns ``scene.truth_at(ts_ms / 1000,
  frame_id)`` unmodified — the exact ground truth for the frame the capture
  layer rendered at the same monotonic timestamp (shared-clock contract).
- without a scene: a canned smooth trajectory (the same math the synthetic
  scene uses) is projected over the profile pin table, with a tiny seeded
  deterministic confidence wobble for realism.  No file access, no GUI —
  only the profile object is needed.

``animate`` (no-scene mode only) gates the canned trajectory. It defaults to
True (existing demo behavior, e.g. showcasing the UI with no camera at all).
The factory sets it False when this detector is standing in for a real
device/window camera whose board has never been calibrated: faking a
"locked" pose there would draw an animated overlay disconnected from the
real, stationary board in frame, and would starve CalibratePanel's manual
alignment guide (app/../frontend CalibratePanel.tsx only falls back to its
fixed alignment rectangle when tracking != "locked"). With animate=False,
detect() reports the same honest "searching" result used when no profile is
loaded at all — see app/vision/interface.py's no-guessing contract.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from app.vision.camera_model import default_camera, project_board, project_wire_exclusion
from app.vision.interface import DetectionResult
from app.vision.synthetic import SyntheticScene, trajectory_pose

__all__ = ["MockDetector"]


class MockDetector:
    """BoardDetector implementation returning synthetic ground truth."""

    def __init__(self, scene: SyntheticScene | None = None,
                 animate: bool = True) -> None:
        self._scene = scene
        self._animate = animate
        self._profile = None
        self._camera = None

    # -- BoardDetector protocol -------------------------------------------------

    def load(self, profile, profile_dir: Path) -> None:
        self._profile = profile

    def detect(self, frame_bgr: np.ndarray, frame_id: int,
               ts_ms: float) -> DetectionResult:
        t_s = float(ts_ms) / 1000.0
        if self._scene is not None:
            return self._scene.truth_at(t_s, frame_id)
        if self._profile is None:
            return DetectionResult(board_id="unknown", frame_id=int(frame_id),
                                   ts_ms=float(ts_ms), tracking="searching",
                                   confidence=0.0, pins=[])
        if not self._animate:
            return DetectionResult(board_id=self._profile.board.id,
                                   frame_id=int(frame_id), ts_ms=float(ts_ms),
                                   tracking="searching", confidence=0.0, pins=[])
        return self._canned(frame_bgr, frame_id, ts_ms, t_s)

    def close(self) -> None:
        self._scene = None

    # -- canned trajectory (no scene) ---------------------------------------------

    def _canned(self, frame_bgr: np.ndarray, frame_id: int, ts_ms: float,
                t_s: float) -> DetectionResult:
        video_size = ((frame_bgr.shape[1], frame_bgr.shape[0])
                      if frame_bgr is not None and hasattr(frame_bgr, "shape")
                      else (1280, 720))
        if self._camera is None or self._camera.size != video_size:
            self._camera = default_camera(video_size)
        rvec, tvec = trajectory_pose(t_s, self._profile.board.outline_mm)
        # Deterministic, gentle confidence wobble (cosmetic realism only).
        conf = 0.93 + 0.05 * math.sin(0.37 * int(frame_id))
        pins, outline = project_board(self._profile, self._camera, rvec,
                                      tvec, pin_confidence=conf)
        wire_exclusion = project_wire_exclusion(
            self._profile, self._camera, rvec, tvec)
        return DetectionResult(
            board_id=self._profile.board.id, frame_id=int(frame_id),
            ts_ms=float(ts_ms), tracking="locked", confidence=float(conf),
            pins=pins, outline_px=outline,
            wire_exclusion_px=wire_exclusion,
            rvec=[float(v) for v in np.asarray(rvec).reshape(3)],
            tvec=[float(v) for v in np.asarray(tvec).reshape(3)])
