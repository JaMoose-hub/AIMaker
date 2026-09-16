"""Vision worker thread.

Loop: take the latest frame from the FrameBus, run the detector, store the
result in DetectionState, and hand the wire-format message to a publish
callback (the WS broadcaster). Pushes are rate-capped at config detection_hz.
Detector exceptions are logged, a tracking="searching" result is emitted, and
the loop keeps running.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from app.capture.bus import FrameBus, FrameSlot
from app.vision.interface import DetectionResult
from app.vision.wire_tracer import projected_pin_pitch

log = logging.getLogger(__name__)


class DetectionState:
    """Thread-safe latest-value holder for the most recent DetectionResult
    and the actual (W, H) of the most recent camera frame."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._result: DetectionResult | None = None
        self._slot: FrameSlot | None = None
        self._video_size: tuple[int, int] | None = None

    def set(self, result: DetectionResult, slot: FrameSlot | None = None) -> None:
        """Store a detection and, when available, its exact source frame.

        Keeping the pair atomically avoids a latest-frame race in downstream
        wire tracing: the camera can advance several frames while pose
        detection is running.  ``slot`` remains optional for injected tests
        and callers that only need the latest logical result.
        """
        with self._lock:
            self._result = result
            self._slot = (
                slot
                if slot is not None and slot.frame_id == result.frame_id
                else None
            )

    def get(self) -> DetectionResult | None:
        with self._lock:
            return self._result

    def get_synchronized(self) -> tuple[FrameSlot, DetectionResult] | None:
        """Return the atomically stored same-frame pair, if one exists."""
        with self._lock:
            if (
                self._slot is None
                or self._result is None
                or self._slot.frame_id != self._result.frame_id
            ):
                return None
            return self._slot, self._result

    def set_video_size(self, size: tuple[int, int]) -> None:
        with self._lock:
            self._video_size = (int(size[0]), int(size[1]))

    def get_video_size(self) -> tuple[int, int] | None:
        """Actual (W, H) of the latest frame; None before the first frame."""
        with self._lock:
            return self._video_size

    def clear(self) -> None:
        with self._lock:
            self._result = None
            self._slot = None


def detection_message(
    result: DetectionResult,
    video_size: tuple[int, int],
    runtime_revision: int = 1,
) -> dict:
    """Serialize a DetectionResult to the WS wire format (docs/api-contract.md §2).

    Pin fields are abbreviated: id / x / y / c (confidence) / v (visible).
    """
    outline = None
    if result.outline_px is not None:
        outline = [[round(float(x), 1), round(float(y), 1)] for x, y in result.outline_px]
    message = {
        "type": "detection",
        "board_id": result.board_id,
        "runtime_revision": int(runtime_revision),
        "frame_id": result.frame_id,
        "ts_ms": result.ts_ms,
        "tracking": result.tracking,
        "confidence": round(float(result.confidence), 3),
        "video_size": [video_size[0], video_size[1]],
        "outline": outline,
        "body": result.body,
        "pins": [
            {
                "id": p.pin_id,
                "x": round(float(p.x), 1),
                "y": round(float(p.y), 1),
                "c": round(float(p.confidence), 3),
                "v": bool(p.visible),
            }
            for p in result.pins
        ],
    }
    if result.pose_mode is not None:
        message["pose_mode"] = result.pose_mode
    if result.pose_landmarks_visible is not None:
        message["pose_landmarks_visible"] = int(result.pose_landmarks_visible)
    pitch_px = projected_pin_pitch(result.pins)
    if pitch_px > 0.0:
        message["geometry"] = {
            "pitch_px": round(float(pitch_px), 3),
            "px_per_mm": round(float(pitch_px / 2.54), 4),
        }
    if (
        result.pose_inliers is not None
        or result.pose_reproj_px is not None
        or result.pose_stability_state is not None
        or result.pose_image_confirmed
    ):
        quality = {}
        if result.pose_path is not None:
            quality["path"] = result.pose_path
        if result.pose_inliers is not None:
            quality["inliers"] = int(result.pose_inliers)
        if result.pose_reproj_px is not None:
            quality["reproj_px"] = round(float(result.pose_reproj_px), 3)
        if result.pose_inlier_board_area_frac is not None:
            quality["inlier_board_area_frac"] = round(
                float(result.pose_inlier_board_area_frac), 4)
        if result.pose_stability_state is not None:
            quality["stability"] = result.pose_stability_state
        if result.pose_motion_px is not None:
            quality["motion_px"] = round(float(result.pose_motion_px), 3)
        if result.pose_pin_motion_px is not None:
            quality["pin_motion_px"] = round(float(result.pose_pin_motion_px), 3)
        if result.pose_image_motion_px is not None:
            quality["image_motion_px"] = round(float(result.pose_image_motion_px), 3)
        if result.pose_image_support is not None:
            quality["image_support"] = int(result.pose_image_support)
        if result.pose_image_confirmed:
            quality["image_confirmed"] = True
        if result.pose_visible_fraction is not None:
            quality["visible_fraction"] = round(
                float(result.pose_visible_fraction), 4)
        message["pose_quality"] = quality
    if result.reference_evidence is not None:
        message.setdefault('pose_quality', {})['reference_recovery'] = result.reference_evidence
    return message


