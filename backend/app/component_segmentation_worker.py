"""Independent generic Pi 5 component-segmentation worker."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from app.capture.bus import FrameBus
from app.vision.yolo_segmentation import (
    ComponentSegment,
    OpenCvYoloSegmentation,
    class_names_from_model_manifest,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComponentSegmentationResult:
    frame_id: int
    ts_ms: float
    video_size: tuple[int, int]
    detections: tuple[ComponentSegment, ...]


class ComponentSegmentationState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._result: ComponentSegmentationResult | None = None

    def set(self, result: ComponentSegmentationResult) -> None:
        with self._lock:
            self._result = result

    def get(self) -> ComponentSegmentationResult | None:
        with self._lock:
            return self._result


def component_segmentation_message(result: ComponentSegmentationResult) -> dict:
    return {
        "type": "component_segments",
        "frame_id": result.frame_id,
        "ts_ms": result.ts_ms,
        "video_size": [result.video_size[0], result.video_size[1]],
        "detections": [
            {
                "class_id": int(item.class_id),
                "class_name": item.class_name,
                "confidence": round(float(item.confidence), 3),
                "box": [round(float(value), 1) for value in item.box_xyxy],
                "polygon": [
                    [round(float(x), 1), round(float(y), 1)]
                    for x, y in item.polygon
                ],
            }
            for item in result.detections
        ],
    }


class ComponentSegmentationWorker:
    def __init__(
        self,
        *,
        bus: FrameBus,
        state: ComponentSegmentationState,
        model_path: Path | str,
        class_names: tuple[str, ...],
        publish: Callable[[dict], None],
        interval_s: float = 0.35,
        input_size: int = 640,
        confidence_threshold: float = 0.35,
        class_confidence_thresholds: dict[str, float] | None = None,
        mask_threshold: float = 0.50,
        nms_iou_threshold: float = 0.45,
        max_detections: int = 30,
    ) -> None:
        self._bus = bus
        self._state = state
        self._publish = publish
        self._interval_s = max(0.05, float(interval_s))
        resolved_class_names = class_names_from_model_manifest(model_path, class_names)
        self._runtime = OpenCvYoloSegmentation(
            model_path,
            class_names=resolved_class_names,
            input_size=input_size,
            confidence_threshold=confidence_threshold,
            class_confidence_thresholds=class_confidence_thresholds,
            mask_threshold=mask_threshold,
            nms_iou_threshold=nms_iou_threshold,
            max_detections=max_detections,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="component-segmentation-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self._interval_s + 0.5))
            self._thread = None

    def _run(self) -> None:
        last_seq = -1
        while not self._stop.is_set():
            slot = self._bus.get_latest(timeout=0.1, newer_than=last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            try:
                detections = tuple(self._runtime.predict(slot.frame))
                result = ComponentSegmentationResult(
                    frame_id=slot.frame_id,
                    ts_ms=slot.ts_ms,
                    video_size=(int(slot.frame.shape[1]), int(slot.frame.shape[0])),
                    detections=detections,
                )
                self._state.set(result)
                self._publish(component_segmentation_message(result))
            except Exception:
                log.exception("component segmentation failed (frame_id=%d)", slot.frame_id)
            if self._stop.wait(self._interval_s):
                break
