"""Occlusion handling: LOCKED -> STALE (frozen pins) -> re-lock.

After lock, 5 frames arrive with a gray rectangle covering ~60% of the
board (the feature-dense region): the tracker must go "stale" (not
"searching") and keep the last good pin coordinates; when the occlusion
clears it must re-lock within 10 frames.
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

from app.vision.factory import create_detector
from app.vision.synthetic import SyntheticScene
from vision_fixtures.make_fixture import build_fixture

VIDEO_SIZE = (1280, 720)
FPS = 30.0


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("boardfix"))


def _occlude(scene, frame, t, frac=0.62):
    """Gray rectangle over the board-mm region x in [0, frac*W] (~60% of
    the board area), projected through the scene's ground-truth pose."""
    w_mm, h_mm = scene.profile.board.outline_mm
    quad_mm = np.array([[0.0, 0.0], [frac * w_mm, 0.0],
                        [frac * w_mm, h_mm], [0.0, h_mm]])
    H = scene.homography_at(t)
    q = (H @ np.hstack([quad_mm, np.ones((4, 1))]).T).T
    quad_px = (q[:, :2] / q[:, 2:3]).astype(np.int32)
    out = frame.copy()
    cv2.fillConvexPoly(out, quad_px, (128, 128, 128))
    return out


def test_occlusion_goes_stale_then_relocks(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    detector = create_detector("pipeline", profile, profile_dir)

    frame_id = 0

    def step(t, occluded=False):
        nonlocal frame_id
        frame = scene.frame_at(t)
        if occluded:
            frame = _occlude(scene, frame, t)
        r = detector.detect(frame, frame_id, t * 1000.0)
        frame_id += 1
        return r

    # Phase 1: lock.
    last_locked = None
    for k in range(15):
        r = step(k / FPS)
        if r.tracking == "locked":
            last_locked = r
    assert last_locked is not None, "never locked in phase 1"
    assert r.tracking == "locked", "must be locked entering the occlusion"
    frozen = {p.pin_id: (p.x, p.y) for p in r.pins}

    # Phase 2: 5 occluded frames -> stale (not searching), pins frozen.
    stale_states = []
    for k in range(15, 20):
        r = step(k / FPS, occluded=True)
        stale_states.append(r.tracking)
        assert r.tracking == "stale", \
            f"expected stale during occlusion, got {r.tracking!r}"
        assert {p.pin_id: (p.x, p.y) for p in r.pins} == frozen, \
            "stale pins must keep the last good coordinates"
        assert r.outline_px is not None
    assert stale_states == ["stale"] * 5

    # Phase 3: occlusion clears -> re-locks within 10 frames.
    relock_idx = None
    for j, k in enumerate(range(20, 30)):
        r = step(k / FPS)
        if r.tracking == "locked":
            relock_idx = j
            break
    assert relock_idx is not None and relock_idx < 10, \
        "did not re-lock within 10 frames after occlusion cleared"

    detector.close()
