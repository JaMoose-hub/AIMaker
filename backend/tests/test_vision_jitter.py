"""Jitter: static pose + per-frame sensor noise -> post-filter pin stability.

30 evaluated frames of the same scene instant with gaussian image noise;
per-pin standard deviation of the filtered output must be <= 1.0 px.
"""
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pytest

from app.vision.factory import create_detector
from app.vision.synthetic import SyntheticScene
from vision_fixtures.make_fixture import build_fixture

VIDEO_SIZE = (1280, 720)
FPS = 30.0
T0 = 2.0
NOISE_SIGMA = 2.0


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("boardfix"))


def test_static_pose_with_noise_is_stable(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    detector = create_detector("pipeline", profile, profile_dir)

    base = scene.frame_at(T0).astype(np.float64)
    rng = np.random.default_rng(99)

    tracks: dict[str, list[tuple[float, float]]] = {}
    warmup = 10
    for k in range(warmup + 30):
        noisy = np.clip(base + rng.normal(0.0, NOISE_SIGMA, base.shape),
                        0, 255).astype(np.uint8)
        # The pose is static but the filter clock must advance.
        r = detector.detect(noisy, k, (T0 + k / FPS) * 1000.0)
        if k >= warmup:
            assert r.tracking == "locked", \
                f"lost lock on frame {k}: {r.tracking!r}"
            for p in r.pins:
                tracks.setdefault(p.pin_id, []).append((p.x, p.y))

    assert len(tracks) == len(profile.pins)
    worst = 0.0
    for pin_id, pts in tracks.items():
        assert len(pts) == 30
        arr = np.asarray(pts)
        std_x = float(np.std(arr[:, 0]))
        std_y = float(np.std(arr[:, 1]))
        worst = max(worst, std_x, std_y)
        assert std_x <= 1.0 and std_y <= 1.0, \
            f"pin {pin_id} jitter std=({std_x:.2f},{std_y:.2f})px > 1.0px"
    print(f"[jitter] worst per-pin std = {worst:.3f}px (limit 1.0)")

    detector.close()
