"""One-shot final visual verification for the complete photoresistor wiring."""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from app.verification.visual_worker import _connection_crop, _full_frame_image, _outline_crop, _view_panel
from app.vlm.models import FinalWiringUnderstanding
from app.vlm.service import FinalWiringValidationResult, VlmService

log = logging.getLogger(__name__)

FINAL_CONNECTIONS: tuple[dict[str, str], ...] = (
    {"board_pin": "3V3", "component_pin": "VCC"},
    {"board_pin": "GND", "component_pin": "GND"},
    {"board_pin": "A0", "component_pin": "AO"},
)


@dataclass(frozen=True)
class _FinalJob:
    step_id: str
    frame_id: int
    image_b64: str


def _outline_center(
    outline: np.ndarray | None,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    if outline is None:
        return fallback
    points = np.asarray(outline, dtype=np.float64)
    if points.shape != (4, 2) or not np.all(np.isfinite(points)):
        return fallback
    center = np.mean(points, axis=0)
    return float(center[0]), float(center[1])


def _encode_final_views(
    frame: np.ndarray,
    board_outline: np.ndarray | None,
    component_outline: np.ndarray | None,
) -> str:
    board_center = _outline_center(board_outline, (frame.shape[1] * 0.35, frame.shape[0] * 0.5))
    component_center = _outline_center(
        component_outline, (frame.shape[1] * 0.70, frame.shape[0] * 0.5)
    )
    panels = (
        _view_panel(frame, "FULL CAMERA VIEW"),
        _view_panel(
            _connection_crop(frame, board_center, component_center),
            "CONNECTION CONTEXT",
            detail=True,
        ),
        _view_panel(
            _outline_crop(frame, board_outline, board_center),
            "ARDUINO ALL TARGET PINS",
            detail=True,
        ),
        _view_panel(
            _outline_crop(frame, component_outline, component_center),
            "SENSOR ALL TARGET PINS",
            detail=True,
        ),
    )
    separator = np.full((360, 12, 3), 12, dtype=np.uint8)
    sheet = np.concatenate(
        (panels[0], separator, panels[1], separator, panels[2], separator, panels[3]),
        axis=1,
    )
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("could not encode final wiring views")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _normalised_connections(data: FinalWiringUnderstanding) -> list[dict[str, object]]:
    expected = list(FINAL_CONNECTIONS)
    by_pair: dict[tuple[str, str], object] = {}
    for item in data.connections:
        board_pin = item.board_pin.upper().replace("_P1", "")
        component_pin = item.component_pin.upper()
        by_pair[(board_pin, component_pin)] = item
    result: list[dict[str, object]] = []
    for pair in expected:
        key = (pair["board_pin"].upper(), pair["component_pin"].upper())
        item = by_pair.get(key)
        if item is None:
            result.append({
                **pair,
                "state": "uncertain",
                "confidence": 0.0,
                "evidence": "VLM did not return this expected connection",
            })
        else:
            result.append({
                "board_pin": pair["board_pin"],
                "component_pin": pair["component_pin"],
                "state": item.state,
                "confidence": round(float(item.confidence), 3),
                "evidence": item.evidence,
            })
    return result


class FinalWiringVlmWorker:
    """Runs one complete-wiring VLM request away from the camera thread."""

    def __init__(
        self,
        service: VlmService,
        board_id: str,
        *,
        publish: Callable[[dict], None] | None = None,
    ) -> None:
        self._service = service
        self._board_id = board_id
        self._publish = publish
        self._cond = threading.Condition()
        self._job: _FinalJob | None = None
        self._last_outcome: dict[str, object] | None = None
        self._last_image_b64: str | None = None
        self._inflight = False
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        with self._cond:
            self._stop = False
        self._thread = threading.Thread(target=self._run, name="final-wiring-vlm-worker", daemon=True)
        self._thread.start()

    def set_board_id(self, board_id: str) -> None:
        with self._cond:
            self._board_id = str(board_id)
            self._job = None
            self._last_outcome = None
            self._last_image_b64 = None
            self._cond.notify_all()

    def stop(self, timeout: float = 10.0) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def diagnostics(self) -> dict[str, object]:
        with self._cond:
            return {
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "queued": self._job is not None,
                "inflight": self._inflight,
                "image_ready": self._last_image_b64 is not None,
                "last_outcome": dict(self._last_outcome) if self._last_outcome else None,
            }

    def preview_jpeg(self) -> bytes | None:
        """Return the exact raw-frame or multi-view JPEG sent to the VLM."""
        with self._cond:
            image_b64 = self._last_image_b64
        if not image_b64:
            return None
        try:
            return base64.b64decode(image_b64, validate=True)
        except (ValueError, TypeError):
            log.exception("could not decode final VLM preview")
            return None

    def submit(self, frame, detection=None, component_pose=None, *, step_id: str) -> bool:
        """Queue final VLM verification without treating pose lock as a gate."""
        if frame is None:
            return False
        pose_context_ready = (
            getattr(detection, "tracking", "searching") == "locked"
            and getattr(component_pose, "tracking", "searching") in {"locked", "stale"}
        )
        try:
            if pose_context_ready:
                image_b64 = _encode_final_views(
                    frame,
                    getattr(detection, "outline_px", None),
                    getattr(component_pose, "outline_px", None),
                )
                capture_mode = "localized"
            else:
                image_b64 = _full_frame_image(frame)
                capture_mode = "full_frame"
        except Exception:
            log.exception("could not prepare final wiring VLM image")
            return False
        with self._cond:
            if self._inflight or self._job is not None:
                return False
            self._job = _FinalJob(
                step_id,
                int(getattr(detection, "frame_id", 0)),
                image_b64,
            )
            self._last_image_b64 = image_b64
            self._last_outcome = {"status": "queued", "capture_mode": capture_mode}
            self._cond.notify_all()
        return True

    def _run(self) -> None:
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stop or self._job is not None)
                if self._stop:
                    return
                job = self._job
                self._job = None
                self._inflight = True
            if job is None:
                continue
            started = time.monotonic()
            result: FinalWiringValidationResult = self._service.ask_final_wiring(
                image_b64=job.image_b64,
                expected_connections=list(FINAL_CONNECTIONS),
            )
            with self._cond:
                self._inflight = False
                if result.ok and result.data is not None:
                    self._last_outcome = {
                        "status": "complete",
                        "step_id": job.step_id,
                        "frame_id": job.frame_id,
                        "connections": _normalised_connections(result.data),
                        "note": result.data.note,
                        "elapsed_s": round(time.monotonic() - started, 3),
                    }
                else:
                    self._last_outcome = {
                        "status": "error",
                        "step_id": job.step_id,
                        "frame_id": job.frame_id,
                        "error": result.error or "vlm_failed",
                        "elapsed_s": round(time.monotonic() - started, 3),
                    }
                outcome = dict(self._last_outcome)
            if self._publish is not None:
                try:
                    self._publish(outcome)
                except Exception:
                    log.exception("final wiring result publish failed")
