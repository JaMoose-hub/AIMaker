"""Detector factory — the single construction seam the backend imports.

    create_detector(kind, profile, profile_dir, scene=None) -> BoardDetector

- kind "mock" with a scene: detector replays the scene's ground truth.
- kind "mock" without a scene: canned smooth trajectory over the profile,
  unless mock_animate=False (main.py passes this for a real device/window
  camera whose board has no calibrated reference yet), in which case it
  honestly reports "searching" instead of a fabricated locked pose.
- kind "pipeline": real CV pipeline (PoseTracker).
- kind "hybrid": YOLO four-corner localization + profile geometry, with the
  real feature pipeline as a fail-safe fallback.

The returned detector is already load()ed; calling load() again is
idempotent and harmless.
"""
from __future__ import annotations

from pathlib import Path

from app.vision.interface import BoardDetector
from app.vision.mock_detector import MockDetector
from app.vision.pipeline_detector import PipelineDetector
from app.vision.pose_tracker import TrackerParams
from app.vision.yolo_profile_detector import HybridBoardDetector, YoloProfileDetector

__all__ = ["create_detector"]


def create_detector(kind: str, profile, profile_dir: Path,
                    scene=None,
                    mock_animate: bool = True,
                    horizontal_fov_deg: float | None = None,
                    yolo_model_path: Path | str | None = None,
                    yolo_reference_recovery_model_path: Path | str | None = None,
                    camera_calibration_path: Path | str | None = None,
                    use_camera_calibration: bool = True,
                    yolo_keypoint_count: int = 4,
                    yolo_input_size: int = 960,
                    yolo_confidence_threshold: float = 0.45,
                    yolo_keypoint_threshold: float = 0.35,
                    yolo_nms_iou_threshold: float = 0.45,
                    yolo_max_reprojection_error_px: float = 8.0,
                    yolo_stability_deadband_px: float = 2.00,
                    yolo_deadband_exit_confirm_frames: int = 5,
                    yolo_jump_threshold_fraction: float = 0.025,
                    yolo_jump_confirm_frames: int = 3,
                    yolo_occlusion_hold_frames: int = 60,
                    yolo_occlusion_visibility_ratio: float = 0.80,
                    yolo_visibility_warmup_frames: int = 5,
                    yolo_runtime_backend: str = "opencv",
                    yolo_directml_device_id: int = 0,
                    yolo_cuda_device_id: int = 0) -> BoardDetector:
    kind = (kind or "").strip().lower()
    if kind == "mock":
        detector: BoardDetector = MockDetector(scene=scene, animate=mock_animate)
    elif kind == "pipeline":
        detector = PipelineDetector(
            horizontal_fov_deg=horizontal_fov_deg,
            camera_calibration_path=camera_calibration_path,
            use_camera_calibration=use_camera_calibration,
        )
    elif kind == "hybrid":
        if yolo_model_path is None:
            raise ValueError("hybrid detector requires yolo_model_path")
        detector = HybridBoardDetector(
            YoloProfileDetector(
                model_path=yolo_model_path,
                reference_recovery_model_path=yolo_reference_recovery_model_path,
                camera_calibration_path=camera_calibration_path,
                use_camera_calibration=use_camera_calibration,
                keypoint_count=yolo_keypoint_count,
                horizontal_fov_deg=horizontal_fov_deg,
                input_size=yolo_input_size,
                confidence_threshold=yolo_confidence_threshold,
                keypoint_threshold=yolo_keypoint_threshold,
                nms_iou_threshold=yolo_nms_iou_threshold,
                max_reprojection_error_px=yolo_max_reprojection_error_px,
                stability_deadband_px=yolo_stability_deadband_px,
                deadband_exit_confirm_frames=yolo_deadband_exit_confirm_frames,
                jump_threshold_fraction=yolo_jump_threshold_fraction,
                jump_confirm_frames=yolo_jump_confirm_frames,
                occlusion_hold_frames=yolo_occlusion_hold_frames,
                occlusion_visibility_ratio=yolo_occlusion_visibility_ratio,
                visibility_warmup_frames=yolo_visibility_warmup_frames,
                runtime_backend=yolo_runtime_backend,
                directml_device_id=yolo_directml_device_id,
                cuda_device_id=yolo_cuda_device_id,
            ),
            PipelineDetector(
                # Pi is green. A blue-blob crop can select HC/TFT instead,
                # starving SIFT recovery while the board is being moved.
                # Preserve the original matching/geometry thresholds and
                # retry budget; Eye's direct YOLO path bypasses this fallback.
                params=TrackerParams(color_roi_enabled=False, sift_frame_max_px=960)
                if profile.board.id == 'raspberry-pi-5' else None,
                horizontal_fov_deg=horizontal_fov_deg,
                camera_calibration_path=camera_calibration_path,
                use_camera_calibration=use_camera_calibration,
            ),
        )
    else:
        raise ValueError(
            f"unknown detector kind {kind!r} (expected 'mock', 'pipeline', or 'hybrid')")
    detector.load(profile, Path(profile_dir))
    return detector
