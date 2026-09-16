"""Thread-safe latest-value holder for the most recent WireTraceResult.

Structurally identical to app.vision_worker.DetectionState (a Lock guarding
get()/set()) - kept as its own small class, not merged into DetectionState,
because it is written by a different producer thread (WireTraceWorker, on
its own throttled cadence) than DetectionState (VisionWorker, up to
detection_hz). One holder per producer keeps the "who writes this" question
unambiguous, same reasoning app.vision_worker.DetectionState already
established for board pose.
"""
from __future__ import annotations

import threading

from app.vision.wire_tracer import WireTraceResult


class WireTraceState:
    """Thread-safe latest-value holder for the most recent WireTraceResult."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._result: WireTraceResult | None = None

    def set(self, result: WireTraceResult) -> None:
        with self._lock:
            self._result = result

    def get(self) -> WireTraceResult | None:
        with self._lock:
            return self._result

    def clear(self) -> None:
        with self._lock:
            self._result = None
