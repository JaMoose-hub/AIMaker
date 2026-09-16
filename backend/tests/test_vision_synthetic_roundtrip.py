"""Round-trip consistency of the synthetic scene geometry.

pose -> plane homography -> projected points must agree with
cv2.projectPoints, the pose must be recoverable from the homography's
correspondences, and truth_at must equal a hand-computed projection.
"""
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import cv2
import numpy as np
import pytest

from app.vision.camera_model import (
    board_outline_mm,
    board_to_vision,
    default_camera,
    plane_homography,
    project_points,
    project_wire_exclusion,
)
from app.vision.synthetic import SyntheticScene, trajectory_pose
from vision_fixtures.make_fixture import build_fixture

VIDEO_SIZE = (1280, 720)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("boardfix"))


@pytest.fixture(scope="module")
def scene(fixture):
    profile, profile_dir = fixture
    return SyntheticScene(profile, profile_dir, VIDEO_SIZE)


def _apply_h(h, pts):
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    q = (h @ np.hstack([pts, np.ones((len(pts), 1))]).T).T
    return q[:, :2] / q[:, 2:3]


def test_homography_matches_projectpoints(fixture):
    """H = K [r1 r2 t] must project z=0 points identically to projectPoints."""
    profile, _ = fixture
    cam = default_camera(VIDEO_SIZE)
    corners = board_outline_mm(profile.board.outline_mm)
    for t in (0.0, 1.7, 5.0, 8.5, 13.3):
        rvec, tvec = trajectory_pose(t, profile.board.outline_mm)
        H = plane_homography(cam, rvec, tvec)
        via_h = _apply_h(H, corners[:, :2])
        via_pp = project_points(corners, cam, rvec, tvec)
        assert np.allclose(via_h, via_pp, atol=1e-8)


def test_pose_recoverable_from_homography(fixture):
    """pose -> homography -> solvePnP(IPPE) recovers the same pose."""
    profile, _ = fixture
    cam = default_camera(VIDEO_SIZE)
    w, h = profile.board.outline_mm
    gx, gy = np.meshgrid(np.linspace(3, w - 3, 5), np.linspace(3, h - 3, 4))
    grid_mm = np.stack([gx.ravel(), gy.ravel()], axis=1)
    obj = np.zeros((len(grid_mm), 3))
    obj[:, :2] = grid_mm

    for t in (1.7, 5.0, 8.5):  # non-zero tilt: IPPE ambiguity resolvable
        rvec_gt, tvec_gt = trajectory_pose(t, profile.board.outline_mm)
        H = plane_homography(cam, rvec_gt, tvec_gt)
        img_pts = _apply_h(H, grid_mm)

        n, rvecs, tvecs, _ = cv2.solvePnPGeneric(
            obj, np.ascontiguousarray(img_pts.reshape(-1, 1, 2)),
            cam.K, cam.dist, flags=cv2.SOLVEPNP_IPPE)
        assert n >= 1
        best = None
        for rv, tv in zip(rvecs, tvecs):
            R, _ = cv2.Rodrigues(rv)
            if (R @ [0, 0, -1.0])[2] < 0 and tv.reshape(3)[2] > 0:
                best = (rv.reshape(3), tv.reshape(3))
                break
        assert best is not None, "no physically-plausible IPPE solution"
        rvec, tvec = best
        assert np.linalg.norm(tvec - tvec_gt) < 0.1  # mm
        R_gt, _ = cv2.Rodrigues(rvec_gt)
        R_est, _ = cv2.Rodrigues(rvec)
        cos_a = (np.trace(R_gt.T @ R_est) - 1.0) / 2.0
        angle_deg = np.degrees(np.arccos(np.clip(cos_a, -1, 1)))
        assert angle_deg < 0.05


def test_truth_matches_hand_computed_projection(fixture, scene):
    """truth_at pin px == cv2.projectPoints of pos_mm with z negated."""
    profile, _ = fixture
    cam = default_camera(VIDEO_SIZE)
    for t in (0.0, 4.2, 9.9):
        truth = scene.truth_at(t, frame_id=42)
        rvec, tvec = scene.pose_at(t)
        pos = np.array([p.pos_mm for p in profile.pins], dtype=np.float64)
        expected, _ = cv2.projectPoints(
            np.ascontiguousarray(board_to_vision(pos)),
            rvec.reshape(3, 1), tvec.reshape(3, 1), cam.K, cam.dist)
        expected = expected.reshape(-1, 2)
        assert truth.tracking == "locked"
        assert truth.confidence == 1.0
        assert truth.board_id == profile.board.id
        assert truth.frame_id == 42
        assert truth.ts_ms == pytest.approx(t * 1000.0)
        assert len(truth.pins) == len(profile.pins)
        for pin, exp in zip(truth.pins, expected):
            assert pin.x == pytest.approx(exp[0], abs=1e-6)
            assert pin.y == pytest.approx(exp[1], abs=1e-6)
        assert truth.outline_px is not None and len(truth.outline_px) == 4


def test_pin_z_offset_is_towards_camera(fixture, scene):
    """Physical parallax: at tilt, the z=8.5 mm pin opening must project on
    the side predicted by a point CLOSER to the camera than the PCB plane."""
    profile, _ = fixture
    cam = default_camera(VIDEO_SIZE)
    t = 8.5  # max tilt (~12 deg)
    rvec, tvec = scene.pose_at(t)
    pin = profile.pins[0]
    top = project_points(board_to_vision(np.array([pin.pos_mm])), cam,
                         rvec, tvec)[0]
    base = project_points(np.array([[pin.pos_mm[0], pin.pos_mm[1], 0.0]]),
                          cam, rvec, tvec)[0]
    # A z-up point closer to the camera appears displaced away from the
    # board's vanishing direction; verify the offset is non-zero and that
    # the top point has *smaller* camera depth than its base.
    R, _ = cv2.Rodrigues(rvec.reshape(3, 1))
    depth_top = (R @ board_to_vision(np.array([pin.pos_mm]))[0] + tvec)[2]
    depth_base = (R @ np.array([pin.pos_mm[0], pin.pos_mm[1], 0.0]) + tvec)[2]
    assert depth_top < depth_base
    assert np.linalg.norm(top - base) > 0.5  # px, visible parallax at 12 deg


def test_wire_exclusion_is_projected_at_header_height(fixture, scene):
    profile, _ = fixture
    cam = default_camera(VIDEO_SIZE)
    rvec, tvec = scene.pose_at(8.5)
    exclusion = project_wire_exclusion(profile, cam, rvec, tvec)
    outline = project_points(
        board_outline_mm(profile.board.outline_mm), cam, rvec, tvec)
    assert len(exclusion) == 4
    # At a non-zero tilt, a header-plane point cannot be identical to the
    # z=0 silhouette. This guards against reintroducing the old pixel-shrink
    # approximation in the live wire mask path.
    assert not np.allclose(np.asarray(exclusion), outline, atol=1e-3)


def test_frame_deterministic_and_well_formed(scene):
    f1 = scene.frame_at(3.3)
    f2 = scene.frame_at(3.3)
    assert f1.shape == (VIDEO_SIZE[1], VIDEO_SIZE[0], 3)
    assert f1.dtype == np.uint8
    assert np.array_equal(f1, f2)
    # Board actually rendered: the frame differs from the pure background.
    f_other = scene.frame_at(9.1)
    assert not np.array_equal(f1, f_other)
