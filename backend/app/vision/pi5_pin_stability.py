"""Image-supported static anchoring and final-coordinate gates for Pi J8.

These are not electrical or absolute pin-location evidence. An anchor is
retained only while *fresh* image features agree with its accepted frame;
there is no cumulative optical-flow integration or moving-camera lock.
"""
from __future__ import annotations

import cv2
import numpy as np


def pin_array(pins) -> np.ndarray:
    return np.asarray([[p.x, p.y] for p in pins], dtype=np.float64)


class PinImageAnchor:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.gray = None
        self.points = None
        self.j8_count = 0
        self.motion_px = None
        self.support = 0
        self.roi = None
        self.frame_shape = None
        self.fully_supported = False

    def seed(self, frame_bgr, pins, outline) -> None:
        self.reset()
        j8 = [p for p in pins if p.header == "J8" and p.visible]
        if len(j8) < 12 or not outline:
            return
        xy = pin_array(j8).astype(np.float32)
        boundary = np.asarray(outline, dtype=np.float32)
        extent = np.concatenate([xy, boundary])
        if not np.all(np.isfinite(extent)):
            return
        h, w = frame_bgr.shape[:2]
        # Keep source-pixel precision and both J8 + board context. The 64px
        # halo covers the 21px LK window at pyramid level 2 and its filters.
        # Align the crop origin with the pyramid grid; never integrate motion.
        x1, y1 = np.maximum(0, np.floor((extent.min(0) - 64) / 4) * 4).astype(int)
        x2, y2 = np.minimum([w, h], np.ceil(extent.max(0) + 65)).astype(int)
        if x2 <= x1 or y2 <= y1:
            return
        offset = np.array([x1, y1], dtype=np.float32)
        xy = xy - offset
        gray = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        mask = np.zeros(gray.shape, dtype=np.uint8)
        hull = cv2.convexHull(xy).astype(np.int32)
        cv2.fillConvexPoly(mask, hull, 255)
        mask = cv2.dilate(mask, np.ones((17, 17), np.uint8))
        pts = cv2.goodFeaturesToTrack(gray, 96, .02, 5, mask=mask)
        if pts is None or len(pts) < 12:
            return
        # Require texture along most of J8, not only one unoccluded end.
        _, _, vt = np.linalg.svd(xy - xy.mean(axis=0), full_matrices=False)
        axis = vt[0]
        if np.ptp(pts.reshape(-1, 2) @ axis) < .6 * np.ptp(xy @ axis):
            return
        context = np.zeros(gray.shape, dtype=np.uint8)
        cv2.fillConvexPoly(context, (boundary - offset).astype(np.int32), 255)
        context[mask != 0] = 0
        other = cv2.goodFeaturesToTrack(gray, 32, .02, 8, mask=context)
        if other is None or len(other) < 8:
            return
        self.j8_count = len(pts)
        self.points = np.concatenate([pts, other]).astype(np.float32)
        self.gray = gray
        self.roi = (x1, y1, x2, y2)
        self.frame_shape = frame_bgr.shape

    def stationary(self, frame_bgr) -> bool:
        self.motion_px = None
        self.support = 0
        self.fully_supported = False
        if self.gray is None or self.points is None:
            return False
        if frame_bgr.shape != self.frame_shape:
            self.reset()
            return False
        x1, y1, x2, y2 = self.roi
        gray = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        try:
            forward, ok, error = cv2.calcOpticalFlowPyrLK(
                self.gray, gray, self.points, None, winSize=(21, 21), maxLevel=2)
            if forward is None:
                return False
            backward, back_ok, _ = cv2.calcOpticalFlowPyrLK(
                gray, self.gray, forward, None, winSize=(21, 21), maxLevel=2)
            if backward is None:
                return False
        except cv2.error:
            return False
        fb = np.linalg.norm((backward - self.points).reshape(-1, 2), axis=1)
        valid = ((ok.ravel() == 1) & (back_ok.ravel() == 1)
                 & (error.ravel() < 12) & np.isfinite(fb) & (fb < .6))
        self.support = int(valid.sum())
        # Both local J8 and surrounding board texture must remain visible.
        if (np.mean(valid[:self.j8_count]) < .80
                or np.mean(valid[self.j8_count:]) < .80):
            return False
        displacement = np.linalg.norm((forward-self.points).reshape(-1, 2), axis=1)
        self.motion_px = float(np.percentile(displacement[valid], 90))
        stationary = bool(np.isfinite(self.motion_px) and self.motion_px <= 1.0)
        # Stronger evidence for replacing a *different* aged display template.
        # Do not turn the ordinary 80% stationary tolerance into permission to
        # learn an obstruction. Both independently seeded regions must be clear.
        self.fully_supported = bool(stationary and np.mean(valid[:self.j8_count]) >= .95
                                    and np.mean(valid[self.j8_count:]) >= .95)
        return stationary


class PinUpdateGate:
    """Check *final pins*, independently of the board-corner deadband."""
    def __init__(self, confirm_frames: int = 2) -> None:
        self.confirm_frames = max(2, confirm_frames)
        self.reset()

    def reset(self) -> None:
        self.pending = None
        self.pending_ids = None
        self.count = 0
        self.motion_px = None

    def ready(self, pins, previous) -> bool:
        ids = tuple(p.pin_id for p in pins)
        if not previous or ids != tuple(p.pin_id for p in previous):
            self.reset()
            return not previous
        xy, last = pin_array(pins), pin_array(previous)
        if not len(xy) or not np.all(np.isfinite(xy)):
            self.reset()
            return False
        self.motion_px = float(np.percentile(np.linalg.norm(xy-last, axis=1), 90))
        if self.motion_px <= 2.0:
            self.pending = None
            self.pending_ids = None
            self.count = 0
            return True
        if (self.pending is None or self.pending_ids != ids
                or np.percentile(np.linalg.norm(xy-self.pending, axis=1), 90) > 1.5):
            self.pending = xy.copy()
            self.pending_ids = ids
            self.count = 1
        else:
            self.pending = .5 * (self.pending + xy)
            self.count += 1
        # Keep the consensus until the caller actually commits the update.
        return self.count >= self.confirm_frames
