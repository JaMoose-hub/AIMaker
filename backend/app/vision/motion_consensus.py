"""Image-compensated acquisition evidence, never velocity prediction.

The last candidate's PCB texture must move to the next candidate's semantic
corners. A moving hand/background or reordered model corners cannot establish
the sequence. Existing temporal count and corner tolerance stay unchanged.
"""
import cv2
import numpy as np

from app.vision.motion_tracking import PlanarFlow


class MotionConsensus:
    def __init__(self):
        self.flow = None
        self.scale = None
        self.frame_id = None
        self.ts_ms = None
        self.evidence = {}

    def compare(self, frame, corners, frame_id, ts_ms, tolerance_px):
        scale = min(1., 960. / max(frame.shape[:2]))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        matched = False
        self.evidence = {'accepted': False, 'source': 'pcb_motion', 'tolerance_px': tolerance_px}
        if (self.flow is not None and scale == self.scale and frame_id > self.frame_id
                and 0 < ts_ms-self.ts_ms <= 1000):
            # No wide search: acquisition is corroboration of adjacent visible
            # candidates, not an unbounded re-identification of another object.
            matrix = self.flow.step(gray, ts_ms=ts_ms, search_budget=lambda: False)
            if matrix is not None and not self.flow.partial:
                error = float(np.max(np.linalg.norm(self.flow.quad/scale-corners, axis=1)))
                matched = error <= tolerance_px
                self.evidence.update(error_px=round(error, 3), inliers=self.flow.support,
                                     support_ratio=round(self.flow.support_ratio, 3))
            else:
                self.evidence['reason'] = self.flow.failure_reason or 'partial_image_support'
        self.evidence['accepted'] = matched
        candidate = PlanarFlow()
        self.flow = candidate if candidate.seed(gray, np.asarray(corners, np.float32)*scale) else None
        self.scale, self.frame_id, self.ts_ms = scale, frame_id, ts_ms
        return matched
