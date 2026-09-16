"""CaptureService: owns the thread that pulls frames from a FrameSource and
pushes them into the FrameBus. Never lets a source error kill the loop."""
from __future__ import annotations

import logging
import threading

from app.capture.bus import FrameBus

log = logging.getLogger(__name__)


class CaptureService:
    def __init__(self, source, bus: FrameBus, name: str = "capture") -> None:
        self._source = source
        self._bus = bus
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._name = name

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=self._name, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self._source.open()
        except Exception:
            log.exception("frame source open() failed; read loop will keep retrying")
        while not self._stop.is_set():
            try:
                item = self._source.read()
            except Exception:
                # Sources should not raise, but never crash the app if they do.
                log.exception("frame source read() raised")
                self._stop.wait(0.1)
                continue
            if item is None:
                self._stop.wait(0.005)
                continue
            if self._stop.is_set():
                break
            if len(item) == 4:
                frame, frame_id, ts_ms, jpeg = item
            elif len(item) == 3:
                frame, frame_id, ts_ms = item
                jpeg = None
            else:
                log.warning("frame source returned an invalid %d-item sample", len(item))
                continue
            self._bus.put(frame, frame_id, ts_ms, jpeg=jpeg)
        try:
            self._source.close()
        except Exception:
            log.exception("frame source close() failed")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("Camera capture has not stopped")
            self._thread = None
