"""Confirm a moving board AND its final pins in image-motion coordinates."""
import numpy as np

from app.vision.motion_tracking import PlanarFlow, transform
from app.vision.pose_continuity import PoseContinuity


class ImageMotionGate:
    def __init__(self, required=4):
        self.required = max(4, int(required))
        self.reset()

    def reset(self):
        self.flow = None
        self.pins = self.ids = self.scale = self.frame_id = self.ts_ms = None
        self.count = 0
        self.window = []
        self.ready_outline = self.ready_pins = None
        self.evidence = {'accepted':False, 'source':'image_motion_gate'}

    def compare(self, frame, outline, pins, frame_id, ts_ms):
        self.evidence = {'accepted':False, 'source':'image_motion_gate'}
        # A rejected sample must never expose the last accepted geometry.
        self.ready_outline = self.ready_pins = None
        gray, scale = PoseContinuity.gray(frame)
        quad = np.asarray(outline, np.float32)
        xy = np.asarray([[p.x,p.y] for p in pins], dtype=float)
        ids = tuple(p.pin_id for p in pins)
        if (quad.shape != (4,2) or not len(xy) or not np.isfinite(quad).all()
                or not np.isfinite(xy).all() or not np.isfinite(ts_ms)):
            self.reset()
            return False
        agrees = False
        if (self.flow is not None and self.ids == ids and self.scale == scale
                and self.flow.gray.shape == gray.shape and frame_id > self.frame_id
                and 0 < ts_ms-self.ts_ms <= 400):
            step = self.flow.step(gray, ts_ms=ts_ms, search_budget=lambda:False)
            if step is not None and not self.flow.partial:
                board_error = float(np.max(np.linalg.norm(self.flow.quad/scale-quad, axis=1)))
                predicted = transform(self.pins*scale, step)/scale
                pin_error = float(np.max(np.linalg.norm(predicted-xy, axis=1)))
                agrees = board_error <= 12 and pin_error <= 6 and self.flow.error_px/scale <= 2
                if agrees:
                    self.window = [(transform(q*scale,step)/scale,transform(p*scale,step)/scale) for q,p in self.window]
                self.evidence.update(board_delta_px=board_error, pin_delta_px=pin_error,
                                     image_error_px=self.flow.error_px/scale, inliers=self.flow.support)
        if not agrees:
            self.window = []
        self.window.append((quad.copy(), xy.copy()))
        self.window = self.window[-self.required:]
        self.count = len(self.window)
        # Each step is independently anchored to its paired candidate image.
        # No integrated transform or old final pins can renew this gate.
        candidate = PlanarFlow()
        self.flow = candidate if candidate.seed(gray, quad*scale) else None
        if self.flow is None:
            self.count = 0
            self.window = []
        self.pins, self.ids, self.scale = xy, ids, scale
        self.frame_id, self.ts_ms = frame_id, ts_ms
        accepted = False
        if self.count >= self.required:
            quads = np.asarray([q for q,p in self.window])
            positions = np.asarray([p for q,p in self.window])
            split = self.required//2
            board_delta = float(np.max(np.linalg.norm(quads[:split].mean(0)-quads[split:].mean(0),axis=1)))
            pin_delta = float(np.max(np.linalg.norm(positions[:split].mean(0)-positions[split:].mean(0),axis=1)))
            self.evidence.update(window_board_delta_px=board_delta, window_pin_delta_px=pin_delta)
            accepted = board_delta <= 3 and pin_delta <= 1.5
            if accepted:
                self.ready_outline, self.ready_pins = quads.mean(0), positions.mean(0)
        self.evidence.update(accepted=accepted, count=self.count, required=self.required)
        return accepted
