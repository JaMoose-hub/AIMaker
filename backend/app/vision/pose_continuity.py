"""Webcam-only semantic pose continuation from observed PCB motion.

An accepted pose supplies semantics, image correspondences supply new coordinates,
and a fresh, ordered model observation corroborates identity/region. No missing
model, box-only extrapolation, or unbounded anchor lifetime can create GPIOs.
"""
from dataclasses import replace

import cv2
import numpy as np

from app.vision.motion_tracking import PlanarFlow, transform


class PoseContinuity:
    def __init__(self, lease_ms=1500., max_gap_ms=400.):
        self.lease_ms = lease_ms
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self):
        self.flow = None
        self.frame_id = self.ts_ms = self.confirmed_ts = None
        self.scale = None
        self.semantic_corners = None
        self.evidence = {}

    @staticmethod
    def gray(frame):
        scale = min(1., 960. / max(frame.shape[:2]))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return gray, scale

    def seed(self, frame, corners, frame_id, ts_ms, support_quad=None):
        gray, scale = self.gray(frame)
        flow = PlanarFlow()
        if not flow.seed(gray, np.asarray(corners if support_quad is None else support_quad, np.float32) * scale):
            self.reset()
            return
        self.flow, self.scale = flow, scale
        self.semantic_corners = np.asarray(corners, np.float32).copy()
        self.frame_id, self.ts_ms, self.confirmed_ts = frame_id, ts_ms, ts_ms

    def propose(self, frame, observation, frame_id, ts_ms):
        self.evidence = {'accepted': False, 'source': 'webcam_pcb_flow'}
        if self.flow is None:
            self.evidence['reason'] = 'no_accepted_anchor'
            return None
        if (frame_id <= self.frame_id or not 0 < ts_ms-self.ts_ms <= self.max_gap_ms
                or ts_ms-self.confirmed_ts > self.lease_ms):
            self.reset()
            self.evidence = {'accepted': False, 'reason': 'anchor_expired'}
            return None
        if observation is None or observation.landmarks_px is not None:
            self.evidence['reason'] = 'no_current_semantic_pose'
            return None
        gray, scale = self.gray(frame)
        if scale != self.scale or gray.shape != self.flow.gray.shape:
            self.reset()
            return None
        raw = np.asarray(observation.corners_px, np.float32)
        if raw.shape != (4, 2) or not np.isfinite(raw).all() or not cv2.isContourConvex(raw):
            self.evidence['reason'] = 'invalid_current_pose'
            return None
        # Local matching only: re-identifying a distant object stays with the
        # model/reference path, rather than moving this anchor across the scene.
        matrix = self.flow.step(gray, ts_ms=ts_ms, search_budget=lambda: False)
        self.frame_id, self.ts_ms = frame_id, ts_ms
        if matrix is None:
            self.evidence['reason'] = self.flow.failure_reason
            return None
        self.semantic_corners = transform(self.semantic_corners * scale, matrix) / scale
        corners = self.semantic_corners
        error = float(np.max(np.linalg.norm(corners-raw, axis=1)))
        diagonal = max(float(np.linalg.norm(corners[2]-corners[0])), 1.)
        # This is a coarse identity agreement, NOT the GPIO error tolerance:
        # returned coordinates come exclusively from subpixel image matches.
        limit = min(18., max(3., .04*diagonal))
        self.evidence.update(model_delta_px=round(error, 3), identity_limit_px=round(limit, 3),
                             image_error_px=round(self.flow.error_px/scale, 3),
                             inliers=self.flow.support, support_ratio=round(self.flow.support_ratio, 3),
                             anchor_age_ms=ts_ms-self.confirmed_ts)
        if error > limit or self.flow.error_px/scale > 2.:
            self.evidence['reason'] = 'model_image_disagreement'
            return None
        self.evidence.update(accepted=True, reason='current_image_support')
        # Only strict fresh model agreement renews semantics. Broad box/pose
        # agreement alone must expire even if background flow appears stable.
        if error <= 3. and not self.flow.partial:
            self.confirmed_ts = ts_ms
        return replace(observation, corners_px=corners.astype(float),
                       box_xyxy=tuple(np.r_[corners.min(0), corners.max(0)]),
                       source='webcam_pcb_flow')
