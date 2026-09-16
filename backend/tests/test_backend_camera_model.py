"""load_camera distortion-vector handling.

OpenCV only accepts distortion vectors of length 4, 5, 8, 12 or 14; a
camera.json with e.g. 6 or 7 entries used to crash every downstream cv2
call. load_camera must pad short vectors to the nearest valid length
(<5 -> 5, 6/7 -> 8) and fall back to the default camera for anything that
still is not a valid OpenCV length.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app.vision.camera_model import default_camera, load_camera, project_points

SIZE = (640, 480)


def write_camera_json(tmp_path: Path, dist: list[float]) -> Path:
    p = tmp_path / "camera.json"
    p.write_text(
        json.dumps({"fx": 600.0, "fy": 600.0, "cx": 320.0, "cy": 240.0,
                    "dist": dist, "quality_status": "ok"}),
        encoding="utf-8",
    )
    return p


def write_sized_camera_json(tmp_path: Path, *, image_size: tuple[int, int]) -> Path:
    p = tmp_path / "camera-sized.json"
    p.write_text(
        json.dumps({
            "fx": 600.0,
            "fy": 610.0,
            "cx": 320.0,
            "cy": 240.0,
            "dist": [0.01] * 5,
            "quality_status": "ok",
            "image_size": list(image_size),
        }),
        encoding="utf-8",
    )
    return p


@pytest.mark.parametrize(
    "n,expected",
    [(0, 5), (2, 5), (4, 5), (5, 5), (6, 8), (7, 8), (8, 8), (12, 12), (14, 14)],
)
def test_dist_padded_to_valid_opencv_length(tmp_path, n, expected):
    cam = load_camera(SIZE, write_camera_json(tmp_path, [0.01] * n))
    assert cam.dist.size == expected
    assert cam.K[0, 0] == 600.0  # the calibration was used, not the default
    assert np.all(cam.dist[:n] == 0.01)
    assert np.all(cam.dist[n:] == 0.0)  # padded tail is zero


@pytest.mark.parametrize("n", [9, 10, 11, 13, 15])
def test_dist_invalid_length_falls_back_to_default(tmp_path, n):
    cam = load_camera(SIZE, write_camera_json(tmp_path, [0.01] * n))
    default = default_camera(SIZE)
    assert np.array_equal(cam.K, default.K)
    assert np.array_equal(cam.dist, default.dist)


@pytest.mark.parametrize("n", [6, 7])
def test_padded_dist_is_usable_by_opencv(tmp_path, n):
    """Sizes 6/7 used to raise inside cv2.projectPoints; padded to 8 they
    must project without error."""
    cam = load_camera(SIZE, write_camera_json(tmp_path, [0.01] * n))
    pts = np.array([[0.0, 0.0, 0.0], [10.0, 5.0, 0.0]])
    px = project_points(pts, cam, np.zeros(3), np.array([0.0, 0.0, 100.0]))
    assert px.shape == (2, 2)
    assert np.isfinite(px).all()


def test_calibrated_intrinsics_scale_to_same_aspect_live_resolution(tmp_path):
    cam = load_camera(
        (1920, 1080),
        write_sized_camera_json(tmp_path, image_size=(1280, 720)),
    )
    assert cam.size == (1920, 1080)
    assert cam.K[0, 0] == pytest.approx(900.0)
    assert cam.K[1, 1] == pytest.approx(915.0)
    assert cam.K[0, 2] == pytest.approx(480.0)
    assert cam.K[1, 2] == pytest.approx(360.0)


def test_calibrated_intrinsics_reject_aspect_ratio_change(tmp_path):
    path = write_sized_camera_json(tmp_path, image_size=(1280, 720))
    cam = load_camera((1440, 1080), path)
    default = default_camera((1440, 1080))
    assert np.array_equal(cam.K, default.K)
    assert np.array_equal(cam.dist, default.dist)


def test_calibration_without_image_size_keeps_legacy_intrinsics(tmp_path):
    cam = load_camera((1920, 1080), write_camera_json(tmp_path, [0.01] * 5))
    assert cam.K[0, 0] == pytest.approx(600.0)
    assert cam.K[1, 1] == pytest.approx(600.0)


def test_rejected_quality_calibration_falls_back_to_default(tmp_path):
    path = write_camera_json(tmp_path, [0.01] * 5)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["quality_status"] = "reject"
    path.write_text(json.dumps(raw), encoding="utf-8")
    cam = load_camera(SIZE, path)
    default = default_camera(SIZE)
    assert np.array_equal(cam.K, default.K)
    assert np.array_equal(cam.dist, default.dist)


def test_legacy_calibration_without_quality_status_falls_back_to_default(tmp_path):
    path = write_camera_json(tmp_path, [0.01] * 5)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("quality_status")
    path.write_text(json.dumps(raw), encoding="utf-8")
    cam = load_camera(SIZE, path)
    default = default_camera(SIZE)
    assert np.array_equal(cam.K, default.K)
    assert np.array_equal(cam.dist, default.dist)


def test_default_camera_accepts_hardware_horizontal_fov():
    cam = default_camera((1280, 720), horizontal_fov_deg=70.42)
    expected = (1280 / 2.0) / np.tan(np.deg2rad(70.42) / 2.0)
    assert cam.K[0, 0] == pytest.approx(expected)
    assert cam.K[1, 1] == pytest.approx(expected)
