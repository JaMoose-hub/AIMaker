"""FrameSource adapter for the proven native-resolution R1 RGB capture path."""
from __future__ import annotations

from collections import deque
import ctypes
import itertools
import multiprocessing as mp
from queue import Empty
import threading
import time

from .worker import MAX_BYTES, camera_worker
from .quality import RgbDenoiser
from .cuda_quality import create_eye_denoiser
from app.eye_timing import wait_eye_deadline

import cv2
import numpy as np

RESOLUTIONS = ((1920, 1080), (2048, 1512), (1080, 1920), (720, 1280))
# 25 FPS is advertised by R1 but stalled during real-device negotiation.
CAMERA_FPS = (30, 60)
DENOISE_MODES = RgbDenoiser.MODES
_FRAME_IDS = itertools.count(1)


def _rate(points) -> float:
    if len(points) < 2 or points[-1][0] <= points[0][0]:
        return 0.0
    return (points[-1][1] - points[0][1]) / (points[-1][0] - points[0][0])


class XrealEyeSource:
    """CaptureService reads latest frames; only a spawned child opens the camera.

    ``open`` starts asynchronously. ``read`` waits at most 200 ms for a new
    capture, apart from processing an available image. Driver failures remain
    visible in ``snapshot`` until the caller explicitly opens a new session.
    """

    def __init__(self, width: int = 1920, height: int = 1080, fps: int = 30,
                 denoise: str = "clean", reinitialize: bool = False):
        if (width, height) not in RESOLUTIONS or fps not in CAMERA_FPS:
            raise ValueError("Unsupported R1 resolution or FPS")
        if denoise not in DENOISE_MODES:
            raise ValueError("Unsupported R1 denoise mode")
        self.width, self.height, self.fps = width, height, fps
        self.denoise = denoise
        self.reinitialize = reinitialize
        self._lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._denoiser_lock = threading.RLock()
        self._closed = threading.Event()
        self._closed.set()
        self._process = self._messages = self._stop_child = None
        self._quality_revision = 0
        self._active_quality_revision = -1
        self._denoiser = None
        self._info = self._empty_info("stopped")
        self._last_stamp = 0.0

    def _empty_info(self, state: str) -> dict:
        return {"state": state, "stage": state, "error": None,
                "requested": {"width": self.width, "height": self.height,
                              "fps": self.fps, "denoise": self.denoise},
                "actual": None, "capture_fps": 0.0, "processing_fps": 0.0,
                "capture_frames": 0, "processed_frames": 0,
                "denoise_backend": "pending" if state == "starting" else "none",
                "denoise_fallback_reason": None,
                "frame_age_seconds": None}

    def open(self) -> None:
        with self._lifecycle_lock:
            if self._process is not None:
                self.close()
            self._closed.clear()
            self._started = time.monotonic()
            self._last_stamp = self._last_sequence = self._processed = 0
            self._next_due = 0.0
            self._last_processed_at = 0.0
            self._capture_points, self._processed_points = deque(), deque()
            self._active_quality_revision = -1
            with self._lock:
                self._info = self._empty_info("starting")
            try:
                context = mp.get_context("spawn")
                self._pixels = context.RawArray(ctypes.c_ubyte, MAX_BYTES)
                self._metadata = context.RawArray(ctypes.c_int64, 4)
                self._frame_lock = context.Lock()
                self._stop_child = context.Event()
                self._messages = context.Queue(maxsize=16)
                self._process = context.Process(
                    target=camera_worker,
                    args=({"width": self.width, "height": self.height, "fps": self.fps},
                          self._pixels, self._metadata, self._frame_lock,
                          self._stop_child, self._messages, self.reinitialize),
                    name="BoardVision-Eye-Capture", daemon=True,
                )
                self._process.start()
            except Exception as exc:
                self._fail(str(exc))

    def set_denoise(self, mode: str) -> None:
        if mode not in DENOISE_MODES:
            raise ValueError("Unsupported R1 denoise mode")
        with self._lock:
            if self.denoise != mode:
                self.denoise = mode
                self._quality_revision += 1
                self._info["requested"] = dict(self._info["requested"], denoise=mode)
                self._info.update(denoise_backend="pending", denoise_fallback_reason=None)

    def snapshot(self) -> dict:
        with self._lock:
            result = dict(self._info)
            result["requested"] = dict(result["requested"])
            if result["actual"] is not None:
                result["actual"] = dict(result["actual"])
            if self._last_stamp:
                result["frame_age_seconds"] = round(time.monotonic() - self._last_stamp, 3)
            return result

    def _release(self) -> None:
        with self._lifecycle_lock:
            process, messages = self._process, self._messages
            self._process = self._messages = None
            if process is not None:
                self._stop_child.set()
                try:
                    process.join(timeout=1.5)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1.5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=1.0)
                    if process.is_alive():
                        raise RuntimeError("Windows did not release the R1 capture process")
                except AssertionError:
                    # A process whose start() failed has no joinable child.
                    pass
                finally:
                    if not process.is_alive():
                        process.close()
            if messages is not None:
                messages.close()
                messages.cancel_join_thread()
            with self._denoiser_lock:
                if self._denoiser is not None:
                    self._denoiser.close()
                    self._denoiser = None
                self._active_quality_revision = -1

    def _fail(self, error: str) -> None:
        with self._lock:
            self._info.update(state="error", error=error,
                              capture_fps=0.0, processing_fps=0.0)
        self._release()

    def close(self) -> None:
        self._closed.set()
        self._release()
        with self._lock:
            self._info.update(state="stopped", stage="stopped",
                              denoise_backend="none",
                              capture_fps=0.0, processing_fps=0.0)
        # Windows needs a short gap before another Media Foundation reader opens.
        time.sleep(0.25)

    def read(self):
        deadline = time.perf_counter() + 0.2
        while not self._closed.is_set() and time.perf_counter() < deadline:
            process, messages = self._process, self._messages
            if process is None:
                self._closed.wait(0.05)
                return None
            try:
                while True:
                    try:
                        message = messages.get_nowait()
                    except Empty:
                        break
                    with self._lock:
                        self._info.update(message)
                with self._lock:
                    error = self._info.get("error")
                    quality, quality_revision = self.denoise, self._quality_revision
                if error:
                    self._fail(error)
                    return None
                now = time.monotonic()
                schedule_now = time.perf_counter()
                raw = None
                if self._frame_lock.acquire(timeout=0.01):
                    try:
                        seq, width, height, stamp_ns = tuple(self._metadata)
                        stamp = stamp_ns / 1e9
                        if seq > self._last_sequence and schedule_now >= self._next_due:
                            raw = np.frombuffer(self._pixels, dtype=np.uint8,
                                                count=width * height * 3).reshape(
                                                    height, width, 3).copy()
                    finally:
                        self._frame_lock.release()
                else:
                    wait_eye_deadline(self._closed, time.perf_counter() + .002)
                    continue
                age = now - (stamp if seq else self._started)
                if age > (8 if seq else 35):
                    self._fail("No new R1 frames. Apply 1080p / 30 FPS, or reconnect USB-C.")
                    return None
                if not process.is_alive():
                    self._fail("R1 capture process exited. Apply the camera settings again.")
                    return None
                if seq:
                    self._last_stamp = stamp
                    if not self._capture_points or seq != self._capture_points[-1][1]:
                        self._capture_points.append((stamp, seq))
                        while len(self._capture_points) > 2 and self._capture_points[0][0] < now - 3:
                            self._capture_points.popleft()
                    with self._lock:
                        self._info.update(
                            actual={"width": width, "height": height,
                                    "fps": self._info.get("driver_reported", {}).get("fps")},
                            capture_frames=seq, capture_fps=_rate(self._capture_points),
                            frame_age_seconds=round(age, 3))
                if raw is None:
                    wait_eye_deadline(self._closed, time.perf_counter() + .002)
                    continue
                begun = time.perf_counter()
                with self._denoiser_lock:
                    if self._closed.is_set():
                        return None
                    if quality_revision != self._active_quality_revision:
                        if self._denoiser is not None:
                            self._denoiser.close()
                        self._denoiser = create_eye_denoiser(quality)
                        self._active_quality_revision = quality_revision
                    if now - self._last_processed_at > 0.5:
                        self._denoiser.reset()
                    enhanced = self._denoiser.process(raw)
                    denoise_backend = self._denoiser.backend
                    denoise_fallback_reason = self._denoiser.fallback_reason
                ok, encoded = cv2.imencode(".jpg", enhanced, [cv2.IMWRITE_JPEG_QUALITY, 95])
                if not ok:
                    raise RuntimeError("Could not encode the R1 preview")
                self._last_sequence = seq
                self._next_due = max(self._next_due + 1 / self.fps, schedule_now)
                with self._lock:
                    # A hot setting or close invalidates the image already in flight.
                    if self._closed.is_set() or quality_revision != self._quality_revision:
                        continue
                    self._processed += 1
                    finished = self._last_processed_at = time.monotonic()
                    self._processed_points.append((finished, self._processed))
                    while len(self._processed_points) > 2 and self._processed_points[0][0] < finished - 3:
                        self._processed_points.popleft()
                    self._info.update(state="live", stage="live", processed_frames=self._processed,
                                      processing_fps=_rate(self._processed_points),
                                      processing_ms=(time.perf_counter() - begun) * 1000,
                                      denoise_backend=denoise_backend,
                                      denoise_fallback_reason=denoise_fallback_reason,
                                      quality=quality)
                    return enhanced, next(_FRAME_IDS), stamp * 1000, encoded.tobytes()
            except Exception as exc:
                if not self._closed.is_set():
                    self._fail(str(exc))
                return None
        return None
