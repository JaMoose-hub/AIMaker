"""Frame sources.

A FrameSource produces (frame_bgr, frame_id, ts_ms) tuples where
ts_ms = time.monotonic() * 1000 at the moment the frame is produced.

Timing contract (see app/vision/synthetic.py): SyntheticCameraSource calls
SyntheticScene.frame_at(t_s) with t_s = the same monotonic seconds used to
stamp ts_ms, and the MockDetector later calls truth_at(ts_ms / 1000.0) — both
sides derive from the same clock so overlay and video agree.
"""
from __future__ import annotations

import logging
from collections import deque
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import
    from app.profiles.models import BoardProfile
    from app.vision.synthetic import SyntheticScene

log = logging.getLogger(__name__)

# FFmpeg/C920 can also return the exact native JPEG that produced frame_bgr.
# CaptureService forwards that optional fourth item to the UI so 1080p video
# does not have to be JPEG-encoded again in Python.
FrameTuple = (
    tuple[np.ndarray, int, float]
    | tuple[np.ndarray, int, float, bytes]
)


def frame_has_signal(frame: np.ndarray | None) -> bool:
    """Return whether a captured frame contains usable non-black signal.

    A DirectShow device can report ``isOpened()`` and a valid-looking
    resolution while returning an all-zero or near-black frame (observed with
    the attached C920 when another application held the stream). A few bright
    sensor/compression speckles must not make that stream look available:
    feeding it into Board Vision creates false searching states and can make a
    camera probe report a usable device that cannot support CV. A mean level
    of 1 on the 8-bit frame is deliberately conservative; truly dark scenes
    are not useful for pin/wire recognition either and should be surfaced as a
    camera-quality failure.
    """
    if frame is None or frame.size == 0:
        return False
    return float(np.mean(frame, dtype=np.float64)) >= 1.0

_REOPEN_INTERVAL_S = 2.0
# UVC/DirectShow devices can emit one or two black frames immediately after a
# format switch while the sensor/decoder warms up.  Probe a small bounded
# number of frames before rejecting the candidate; this is intentionally a
# count, not an unbounded sleep/read loop, because a wedged driver must not
# stall backend startup or camera selection indefinitely.
_PROBE_READ_ATTEMPTS = 3
# Some UVC drivers advertise MJPG at the requested size but return black
# frames. Keep a driver-default escape hatch; it may negotiate a lower size,
# which is still preferable to feeding a black stream into CV (the physical
# scale gate will report the lower resolution honestly).
_CAPTURE_CODECS: tuple[str | None, ...] = ("MJPG", "YUY2", None)
_MAX_MJPEG_BUFFER_BYTES = 32 * 1024 * 1024


def extract_complete_mjpeg_frames(buffer: bytearray) -> list[bytes]:
    """Remove and return every complete JPEG frame currently in *buffer*.

    DirectShow MJPEG packets are ordinary JPEG images concatenated by the
    FFmpeg ``mjpeg`` muxer. JPEG entropy data byte-stuffs literal 0xff bytes,
    so SOI/EOI markers are safe frame boundaries. Keeping an incomplete tail
    lets the next pipe read finish a frame without copying a 1080p raw image
    through the subprocess pipe.
    """
    return MjpegFrameParser(buffer).feed(b'')


class MjpegFrameParser:
    """Keep a scan cursor across small pipe reads, not an O(n^2) JPEG rescan."""
    def __init__(self, buffer: bytearray | None = None):
        self.buffer = buffer if buffer is not None else bytearray()
        self._eoi_from = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        buffer = self.buffer
        buffer.extend(chunk)
        frames = []
        while buffer:
            if not self._eoi_from:
                soi = buffer.find(b'\xff\xd8')
                if soi < 0:
                    # A marker may straddle reads; retain its first byte.
                    buffer[:] = b'\xff' if buffer[-1:] == b'\xff' else b''
                    break
                if soi:
                    del buffer[:soi]
                self._eoi_from = 2
            eoi = buffer.find(b'\xff\xd9', self._eoi_from)
            if eoi < 0:
                self._eoi_from = max(2, len(buffer) - 1)
                if len(buffer) > _MAX_MJPEG_BUFFER_BYTES:
                    newest = buffer.rfind(b'\xff\xd8', 2)
                    if newest > 0:
                        del buffer[:newest]
                        self._eoi_from = 2
                    else:
                        buffer.clear()
                        self._eoi_from = 0
                break
            end = eoi + 2
            # Copy once; bytearray slicing followed by bytes copies twice.
            frames.append(bytes(memoryview(buffer)[:end]))
            del buffer[:end]
            self._eoi_from = 0
        return frames


def read_signal_frame(cap, attempts: int = _PROBE_READ_ATTEMPTS,
                      ) -> tuple[np.ndarray | None, bool]:
    """Read a bounded warm-up window and return ``(frame, saw_frame)``.

    ``saw_frame`` distinguishes an opened-but-black stream from a device
    that never returned a frame.  Both are unusable, but the camera picker
    exposes the distinction to make driver/occupancy failures diagnosable.
    Keeping this helper shared between the live source and the picker avoids
    one entry point accepting a transiently black first frame while the other
    rejects it.
    """
    saw_frame = False
    for _ in range(max(1, int(attempts))):
        try:
            ok, frame = cap.read()
        except Exception:
            continue
        if not ok or frame is None:
            continue
        saw_frame = True
        if frame_has_signal(frame):
            return frame, saw_frame
    return None, saw_frame


@runtime_checkable
class FrameSource(Protocol):
    """Produced frames are BGR uint8 arrays in source-video pixel space."""

    def open(self) -> None: ...

    def read(self) -> FrameTuple | None:
        """Return the next frame, or None if no frame is available right now.

        Must never raise on transient failure - recover internally.
        """
        ...

    def close(self) -> None: ...


