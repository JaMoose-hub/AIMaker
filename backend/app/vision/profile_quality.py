"""Read-only runtime quality checks for a board profile.

The detector can run with a synthetic or legacy profile, but that does not
mean the profile is ready for a physical accuracy claim.  Keep this check
separate from detection so the API and UI can make that distinction explicit.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from app.vision.reference_calibration import reference_scale_report

DEFAULT_MIN_FEATURES = 100
DEFAULT_MAX_RMS_PX = 1.2
DEFAULT_MAX_VIEW_RMS_PX = 2.5
DEFAULT_MIN_COVERAGE = 0.30


def _camera_quality(camera_path: Path) -> dict[str, Any]:
    if not camera_path.is_file():
        return {
            "camera_calibrated": False,
            "camera_quality_ok": False,
            "camera_quality_status": None,
            "camera_rms_reprojection_error_px": None,
            "camera_max_view_rms_px": None,
            "camera_coverage_fraction": None,
            "issues": ["camera.json is absent; pose uses the FOV fallback"],
        }

    issues: list[str] = []
    try:
        raw = json.loads(camera_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "camera_calibrated": True,
            "camera_quality_ok": False,
            "camera_quality_status": None,
            "camera_rms_reprojection_error_px": None,
            "camera_max_view_rms_px": None,
            "camera_coverage_fraction": None,
            "issues": [f"camera.json is not valid JSON ({type(exc).__name__})"],
        }

    if not isinstance(raw, dict):
        return {
            "camera_calibrated": True,
            "camera_quality_ok": False,
            "camera_quality_status": None,
            "camera_rms_reprojection_error_px": None,
            "camera_max_view_rms_px": None,
            "camera_coverage_fraction": None,
            "issues": ["camera.json root must be an object"],
        }

    quality_status = raw.get("quality_status")
    if quality_status != "ok":
        if quality_status is None:
            issues.append("camera.json has no quality_status; rerun camera calibration")
        else:
            issues.append(f"camera calibration quality_status={quality_status!r}")

    values: dict[str, float | None] = {}
    for key in ("rms_reprojection_error_px", "max_view_rms_px", "coverage_fraction"):
        try:
            values[key] = float(raw[key])
        except (KeyError, TypeError, ValueError):
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
        "camera_calibrated": True,
        "camera_quality_ok": not issues,
        "camera_quality_status": quality_status,
        "camera_rms_reprojection_error_px": rms,
        "camera_max_view_rms_px": max_view,
        "camera_coverage_fraction": coverage,
        "issues": issues,
    }


def _feature_count(features_path: Path) -> int:
    if not features_path.is_file():
        return 0
    try:
        with np.load(features_path) as features:
            return int(len(features["xy_mm"]))
    except (KeyError, OSError, ValueError, TypeError):
        return 0


def inspect_profile_quality(
    profile: object,
    profile_dir: str | Path,
    *,
    camera_calibration_path: str | Path | None = None,
    min_pin_pitch_px: float | None = None,
    min_px_per_mm: float | None = None,
) -> dict[str, Any]:
    """Return a JSON-safe physical-gate report without changing any files."""
    profile_dir = Path(profile_dir)
    pin_geometry = [
        (pin.header, pin.index, pin.pos_mm[0], pin.pos_mm[1])
        for pin in profile.pins
    ]
    scale_options: dict[str, float] = {}
    if min_pin_pitch_px is not None:
        scale_options["min_pin_pitch_px"] = float(min_pin_pitch_px)
    if min_px_per_mm is not None:
        scale_options["min_px_per_mm"] = float(min_px_per_mm)
    scale = reference_scale_report(
        np.asarray(profile.reference.mm_to_px, dtype=np.float64),
        pin_geometry,
        **scale_options,
    )
    shared_camera = (
        Path(camera_calibration_path)
        if camera_calibration_path is not None
        else None
    )
    camera_path = (
        shared_camera
        if shared_camera is not None and shared_camera.is_file()
        else profile_dir / "camera.json"
    )
    camera = _camera_quality(camera_path)
    feature_count = _feature_count(profile_dir / "features.npz")

    warnings: list[str] = []
    if scale["status"] != "ok":
        warnings.append(
            f"pin pitch {float(scale['pitch_px']):.2f}px "
            f"({float(scale['px_per_mm']):.2f}px/mm) is below the physical target"
        )
    warnings.extend(str(issue) for issue in camera["issues"])
    if feature_count < DEFAULT_MIN_FEATURES:
        warnings.append(
            f"feature cache is missing or too small ({feature_count} features)"
        )

    physical_gate_ready = (
        scale["status"] == "ok"
        and camera["camera_quality_ok"]
        and feature_count >= DEFAULT_MIN_FEATURES
    )
    return {
        "status": "ready" if physical_gate_ready else "warning",
        "physical_gate_ready": physical_gate_ready,
        "pitch_px": round(float(scale["pitch_px"]), 4),
        "px_per_mm": round(float(scale["px_per_mm"]), 4),
        "min_pitch_px": float(scale["min_pitch_px"]),
        "min_px_per_mm": float(scale["min_px_per_mm"]),
        "camera_calibrated": camera["camera_calibrated"],
        "camera_quality_ok": camera["camera_quality_ok"],
        "camera_quality_status": camera["camera_quality_status"],
        "camera_rms_reprojection_error_px": camera["camera_rms_reprojection_error_px"],
        "camera_max_view_rms_px": camera["camera_max_view_rms_px"],
        "camera_coverage_fraction": camera["camera_coverage_fraction"],
        "feature_count": feature_count,
        "warnings": warnings,
    }


__all__ = ["inspect_profile_quality"]
