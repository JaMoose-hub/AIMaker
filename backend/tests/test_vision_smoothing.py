"""Unit tests for the One-Euro filter and the PoseFilter."""
import math
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np
import pytest

from app.vision.smoothing import OneEuroFilter, PoseFilter


def test_first_sample_passes_through():
    f = OneEuroFilter()
    assert f.filter(5.0, 0.0) == 5.0


def test_constant_input_is_unchanged():
    f = OneEuroFilter()
    for k in range(50):
        y = f.filter(3.25, k / 30.0)
    assert y == pytest.approx(3.25, abs=1e-9)


def test_noise_is_attenuated():
    rng = np.random.default_rng(1)
    noise = rng.normal(0.0, 1.0, 300)
    f = OneEuroFilter(min_cutoff=1.0, beta=0.007)
    out = [f.filter(float(v), k / 30.0) for k, v in enumerate(noise)]
    assert np.std(out[30:]) < 0.6 * np.std(noise[30:])


def test_step_response_is_monotonic_and_converges():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.1)
    f.filter(0.0, 0.0)
    ys = [f.filter(10.0, (k + 1) / 30.0) for k in range(60)]
    assert all(b >= a - 1e-12 for a, b in zip(ys, ys[1:]))
    assert ys[-1] == pytest.approx(10.0, abs=0.05)


def test_faster_motion_gets_less_lag():
    def lag(beta):
        f = OneEuroFilter(min_cutoff=0.5, beta=beta)
        t, y = 0.0, 0.0
        for k in range(90):
            t = k / 30.0
            y = f.filter(float(k), t)  # ramp input
        return abs(89 - y)
    assert lag(1.0) < lag(0.0)


def test_vector_input_filters_elementwise():
    f = OneEuroFilter()
    v = np.array([1.0, -2.0, 3.0])
    for k in range(40):
        y = f.filter(v, k / 30.0)
    assert np.allclose(y, v)


def test_non_advancing_time_does_not_crash():
    f = OneEuroFilter()
    f.filter(1.0, 1.0)
    y = f.filter(2.0, 1.0)  # same timestamp: pass-through, no ZeroDivision
    assert math.isfinite(y)


def test_reset_forgets_state():
    f = OneEuroFilter()
    for k in range(10):
        f.filter(100.0, k / 30.0)
    f.reset()
    assert f.filter(-5.0, 100.0) == -5.0


# ---------------------------------------------------------------------------
# PoseFilter
# ---------------------------------------------------------------------------

def test_pose_filter_constant_pose_unchanged():
    pf = PoseFilter()
    rvec = np.array([0.1, -0.2, 1.3])
    tvec = np.array([10.0, -5.0, 200.0])
    for k in range(50):
        r, t = pf.apply(rvec, tvec, k / 30.0)
    assert np.allclose(t, tvec, atol=1e-9)
    assert np.allclose(r, rvec, atol=1e-6)


def test_pose_filter_smooths_translation_noise():
    rng = np.random.default_rng(2)
    pf = PoseFilter(min_cutoff=1.0, beta=0.01)
    tvec = np.array([0.0, 0.0, 200.0])
    outs = []
    for k in range(200):
        noisy = tvec + rng.normal(0.0, 0.5, 3)
        _, t = pf.apply(np.zeros(3), noisy, k / 30.0)
        outs.append(t)
    outs = np.asarray(outs)[30:]
    assert np.std(outs[:, 0]) < 0.3   # raw std was 0.5


def test_pose_filter_quaternion_hemisphere_continuity():
    """Rotations near 180 deg (where q flips sign) must stay stable."""
    pf = PoseFilter()
    outs = []
    for k in range(60):
        angle = math.pi - 0.05 + 0.1 * math.sin(k / 5.0)  # wobbles about pi
        rvec = np.array([0.0, 0.0, angle])
        r, _ = pf.apply(rvec, np.array([0.0, 0.0, 100.0]), k / 30.0)
        outs.append(r)
    import cv2
    for r_prev, r_next in zip(outs, outs[1:]):
        # successive filtered ROTATIONS differ by a small geodesic angle
        # (the rvec vector itself may wrap at pi — that is fine).
        R0, _ = cv2.Rodrigues(np.asarray(r_prev))
        R1, _ = cv2.Rodrigues(np.asarray(r_next))
        cos_a = (np.trace(R0.T @ R1) - 1.0) / 2.0
        diff = math.acos(min(1.0, max(-1.0, cos_a)))
        assert diff < 0.2, f"rotation output jumped by {diff:.3f} rad"


def test_pose_filter_reset():
    pf = PoseFilter()
    for k in range(10):
        pf.apply(np.array([0.0, 0.0, 0.5]), np.array([1.0, 2.0, 3.0]),
                 k / 30.0)
    pf.reset()
    rvec = np.array([1.0, 0.0, 0.0])
    tvec = np.array([9.0, 9.0, 9.0])
    r, t = pf.apply(rvec, tvec, 50.0)
    assert np.allclose(r, rvec, atol=1e-9)
    assert np.allclose(t, tvec, atol=1e-9)


def test_invalid_cutoff_rejected():
    with pytest.raises(ValueError):
        OneEuroFilter(min_cutoff=0.0)
