"""The seam between the CV pipeline and the rest of the backend.

Contract rules (do not break):
- The backend only talks to detectors through `BoardDetector`.
- `detect()` is called from the vision worker thread with the latest frame;
  it must never block for long (>100 ms) and must always return a
  `DetectionResult` (use tracking="searching" with empty pins when the board
  is not found - never return None).
- Pin coordinates are in *source video pixel* space (same space as the MJPEG
  stream), origin top-left.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

TrackingState = Literal["searching", "locked", "stale"]
PoseMode = Literal["pnp_8pt", "hybrid_4pt", "feature_fallback"]


@dataclass
class PinDetection:
    pin_id: str
    x: float
    y: float
    confidence: float
    visible: bool = True  # False when projected outside the frame
    # Internal metadata used by the wire endpoint lattice.  These fields are
    # intentionally omitted from the public WS serialization.
    header: str | None = None
    index: int | None = None


@dataclass
class DetectionResult:
    board_id: str
    frame_id: int
    ts_ms: float
    tracking: TrackingState
    confidence: float  # overall pose confidence 0..1
    pins: list[PinDetection] = field(default_factory=list)
    # Board outline quad in video px, order: the four board corners
    # (0,0), (W,0), (W,H), (0,H) in board-mm space.
    outline_px: list[tuple[float, float]] | None = None
    # 6-DoF pose (OpenCV rvec/tvec, board-mm -> camera), for debug/telemetry.
    rvec: list[float] | None = None
    tvec: list[float] | None = None
    # Projected exclusion polygon at header-pin height for wire segmentation.
    wire_exclusion_px: list[tuple[float, float]] | None = None
    # Pose-quality evidence kept separate from the headline confidence.  The
    # latter is a compact score; these values make it possible to diagnose a
    # high score that is supported by too few or too-local image features.
    pose_path: str | None = None  # "detect" | "track" | "stale" | "yolo"
    pose_inliers: int | None = None
    pose_reproj_px: float | None = None
    pose_inlier_board_area_frac: float | None = None
    # YOLO/Profile temporal guard diagnostics. These are additive telemetry:
    # they never change pin semantics, but explain why geometry was frozen.
    pose_stability_state: str | None = None
    pose_motion_px: float | None = None
    # Independent local-image / final-pin diagnostics (not electrical proof).
    pose_pin_motion_px: float | None = None
    pose_image_motion_px: float | None = None
    pose_image_support: int | None = None
    pose_visible_fraction: float | None = None
    pose_mode: PoseMode | None = None
    pose_landmarks_visible: int | None = None
    # Same-frame model quad before temporal holding; display-flow corroboration
    # only. Never use this as a verified pin/wiring detection.
    motion_outline_px: list[tuple[float, float]] | None = None
    # Fresh, strong J8 AND board-context evidence on this exact source frame.
    # Not inherited by held results and never electrical verification.
    pose_image_confirmed: bool = False
    # Independent fresh object box. Never read by pin/wiring verification.
    body: dict | None = None
    reference_evidence: dict | None = None


class BoardDetector(Protocol):
    """Implemented by PipelineDetector (real CV) and MockDetector (replay)."""

    def load(self, profile: "object", profile_dir: Path) -> None:
        """Load board profile + reference assets. Called once before detect()."""
        ...

    def detect(self, frame_bgr: np.ndarray, frame_id: int, ts_ms: float) -> DetectionResult:
        ...

    def close(self) -> None:
        ...
