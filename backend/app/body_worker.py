"""Independent Pi body identity cadence; never waits on GPIO feature search."""
from __future__ import annotations

import threading
import time

from app.vision.body_tracking import BodyFallback


class BodyVisionWorker:
    def __init__(self, bus, runtime_manager, demand, locator, interval_ms=350):
        self.bus, self.runtime_manager, self.demand = bus, runtime_manager, demand
        self.locator, self.interval_ms = locator, interval_ms
        # This worker owns cadence. A second source-timestamp throttle could
        # skip alternating frames (camera quantization around 350 ms).
        self.detector = BodyFallback(locator, interval_ms=0)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pair = None
        self._thread = None

    def get_synchronized(self):
        with self._lock:
            return self._pair

    def process(self, slot):
        runtime = self.runtime_manager.snapshot()
        body = (self.detector.detect(slot.frame, slot.ts_ms)
                if runtime.board_id == 'raspberry-pi-5' else None)
        message = {'body': body, 'frame_id': slot.frame_id, 'ts_ms': slot.ts_ms,
                   'board_id': runtime.board_id, 'runtime_revision': runtime.runtime_revision}
        # One immutable source/result pair, including explicit misses.
        with self._lock:
            self._pair = (slot, message)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='pi-body-vision', daemon=True)
        self._thread.start()

    def _run(self):
        seq = -1
        while not self._stop.is_set():
            if not self.demand.requested() or self.runtime_manager.snapshot().board_id != 'raspberry-pi-5':
                with self._lock:
                    self._pair = None
                self._stop.wait(.1)
                continue
            slot = self.bus.get_latest(timeout=.1, newer_than=seq)
            if slot is None:
                continue
            seq = slot.seq
            started = time.monotonic()
            self.process(slot)
            self._stop.wait(max(0, self.interval_ms / 1000 - (time.monotonic() - started)))

    def stop(self, *, close_models=True):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError('body worker did not stop')
            self._thread = None
        if close_models:
            self.detector.close()
        self.reset_tracking()

    def reset_tracking(self):
        """Forget source evidence while retaining the body's loaded locator."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError('stop body worker before resetting tracking')
        self.detector.last_ts = float('-inf')
        with self._lock:
            self._pair = None