class VisionWorker:
    def __init__(
        self,
        bus: FrameBus,
        detector,
        state: DetectionState,
        board_id: str,
        video_size: tuple[int, int],
        detection_hz: float = 30.0,
        publish: Callable[[dict], None] | None = None,
        runtime_revision: int = 1,
    ) -> None:
        self._bus = bus
        self._detector = detector
        self._detector_lock = threading.Lock()
        self._state = state
        self._board_id = board_id
        self._video_size = video_size  # configured size; wire messages use the actual frame size
        self._min_push_interval = 1.0 / max(detection_hz, 1e-3)
        self._publish = publish
        self._runtime_revision = int(runtime_revision)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vision-worker", daemon=True)
        self._thread.start()

    def set_detector(
        self,
        new_detector,
        *,
        board_id: str | None = None,
        runtime_revision: int | None = None,
    ) -> None:
        """Hot-swap the live detector (e.g. after POST /api/calibrate
        rebuilds the reference and produces a freshly-loaded detector).

        A plain attribute assignment would already be safe under the GIL,
        but the lock makes the swap-is-atomic-and-visible-immediately intent
        explicit and pairs with the read in ``_run``.
        """
        with self._detector_lock:
            self._detector = new_detector
            if board_id is not None:
                self._board_id = board_id
            if runtime_revision is not None:
                self._runtime_revision = int(runtime_revision)

    def _run(self) -> None:
        last_seq = -1
        last_push = float("-inf")
        while not self._stop.is_set():
            slot = self._bus.get_latest(timeout=0.2, newer_than=last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            # Device cameras may deliver a resolution different from the
            # configured one; overlays must be registered against the ACTUAL
            # frame size, never the config size.
            actual_size = (int(slot.frame.shape[1]), int(slot.frame.shape[0]))
            self._state.set_video_size(actual_size)
            try:
                # Hold the same lock used by set_detector for the short
                # inference call. A completed swap can therefore safely close
                # the old ONNX session without racing an in-flight frame.
                with self._detector_lock:
                    detector = self._detector
                    board_id = self._board_id
                    runtime_revision = self._runtime_revision
                    result = detector.detect(slot.frame, slot.frame_id, slot.ts_ms)
                if result is None:  # contract violation by detector - stay alive
                    raise ValueError("detector returned None (contract: always DetectionResult)")
            except Exception:
                with self._detector_lock:
                    board_id = self._board_id
                    runtime_revision = self._runtime_revision
                log.exception("detector.detect failed (frame_id=%d)", slot.frame_id)
                result = DetectionResult(
                    board_id=board_id,
                    frame_id=slot.frame_id,
                    ts_ms=slot.ts_ms,
                    tracking="searching",
                    confidence=0.0,
                    pins=[],
                )
            self._state.set(result, slot)
            now = time.monotonic()
            if self._publish is not None and (now - last_push) >= self._min_push_interval:
                last_push = now
                try:
                    self._publish(
                        detection_message(result, actual_size, runtime_revision)
                    )
                except Exception:
                    log.exception("detection publish failed")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("Vision worker has not stopped")
            self._thread = None
