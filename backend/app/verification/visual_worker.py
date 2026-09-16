"""Latest-only optional VLM worker for guided full-frame insertion checks."""
from __future__ import annotations

import base64
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from app.verification.models import VerificationEvidence
from app.verification.state import VerificationState
from app.vlm.models import InsertionUnderstanding
from app.vlm.service import VlmService

log = logging.getLogger(__name__)

_SAFETY_RELIABILITY_CAP = 0.88


@dataclass(frozen=True)
class _InsertionJob:
    step_id: str
    board_pin: str
    component_pin: str
    frame_id: int
    image_b64: str


def _full_frame_image(frame: np.ndarray) -> str:
    """Encode the complete raw camera frame; do not include frontend UI."""
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise RuntimeError("could not encode full-frame insertion image")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def _clip_crop(
    frame: np.ndarray,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> np.ndarray:
    height, width = frame.shape[:2]
    left = max(0, min(width - 1, int(np.floor(x1))))
    top = max(0, min(height - 1, int(np.floor(y1))))
    right = max(left + 1, min(width, int(np.ceil(x2))))
    bottom = max(top + 1, min(height, int(np.ceil(y2))))
    return frame[top:bottom, left:right].copy()


def _center_crop(
    frame: np.ndarray,
    center: tuple[float, float],
    crop_width: float,
    crop_height: float,
) -> np.ndarray:
    half_width = crop_width / 2.0
    half_height = crop_height / 2.0
    return _clip_crop(
        frame,
        center[0] - half_width,
        center[1] - half_height,
        center[0] + half_width,
        center[1] + half_height,
    )


def _outline_crop(
    frame: np.ndarray,
    outline: np.ndarray | None,
    fallback_center: tuple[float, float],
) -> np.ndarray:
    if outline is None:
        return _center_crop(frame, fallback_center, 360.0, 360.0)
    points = np.asarray(outline, dtype=np.float64)
    if points.shape != (4, 2) or not np.all(np.isfinite(points)):
        return _center_crop(frame, fallback_center, 360.0, 360.0)
    x1, y1 = np.min(points, axis=0)
    x2, y2 = np.max(points, axis=0)
    object_width = max(1.0, x2 - x1)
    object_height = max(1.0, y2 - y1)
    margin = max(32.0, 0.35 * max(object_width, object_height))
    crop_width = max(object_width + 2.0 * margin, 260.0)
    crop_height = max(object_height + 2.0 * margin, 320.0)
    return _center_crop(
        frame,
        (float((x1 + x2) / 2.0), float((y1 + y2) / 2.0)),
        crop_width,
        crop_height,
    )


def _connection_crop(
    frame: np.ndarray,
    board_center: tuple[float, float],
    component_center: tuple[float, float],
) -> np.ndarray:
    x1 = min(board_center[0], component_center[0])
    y1 = min(board_center[1], component_center[1])
    x2 = max(board_center[0], component_center[0])
    y2 = max(board_center[1], component_center[1])
    span = max(x2 - x1, y2 - y1, 1.0)
    margin = max(70.0, 0.18 * span)
    return _clip_crop(frame, x1 - margin, y1 - margin, x2 + margin, y2 + margin)


def _enhance_detail(image: np.ndarray) -> np.ndarray:
    contrasted = cv2.convertScaleAbs(image, alpha=1.35, beta=0)
    blurred = cv2.GaussianBlur(contrasted, (0, 0), 1.0)
    return cv2.addWeighted(contrasted, 1.35, blurred, -0.35, 0)


def _view_panel(
    image: np.ndarray,
    label: str,
    *,
    width: int = 480,
    height: int = 360,
    detail: bool = False,
) -> np.ndarray:
    if detail:
        image = _enhance_detail(image)
    source_height, source_width = image.shape[:2]
    scale = min(width / max(1, source_width), height / max(1, source_height))
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_CUBIC)
    panel = np.full((height, width, 3), 12, dtype=np.uint8)
    offset_x = (width - resized_width) // 2
    offset_y = (height - resized_height) // 2
    panel[offset_y:offset_y + resized_height, offset_x:offset_x + resized_width] = resized
    cv2.rectangle(panel, (0, 0), (width - 1, 28), (12, 12, 12), -1)
    cv2.putText(
        panel,
        label,
        (10, 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (255, 255, 0),
        1,
        cv2.LINE_AA,
    )
    return panel


def _insertion_views_image(
    frame: np.ndarray,
    board_center: tuple[float, float],
    component_center: tuple[float, float],
    board_outline: np.ndarray | None,
    component_outline: np.ndarray | None,
    board_label: str,
    component_label: str,
) -> str:
    """Build a full-frame plus dynamic detail views for the VLM."""
    panels = (
        _view_panel(frame, "FULL CAMERA VIEW"),
        _view_panel(
            _connection_crop(frame, board_center, component_center),
            "CONNECTION CONTEXT",
            detail=True,
        ),
        _view_panel(
            _center_crop(frame, board_center, 440.0, 300.0),
            f"ARDUINO TARGET {board_label}",
            detail=True,
        ),
        _view_panel(
            _outline_crop(frame, component_outline, component_center),
            f"SENSOR TARGET {component_label}",
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
        raise RuntimeError("could not encode insertion multi-view image")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def insertion_evidence(data: InsertionUnderstanding, *, now_ms: float) -> VerificationEvidence:
    board = data.board_endpoint
    component = data.component_endpoint
    states = (board.state, component.state)
    details = {
        "board_state": board.state,
        "component_state": component.state,
        "same_wire": data.same_wire,
        "same_wire_confidence": round(data.same_wire_confidence, 3),
        "board_evidence": board.evidence,
        "component_evidence": component.evidence,
    }
    if "empty" in states:
        score = min(_SAFETY_RELIABILITY_CAP, max(
            endpoint.confidence
            for endpoint in (board, component)
            if endpoint.state == "empty"
        ))
        return VerificationEvidence(
            "visual", "fail", score, min(board.confidence, component.confidence),
            "vlm_connector_missing", now_ms, 0.0,
            "vlm_insertion", details,
        )
    seated_states = {"inserted_target", "inserted_adjacent"}
    if all(state in seated_states for state in states) and data.same_wire != "unlikely":
        score = min(
            _SAFETY_RELIABILITY_CAP,
            board.confidence,
            component.confidence,
            data.same_wire_confidence if data.same_wire == "likely" else 0.80,
        )
        adjacent = "inserted_adjacent" in states
        if adjacent:
            return VerificationEvidence(
                "visual", "fail", score, min(board.confidence, component.confidence),
                "vlm_adjacent_pin", now_ms, 0.0,
                "vlm_insertion", details,
            )
        return VerificationEvidence(
            "visual", "pass", score, min(board.confidence, component.confidence),
            "vlm_both_endpoints_inserted",
            now_ms, 0.0,
            "vlm_insertion", details,
        )
    reason = "vlm_occluded" if "occluded" in states else "vlm_uncertain"
    return VerificationEvidence.uncertain(
        "visual",
        reason,
        as_of_ms=now_ms,
        # A VLM verdict belongs to one explicit snapshot. Keep it until the
        # user requests another snapshot or changes the teaching step.
        fresh_until_ms=0.0,
        method="vlm_insertion",
        quality=min(board.confidence, component.confidence),
        details=details,
    )


class InsertionVlmWorker:
    """Runs model I/O off the camera, pose, and wire threads."""

    def __init__(
        self,
        service: VlmService,
        state: VerificationState,
        board_id: str,
        *,
        publish: Callable[[dict], None] | None = None,
        min_interval_s: float = 1.5,
    ) -> None:
        self._service = service
        self._state = state
        self._board_id = board_id
        self._publish = publish
        self._min_interval_s = max(0.2, float(min_interval_s))
        self._cond = threading.Condition()
        self._job: _InsertionJob | None = None
        self._last_submit: dict[str, float] = {}
        self._inflight_step_id: str | None = None
        self._last_outcome: dict[str, object] | None = None
        self._last_image_b64: str | None = None
        self._stop = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        with self._cond:
            self._stop = False
        self._thread = threading.Thread(
            target=self._run, name="insertion-vlm-worker", daemon=True
        )
        self._thread.start()

    def set_board_id(self, board_id: str) -> None:
        with self._cond:
            self._board_id = str(board_id)
            self._job = None
            self._last_submit.clear()
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
        """Small read-only runtime snapshot; never includes image/model text."""
        with self._cond:
            return {
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "queued_step_id": self._job.step_id if self._job is not None else None,
                "inflight_step_id": self._inflight_step_id,
                "submitted_step_ids": sorted(self._last_submit),
                "image_ready": self._last_image_b64 is not None,
                "last_outcome": dict(self._last_outcome) if self._last_outcome else None,
            }

    def preview_jpeg(self) -> bytes | None:
        """Return the exact full-frame composite sent to the insertion VLM."""
        with self._cond:
            image_b64 = self._last_image_b64
        if not image_b64:
            return None
        try:
            return base64.b64decode(image_b64, validate=True)
        except (ValueError, TypeError):
            log.exception("could not decode insertion VLM preview")
            return None

    def submit(self, step, frame, detection=None, component_pose=None) -> bool:
        """Capture one VLM image without requiring continuous pose lock.

        A current pose supplies enlarged endpoint crops. If a board or Sensor
        is momentarily out of the pose tracker, submit the raw full-resolution
        snapshot instead; this is still a deliberate VLM verification.
        """
        if frame is None or not step.expected_role:
            return False
        board_pin = next(
            (
                pin for pin in getattr(detection, "pins", ())
                if pin.pin_id == step.expected_pin_id and pin.visible
            ),
            None,
        )
        component_pin = next(
            (
                pin for pin in getattr(component_pose, "pins", ())
                if pin.id == step.expected_role and pin.visible
            ),
            None,
        )
        pose_context_ready = (
            getattr(detection, "tracking", "searching") == "locked"
            and getattr(component_pose, "tracking", "searching") in {"locked", "stale"}
            and (
                not step.component_id
                or getattr(component_pose, "component_id", None) == step.component_id
            )
            and board_pin is not None
            and component_pin is not None
        )
        now = time.monotonic()
        with self._cond:
            if now - self._last_submit.get(step.step_id, 0.0) < self._min_interval_s:
                return False
            self._last_submit[step.step_id] = now
        try:
            if pose_context_ready:
                image_b64 = _insertion_views_image(
                    frame,
                    (float(board_pin.x), float(board_pin.y)),
                    (float(component_pin.x), float(component_pin.y)),
                    getattr(detection, "outline_px", None),
                    getattr(component_pose, "outline_px", None),
                    step.expected_pin_id,
                    step.expected_role,
                )
                capture_mode = "localized"
            else:
                image_b64 = _full_frame_image(frame)
                capture_mode = "full_frame"
        except Exception:
            log.exception("could not prepare insertion multi-view VLM image")
            return False
        job = _InsertionJob(
            step.step_id,
            step.expected_pin_id,
            step.expected_role,
            int(getattr(detection, "frame_id", 0)),
            image_b64,
        )
        with self._cond:
            self._job = job  # latest-only: an old queued image has no value
            self._last_image_b64 = image_b64
            self._last_outcome = {
                "step_id": step.step_id,
                "status": "queued",
                "capture_mode": capture_mode,
            }
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
            if job is None:
                continue
            started = time.monotonic()
            with self._cond:
                self._inflight_step_id = job.step_id
            result = self._service.ask_insertion(
                image_b64=job.image_b64,
                board_pin=job.board_pin,
                component_pin=job.component_pin,
            )
            if not result.ok or result.data is None:
                log.warning("insertion VLM unavailable: %s", result.error)
                now_ms = time.monotonic() * 1000.0
                with self._cond:
                    self._inflight_step_id = None
                    self._last_outcome = {
                        "step_id": job.step_id,
                        "status": "error",
                        "error": result.error or "vlm_failed",
                        "elapsed_s": round(time.monotonic() - started, 3),
                    }
                unavailable = VerificationEvidence.uncertain(
                    "visual",
                    "vlm_unavailable",
                    as_of_ms=now_ms,
                    fresh_until_ms=0.0,
                    method="vlm_insertion",
                    details={"error": result.error or "vlm_failed"},
                )
                if self._state.update(
                    job.step_id, [unavailable], now_ms=now_ms
                ) and self._publish is not None:
                    message = self._state.message(
                        self._board_id, job.frame_id, now_ms
                    )
                    if message is not None:
                        self._publish(message)
                continue
            now_ms = time.monotonic() * 1000.0
            with self._cond:
                self._inflight_step_id = None
                self._last_outcome = {
                    "step_id": job.step_id,
                    "status": "complete",
                    "board_state": result.data.board_endpoint.state,
                    "component_state": result.data.component_endpoint.state,
                    "elapsed_s": round(time.monotonic() - started, 3),
                }
            if not self._state.update(
                job.step_id,
                [insertion_evidence(result.data, now_ms=now_ms)],
                now_ms=now_ms,
            ):
                continue
            if self._publish is not None:
                message = self._state.message(self._board_id, job.frame_id, now_ms)
                if message is not None:
                    self._publish(message)
