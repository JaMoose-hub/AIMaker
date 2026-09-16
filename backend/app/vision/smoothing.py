"""Temporal smoothing: One-Euro filter + 6-DoF PoseFilter.

One-Euro filter (Casiez, Roussel, Vogel — CHI 2012), vendored, vectorized
over numpy arrays (each component filtered independently; the adaptive
cutoff is computed per component from its own derivative).

PoseFilter smoothing strategy (documented choice):
- tvec: one One-Euro per component (3 total, done as one vectorized filter).
- rotation: rvec -> R -> unit quaternion; the quaternion is sign-aligned to
  the previously filtered quaternion (q and -q are the same rotation, so we
  keep the hemisphere consistent), each of the 4 components goes through a
  One-Euro filter, and the result is renormalized back to a unit quaternion
  before converting to rvec.  For the small inter-frame rotations of a
  tracked board this is numerically indistinguishable from slerp towards the
  target and is much simpler.
- ``reset()`` clears all state; the next sample passes through unfiltered
  (called by the tracker on re-acquisition).
"""
from __future__ import annotations

import math

import numpy as np

__all__ = ["OneEuroFilter", "PoseFilter"]


class _LowPass:
    """First-order low-pass with per-call alpha (vectorized)."""

    def __init__(self) -> None:
        self.initialized = False
        self.prev: np.ndarray | float = 0.0

    def apply(self, x, alpha):
        if not self.initialized:
            self.initialized = True
            self.prev = x
            return x
        y = alpha * x + (1.0 - alpha) * self.prev
        self.prev = y
        return y

    def reset(self) -> None:
        self.initialized = False
        self.prev = 0.0


class OneEuroFilter:
    """Adaptive low-pass: low jitter when still, low lag when moving.

    Parameters
    ----------
    min_cutoff : Hz, jitter floor (lower = smoother when static).
    beta       : speed coefficient (higher = less lag when moving).
    d_cutoff   : Hz, cutoff for the derivative estimate.

    Call ``filter(x, t_s)`` with a monotonically increasing timestamp in
    seconds.  ``x`` may be a float or an ndarray (filtered element-wise).
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007,
                 d_cutoff: float = 1.0) -> None:
        if min_cutoff <= 0 or d_cutoff <= 0:
            raise ValueError("cutoff frequencies must be > 0")
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x = _LowPass()
        self._dx = _LowPass()
        self._t_prev: float | None = None

    @staticmethod
    def _alpha(cutoff, dt: float):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x, t_s: float):
        x = np.asarray(x, dtype=np.float64) if not np.isscalar(x) else float(x)
        if self._t_prev is None or t_s <= self._t_prev:
            # First sample (or non-advancing clock): pass through.
            self._t_prev = float(t_s)
            self._x.reset()
            self._dx.reset()
            self._dx.apply(np.zeros_like(x) if not np.isscalar(x) else 0.0,
                           1.0)
            return self._x.apply(x, 1.0)
        dt = float(t_s) - self._t_prev
        self._t_prev = float(t_s)
        dx = (x - self._x.prev) / dt
        edx = self._dx.apply(dx, self._alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * np.abs(edx)
        return self._x.apply(x, self._alpha(cutoff, dt))

    def reset(self) -> None:
        self._x.reset()
        self._dx.reset()
        self._t_prev = None


# ---------------------------------------------------------------------------
# Quaternion helpers (numpy only; w, x, y, z order)
# ---------------------------------------------------------------------------

def _rvec_to_quat(rvec: np.ndarray) -> np.ndarray:
    r = np.asarray(rvec, dtype=np.float64).reshape(3)
    angle = float(np.linalg.norm(r))
    if angle < 1e-12:
        return np.array([1.0, 0.0, 0.0, 0.0])
    axis = r / angle
    s = math.sin(angle / 2.0)
    return np.array([math.cos(angle / 2.0), axis[0] * s, axis[1] * s,
                     axis[2] * s])


def _quat_to_rvec(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, dtype=np.float64).reshape(4)
    q = q / np.linalg.norm(q)
    w = float(np.clip(q[0], -1.0, 1.0))
    angle = 2.0 * math.acos(w)
    s = math.sqrt(max(1.0 - w * w, 0.0))
    if s < 1e-9 or angle < 1e-12:
        return np.zeros(3)
    if angle > math.pi:  # keep the short representation
        angle -= 2.0 * math.pi
    return (q[1:4] / s) * angle


class PoseFilter:
    """One-Euro smoothing of an OpenCV (rvec, tvec) pose. See module doc."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02,
                 d_cutoff: float = 1.0, rot_min_cutoff: float | None = None,
                 rot_beta: float | None = None) -> None:
        self._t_filter = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self._q_filter = OneEuroFilter(
            rot_min_cutoff if rot_min_cutoff is not None else min_cutoff,
            rot_beta if rot_beta is not None else beta, d_cutoff)
        self._q_prev: np.ndarray | None = None

    def apply(self, rvec: np.ndarray, tvec: np.ndarray,
              t_s: float) -> tuple[np.ndarray, np.ndarray]:
        t = np.asarray(tvec, dtype=np.float64).reshape(3)
        q = _rvec_to_quat(rvec)
        if self._q_prev is not None and float(np.dot(q, self._q_prev)) < 0.0:
            q = -q  # hemisphere alignment: q and -q are the same rotation
        t_f = self._t_filter.filter(t, t_s)
        q_f = np.asarray(self._q_filter.filter(q, t_s), dtype=np.float64)
        n = float(np.linalg.norm(q_f))
        q_f = q_f / n if n > 1e-12 else np.array([1.0, 0.0, 0.0, 0.0])
        self._q_prev = q_f
        return _quat_to_rvec(q_f), np.asarray(t_f, dtype=np.float64).reshape(3)

    def reset(self) -> None:
        self._t_filter.reset()
        self._q_filter.reset()
        self._q_prev = None
