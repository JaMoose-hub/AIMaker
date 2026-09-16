"""PipelineDetector: the real-CV BoardDetector implementation.

load() reads the reference image (profile_dir / profile.reference.image),
an optional precomputed feature cache (profile_dir / features.npz with
arrays ``xy_mm`` (N,2) float and ``desc`` (N,32) uint8), an optional feature
mask (profile.reference.feature_mask, 255 = usable), and optional camera
intrinsics (profile_dir / camera.json, see camera_model.py).

detect() delegates to PoseTracker and never raises: any internal error is
swallowed and reported as tracking="searching" with empty pins, per the
interface.py contract.
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from app.vision.interface import DetectionResult
from app.vision.pose_tracker import PoseTracker, TrackerParams

log = logging.getLogger(__name__)

__all__ = ["PipelineDetector"]

FEATURE_CACHE_NAME = "features.npz"
CAMERA_JSON_NAME = "camera.json"


class PipelineDetector:
    """BoardDetector implementation backed by PoseTracker."""

    def __init__(self, params: TrackerParams | None = None,
                 horizontal_fov_deg: float | None = None,
                 camera_calibration_path: Path | str | None = None,
                 use_camera_calibration: bool = True) -> None:
        self._params = params
        self._use_camera_calibration = bool(use_camera_calibration)
        self._horizontal_fov_deg = horizontal_fov_deg if use_camera_calibration else None
        self._camera_calibration_path = (
            Path(camera_calibration_path)
            if camera_calibration_path is not None
            else None
        )
        self._tracker: PoseTracker | None = None
        self._profile = None
        self._profile_dir: Path | None = None

    # -- BoardDetector protocol -------------------------------------------------

    def load(self, profile, profile_dir: Path) -> None:
        profile_dir = Path(profile_dir)
        self._profile = profile
        self._profile_dir = profile_dir

        ref_path = profile_dir / profile.reference.image
        reference = cv2.imread(str(ref_path), cv2.IMREAD_COLOR)
        if reference is None:
            raise FileNotFoundError(f"reference image not found: {ref_path}")

        feature_mask = None
        if profile.reference.feature_mask:
            mask_path = profile_dir / profile.reference.feature_mask
            feature_mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
            if feature_mask is None:
                log.warning("feature mask %s unreadable; ignoring", mask_path)

        selected_camera = self._selected_camera()
        self._tracker = PoseTracker(
            profile=profile,
            reference_bgr=reference,
            mm_to_px=np.asarray(profile.reference.mm_to_px, dtype=np.float64),
            video_size=None,  # inferred from the first frame
            feature_mask=feature_mask,
            camera_json=selected_camera,
            horizontal_fov_deg=self._horizontal_fov_deg,
            params=self._params,
        )

        cache = profile_dir / FEATURE_CACHE_NAME
        if cache.is_file():
            try:
                data = np.load(cache)
                self._tracker.set_reference_features(data["xy_mm"],
                                                     data["desc"])
                log.info("loaded %d cached reference features from %s",
                         len(data["xy_mm"]), cache)
            except Exception as exc:
                # One clean line, no traceback: a stale/foreign cache is
                # expected and the tracker recomputes from the reference.
                log.warning("feature cache %s unusable (%s: %s); recomputing "
                            "from reference image", cache,
                            type(exc).__name__, exc)

    def detect(self, frame_bgr: np.ndarray, frame_id: int,
               ts_ms: float) -> DetectionResult:
        if self._tracker is None:
            return self._searching(frame_id, ts_ms)
        try:
            return self._tracker.process(frame_bgr, frame_id, ts_ms)
        except Exception:
            log.exception("pipeline detect failed on frame %d", frame_id)
            return self._searching(frame_id, ts_ms)

    def close(self) -> None:
        self._tracker = None

    def _selected_camera(self) -> Path | None:
        if not self._use_camera_calibration:
            return None
        shared = self._camera_calibration_path
        if shared is not None and shared.is_file():
            return shared
        local = self._profile_dir / CAMERA_JSON_NAME if self._profile_dir else None
        return local if local is not None and local.is_file() else None

    def reset_for_camera(self, *, horizontal_fov_deg: float | None = None,
                         camera_calibration_path: Path | str | None = None,
                         use_camera_calibration: bool = True) -> None:
        """Clear source-dependent tracking while retaining reference features.

        The owning vision worker must be stopped or hold its detector lock.
        """
        self._use_camera_calibration = bool(use_camera_calibration)
        self._horizontal_fov_deg = horizontal_fov_deg if use_camera_calibration else None
        self._camera_calibration_path = Path(camera_calibration_path) if camera_calibration_path is not None else None
        if self._tracker is not None:
            self._tracker.reset_for_camera(
                camera_json=self._selected_camera(),
                horizontal_fov_deg=self._horizontal_fov_deg,
            )

    # -- helpers ------------------------------------------------------------------

    def _searching(self, frame_id: int, ts_ms: float) -> DetectionResult:
        board_id = self._profile.board.id if self._profile else "unknown"
        return DetectionResult(board_id=board_id, frame_id=int(frame_id),
                               ts_ms=float(ts_ms), tracking="searching",
                               confidence=0.0, pins=[], outline_px=None)

    @property
    def tracker(self) -> PoseTracker | None:
        """Exposed for tests/telemetry (timing, last path)."""
        return self._tracker
