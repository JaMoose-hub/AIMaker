"""Acquire a moving PCB by comparing poses in image-aligned coordinates.

Four nearby screen coordinates are not four consistent poses when the board
is moving. This bounded window removes measured planar image motion first,
then tests agreement of independent model observations. It never initializes
from a missing model, a box, a hand-only flow or a predicted velocity.
"""
import cv2
import numpy as np

from app.vision.motion_tracking import PlanarFlow, transform
from app.vision.pose_continuity import PoseContinuity


class ImagePoseWindow:
    def __init__(self, required=4, max_gap_ms=400):
        self.required = max(4, int(required))
        self.max_gap_ms = max_gap_ms
        self.reset()

    def reset(self):
        self.flow = None
        self.matrix = np.eye(3)
        self.samples = []
        self.frame_id = self.ts_ms = self.scale = None
        self.started_ts = None
        self.bridge_frames = 0
        self.evidence = {'accepted': False, 'source': 'image_aligned_pose_window'}

    def _seed(self, gray, scale, corners, frame_id, ts_ms, support_quad):
        self.reset()
        flow = PlanarFlow()
        if flow.seed(gray, support_quad * scale):
            self.flow, self.scale = flow, scale
            self.frame_id, self.ts_ms = frame_id, ts_ms
            self.started_ts = ts_ms
            self.samples = [corners.copy()]
        self.evidence.update(count=len(self.samples), reason=flow.failure_reason or 'collecting')

    def update(self, frame, corners, frame_id, ts_ms, tolerance_px=3, support_quad=None):
        self.evidence = {'accepted': False, 'source': 'image_aligned_pose_window'}
        corners = np.asarray(corners, np.float32)
        if (frame is None or frame.size == 0 or corners.shape != (4, 2)
                or not np.isfinite(corners).all() or not np.isfinite(ts_ms)
                or not cv2.isContourConvex(corners)):
            self.reset()
            return None
        gray, scale = PoseContinuity.gray(frame)
        support_quad = corners if support_quad is None else np.asarray(support_quad, np.float32)
        if (self.flow is None or gray.shape != self.flow.gray.shape or scale != self.scale
                or not 0 < ts_ms-self.ts_ms <= self.max_gap_ms or frame_id <= self.frame_id
                or ts_ms-self.started_ts > 1500):
            self._seed(gray, scale, corners, frame_id, ts_ms, support_quad)
            return None
        if not self._advance_gray(gray, scale, frame_id, ts_ms):
            self._seed(gray, scale, corners, frame_id, ts_ms, support_quad)
            self.evidence['reason'] = 'image_support_interrupted'
            return None
        aligned = transform(corners, np.linalg.inv(self.matrix))
        self.frame_id, self.ts_ms = frame_id, ts_ms
        center = np.mean(self.samples, axis=0)
        # A different order/object cannot be averaged into a plausible pose.
        if (not np.isfinite(aligned).all()
                or np.max(np.linalg.norm(aligned-center, axis=1)) > 4*tolerance_px):
            self._seed(gray, scale, corners, frame_id, ts_ms, support_quad)
            self.evidence['reason'] = 'semantic_disagreement'
            return None
        self.samples.append(aligned)
        self.samples = self.samples[-self.required:]
        self.evidence.update(count=len(self.samples), required=self.required,
                             inliers=self.flow.support, image_error_px=self.flow.error_px/scale,
                             bridge_frames=self.bridge_frames)
        if len(self.samples) < self.required:
            self.evidence['reason'] = 'collecting'
            return None
        values = np.asarray(self.samples)
        split = len(values)//2
        # Keep the old 3px agreement scale, now in a common board coordinate
        # frame. Both halves must agree; one good last frame is insufficient.
        drift = float(np.max(np.linalg.norm(values[:split].mean(0)-values[split:].mean(0), axis=1)))
        mean = values.mean(0)
        error = float(np.max(np.sqrt(np.mean(np.sum((values-mean)**2, axis=2), axis=0)/len(values))))
        self.evidence.update(half_window_delta_px=drift, mean_spread_px=error)
        if drift > tolerance_px or error > tolerance_px:
            self.evidence['reason'] = 'window_not_consistent'
            return None
        result = transform(mean, self.matrix)
        if not np.isfinite(result).all() or not cv2.isContourConvex(result.astype(np.float32)):
            self.reset()
            return None
        self.evidence.update(accepted=True, reason='image_aligned_consensus')
        return result

    def _advance_gray(self, gray, scale, frame_id, ts_ms):
        if (self.flow is None or gray.shape != self.flow.gray.shape or scale != self.scale
                or not 0 < ts_ms-self.ts_ms <= self.max_gap_ms or frame_id <= self.frame_id
                or ts_ms-self.started_ts > 1500):
            return False
        step = self.flow.step(gray, ts_ms=ts_ms, search_budget=lambda: False)
        if step is None or self.flow.partial or self.flow.error_px/scale > 2:
            return False
        scaling = np.diag([scale, scale, 1.0])
        self.matrix = np.linalg.inv(scaling) @ step @ scaling @ self.matrix
        self.frame_id, self.ts_ms = frame_id, ts_ms
        return True

    def advance(self, frame, frame_id, ts_ms):
        """Consume a real intermediate image, never a new semantic vote.

        Owned by the component worker thread. No overlay is published and no
        model/visibility lease is renewed. Failure invalidates the whole window.
        """
        if self.flow is None:
            return False
        gray, scale = PoseContinuity.gray(frame)
        if not self._advance_gray(gray, scale, frame_id, ts_ms):
            self.reset()
            self.evidence['reason'] = 'intermediate_image_support_interrupted'
            return False
        self.bridge_frames += 1
        return True
