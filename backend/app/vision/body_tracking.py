"""Object-body evidence for display only; never authorizes semantic pins.

The source detector owns identity. LK transports its box onto the current
camera image for at most 650 ms; no prediction, old-box hold or wide search.
"""
from __future__ import annotations

from copy import deepcopy
import logging

import numpy as np

from app.vision.motion_tracking import PlanarFlow

log = logging.getLogger(__name__)


def body_observation(observation, frame_size, source="pose_model"):
    if observation is None:
        return None
    box = np.asarray(observation.box_xyxy, dtype=float)
    width, height = frame_size
    if box.shape != (4,) or not np.isfinite(box).all():
        return None
    x1, y1, x2, y2 = box
    if (x2 - x1 < 16 or y2 - y1 < 16
            or (x2 - x1) * (y2 - y1) > width * height * .75
            or x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height
            or not np.isfinite(observation.confidence)):
        return None
    box = np.clip(box, [2, 2, 2, 2], [width-3, height-3, width-3, height-3])
    return {"box": box.round(2).tolist(),
            "confidence": round(float(observation.confidence), 4), "source": source}


class BodyFallback:
    """A second, existing Pi model used only for object boxes at <= 3 Hz.

    No result is retained here: skipped calls emit no new observation. The
    display tracker alone owns the short, timestamped image-evidence lease.
    """
    def __init__(self, locator, interval_ms=350):
        self.locator = locator
        self.interval_ms = interval_ms
        self.last_ts = float('-inf')

    def detect(self, frame, ts_ms):
        if 0 <= ts_ms - self.last_ts < self.interval_ms:
            return None
        self.last_ts = ts_ms
        try:
            return body_observation(self.locator.locate(frame),
                                    (frame.shape[1], frame.shape[0]), "pi_body_fallback")
        except Exception:
            log.exception('body-only fallback failed; preserving primary pose')
            return None

    def close(self):
        self.locator.close()


class BodyTrack:
    def __init__(self, lease_ms=650):
        self.flow = PlanarFlow()
        self.lease_ms = lease_ms
        self.seen_frame = -1
        self.body = None
        self.source_ts = 0
        self.source_frame = -1
        self.scale = 1.

    def observe(self, message, gray, scale):
        frame_id = message['frame_id']
        if frame_id <= self.seen_frame:
            return
        self.seen_frame = frame_id
        body = message.get('body')
        if body is None:
            return
        x1, y1, x2, y2 = body['box']
        quad = np.asarray([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]) * scale
        if not self.flow.seed(gray, quad):
            # A failed fresh seed cannot renew the old observation's lease.
            return
        self.body = deepcopy(body)
        self.source_ts, self.source_frame = message['ts_ms'], frame_id
        self.scale = scale

    def update(self, gray, frame_id, ts_ms):
        age = ts_ms - self.source_ts
        if self.body is None or not 0 <= age <= self.lease_ms:
            self.body = None
            return None
        if frame_id != self.source_frame:
            matrix = self.flow.step(gray, ts_ms=ts_ms, search_budget=lambda: False)
            # Partial support can still identify the body. PlanarFlow has
            # already checked spread, forward/backward error and RANSAC; it
            # does not authorize hidden pins, and cannot extend our lease.
            if matrix is None:
                self.body = None
                return None
        outline = self.flow.quad / self.scale
        return {**self.body, 'outline': outline.round(1).tolist(),
                'partial': bool(self.flow.partial),
                'frame_id': frame_id, 'source_frame_id': self.source_frame,
                'age_ms': round(age, 2), 'display_only': True}