class DeviceCameraSource:
    """Physical camera via cv2.VideoCapture (DirectShow by default).

    Robustness: every property set is best-effort (log + continue); read
    failures trigger a reopen attempt at most every 2 s and never raise.

    Thread-safety: ``self._lock`` guards every access to ``self._cap`` (and
    the ``self._index``/``self._frame_id`` bookkeeping that goes with it).
    Two threads touch this object at runtime:

    - CaptureService's read loop thread, which calls ``read()`` in a tight
      loop (and ``read()`` itself calls ``_try_open_locked()`` inline on a
      transient failure).
    - Whichever thread calls ``switch_to()`` to hot-swap the active device
      index (the POST /api/cameras/select request handler, via
      ``loop.run_in_executor`` since this is blocking I/O - see
      app/api/cameras.py).

    Without the lock, ``switch_to()`` could call ``old_cap.release()`` on
    the very same ``cv2.VideoCapture`` object the read-loop thread is
    concurrently blocked inside ``cap.read()`` for - releasing a capture
    handle out from under an in-flight native read is a real crash risk for
    OpenCV's MSMF backend, not merely a Python-level race. The lock is held
    for the full duration of each ``cap.read()``/open/release call (not just
    the pointer swap) so the two operations can never interleave on the same
    handle. This makes ``switch_to()`` block for at most one in-flight
    read/reopen before it can proceed - acceptable since switches are rare,
    user-triggered actions, not something on the hot path.
    """

    def __init__(self, device_index: int, width: int, height: int, fps: float,
                 capture_api: str = "dshow", *, buffer_size: int = 1,
                 lock_auto_focus: bool = False,
                 focus: float | None = None,
                 lock_auto_exposure: bool = False,
                 lock_auto_white_balance: bool = False,
                 exposure: float | None = None,
                 gain: float | None = None,
                 white_balance_temperature: float | None = None) -> None:
        self._index = device_index
        self._width = width
        self._height = height
        self._fps = fps
        self._capture_api = capture_api  # "msmf" | "dshow", see CameraConfig.capture_api
        self._buffer_size = max(1, min(int(buffer_size), 8))
        self._lock_auto_focus = lock_auto_focus
        self._focus = focus
        self._lock_auto_exposure = lock_auto_exposure
        self._lock_auto_white_balance = lock_auto_white_balance
        self._exposure = exposure
        self._gain = gain
        self._white_balance_temperature = white_balance_temperature
        self._cap = None
        self._frame_id = 0
        self._last_open_attempt = float("-inf")
        self._lock = threading.Lock()

    def _cv2_api(self):
        import cv2

        return cv2.CAP_DSHOW if self._capture_api == "dshow" else cv2.CAP_MSMF

    @property
    def current_index(self) -> int:
        """The device index currently backing this source (thread-safe)."""
        with self._lock:
            return self._index

    def open(self) -> None:
        with self._lock:
            self._try_open_locked()

    def _apply_settings(self, cap, index: int, codec: str | None = "MJPG") -> None:
        """Best-effort codec/size/fps and optional UVC image controls.

        DirectShow UVC cameras such as the C920 commonly expose 1920x1080
        only when MJPG is selected *before* the dimensions are requested.
        Applying width/height first can silently negotiate a 1280x720
        uncompressed mode, reducing the physical pin pitch and therefore the
        accuracy of every downstream stage. The order is intentional and is
        used identically for initial open and hot-switch.

        Caller holds self._lock.
        """
        import cv2

        # FrameBus is latest-only. Keeping a driver queue deeper than one
        # frame makes a moving board/wire look like pose lag even when the CV
        # tracker is correct. Not every backend accepts this property, so it
        # remains a best-effort latency hint.
        buffer_prop = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
        if buffer_prop is not None:
            try:
                if not cap.set(buffer_prop, self._buffer_size):
                    log.info("camera %d: buffer_size=%d not accepted",
                             index, self._buffer_size)
            except Exception:
                log.info("camera %d: error setting buffer_size=%d",
                         index, self._buffer_size, exc_info=True)

        if codec is not None:
            try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                if not cap.set(cv2.CAP_PROP_FOURCC, fourcc):
                    log.info("camera %d: %s fourcc not accepted", index, codec)
            except Exception:
                log.info("camera %d: error setting %s fourcc", index, codec, exc_info=True)

            for prop, value, name in (
                (cv2.CAP_PROP_FRAME_WIDTH, self._width, "width"),
                (cv2.CAP_PROP_FRAME_HEIGHT, self._height, "height"),
                (cv2.CAP_PROP_FPS, self._fps, "fps"),
            ):
                try:
                    if not cap.set(prop, value):
                        log.warning("camera %d: could not set %s=%s", index, name, value)
                except Exception:
                    log.warning("camera %d: error setting %s", index, name, exc_info=True)
        if self._lock_auto_focus or self._focus is not None:
            try:
                if not cap.set(cv2.CAP_PROP_AUTOFOCUS, 0):
                    log.info("camera %d: autofocus disable not supported", index)
            except Exception:
                log.info("camera %d: error disabling autofocus", index, exc_info=True)
        if self._focus is not None:
            try:
                if not cap.set(cv2.CAP_PROP_FOCUS, float(self._focus)):
                    log.info("camera %d: focus=%s not accepted", index, self._focus)
            except Exception:
                log.info("camera %d: error setting focus=%s", index, self._focus, exc_info=True)

        # UVC exposure/white-balance controls are deliberately best-effort:
        # OpenCV exposes them inconsistently across DirectShow devices.  Do
        # not fail camera startup merely because one control is unavailable.
        if self._lock_auto_exposure:
            auto_exposure = getattr(cv2, "CAP_PROP_AUTO_EXPOSURE", None)
            if auto_exposure is not None:
                try:
                    if not cap.set(auto_exposure, 0.25):
                        log.info("camera %d: manual exposure mode not supported", index)
                except Exception:
                    log.info("camera %d: error locking auto exposure", index, exc_info=True)
        if self._exposure is not None:
            try:
                if not cap.set(cv2.CAP_PROP_EXPOSURE, float(self._exposure)):
                    log.info("camera %d: exposure=%s not accepted", index, self._exposure)
            except Exception:
                log.info("camera %d: error setting exposure", index, exc_info=True)
        if self._gain is not None:
            try:
                if not cap.set(cv2.CAP_PROP_GAIN, float(self._gain)):
                    log.info("camera %d: gain=%s not accepted", index, self._gain)
            except Exception:
                log.info("camera %d: error setting gain", index, exc_info=True)

        if self._lock_auto_white_balance:
            auto_wb = getattr(cv2, "CAP_PROP_AUTO_WB", None)
            if auto_wb is not None:
                try:
                    if not cap.set(auto_wb, 0):
                        log.info("camera %d: manual white balance not supported", index)
                except Exception:
                    log.info("camera %d: error locking auto white balance", index, exc_info=True)
        if self._white_balance_temperature is not None:
            wb_temperature = getattr(cv2, "CAP_PROP_WB_TEMPERATURE", None)
            if wb_temperature is not None:
                try:
                    if not cap.set(wb_temperature, float(self._white_balance_temperature)):
                        log.info(
                            "camera %d: white balance temperature=%s not accepted",
                            index, self._white_balance_temperature,
                        )
                except Exception:
                    log.info("camera %d: error setting white balance temperature", index, exc_info=True)

    def _open_candidate_locked(self, index: int, codec: str | None):
        """Open, configure, and probe one codec candidate.

        A candidate is returned only after a real non-black frame arrives.
        Failed candidates are released here so callers can safely try the
        next format without disturbing an existing live handle.
        """
        import cv2

        cap = None
        try:
            cap = cv2.VideoCapture(index, self._cv2_api())
            if not cap.isOpened():
                cap.release()
                return None
            self._apply_settings(cap, index, codec=codec)
            frame, _saw_frame = read_signal_frame(cap)
            if frame is None:
                cap.release()
                return None
            return cap, frame
        except Exception:
            log.debug(
                "camera %d: %s candidate failed",
                index, codec or "driver-default", exc_info=True,
            )
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            return None

    def _try_open_locked(self) -> None:
        """Open self._index, replacing whatever self._cap currently holds.
        Caller holds self._lock. Used both by open() and by read()'s
        same-index reopen-on-failure path - there is nothing to preserve on
        rollback here because the index isn't changing."""
        self._last_open_attempt = time.monotonic()
        self._release_locked()
        candidate = None
        selected_codec: str | None = None
        for codec in _CAPTURE_CODECS:
            candidate = self._open_candidate_locked(self._index, codec)
            if candidate is not None:
                selected_codec = codec
                break
        if candidate is None:
            log.warning("camera %d failed to open with a usable frame; retry every %.0fs",
                        self._index, _REOPEN_INTERVAL_S)
            return

        cap, probe_frame = candidate
        actual_h, actual_w = probe_frame.shape[:2]
        if (actual_w, actual_h) != (self._width, self._height):
            log.warning(
                "camera %d delivered %dx%d instead of requested %dx%d; "
                "accuracy gates must use the delivered frame size",
                self._index, actual_w, actual_h, self._width, self._height,
            )
        self._cap = cap
        log.info("camera %d opened (%dx%d requested, actual %dx%d, codec=%s)",
                 self._index, self._width, self._height, actual_w, actual_h,
                 selected_codec or "driver-default")

    def _release_locked(self) -> None:
        """Caller holds self._lock."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                log.debug("camera %d: release failed", self._index, exc_info=True)
            self._cap = None

    def read(self) -> FrameTuple | None:
        with self._lock:
            if self._cap is None and time.monotonic() - self._last_open_attempt >= _REOPEN_INTERVAL_S:
                self._try_open_locked()
            if self._cap is None:
                got = None
            else:
                try:
                    ok, frame = self._cap.read()
                except Exception:
                    log.warning("camera %d: read raised", self._index, exc_info=True)
                    ok, frame = False, None
                if ok and frame_has_signal(frame):
                    self._frame_id += 1
                    got = (frame, self._frame_id, time.monotonic() * 1000.0)
                else:
                    got = None
                    if time.monotonic() - self._last_open_attempt >= _REOPEN_INTERVAL_S:
                        log.warning("camera %d: read failed, reopening", self._index)
                        self._try_open_locked()
        if got is not None:
            return got
        time.sleep(0.05)
        return None

    def switch_to(self, new_index: int) -> tuple[bool, int, int]:
        """Hot-swap the active device to `new_index`, applying the same
        width/height/fps, codec, and optional UVC image-control settings used
        at construction.

        On success: releases the previous capture handle only AFTER the new
        one has opened AND produced a real frame, swaps it in, and returns
        (True, actual_width, actual_height).

        On failure (index won't open, or opens but yields no frame): the
        previous capture handle is left completely untouched - it is never
        released - so the source keeps serving frames from the original
        index. Returns (False, 0, 0).
        """
        with self._lock:
            candidate = None
            selected_codec: str | None = None
            for codec in _CAPTURE_CODECS:
                candidate = self._open_candidate_locked(new_index, codec)
                if candidate is not None:
                    selected_codec = codec
                    break
            if candidate is None:
                log.warning("camera switch_to(%d) failed: no usable frame", new_index)
                return False, 0, 0
            new_cap, frame = candidate

            # Success: only now touch the old handle - a failed attempt above
            # must never have released it.
            old_cap = self._cap
            self._cap = new_cap
            self._index = new_index
            self._frame_id = 0
            self._last_open_attempt = time.monotonic()
            if old_cap is not None:
                try:
                    old_cap.release()
                except Exception:
                    log.debug("camera: release of previous capture handle failed", exc_info=True)
            h, w = frame.shape[:2]
            log.info("camera switched to index %d (%dx%d, codec=%s)",
                     new_index, w, h, selected_codec or "driver-default")
            return True, int(w), int(h)

    def set_focus(self, value: float | None) -> tuple[bool, float | None]:
        """Change focus on the LIVE capture handle (no restart).

        value is a driver focus unit (the C920 accepts 0-250 in steps of 5,
        measured 2026-08-01 via DirectShow: set() returned True and read-back
        matched exactly at every step). ``None`` hands control back to
        autofocus.

        The new value is also stored on ``self``, so ``_apply_settings()``
        reapplies it if the device is reopened - otherwise a transient USB
        reconnect would silently drop a focus lock the accuracy session
        depends on (config.yaml's ``camera.focus`` only covers cold start).

        Returns (accepted, read_back). ``accepted`` is the driver's own
        answer to set(); ``read_back`` is what the driver reports afterwards
        (None when no capture handle is open).
        """
        import cv2

        with self._lock:
            # Store first: the values must survive a reopen even if the
            # live set() below fails or there is no handle right now.
            if value is None:
                self._focus = None
                self._lock_auto_focus = False
            else:
                self._focus = float(value)
                self._lock_auto_focus = True
            if self._cap is None:
                return False, None
            accepted = True
            try:
                # Autofocus must be disabled before a manual value sticks;
                # re-enabled first when handing control back.
                accepted &= bool(self._cap.set(cv2.CAP_PROP_AUTOFOCUS,
                                               0 if value is not None else 1))
                if value is not None:
                    accepted &= bool(self._cap.set(cv2.CAP_PROP_FOCUS, float(value)))
            except Exception:
                log.warning("camera %d: focus control raised", self._index, exc_info=True)
                return False, None
            try:
                read_back = float(self._cap.get(cv2.CAP_PROP_FOCUS))
            except Exception:
                read_back = None
            log.info("camera %d: focus -> %s (accepted=%s, read_back=%s)",
                     self._index, "auto" if value is None else value,
                     accepted, read_back)
            return accepted, read_back

    def focus_state(self) -> dict:
        """Current focus/autofocus state as reported by the driver."""
        import cv2

        with self._lock:
            state: dict = {
                "manual": self._focus is not None,
                "configured_focus": self._focus,
                "read_back": None,
                "autofocus_raw": None,
                "camera_open": self._cap is not None,
            }
            if self._cap is None:
                return state
            try:
                state["read_back"] = float(self._cap.get(cv2.CAP_PROP_FOCUS))
                state["autofocus_raw"] = float(self._cap.get(cv2.CAP_PROP_AUTOFOCUS))
            except Exception:
                log.debug("camera %d: focus read failed", self._index, exc_info=True)
            return state

    def close(self) -> None:
        with self._lock:
            self._release_locked()


class FfmpegMjpegCameraSource:
    """Low-latency DirectShow MJPEG camera source backed by FFmpeg.

    OpenCV's DirectShow backend can accept ``CAP_PROP_FOURCC=MJPG`` yet still
    negotiate YUY2 on the C920. At 1920x1080 that uncompressed USB 2.0 path is
    limited to 5 fps. FFmpeg can explicitly select the camera's native MJPEG
    mode and copy each compressed JPEG packet to stdout at 30 fps.

    A reader thread drains that pipe continuously into a single latest-frame
    slot. CaptureService therefore never accumulates stale camera frames, and
    its ``read()`` remains bounded even if the camera or FFmpeg process exits.
    """

    def __init__(
        self,
        device_index: int,
        device_name: str,
        width: int,
        height: int,
        fps: float,
        *,
        ffmpeg_path: str = "ffmpeg",
        native_uvc_controls: bool = False,
        uvc_image_controls: dict[str, int] | None = None,
        lock_auto_focus: bool = False,
        focus: float | None = None,
        lock_auto_exposure: bool = False,
        lock_auto_white_balance: bool = False,
        exposure: float | None = None,
        gain: float | None = None,
        white_balance_temperature: float | None = None,
    ) -> None:
        self._index = int(device_index)
        self._device_name = str(device_name)
        self._width = int(width)
        self._height = int(height)
        self._fps = float(fps)
        self._ffmpeg_path = str(ffmpeg_path)
        self._native_uvc_controls = bool(native_uvc_controls)
        self._uvc_image_controls = dict(uvc_image_controls or {})
        self._uvc_control_report: dict | None = None
        self._native_autofocus_requested = False
        self._lock_auto_focus = bool(lock_auto_focus)
        self._focus = focus
        self._lock_auto_exposure = bool(lock_auto_exposure)
        self._lock_auto_white_balance = bool(lock_auto_white_balance)
        self._exposure = exposure
        self._gain = gain
        self._white_balance_temperature = white_balance_temperature

        self._condition = threading.Condition()
        self._lifecycle_lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_tail: deque[str] = deque(maxlen=12)
        self._latest: FrameTuple | None = None
        self._latest_seq = 0
        self._delivered_seq = 0
        self._frame_id = 0
        self._closed = True
        self._last_start_attempt = float("-inf")
        self._focus_read_back: float | None = None
        self._autofocus_read_back: float | None = None

        from . import control_store
        self.control_identity = control_store.identity(self._device_name, width, height, fps)
        self._live_control_overrides = control_store.load(self.control_identity) if self._native_uvc_controls else {}

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def ffmpeg_path(self) -> str:
        return self._ffmpeg_path

    @property
    def capture_mode(self) -> dict:
        return dict(width=self._width, height=self._height, fps=self._fps)

    def configure_mode(self, *, width: int, height: int, fps: float) -> None:
        """Change transport mode only, after CaptureService has fully stopped."""
        from . import control_store
        with self._lifecycle_lock:
            if not self._closed or self._process is not None:
                raise RuntimeError('Stop capture before changing resolution')
            if width <= 0 or height <= 0 or not 0 < fps <= 120:
                raise ValueError('Invalid camera mode')
            self._width, self._height, self._fps = int(width), int(height), float(fps)
            self.control_identity = control_store.identity(self._device_name, width, height, fps)
            # Retain current controls; never import another camera/mode's settings.

    @property
    def current_index(self) -> int:
        return self._index

    def command(self) -> list[str]:
        """Exact argv used for the native C920 MJPEG capture process."""
        fps_text = f"{self._fps:g}"
        return [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel", "warning",
            "-nostdin",
            "-f", "dshow",
            "-rtbufsize", "64M",
            "-video_size", f"{self._width}x{self._height}",
            "-framerate", fps_text,
            "-vcodec", "mjpeg",
            "-i", f"video={self._device_name}",
            "-an", "-sn", "-dn",
            "-c:v", "copy",
            "-flush_packets", "1",
            "-f", "mjpeg",
            "pipe:1",
        ]

    def open(self) -> None:
        with self._condition:
            self._closed = False
            self._latest = None
            self._latest_seq = 0
            self._delivered_seq = 0
            self._frame_id = 0
        self._ensure_started(force=True)

    def _controls_requested(self) -> bool:
        return any((
            self._lock_auto_focus,
            self._focus is not None,
            self._lock_auto_exposure,
            self._lock_auto_white_balance,
            self._exposure is not None,
            self._gain is not None,
            self._white_balance_temperature is not None,
            bool(self._uvc_image_controls),
            self._native_autofocus_requested,
            bool(self._live_control_overrides),
        ))

    def _apply_native_uvc_controls(self) -> None:
        from .windows_uvc import apply_controls
        settings = {key: {"value": value, "flags": 2}
                    for key, value in self._uvc_image_controls.items()}
        for key, value in (("focus", self._focus), ("exposure", self._exposure),
                           ("gain", self._gain), ("white_balance", self._white_balance_temperature)):
            if value is not None:
                settings[key] = {"value": int(value), "flags": 2}
        if self._native_autofocus_requested:
            settings["focus"] = {"value": int(self._focus_read_back or 0), "flags": 1}
        settings.update(self._live_control_overrides)
        try:
            self._uvc_control_report = apply_controls(self._device_name, settings)
            for control in self._uvc_control_report['controls']:
                if control['Name'] == 'focus':
                    self._focus_read_back = control['Value']
                    self._autofocus_read_back = control['Flags']
                    self._focus = control['Value'] if control['Flags'] == 2 else None
                    self._lock_auto_focus = control['Flags'] == 2
                    self._native_autofocus_requested = control['Flags'] == 1
        except Exception as error:
            self._uvc_control_report = {"verified": False, "error": str(error)}
            self._focus_read_back = self._autofocus_read_back = None
            log.warning("FFmpeg camera %s: native UVC read-back failed: %s",
                        self._device_name, error)

    def _apply_controls_before_ffmpeg_locked(self) -> None:
        """Set UVC controls through a short DirectShow handle, then release it.

        FFmpeg owns the live camera handle, so OpenCV cannot adjust focus at
        the same time. DirectShow camera controls persist across the immediate
        close/reopen used here on the C920. This also keeps the existing focus
        API useful: changing focus briefly restarts FFmpeg instead of silently
        claiming success while the lens never moved.
        """
        if not self._controls_requested():
            return
        if self._native_uvc_controls:
            # No 720p OpenCV control stream: that extra device session was
            # observed to restore unrelated driver knobs on C920 restart.
            self._apply_native_uvc_controls()
            return
        # Camera-control properties are resolution-independent. Opening the
        # temporary handle at 1080p would force OpenCV back onto 5 fps YUY2
        # and spend about five seconds warming up before FFmpeg can start.
        # Use the C920's faster 720p control session, then reopen 1080p MJPEG.
        control_width = min(self._width, 1280)
        control_height = min(self._height, 720)
        controller = DeviceCameraSource(
            self._index,
            control_width,
            control_height,
            self._fps,
            capture_api="dshow",
            buffer_size=1,
            lock_auto_focus=self._lock_auto_focus,
            focus=self._focus,
            lock_auto_exposure=self._lock_auto_exposure,
            lock_auto_white_balance=self._lock_auto_white_balance,
            exposure=self._exposure,
            gain=self._gain,
            white_balance_temperature=self._white_balance_temperature,
        )
        try:
            controller.open()
            state = controller.focus_state()
            self._focus_read_back = state.get("read_back")
            self._autofocus_read_back = state.get("autofocus_raw")
        except Exception:
            log.warning(
                "FFmpeg camera %s: preflight UVC controls failed",
                self._device_name,
                exc_info=True,
            )
        finally:
            controller.close()

    def _ensure_started(self, *, force: bool = False) -> None:
        with self._lifecycle_lock:
            with self._condition:
                if self._closed:
                    return
            process = self._process
            if process is not None and process.poll() is None:
                return
            now = time.monotonic()
            if not force and now - self._last_start_attempt < _REOPEN_INTERVAL_S:
                return
            self._last_start_attempt = now
            self._stop_process_locked()
            self._apply_controls_before_ffmpeg_locked()
            try:
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    self.command(),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=creationflags,
                )
            except Exception:
                log.warning(
                    "FFmpeg camera %s failed to start; retry every %.0fs",
                    self._device_name,
                    _REOPEN_INTERVAL_S,
                    exc_info=True,
                )
                return
            self._process = process
            self._stderr_tail.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                args=(process,),
                name="ffmpeg-mjpeg-reader",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                args=(process,),
                name="ffmpeg-mjpeg-stderr",
                daemon=True,
            )
            self._reader_thread.start()
            self._stderr_thread.start()
            log.info(
                "FFmpeg camera started: %s %dx%d@%g MJPEG",
                self._device_name,
                self._width,
                self._height,
                self._fps,
            )

    def _reader_loop(self, process: subprocess.Popen) -> None:
        import cv2

        stdout = process.stdout
        if stdout is None:
            return
        parser = MjpegFrameParser()
        first_signal_checked = False
        try:
            while True:
                chunk = stdout.read(64 * 1024)
                if not chunk:
                    break
                frames = parser.feed(chunk)
                if not frames:
                    continue
                # If the pipe delivered several frames while Python was busy,
                # decode only the newest one. Old images are already stale.
                encoded = np.frombuffer(frames[-1], dtype=np.uint8)
                frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                if frame is None:
                    continue
                if not first_signal_checked:
                    if not frame_has_signal(frame):
                        log.warning("FFmpeg camera %s produced a black frame", self._device_name)
                        continue
                    first_signal_checked = True
                    actual_h, actual_w = frame.shape[:2]
                    if (actual_w, actual_h) != (self._width, self._height):
                        log.warning(
                            "FFmpeg camera %s delivered %dx%d instead of %dx%d",
                            self._device_name,
                            actual_w,
                            actual_h,
                            self._width,
                            self._height,
                        )
                    if self._native_uvc_controls and self._controls_requested():
                        # FFmpeg's new filter can overwrite preflight values.
                        # Restore/read back on the active device, once per open.
                        # Discard the image acquired before this restoration.
                        self._apply_native_uvc_controls()
                        continue
                timestamp_ms = time.monotonic() * 1000.0
                with self._condition:
                    if self._closed or process is not self._process:
                        break
                    self._frame_id += 1
                    self._latest = (
                        frame,
                        self._frame_id,
                        timestamp_ms,
                        frames[-1],
                    )
                    self._latest_seq += 1
                    self._condition.notify_all()
        except Exception:
            with self._condition:
                closed = self._closed
            if not closed:
                log.warning("FFmpeg MJPEG reader failed", exc_info=True)
        finally:
            with self._condition:
                closed = self._closed
                is_current = process is self._process
            if not closed and is_current and process.poll() is not None:
                tail = " | ".join(self._stderr_tail)
                log.warning(
                    "FFmpeg camera exited with code %s%s",
                    process.returncode,
                    f": {tail}" if tail else "",
                )
            with self._condition:
                self._condition.notify_all()

    def _stderr_loop(self, process: subprocess.Popen) -> None:
        stderr = process.stderr
        if stderr is None:
            return
        try:
            for raw_line in iter(stderr.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    self._stderr_tail.append(line)
                    log.debug("ffmpeg camera: %s", line)
        except Exception:
            with self._condition:
                closed = self._closed
            if not closed:
                log.debug("FFmpeg stderr reader failed", exc_info=True)

    def _stop_process_locked(self) -> None:
        process = self._process
        reader = self._reader_thread
        stderr_reader = self._stderr_thread
        self._process = None
        self._reader_thread = None
        self._stderr_thread = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1.0)
            except Exception:
                log.debug("FFmpeg camera process stop failed", exc_info=True)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
        current = threading.current_thread()
        for thread in (reader, stderr_reader):
            if thread is not None and thread is not current and thread.is_alive():
                thread.join(timeout=1.0)

    def read(self) -> FrameTuple | None:
        self._ensure_started()
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._closed or self._latest_seq > self._delivered_seq,
                timeout=0.25,
            )
            if self._closed:
                return None
            if ready and self._latest is not None:
                self._delivered_seq = self._latest_seq
                return self._latest
        # A dead process is restarted by the next bounded read call.
        self._ensure_started()
        return None

    def switch_to(self, new_index: int) -> tuple[bool, int, int]:
        # FFmpeg selects DirectShow cameras by stable device name, not by the
        # unrelated OpenCV integer index. Keep the fixed C920 live instead of
        # guessing a name/index mapping and silently opening the wrong camera.
        if int(new_index) == self._index:
            return True, self._width, self._height
        log.warning(
            "FFmpeg camera switch_to(%d) rejected: configured device is %s at index %d",
            new_index,
            self._device_name,
            self._index,
        )
        return False, 0, 0

    @property
    def supports_live_controls(self) -> bool:
        return self._native_uvc_controls

    def discover_live_controls(self) -> bool:
        """Read capabilities for this device without applying/loading settings.

        Called once after an explicit camera switch, not by the status poll.
        A failed property query must not take down a working video stream.
        """
        from .windows_uvc import read_controls, supports_tuning
        with self._lifecycle_lock:
            try:
                self._native_uvc_controls = supports_tuning(read_controls(self._device_name))
            except Exception:
                self._native_uvc_controls = False
                log.warning('Camera control discovery failed; stream left running', exc_info=True)
            return self._native_uvc_controls

    def read_live_controls(self) -> dict:
        from .windows_uvc import read_controls
        if not self.supports_live_controls:
            raise RuntimeError('Live property controls unavailable')
        with self._lifecycle_lock:
            return read_controls(self._device_name)

    def apply_live_controls(self, settings: dict) -> dict:
        from .windows_uvc import apply_controls
        from .control_store import valid_settings
        settings = valid_settings(settings)
        if not self.supports_live_controls:
            raise RuntimeError('Live property controls unavailable')
        with self._lifecycle_lock:
            # A verified write updates the settings reused by reconnect/startup.
            # Never stop FFmpeg or open an OpenCV capture handle here.
            report = apply_controls(self._device_name, settings)
            self._live_control_overrides.update(settings)
            self._uvc_control_report = report
            if 'focus' in settings:
                entry = settings['focus']
                self._focus = entry['value'] if entry['flags'] == 2 else None
                self._lock_auto_focus = entry['flags'] == 2
                self._native_autofocus_requested = entry['flags'] == 1
                self._focus_read_back = next((p['Value'] for p in report['controls'] if p['Name'] == 'focus'), None)
                self._autofocus_read_back = entry['flags']
            return report

    def set_focus(self, value: float | None) -> tuple[bool, float | None]:
        with self._lifecycle_lock:
            if self.supports_live_controls:
                try:
                    current = next(p for p in self.read_live_controls()['controls'] if p['Name'] == 'focus')
                    self.apply_live_controls({'focus': {'value': current['Value'] if value is None else int(value),
                                                       'flags': 1 if value is None else 2}})
                    return True, self._focus_read_back
                except Exception:
                    log.warning('Native live focus failed; stream left running', exc_info=True)
                    return False, None
            self._native_autofocus_requested = value is None
            if value is None:
                self._focus = None
                self._lock_auto_focus = False
            else:
                self._focus = float(value)
                self._lock_auto_focus = True
            self._stop_process_locked()
            self._last_start_attempt = float("-inf")
            self._ensure_started(force=True)
            return self._focus_read_back is not None, self._focus_read_back

    def focus_state(self) -> dict:
        process = self._process
        return {
            "manual": self._focus is not None,
            "configured_focus": self._focus,
            "read_back": self._focus_read_back,
            "autofocus_raw": self._autofocus_read_back,
            "camera_open": process is not None and process.poll() is None,
            "capture_backend": "ffmpeg",
            "uvc_controls": self._uvc_control_report,
        }

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        with self._lifecycle_lock:
            self._stop_process_locked()


class WindowCaptureSource:
    """Captures a visible desktop window's client area as the video source.

    Motivating use case (2026-07-29, live-verified): an iPhone mounted
    overhead as the demo camera, its screen mirrored to this PC via a
    screen-sharing app. The app registers NO virtual camera device (verified against the
    Windows device list), so cv2.VideoCapture can never see it - but the
    mirror window itself can be captured with user32.PrintWindow at 40+ fps,
    and the pose pipeline locks on the mirrored camera view (123 Lowe
    survivors vs. the 25-inlier gate on a real captured frame; all 32 pins
    visible). Works for any window (title substring match).

    Capture path: PrintWindow with PW_CLIENTONLY|PW_RENDERFULLCONTENT ->
    GDI DIB -> numpy BGR. Pure ctypes against user32/gdi32 - no new
    dependencies. PW_RENDERFULLCONTENT captures DWM-composited content, so
    the window may be covered by other windows - but NOT minimized (a
    minimized window has a 0x0/stale client area; read() then returns None
    and the stream freezes until it is restored).

    Contract notes:
    - Frame size follows the window's client area, NOT config width/height;
      resizing the window mid-stream changes frame dimensions. Downstream
      handles this: MJPEG encodes per-frame, the frontend letterboxes from
      the <img>'s natural size, and detection coordinates are per-frame.
    - Paced at the configured fps like SyntheticCameraSource (the mirror
      pushes ~30-60Hz; capturing faster than config.fps would just burn CPU
      re-reading identical composited frames).
    - Never raises from read(): window gone (mirror disconnected, window
      closed) -> None + re-find the window by title at most every
      _REOPEN_INTERVAL_S, same recovery pattern as DeviceCameraSource.
    """

    def __init__(self, title_substr: str, fps: float) -> None:
        self._title_substr = title_substr
        self._interval = 1.0 / max(fps, 1e-3)
        self._hwnd: int | None = None
        self._frame_id = 0
        self._next_t: float | None = None
        self._last_find_attempt = float("-inf")

    def open(self) -> None:
        import ctypes

        # Best-effort: make GetClientRect return physical pixels on scaled
        # displays so the captured bitmap isn't a blurry DPI-virtualized
        # upscale. Process-wide, but this backend has no GUI of its own.
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            log.debug("SetProcessDPIAware failed", exc_info=True)
        self._next_t = None
        self._find_window()

    def _find_window(self) -> None:
        """Locate the first visible top-level window whose title contains
        the configured substring (case-insensitive). Sets self._hwnd."""
        import ctypes
        from ctypes import wintypes

        self._last_find_attempt = time.monotonic()
        user32 = ctypes.windll.user32
        matches: list[int] = []
        needle = self._title_substr.lower()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if needle in buf.value.lower():
                        matches.append(hwnd)
            return True

        try:
            user32.EnumWindows(_cb, 0)
        except Exception:
            log.warning("window capture: EnumWindows failed", exc_info=True)
        if matches:
            if self._hwnd != matches[0]:
                log.info("window capture: found window %#x for title ~ %r",
                         matches[0], self._title_substr)
            self._hwnd = matches[0]
        else:
            if self._hwnd is not None:
                log.warning("window capture: window for title ~ %r is gone; "
                            "will re-search every %.0fs",
                            self._title_substr, _REOPEN_INTERVAL_S)
            self._hwnd = None

    def _capture(self) -> np.ndarray | None:
        """One PrintWindow capture of the client area. None on any failure."""
        import ctypes

        if self._hwnd is None:
            return None
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _BMIH(ctypes.Structure):
            _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                        ("biClrImportant", ctypes.c_uint32)]

        class _BMI(ctypes.Structure):
            _fields_ = [("bmiHeader", _BMIH), ("bmiColors", ctypes.c_uint32 * 3)]

        rect = _RECT()
        if not user32.GetClientRect(self._hwnd, ctypes.byref(rect)):
            return None
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w <= 0 or h <= 0:
            return None

        hdc_win = user32.GetWindowDC(self._hwnd)
        if not hdc_win:
            return None
        img = None
        hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
        try:
            old = gdi32.SelectObject(hdc_mem, hbmp)
            # PW_CLIENTONLY(1) | PW_RENDERFULLCONTENT(2)
            if user32.PrintWindow(self._hwnd, hdc_mem, 3):
                bmi = _BMI()
                bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
                bmi.bmiHeader.biWidth = w
                bmi.bmiHeader.biHeight = -h  # negative = top-down row order
                bmi.bmiHeader.biPlanes = 1
                bmi.bmiHeader.biBitCount = 32
                bmi.bmiHeader.biCompression = 0  # BI_RGB
                buf = ctypes.create_string_buffer(w * h * 4)
                if gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0) == h:
                    img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[:, :, :3].copy()
            gdi32.SelectObject(hdc_mem, old)
        finally:
            gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(self._hwnd, hdc_win)
        return img

    def read(self) -> FrameTuple | None:
        # Same fixed-cadence pacing as SyntheticCameraSource.
        now = time.monotonic()
        if self._next_t is None:
            self._next_t = now
        delay = self._next_t - now
        if delay > 0:
            time.sleep(delay)
        self._next_t += self._interval
        if self._next_t < time.monotonic() - 1.0:
            self._next_t = time.monotonic() + self._interval

        if self._hwnd is None:
            if time.monotonic() - self._last_find_attempt >= _REOPEN_INTERVAL_S:
                self._find_window()
            if self._hwnd is None:
                return None
        try:
            frame = self._capture()
        except Exception:
            log.warning("window capture: capture raised", exc_info=True)
            frame = None
        if frame is None:
            # Window may have been closed/minimized - drop the handle so the
            # next read re-searches (it may have been recreated with a new
            # hwnd, e.g. a phone-mirror reconnect).
            self._hwnd = None
            return None
        self._frame_id += 1
        return frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        self._hwnd = None


class SyntheticCameraSource:
    """Renders frames from a SyntheticScene, paced at the configured fps."""

    def __init__(self, scene: "SyntheticScene", fps: float) -> None:
        self._scene = scene
        self._interval = 1.0 / max(fps, 1e-3)
        self._next_t: float | None = None
        self._frame_id = 0

    def open(self) -> None:
        self._next_t = None

    def read(self) -> FrameTuple | None:
        now = time.monotonic()
        if self._next_t is None:
            self._next_t = now
        delay = self._next_t - now
        if delay > 0:
            time.sleep(delay)
        # Fixed cadence; if we fell far behind (>1 s), resynchronise.
        self._next_t += self._interval
        if self._next_t < time.monotonic() - 1.0:
            self._next_t = time.monotonic() + self._interval
        t_s = time.monotonic()
        try:
            frame = self._scene.frame_at(t_s)
        except Exception:
            log.exception("synthetic scene frame_at(%.3f) failed", t_s)
            time.sleep(0.05)
            return None
        self._frame_id += 1
        return frame, self._frame_id, t_s * 1000.0

    def close(self) -> None:
        pass


def create_synthetic_scene(
    profile: "BoardProfile", profile_dir: Path, video_size: tuple[int, int]
) -> "SyntheticScene":
    """Construct a SyntheticScene. app.vision.synthetic is imported lazily
    here so code paths (and tests) that never use the synthetic camera do not
    require that module to exist."""
    from app.vision.synthetic import SyntheticScene  # lazy: parallel-built module

    return SyntheticScene(profile, profile_dir, video_size)


def create_frame_source(
    config,
    profile: "BoardProfile | None" = None,
    board_profile_dir: Path | None = None,
    scene: "SyntheticScene | None" = None,
):
    """Build the FrameSource for the given AppConfig.

    Returns (source, scene): scene is the SyntheticScene used (created here if
    needed), or None for a device camera. The caller passes the scene on to
    app.vision.factory.create_detector so detector ground truth matches video.
    """
    cam = config.camera
    if cam.source == "device":
        if cam.capture_backend == "ffmpeg":
            return FfmpegMjpegCameraSource(
                cam.device_index,
                cam.ffmpeg_device_name,
                cam.width,
                cam.height,
                cam.fps,
                ffmpeg_path=cam.ffmpeg_path,
                native_uvc_controls=cam.native_uvc_controls,
                uvc_image_controls=cam.uvc_image_controls,
                lock_auto_focus=cam.lock_auto_focus,
                focus=cam.focus,
                lock_auto_exposure=cam.lock_auto_exposure,
                lock_auto_white_balance=cam.lock_auto_white_balance,
                exposure=cam.exposure,
                gain=cam.gain,
                white_balance_temperature=cam.white_balance_temperature,
            ), None
        return DeviceCameraSource(cam.device_index, cam.width, cam.height, cam.fps,
                                  capture_api=cam.capture_api,
                                  buffer_size=cam.buffer_size,
                                  lock_auto_focus=cam.lock_auto_focus,
                                  focus=cam.focus,
                                  lock_auto_exposure=cam.lock_auto_exposure,
                                  lock_auto_white_balance=cam.lock_auto_white_balance,
                                  exposure=cam.exposure,
                                  gain=cam.gain,
                                  white_balance_temperature=cam.white_balance_temperature), None
    if cam.source == "window":
        return WindowCaptureSource(cam.window_title, cam.fps), None
    if scene is None:
        if profile is None or board_profile_dir is None:
            raise ValueError("synthetic camera requires profile and board_profile_dir")
        scene = create_synthetic_scene(profile, board_profile_dir, (cam.width, cam.height))
    return SyntheticCameraSource(scene, cam.fps), scene
