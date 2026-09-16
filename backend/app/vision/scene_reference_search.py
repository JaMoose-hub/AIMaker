"""Bounded, current-image recovery from an already calibrated PCB reference.

Search windows only bound SIFT computation: neither a window nor a previous
quad is ever returned as a board observation. All existing correspondence,
coverage, reprojection and geometry checks remain authoritative.
"""
from types import SimpleNamespace

import numpy as np


class SceneReferenceSearch:
    def __init__(self, matcher, interval_ms=500, local_lease_ms=1500):
        self.matcher = matcher
        self.interval_ms = float(interval_ms)
        self.local_lease_ms = float(local_lease_ms)
        self.reset()

    def reset(self):
        self._frame_id = None
        self._ts_ms = None
        self._size = None
        self._last_global = None
        self._box = None
        self._confirmed_ms = None
        self.evidence = {}

    def locate(self, frame, frame_id, ts_ms):
        self.evidence = {'source': 'reference_sift', 'accepted': False}
        if frame is None or frame.size == 0 or not np.isfinite(ts_ms):
            self.reset()
            return None
        size = frame.shape[:2]
        if (size != self._size or (self._ts_ms is not None and
                (ts_ms < self._ts_ms or frame_id < self._frame_id))):
            self.reset()
        if frame_id == self._frame_id or ts_ms == self._ts_ms:
            self.evidence['reason'] = 'duplicate_frame'
            return None
        self._size, self._frame_id, self._ts_ms = size, frame_id, ts_ms
        # First search around the last *verified* board. Fresh matching is
        # still required, so a covered/removed board cannot persist here.
        windows = []
        if self._box is not None and ts_ms - self._confirmed_ms <= self.local_lease_ms:
            windows.append(('local_reference', self._box))
        if self._last_global is None or ts_ms - self._last_global >= self.interval_ms:
            windows.append(('scene_reference', (0, 0, size[1], size[0])))
        total_ms = 0.0
        for scope, box in windows:
            if scope == 'scene_reference':
                self._last_global = ts_ms
            # A region is not a YOLO detection; confidence is explicitly zero.
            result = self.matcher.locate(frame, SimpleNamespace(box_xyxy=box, confidence=0.0))
            total_ms += float(self.matcher.evidence.get('ms', 0))
            self.evidence = {**self.matcher.evidence, 'scope': scope, 'ms': round(total_ms, 2)}
            if result is not None:
                self._box = tuple(result.box_xyxy)
                self._confirmed_ms = ts_ms
                return result
        if not windows:
            self.evidence['reason'] = 'scene_search_cooldown'
        return None

    def recent(self, ts_ms):
        return self._confirmed_ms is not None and 0 <= ts_ms-self._confirmed_ms <= 750
