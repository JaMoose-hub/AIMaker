"""Optional single-photo Pi 5 pin hints using the existing production detector.

No camera, backend session, hardware, or cloud service is started.  Coordinates
are navigation candidates in the EXIF-transposed image, never wiring evidence.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import Any


def _detector_options(repo: Path, model_path: Path | None) -> dict[str, Any]:
    """Read the configured Pi model rather than picking a manifest entry."""
    import yaml

    config_path = repo / "backend" / "config.yaml"
    if not config_path.is_file():
        config_path = repo / "backend" / "config.example.yaml"
    if not config_path.is_file():
        raise FileNotFoundError("Board Vision configuration is unavailable")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    options = config.get("yolo_pose", {}) if isinstance(config, dict) else {}
    if not isinstance(options, dict):
        raise ValueError("Invalid yolo_pose configuration")

    def resolve(value: str | Path) -> Path:
        path = Path(value)
        return (path if path.is_absolute() else config_path.parent / path).resolve()

    preferred = options.get("board_8pt_model_paths", {}).get("raspberry-pi-5")
    preferred_path = resolve(preferred) if preferred else None
    board_models = options.get("board_model_paths", {})
    configured = board_models.get("raspberry-pi-5")
    keypoint_count = 4
    if preferred_path is not None and preferred_path.is_file():
        configured_path = preferred_path
        keypoint_count = 8
    elif configured:
        configured_path = resolve(configured)
    else:
        raise ValueError("No Pi 5 pose model is configured; choose a model explicitly")

    # An override must use the configured pose model's keypoint schema.  A
    # configured eight-point path has a known schema even if it is inactive.
    selected_path = Path(model_path).resolve() if model_path is not None else configured_path
    if model_path is not None and preferred_path is not None and selected_path == preferred_path:
        keypoint_count = 8
    if not selected_path.is_file():
        raise FileNotFoundError(f"Pi 5 pose model is unavailable: {selected_path.name}")
    thresholds = options.get("board_confidence_thresholds", {})
    return {
        "model_path": selected_path,
        "input_size": int(options.get("input_size", 960)),
        "keypoint_count": keypoint_count,
        "confidence_threshold": float(thresholds.get("raspberry-pi-5", options.get("confidence_threshold", 0.45))),
        "keypoint_threshold": float(options.get("keypoint_threshold", 0.35)),
        "nms_iou_threshold": float(options.get("nms_iou_threshold", 0.45)),
    }


def detect_pin_hints(
    image_path: Path,
    *,
    repo: Path | None = None,
    model_path: Path | None = None,
) -> dict[str, Any]:
    """Run one fresh CPU inference and return finite, visible physical-pin hints.

    Imports and model loading are intentionally optional.  Exceptions propagate
    to the caller so its manual photo viewer can remain available without these
    dependencies.  Repeating a photo to satisfy tracking stability is forbidden.
    """
    repo = Path(repo).resolve() if repo is not None else Path(__file__).resolve().parents[2]
    backend = str(repo / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)

    import cv2
    import numpy as np
    from poc import load_photo
    from app.profiles.store import ProfileStore
    from app.vision.yolo_profile_detector import YoloProfileDetector

    options = _detector_options(repo, model_path)
    # Use exactly the viewer's canonical EXIF orientation and ICC-to-sRGB
    # normalization, keeping all candidate coordinates in that pixel space.
    canonical = load_photo(Path(image_path))
    width, height = canonical.size
    frame_bgr = cv2.cvtColor(np.asarray(canonical), cv2.COLOR_RGB2BGR)
    if min(width, height) < 16:
        raise ValueError("Photo is too small for GPIO localization")

    store = ProfileStore(repo / "profiles")
    profile, _ = store.load("raspberry-pi-5")
    detector = YoloProfileDetector(
        **options,
        runtime_backend="opencv",
        use_camera_calibration=False,
    )
    try:
        if not detector.available:
            raise RuntimeError("Pi 5 ONNX model could not be loaded by OpenCV")
        detector.load(profile, store.board_dir("raspberry-pi-5"))
        detector.set_yolo_only(True)
        result = detector.detect(frame_bgr, frame_id=1, ts_ms=0.0)
    finally:
        detector.close()

    hints: list[dict[str, Any]] = []
    for pin in result.pins:
        if pin.header != "J8" or pin.index is None or not pin.visible:
            continue
        x, y, confidence = float(pin.x), float(pin.y), float(pin.confidence)
        if not all(math.isfinite(value) for value in (x, y, confidence)):
            continue
        physical_pin = int(pin.index)
        if not (1 <= physical_pin <= 40 and 0 <= x < width and 0 <= y < height):
            continue
        hints.append({
            "id": f"J8-{physical_pin}",
            "x": x,
            "y": y,
            "physical_pin": physical_pin,
            "verified": False,
            "source": "model_projection",
            "confidence": confidence,
        })
    hints.sort(key=lambda item: item["physical_pin"])
    outline = None
    if result.outline_px is not None:
        candidate_outline = [[float(x), float(y)] for x, y in result.outline_px]
        if all(math.isfinite(value) for point in candidate_outline for value in point):
            outline = candidate_outline
    confidence = float(result.confidence)
    return {
        "pin_hints": hints,
        "detection": {
            "tracking": result.tracking,
            "confidence": confidence if math.isfinite(confidence) else None,
            "model_filename": options["model_path"].name,
            "runtime_backend": "opencv",
            "input_size": options["input_size"],
            "keypoint_count": options["keypoint_count"],
            "image_size": [width, height],
            "coordinate_system": "exif_transposed_pixels",
            "outline": outline,
            "pose_path": result.pose_path,
            "warning": "候選位置，未驗證接線",
            "error": None,
        },
    }
