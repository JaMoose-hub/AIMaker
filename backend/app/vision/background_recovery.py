"""One background descriptor proposal; only foreground LK may accept it."""
from concurrent.futures import ThreadPoolExecutor
import numpy as np

from app.vision.motion_tracking import PlanarFlow


class BackgroundRecovery:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='webcam-recovery')
        self.pending = None
        self.closed = False
        self.samples = []

    def observe(self, flow, ts_ms):
        if self.samples and (self.samples[-1][0] is not flow or self.samples[-1][1] is not flow.anchor):
            self.samples = []
        if not self.samples or ts_ms > self.samples[-1][2]:
            self.samples.append((flow, flow.anchor, ts_ms, flow.quad.copy()))
            self.samples = self.samples[-2:]

    def search_quad(self, flow, ts_ms):
        if len(self.samples) == 2:
            a, b = self.samples
            dt, age = b[2]-a[2], ts_ms-b[2]
            if b[0] is flow and b[1] is flow.anchor and 0 < dt <= 100 and 0 <= age <= 120:
                shift = (b[3]-a[3])*(age/dt)
                if np.isfinite(shift).all() and np.max(np.linalg.norm(shift, axis=1)) <= np.linalg.norm(b[3][2]-b[3][0])*.15:
                    return b[3]+shift
        return flow.quad.copy()

    def close(self):
        self.closed = True
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.pending = None

    def propose(self, flow, gray, ts_ms, allow_submit):
        hint = None
        if self.pending is not None:
            owner, anchor, submitted, future = self.pending
            if future.done():
                self.pending = None
                try:
                    candidate = future.result()
                except Exception:
                    candidate = None
                if owner is flow and anchor is flow.anchor and 0 <= ts_ms-submitted <= 150:
                    hint = candidate
        submitted_now = False
        if hint is None and allow_submit and self.pending is None and not self.closed:
            # Private OpenCV instance and pose arrays: the job cannot mutate
            # live flow, pins, leases or descriptor caches. Images are immutable.
            clone = PlanarFlow(pi5_cable_guard=flow.pi5_cable_guard)
            clone.anchor = flow.anchor
            clone.quad = flow.quad.copy()
            clone.search_quad = self.search_quad(flow, ts_ms)
            clone.anchor_matrix = flow.anchor_matrix.copy()
            future = self.pool.submit(clone._wide_search, gray)
            self.pending = (flow, flow.anchor, ts_ms, future)
            submitted_now = True
        return hint, submitted_now
