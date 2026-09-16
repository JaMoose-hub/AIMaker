"""One-shot manual VLM check for colour consistency at guided wire endpoints."""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from app.verification.visual_worker import _center_crop, _connection_crop, _view_panel
from app.vlm.service import VlmService, WireColorValidationResult

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _WireColorJob:
    step_id: str
    frame_id: int
    board_pin: str
    component_pin: str
    image_b64: str


def _wire_color_views_image(
    frame: np.ndarray,
    board_center: tuple[float, float],
    component_center: tuple[float, float],
    board_pin: str,
    component_pin: str,
) -> str:
    """Encode overview/context plus close endpoint crops for a manual VLM call."""
    panels = (
        _view_panel(frame, "FULL CAMERA VIEW"),
        _view_panel(
            _connection_crop(frame, board_center, component_center),
            "CONNECTION CONTEXT",
            detail=True,
        ),
        _view_panel(
            _center_crop(frame, board_center, 260.0, 220.0),
            f"UNO Q COLOUR AT {board_pin}",
            detail=True,
        ),
        _view_panel(
            _center_crop(frame, component_center, 260.0, 220.0),
            f"SENSOR COLOUR AT {component_pin}",
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
        raise RuntimeError("could not encode wire-colour VLM image")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


class WireColorVlmWorker:
    """Runs user-requested wire-colour questions away from the camera thread."""

    def __init__(self, service: VlmService) -> None:
        self._service = service
        self._cond = threading.Condition()
        self._job: _WireColorJob | None = None
        self._inflight = False
        self._last_outcome: dict[str, object] | None = None
        self._last_image_b64: str | None = None
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        with self._cond:
            self._stop = False
        self._thread = threading.Thread(target=self._run, name="wire-color-vlm-worker", daemon=True)
        self._thread.start()

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
        with self._cond:
            image_b64 = self._last_image_b64
        if not image_b64:
            return None
        try:
            return base64.b64decode(image_b64, validate=True)
        except (ValueError, TypeError):
            log.exception("could not decode wire-colour VLM preview")
            return None

    def submit(self, step, frame, detection, component_pose, *, frame_id: int) -> bool:
        if frame is None or detection is None or component_pose is None or not step.expected_role:
            return False
        board_pin = next(
            (pin for pin in detection.pins if pin.pin_id == step.expected_pin_id and pin.visible),
            None,
        )
        component_pin = next(
            (pin for pin in component_pose.pins if pin.id == step.expected_role and pin.visible),
            None,
        )
        if board_pin is None or component_pin is None:
            return False
        try:
            image_b64 = _wire_color_views_image(
                frame,
                (float(board_pin.x), float(board_pin.y)),
                (float(component_pin.x), float(component_pin.y)),
                step.expected_pin_id,
                step.expected_role,
            )
        except Exception:
            log.exception("could not prepare wire-colour VLM image")
            return False
        with self._cond:
            if self._inflight or self._job is not None:
                return False
            self._job = _WireColorJob(
                step.step_id,
                int(frame_id),
                step.expected_pin_id,
                step.expected_role,
                image_b64,
            )
            self._last_image_b64 = image_b64
            self._last_outcome = {"status": "queued", "step_id": step.step_id}
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
            result: WireColorValidationResult = self._service.ask_wire_color(
                image_b64=job.image_b64,
                board_pin=job.board_pin,
                component_pin=job.component_pin,
            )
            with self._cond:
                self._inflight = False
                if result.ok and result.data is not None:
                    self._last_outcome = {
                        "status": "complete",
                        "step_id": job.step_id,
                        "frame_id": job.frame_id,
                        "board_color": result.data.board_color,
                        "component_color": result.data.component_color,
                        "same_color": result.data.same_color,
                        "confidence": round(float(result.data.confidence), 3),
                        "board_evidence": result.data.board_evidence,
                        "component_evidence": result.data.component_evidence,
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
