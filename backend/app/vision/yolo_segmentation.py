"""OpenCV DNN decoder for Ultralytics YOLO segmentation exports.

The component model is deliberately independent from board-pose detection:
it identifies visible Pi 5 parts, while the board-pose model remains the
authoritative source for board GPIO projection and wiring guidance.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComponentSegment:
    class_id: int
    class_name: str
    confidence: float
    box_xyxy: tuple[float, float, float, float]
    polygon: np.ndarray


def class_names_from_model_manifest(
    model_path: Path | str,
    fallback: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    """Load class order emitted by Component Training Studio when available.

    ONNX does not reliably preserve Ultralytics class names.  A sidecar keeps
    the decoder order synchronized without rewriting backend config for each
    newly trained model.  Invalid/absent sidecars safely retain configured
    names so older models remain compatible.
    """
    fallback_names = tuple(str(name) for name in fallback)
    manifest_path = Path(model_path).with_suffix(".json")
    if not manifest_path.is_file():
        return fallback_names
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("task") != "segment":
            raise ValueError(f"unsupported task={payload.get('task')!r}")
        names = payload.get("class_names")
        if (
            not isinstance(names, list)
            or not names
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)
        ):
            raise ValueError("class_names must be a non-empty unique string list")
        return tuple(name.strip() for name in names)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("ignoring invalid component model manifest %s: %s", manifest_path, exc)
        return fallback_names


def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float, int, int, int, int]:
    height, width = frame.shape[:2]
    scale = min(size / float(width), size / float(height))
    resized_w = max(1, int(round(width * scale)))
    resized_h = max(1, int(round(height * scale)))
    resized = cv2.resize(frame, (resized_w, resized_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    pad_x = (size - resized_w) // 2
    pad_y = (size - resized_h) // 2
    canvas[pad_y:pad_y + resized_h, pad_x:pad_x + resized_w] = resized
    return canvas, scale, pad_x, pad_y, resized_w, resized_h


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50.0, 50.0)))


def _rows(output: np.ndarray, channels: int) -> np.ndarray:
    values = np.asarray(output, dtype=np.float32)
    if values.ndim == 3 and values.shape[0] == 1:
        values = values[0]
    if values.ndim != 2:
        raise ValueError(f"YOLO segmentation output must be rank 2/3, got {values.shape}")
    if values.shape[0] == channels:
        values = values.T
    elif values.shape[1] != channels:
        raise ValueError(
            f"YOLO segmentation output has {values.shape}; expected {channels} channels"
        )
    return np.ascontiguousarray(values, dtype=np.float32)


def _map_polygon(
    polygon: np.ndarray,
    *,
    scale: float,
    pad_x: int,
    pad_y: int,
    frame_size: tuple[int, int],
) -> np.ndarray:
    width, height = frame_size
    mapped = np.asarray(polygon, dtype=np.float32).copy()
    mapped[:, 0] = (mapped[:, 0] - pad_x) / scale
    mapped[:, 1] = (mapped[:, 1] - pad_y) / scale
    mapped[:, 0] = np.clip(mapped[:, 0], 0.0, max(width - 1.0, 0.0))
    mapped[:, 1] = np.clip(mapped[:, 1], 0.0, max(height - 1.0, 0.0))
    return mapped


def decode_yolo_segmentation(
    outputs: tuple[np.ndarray, np.ndarray] | list[np.ndarray],
    *,
    frame_size: tuple[int, int],
    input_size: int,
    scale: float,
    pad_x: int,
    pad_y: int,
    resized_size: tuple[int, int],
    class_names: tuple[str, ...],
    confidence_threshold: float = 0.35,
    class_confidence_thresholds: dict[str, float] | None = None,
    mask_threshold: float = 0.50,
    nms_iou_threshold: float = 0.45,
    max_detections: int = 30,
) -> list[ComponentSegment]:
    """Decode the two-output YOLO11-seg ONNX tensor into source-frame polygons."""
    if len(outputs) < 2:
        raise ValueError("YOLO segmentation model must return detection and prototype outputs")
    prototype = np.asarray(outputs[1], dtype=np.float32)
    if prototype.ndim == 4:
        prototype = prototype[0]
    if prototype.ndim != 3:
        raise ValueError(f"unexpected mask prototype shape {prototype.shape}")
    mask_count = int(prototype.shape[0])
    class_count = len(class_names)
    rows = _rows(outputs[0], 4 + class_count + mask_count)
    scores_all = rows[:, 4:4 + class_count]
    class_ids = np.argmax(scores_all, axis=1)
    scores = scores_all[np.arange(len(rows)), class_ids]
    thresholds = np.asarray(
        [
            float((class_confidence_thresholds or {}).get(name, confidence_threshold))
            for name in class_names
        ],
        dtype=np.float32,
    )
    thresholds = np.clip(thresholds, 0.0, 1.0)
    valid = (
        np.isfinite(scores)
        & (scores >= thresholds[class_ids])
        & np.all(np.isfinite(rows[:, :4]), axis=1)
        & (rows[:, 2] > 1.0)
        & (rows[:, 3] > 1.0)
    )
    if not np.any(valid):
        return []

    candidate_rows = rows[valid]
    candidate_scores = scores[valid]
    candidate_classes = class_ids[valid]
    boxes_xywh = candidate_rows[:, :4]
    boxes = np.column_stack(
        [
            boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2.0,
            boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2.0,
            boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2.0,
            boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2.0,
        ]
    )
    boxes[:, [0, 2]] = np.clip(boxes[:, [0, 2]], 0.0, float(input_size - 1))
    boxes[:, [1, 3]] = np.clip(boxes[:, [1, 3]], 0.0, float(input_size - 1))

    keep: list[int] = []
    for class_id in np.unique(candidate_classes):
        indices = np.flatnonzero(candidate_classes == class_id)
        local_boxes = boxes[indices]
        local_scores = candidate_scores[indices]
        class_threshold = float(thresholds[int(class_id)])
        xywh = np.column_stack(
            [local_boxes[:, 0], local_boxes[:, 1],
             local_boxes[:, 2] - local_boxes[:, 0],
             local_boxes[:, 3] - local_boxes[:, 1]]
        )
        selected = cv2.dnn.NMSBoxes(
            xywh.tolist(), local_scores.tolist(),
            class_threshold, float(nms_iou_threshold),
        )
        if len(selected):
            keep.extend(int(indices[int(index)]) for index in np.asarray(selected).reshape(-1))
    keep.sort(key=lambda index: float(candidate_scores[index]), reverse=True)
    keep = keep[:max(1, int(max_detections))]

    proto_flat = prototype.reshape(mask_count, -1)
    proto_height, proto_width = int(prototype.shape[1]), int(prototype.shape[2])
    masks = _sigmoid(candidate_rows[:, 4 + class_count:] @ proto_flat)
    frame_width, frame_height = frame_size
    crop_x1, crop_y1 = int(pad_x), int(pad_y)
    crop_x2 = min(input_size, crop_x1 + int(resized_size[0]))
    crop_y2 = min(input_size, crop_y1 + int(resized_size[1]))
    results: list[ComponentSegment] = []
    for index in keep:
        mask_small = masks[index].reshape(proto_height, proto_width)
        mask_input = cv2.resize(mask_small, (input_size, input_size), interpolation=cv2.INTER_LINEAR)
        mask_input = mask_input >= float(mask_threshold)
        x1, y1, x2, y2 = (int(round(value)) for value in boxes[index])
        mask_input[:max(0, y1), :] = False
        mask_input[min(input_size, y2):, :] = False
        mask_input[:, :max(0, x1)] = False
        mask_input[:, min(input_size, x2):] = False
        mask_original = mask_input[crop_y1:crop_y2, crop_x1:crop_x2]
        if mask_original.size == 0:
            continue
        mask_original = cv2.resize(
            mask_original.astype(np.uint8), (frame_width, frame_height),
            interpolation=cv2.INTER_NEAREST,
        )
        contours, _ = cv2.findContours(mask_original, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(contour) < 4.0:
            continue
        epsilon = max(0.8, 0.006 * cv2.arcLength(contour, True))
        polygon = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2).astype(np.float32)
        if len(polygon) < 3:
            continue
        mapped_box = np.array(
            [[boxes[index, 0], boxes[index, 1]], [boxes[index, 2], boxes[index, 3]]],
            dtype=np.float32,
        )
        mapped_box = _map_polygon(
            mapped_box, scale=scale, pad_x=pad_x, pad_y=pad_y,
            frame_size=frame_size,
        )
        results.append(
            ComponentSegment(
                class_id=int(candidate_classes[index]),
                class_name=class_names[int(candidate_classes[index])],
                confidence=float(candidate_scores[index]),
                box_xyxy=(
                    float(mapped_box[0, 0]), float(mapped_box[0, 1]),
                    float(mapped_box[1, 0]), float(mapped_box[1, 1]),
                ),
                polygon=_map_polygon(
                    polygon, scale=1.0, pad_x=0, pad_y=0,
                    frame_size=frame_size,
                ),
            )
        )
    return results


class OpenCvYoloSegmentation:
    """Small, CPU-safe OpenCV DNN runtime for the component model."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        class_names: tuple[str, ...],
        input_size: int = 640,
        confidence_threshold: float = 0.35,
        class_confidence_thresholds: dict[str, float] | None = None,
        mask_threshold: float = 0.50,
        nms_iou_threshold: float = 0.45,
        max_detections: int = 30,
    ) -> None:
        self.model_path = Path(model_path)
        self.class_names = class_names
        self.input_size = int(input_size)
        self.confidence_threshold = float(confidence_threshold)
        self.class_confidence_thresholds = dict(class_confidence_thresholds or {})
        self.mask_threshold = float(mask_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.max_detections = int(max_detections)
        self._net = None
        self._load()

    def _load(self) -> None:
        if not self.model_path.is_file():
            log.warning("component segmentation model is absent at %s", self.model_path)
            return
        try:
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            log.info("loaded component segmentation ONNX model from %s", self.model_path)
        except cv2.error as exc:
            log.warning("cannot load component segmentation model %s: %s", self.model_path, exc)

    @property
    def available(self) -> bool:
        return self._net is not None

    def predict(self, frame_bgr: np.ndarray) -> list[ComponentSegment]:
        if self._net is None or frame_bgr is None or frame_bgr.size == 0:
            return []
        image, scale, pad_x, pad_y, resized_w, resized_h = _letterbox(frame_bgr, self.input_size)
        blob = cv2.dnn.blobFromImage(
            image, scalefactor=1.0 / 255.0, size=(self.input_size, self.input_size),
            swapRB=True, crop=False,
        )
        self._net.setInput(blob)
        outputs = self._net.forward(self._net.getUnconnectedOutLayersNames())
        return decode_yolo_segmentation(
            outputs,
            frame_size=(frame_bgr.shape[1], frame_bgr.shape[0]),
            input_size=self.input_size,
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            resized_size=(resized_w, resized_h),
            class_names=self.class_names,
            confidence_threshold=self.confidence_threshold,
            class_confidence_thresholds=self.class_confidence_thresholds,
            mask_threshold=self.mask_threshold,
            nms_iou_threshold=self.nms_iou_threshold,
            max_detections=self.max_detections,
        )
