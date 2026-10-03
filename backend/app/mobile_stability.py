"""Phone capture readiness in native pixels; never transforms display geometry."""
from __future__ import annotations

import math

import numpy as np


# Initial framing tolerances, relative to the first Pi observation in this hold.
# They describe hand/model motion, not physical GPIO accuracy.
TRANSLATION_FRACTION = .08
CORNER_FRACTION = .12
ROTATION_DEGREES = 8.
SCALE_FRACTION = .12
HOLD_SECONDS = 1.
HISTORY_SECONDS = 1.4
DROPOUT_SECONDS = .7
MIN_VALID_FRAMES = 3


def valid_points(points):
    if "raspberry-pi-5" not in points:
        return False
    for corners in points.values():
        q = np.asarray(corners, dtype=float)
        if q.shape != (4, 2) or not np.isfinite(q).all():
            return False
        edges = np.roll(q, -1, axis=0) - q
        cross = edges[:, 0] * np.roll(edges[:, 1], -1) - edges[:, 1] * np.roll(edges[:, 0], -1)
        if not (np.all(cross > 0) or np.all(cross < 0)) or np.linalg.norm(q - q.mean(0)) < 1:
            return False
    return True


def stable_geometry(anchor, current):
    """Same ordered corners, same board scale for both board and target motion.

    Translation, rotation and uniform image resize of *both* observations leave
    this comparison unchanged. The anchor never follows gradual camera drift.
    """
    if set(anchor) != set(current) or not valid_points(anchor) or not valid_points(current):
        return False
    board = np.asarray(anchor["raspberry-pi-5"], dtype=float)
    diagonal = (np.linalg.norm(board[2] - board[0]) + np.linalg.norm(board[3] - board[1])) / 2
    for name, corners in current.items():
        a, b = np.asarray(anchor[name], dtype=float), np.asarray(corners, dtype=float)
        # A reflection of semantic corner order can have zero fitted rotation
        # on a small square. It is not stable motion, even within Pi's tolerance.
        def winding(q):
            return np.sign(np.sum(q[:, 0]*np.roll(q[:, 1], -1) - q[:, 1]*np.roll(q[:, 0], -1)))
        if winding(a) != winding(b):
            return False
        ac, bc = a.mean(0), b.mean(0)
        if np.linalg.norm(bc-ac) > TRANSLATION_FRACTION*diagonal:
            return False
        if np.max(np.linalg.norm(b-a, axis=1)) > CORNER_FRACTION*diagonal:
            return False
        a, b = a-ac, b-bc
        scale = np.linalg.norm(b)/np.linalg.norm(a)
        angle = abs(math.degrees(math.atan2(np.sum(a[:, 0]*b[:, 1]-a[:, 1]*b[:, 0]), np.sum(a*b))))
        if not 1/(1+SCALE_FRACTION) <= scale <= 1+SCALE_FRACTION or angle > ROTATION_DEGREES:
            return False
    return True


def clear_candidate(stream):
    stream.update(stable_since=None, stable_count=0, previous=None, anchor=None,
                  stable_times=[], qualified_received=None, invalid_count=0)


def accept_candidate(stream, points, received):
    last = stream["qualified_received"]
    if (stream["anchor"] is None or last is None or received-last > DROPOUT_SECONDS+1e-9
            or not stable_geometry(stream["anchor"], points)):
        clear_candidate(stream)
        stream.update(anchor=points, lock_id=None)
    times = [stamp for stamp in stream["stable_times"] if received-stamp <= HISTORY_SECONDS+1e-9]
    times.append(received)
    stream.update(stable_times=times, stable_since=times[0], stable_count=len(times),
                  qualified_received=received, invalid_count=0, previous=points)
    return len(times) >= MIN_VALID_FRAMES and received-times[0] >= HOLD_SECONDS-1e-9
