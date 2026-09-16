"""FrameBus: thread-safe single-slot holder for the latest camera frame.

- put() never blocks and never queues: it overwrites the slot and wakes waiters.
- get_latest(timeout) returns the newest frame or None on timeout.
- get_latest(..., newer_than=seq) waits for a frame *newer* than `seq`, which
  lets consumers (MJPEG clients, vision worker) avoid re-processing the same
  frame in a tight loop.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FrameSlot:
    frame: np.ndarray  # BGR uint8 (H, W, 3)
    frame_id: int
    ts_ms: float  # time.monotonic() * 1000 at capture
    seq: int  # bus-local monotonically increasing sequence number
    # Exact camera JPEG when the source supplies one.  /video can pass this
    # through without spending CPU re-encoding the same 1080p frame.
    jpeg: bytes | None = None


class FrameBus:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._slot: FrameSlot | None = None
        self._seq = 0

    def put(self, frame: np.ndarray, frame_id: int, ts_ms: float,
            jpeg: bytes | None = None) -> None:
        """Store the newest frame. Never blocks (single slot, overwrite)."""
        with self._cond:
            self._seq += 1
            self._slot = FrameSlot(
                frame=frame,
                frame_id=frame_id,
                ts_ms=ts_ms,
                seq=self._seq,
                jpeg=jpeg,
            )
            self._cond.notify_all()

    def get_latest(self, timeout: float | None = None, newer_than: int | None = None) -> FrameSlot | None:
        """Return the newest FrameSlot, or None if none arrives within timeout.

        If `newer_than` is given, only a slot with seq > newer_than qualifies;
        otherwise any stored slot qualifies immediately.
        """
        min_seq = -1 if newer_than is None else newer_than
        with self._cond:
            ok = self._cond.wait_for(
                lambda: self._slot is not None and self._seq > min_seq,
                timeout=timeout,
            )
            return self._slot if ok else None

    @property
    def latest_seq(self) -> int:
        with self._cond:
            return self._seq

    def clear(self) -> None:
        """Forget the previous camera image without rewinding consumer cursors."""
        with self._cond:
            self._slot = None
            self._cond.notify_all()
