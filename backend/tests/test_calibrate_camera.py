"""Quality gates for checkerboard camera calibration."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))

from calibrate_camera import calibration_quality_report  # noqa: E402


def _synthetic_view():
    camera = np.array(
        [[100.0, 0.0, 50.0], [0.0, 100.0, 50.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    distortion = np.zeros(5, dtype=np.float64)
    obj = np.array(
        [[-4.0, -3.0, 0.0], [4.0, -3.0, 0.0],
         [4.0, 3.0, 0.0], [-4.0, 3.0, 0.0]],
        dtype=np.float32,
    )
    rvec = np.zeros((3, 1), dtype=np.float64)
    tvec = np.array([[0.0], [0.0], [10.0]], dtype=np.float64)
    corners, _ = cv2.projectPoints(obj, rvec, tvec, camera, distortion)
    return camera, distortion, obj, corners, rvec, tvec


def test_calibration_quality_accepts_low_error_well_covered_views():
    camera, distortion, obj, corners, rvec, tvec = _synthetic_view()
    report = calibration_quality_report(
        (100, 100), [obj], [corners], [rvec], [tvec],
        camera, distortion, 0.0,
    )
    assert report["quality_status"] == "ok"
    assert report["coverage_fraction"] > 0.2
    assert report["max_view_rms_px"] == pytest.approx(0.0, abs=1e-10)
    assert report["quality_issues"] == []


def test_calibration_quality_rejects_rms_and_coverage_failures():
    camera, distortion, obj, corners, rvec, tvec = _synthetic_view()
    shifted = corners + np.array([[[4.0, 0.0]]], dtype=np.float32)
    report = calibration_quality_report(
        (100, 100), [obj], [shifted], [rvec], [tvec],
        camera, distortion, 2.0, min_coverage=0.6,
    )
    assert report["quality_status"] == "reject"
    assert len(report["quality_issues"]) == 3
