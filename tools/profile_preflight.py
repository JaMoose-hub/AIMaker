"""Check whether a board profile is suitable for a physical accuracy gate.

This is deliberately a read-only diagnostic.  It does not rewrite
``board.json`` or feature caches.  A profile can be valid for synthetic tests
and still be unsuitable for a physical gate when the reference is too small
or camera intrinsics have not been calibrated.

Example::

    backend\\.venv\\Scripts\\python.exe tools\\profile_preflight.py --json
    backend\\.venv\\Scripts\\python.exe tools\\profile_preflight.py --strict
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.profiles.models import BoardProfile  # noqa: E402
from calibrate_camera import (  # noqa: E402
    DEFAULT_MAX_RMS_PX,
    DEFAULT_MAX_VIEW_RMS_PX,
    DEFAULT_MIN_COVERAGE,
)
from scale_quality import (  # noqa: E402
    DEFAULT_MIN_PIN_PITCH_PX,
    DEFAULT_MIN_PX_PER_MM,
    reference_scale_report,
)

DEFAULT_MIN_PITCH_PX = DEFAULT_MIN_PIN_PITCH_PX
DEFAULT_MIN_PX_PER_MM = DEFAULT_MIN_PX_PER_MM


def _scale_status(
    pitch_px: float,
    *,
    min_pitch_px: float = DEFAULT_MIN_PITCH_PX,
    min_px_per_mm: float = DEFAULT_MIN_PX_PER_MM,
) -> str:
    px_per_mm = float(pitch_px) / 2.54 if pitch_px > 0 else 0.0
    if pitch_px < float(min_pitch_px) or px_per_mm < float(min_px_per_mm):
        return "reject"
    return "ok"


def _inspect_camera_quality(camera_path: Path) -> dict[str, Any]:
    """Read calibration quality metadata without opening the camera."""
    if not camera_path.is_file():
        return {
            "status": "missing",
            "quality_status": None,
            "rms_reprojection_error_px": None,
            "max_view_rms_px": None,
            "coverage_fraction": None,
            "issues": [],
        }
    try:
        raw = json.loads(camera_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "status": "reject",
            "quality_status": None,
            "rms_reprojection_error_px": None,
            "max_view_rms_px": None,
            "coverage_fraction": None,
            "issues": [f"camera.json is not valid JSON ({type(exc).__name__})"],
        }
    if not isinstance(raw, dict):
        return {
            "status": "reject",
            "quality_status": None,
            "rms_reprojection_error_px": None,
            "max_view_rms_px": None,
            "coverage_fraction": None,
            "issues": ["camera.json root must be an object"],
        }

    quality_status = raw.get("quality_status")
    issues: list[str] = []
    if quality_status != "ok":
        if quality_status is None:
            issues.append("camera.json has no quality_status; rerun calibrate_camera.py")
        else:
            issues.append(f"camera calibration quality_status={quality_status!r}")

    values: dict[str, float | None] = {}
    for key in ("rms_reprojection_error_px", "max_view_rms_px", "coverage_fraction"):
        value = raw.get(key)
        try:
            values[key] = float(value)
        except (TypeError, ValueError):
            values[key] = None
            issues.append(f"camera.json missing numeric {key}")

    rms = values["rms_reprojection_error_px"]
    max_view = values["max_view_rms_px"]
    coverage = values["coverage_fraction"]
    if rms is not None and rms > DEFAULT_MAX_RMS_PX:
        issues.append(f"camera RMS {rms:.3f}px > {DEFAULT_MAX_RMS_PX:.3f}px")
    if max_view is not None and max_view > DEFAULT_MAX_VIEW_RMS_PX:
        issues.append(
            f"camera worst-view RMS {max_view:.3f}px > {DEFAULT_MAX_VIEW_RMS_PX:.3f}px"
        )
    if coverage is not None and coverage < DEFAULT_MIN_COVERAGE:
        issues.append(
            f"camera corner coverage {coverage:.3f} < {DEFAULT_MIN_COVERAGE:.3f}"
        )
    return {
        "status": "ok" if not issues else "reject",
        "quality_status": quality_status,
        "rms_reprojection_error_px": rms,
        "max_view_rms_px": max_view,
        "coverage_fraction": coverage,
        "issues": issues,
    }


def inspect_profile(
    board_json: Path,
    *,
    min_pitch_px: float = DEFAULT_MIN_PITCH_PX,
    min_px_per_mm: float = DEFAULT_MIN_PX_PER_MM,
) -> dict[str, Any]:
    """Return a JSON-safe, read-only physical-gate preflight report."""
    payload = json.loads(board_json.read_text(encoding="utf-8"))
    profile = BoardProfile.model_validate(payload)
    board_dir = board_json.parent
    reference_path = board_dir / profile.reference.image
    reference = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
    if reference is None:
        raise RuntimeError(f"reference image not readable: {reference_path}")

    pin_geometry = [
        (pin.header, pin.index, pin.pos_mm[0], pin.pos_mm[1])
        for pin in profile.pins
    ]
    scale = reference_scale_report(
        profile.reference.mm_to_px,
        pin_geometry,
        min_pin_pitch_px=min_pitch_px,
        min_px_per_mm=min_px_per_mm,
    )
    pitch_px = float(scale["pitch_px"])
    px_per_mm = float(scale["px_per_mm"])
    camera_path = board_dir / "camera.json"
    camera_quality = _inspect_camera_quality(camera_path)
    features_path = board_dir / "features.npz"
    feature_count = 0
    if features_path.is_file():
        try:
            with np.load(features_path) as features:
                feature_count = int(len(features["xy_mm"]))
        except Exception:
            feature_count = 0

    warnings: list[str] = []
    scale_status = str(scale["status"])
    if scale_status == "reject":
        warnings.append(
            f"pin pitch {pitch_px:.2f}px ({px_per_mm:.2f}px/mm) is below "
            f"the physical target {min_px_per_mm:.1f}px/mm"
        )
    if not camera_path.is_file():
        warnings.append("camera.json is absent; pose uses the FOV fallback")
    elif camera_quality["status"] != "ok":
        warnings.extend(str(item) for item in camera_quality["issues"])
    if feature_count < 100:
        warnings.append(f"feature cache is missing or too small ({feature_count} features)")
    reference_size = [int(reference.shape[1]), int(reference.shape[0])]
    declared_size = [int(profile.reference.width_px), int(profile.reference.height_px)]
    if reference_size != declared_size:
        warnings.append(
            f"reference size {reference_size} differs from profile declaration {declared_size}"
        )
    return {
        "board_id": profile.board.id,
        "board_json": str(board_json.resolve()),
        "reference_image": str(reference_path.resolve()),
        "reference_size": reference_size,
        "declared_reference_size": declared_size,
        "pin_count": len(profile.pins),
        "pitch_px": round(pitch_px, 4),
        "px_per_mm": round(px_per_mm, 4),
        "scale_status": scale_status,
        "min_pitch_px": float(min_pitch_px),
        "min_px_per_mm": float(min_px_per_mm),
        "camera_calibrated": camera_path.is_file(),
        "camera_quality_ok": camera_quality["status"] == "ok",
        "camera_quality_status": camera_quality["quality_status"],
        "camera_rms_reprojection_error_px": camera_quality["rms_reprojection_error_px"],
        "camera_max_view_rms_px": camera_quality["max_view_rms_px"],
        "camera_coverage_fraction": camera_quality["coverage_fraction"],
        "camera_json": str(camera_path.resolve()) if camera_path.is_file() else None,
        "feature_count": feature_count,
        "physical_gate_ready": (
            scale_status == "ok"
            and camera_quality["status"] == "ok"
            and feature_count >= 100
        ),
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board-json", type=Path,
        default=ROOT / "profiles" / "boards" / "arduino-uno-q" / "board.json",
    )
    parser.add_argument("--min-pitch-px", type=float, default=DEFAULT_MIN_PITCH_PX)
    parser.add_argument("--min-px-per-mm", type=float, default=DEFAULT_MIN_PX_PER_MM)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 2 unless the profile is ready for the physical accuracy gate",
    )
    args = parser.parse_args()
    if args.min_pitch_px <= 0 or args.min_px_per_mm <= 0:
        parser.error("minimum scale thresholds must be positive")
    try:
        report = inspect_profile(
            args.board_json.resolve(),
            min_pitch_px=args.min_pitch_px,
            min_px_per_mm=args.min_px_per_mm,
        )
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"profile preflight failed: {exc}") from exc
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"board: {report['board_id']}")
        print(f"reference: {report['reference_size'][0]}x{report['reference_size'][1]}")
        print(f"pin pitch: {report['pitch_px']:.2f}px ({report['px_per_mm']:.2f}px/mm)")
        print(f"scale: {report['scale_status']}")
        print(f"camera calibrated: {report['camera_calibrated']}")
        print(f"camera quality: {report['camera_quality_status'] or 'missing'}")
        print(f"features: {report['feature_count']}")
        print(f"physical gate ready: {report['physical_gate_ready']}")
        for warning in report["warnings"]:
            print(f"WARNING: {warning}")
    if args.strict and not report["physical_gate_ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
