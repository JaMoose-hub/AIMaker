"""OpenCV-DNN runtime for ordered 4/8-keypoint YOLO board-pose models.

The runtime deliberately has no PyTorch/Ultralytics dependency.  Training is
an offline concern; production consumes a fixed-shape, non-NMS ONNX export.
The expected model has one class and four ordered keypoints in the active
board profile coordinate system::

    0: TL (0, 0)       1: TR (W, 0)
    2: BR (W, H)       3: BL (0, H)

Ultralytics-style raw pose output is accepted in either (1, C, N) or
(1, N, C) layout, where C = 4 + num_classes + keypoints * 3.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

BOARD_KEYPOINT_COUNT = 4  # semantic board-corner prefix, kept for compatibility


@dataclass(frozen=True)
class BoardPoseObservation:
    """One board instance in source-frame pixel coordinates."""

    corners_px: np.ndarray  # (4, 2), semantic order TL/TR/BR/BL
    confidence: float
    keypoint_confidences: np.ndarray  # (4,)
    box_xyxy: tuple[float, float, float, float]
    # Full ordered model output. For legacy four-point models this is None and
    # callers use corners_px. New Pi 5 models provide all eight landmarks.
    landmarks_px: np.ndarray | None = None
    source: str = 'yolo'

    @property
    def all_points_px(self) -> np.ndarray:
        return self.corners_px if self.landmarks_px is None else self.landmarks_px


class BoardPoseLocator(Protocol):
    @property
    def available(self) -> bool: ...

    def locate(self, frame_bgr: np.ndarray) -> BoardPoseObservation | None: ...

    def close(self) -> None: ...


def refine_board_corners_from_pcb(
    frame_bgr: np.ndarray,
    observation: BoardPoseObservation,
    *,
    reference_board_bgr: np.ndarray | None = None,
    boundary_evidence: dict | None = None,
) -> BoardPoseObservation | None:
    """Refine YOLO keypoints against the visible PCB boundary.

    YOLO supplies the semantic corner order and a tight search region.  The
    color contour supplies a sharper physical board edge than a four-point
    regression head can usually provide.  Conservative geometry gates make
    this optional: callers must keep the original observation when no safe
    refinement is available.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    if boundary_evidence is not None:
        boundary_evidence.clear()
    h, w = frame_bgr.shape[:2]
    predicted = np.asarray(observation.corners_px, dtype=np.float64)
    if predicted.shape != (BOARD_KEYPOINT_COUNT, 2) or not np.all(np.isfinite(predicted)):
        return None

    bx1, by1, bx2, by2 = (float(v) for v in observation.box_xyxy)
    box_w, box_h = bx2 - bx1, by2 - by1
    if box_w <= 4.0 or box_h <= 4.0:
        return None
    # Pi 5's YOLO box can stop before the metal I/O side while the physical
    # green PCB continues to the header. Give the contour enough context to
    # recover the full board rectangle instead of accepting inner keypoints.
    margin = 0.22 * max(box_w, box_h)
    x1 = max(0, int(np.floor(bx1 - margin)))
    y1 = max(0, int(np.floor(by1 - margin)))
    x2 = min(w, int(np.ceil(bx2 + margin)))
    y2 = min(h, int(np.ceil(by2 + margin)))
    if x2 - x1 < 5 or y2 - y1 < 5:
        return None

    # Support both shipped board profiles: UNO Q is blue, Pi 5 is green.
    # The wide S/V bounds tolerate highlights and shadows while excluding the
    # neutral desk and white connectors. This is only a local board-edge
    # refinement; it never supplies semantic pin positions.
    # Work only inside the YOLO search ROI. On a 1080p stream the board often
    # occupies <20% of the frame; converting and morphologically filtering the
    # full frame made a successful lock substantially slower than searching.
    roi_bgr = frame_bgr[y1:y2, x1:x2]
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(
        hsv,
        np.array([80, 45, 20], dtype=np.uint8),
        np.array([135, 255, 255], dtype=np.uint8),
    )
    green = cv2.inRange(
        hsv,
        np.array([25, 35, 18], dtype=np.uint8),
        np.array([95, 255, 245], dtype=np.uint8),
    )
    mask = cv2.bitwise_or(blue, green)

    short_side = float(min(h, w))
    close_size = max(5, int(round(short_side * 0.023)))
    open_size = max(3, int(round(short_side * 0.0065)))
    close_size += 1 - close_size % 2
    open_size += 1 - open_size % 2
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((close_size, close_size), dtype=np.uint8)
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_OPEN, np.ones((open_size, open_size), dtype=np.uint8)
    )

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if x1 or y1:
        offset = np.array([[[x1, y1]]], dtype=np.int32)
        contours = [contour + offset for contour in contours]
    predicted_center = predicted.mean(axis=0)
    search_diagonal = max(float(np.hypot(x2 - x1, y2 - y1)), 1.0)
    min_area = max(100.0, 0.05 * float((x2 - x1) * (y2 - y1)))
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        moments = cv2.moments(contour)
        if abs(float(moments["m00"])) < 1e-9:
            continue
        center = np.array(
            [moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]],
            dtype=np.float64,
        )
        if float(np.linalg.norm(center - predicted_center)) > 0.35 * search_diagonal:
            continue
        candidates.append((area, contour))
    if not candidates:
        return None

    contour = max(candidates, key=lambda item: item[0])[1]
    contour_area = float(cv2.contourArea(contour))
    rectangle = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float64)
    if boundary_evidence is not None:
        # Pi's loose colored leads can join the PCB mask into a long, sparse
        # contour. A tinted desk can instead fill the artificial search ROI.
        # Neither is physical board-edge evidence, even if its rectangle has
        # a plausible aspect ratio. Do not alter the legacy blue-board path.
        rectangle_area = abs(float(cv2.contourArea(rectangle.astype(np.float32))))
        fill = contour_area / max(rectangle_area, 1.0)
        points = contour.reshape(-1, 2)
        at_search_edge = bool(
            np.any(points[:, 0] <= x1) or np.any(points[:, 0] >= x2 - 1)
            or np.any(points[:, 1] <= y1) or np.any(points[:, 1] >= y2 - 1)
        )
        boundary_evidence.update(fill=round(fill, 4), at_search_edge=at_search_edge)
        if fill < .65 or at_search_edge:
            boundary_evidence['rejected'] = True
            return None
    rectangle_center = rectangle.mean(axis=0)
    ordered_rectangle = rectangle[
        np.argsort(
            np.arctan2(
                rectangle[:, 1] - rectangle_center[1],
                rectangle[:, 0] - rectangle_center[0],
            )
        )
    ].astype(np.float64)
    rectangle_edges = np.linalg.norm(
        ordered_rectangle - np.roll(ordered_rectangle, -1, axis=0), axis=1
    )
    rectangle_aspect_ok = bool(
        np.min(rectangle_edges) > 8.0
        and 1.15 <= float(np.max(rectangle_edges) / np.min(rectangle_edges)) <= 3.5
    )
    # A large, rectangular green/blue contour occupying the YOLO search ROI
    # is stronger board evidence than the old inner keypoint regression. This
    # is what lets the Pi 5's green PCB correct its pin projection.
    roi_area = float(max((x2 - x1) * (y2 - y1), 1))
    trusted_color_contour = rectangle_aspect_ok and contour_area >= 0.20 * roi_area
    assigned: np.ndarray | None = None
    reference_orientation_matched = False
    if reference_board_bgr is not None and reference_board_bgr.size > 0:
        ref_h, ref_w = reference_board_bgr.shape[:2]
        if ref_w >= 32 and ref_h >= 32:
            center = rectangle.mean(axis=0)
            clockwise = rectangle[
                np.argsort(
                    np.arctan2(
                        rectangle[:, 1] - center[1],
                        rectangle[:, 0] - center[0],
                    )
                )
            ].astype(np.float32)
            destination = np.array(
                [[0, 0], [ref_w - 1, 0], [ref_w - 1, ref_h - 1], [0, ref_h - 1]],
                dtype=np.float32,
            )

            def _appearance(image: np.ndarray) -> np.ndarray:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
                return cv2.GaussianBlur(cv2.equalizeHist(gray), (5, 5), 0)

            reference_appearance = _appearance(reference_board_bgr)
            oriented: list[tuple[float, np.ndarray]] = []
            for shift in range(BOARD_KEYPOINT_COUNT):
                candidate = np.roll(clockwise, -shift, axis=0)
                transform = cv2.getPerspectiveTransform(candidate, destination)
                canonical = cv2.warpPerspective(
                    frame_bgr, transform, (ref_w, ref_h), flags=cv2.INTER_LINEAR
                )
                score = float(
                    cv2.matchTemplate(
                        _appearance(canonical),
                        reference_appearance,
                        cv2.TM_CCOEFF_NORMED,
                    )[0, 0]
                )
                if np.isfinite(score):
                    oriented.append((score, candidate.astype(np.float64)))
            oriented.sort(key=lambda item: item[0], reverse=True)
            # A weak or ambiguous template match must not redefine GPIO
            # semantics. The 50-image capture set has a minimum winning
            # margin above 0.26; these gates leave lighting tolerance while
            # making a trusted match strong enough to overrule badly
            # regressed YOLO keypoints at unseen 90/180-degree rotations.
            if (
                len(oriented) >= 2
                and oriented[0][0] >= 0.20
                and oriented[0][0] - oriented[1][0] >= 0.15
            ):
                assigned = oriented[0][1]
                reference_orientation_matched = True
    if assigned is None:
        assigned = np.asarray(
            min(
                (np.roll(ordered_rectangle, -shift, axis=0) for shift in range(4)),
                key=lambda points: float(
                    np.linalg.norm(np.asarray(points) - predicted, axis=1).sum()
                ),
            ),
            dtype=np.float64,
        )

    predicted_area = abs(float(cv2.contourArea(predicted.astype(np.float32))))
    refined_area = abs(float(cv2.contourArea(assigned.astype(np.float32))))
    if predicted_area <= 1.0:
        return None
    if (
        not reference_orientation_matched
        and not trusted_color_contour
        and not 0.45 <= refined_area / predicted_area <= 1.75
    ):
        return None
    predicted_diagonal = max(
        float(np.linalg.norm(predicted[2] - predicted[0])),
        float(np.linalg.norm(predicted[3] - predicted[1])),
        1.0,
    )
    # At the far edge of the supported distance range the small training set
    # can over-estimate the box by nearly 2x while preserving the correct
    # board center and semantic orientation.  The color contour is still
    # reliable there, so permit a bounded half-diagonal correction.  Area,
    # center-distance, ROI, color and downstream PnP gates all remain active.
    # A trusted appearance match already verifies both board identity and
    # semantic rotation, so the YOLO-to-contour shift is no longer meaningful
    # (the failure being repaired can put keypoints near edge midpoints).
    if not reference_orientation_matched and not trusted_color_contour and (
        float(np.max(np.linalg.norm(assigned - predicted, axis=1)))
        > 0.50 * predicted_diagonal
    ):
        return None

    landmarks = None
    if observation.landmarks_px is not None:
        landmarks = np.asarray(observation.landmarks_px, dtype=np.float64).copy()
        if landmarks.shape[0] >= BOARD_KEYPOINT_COUNT:
            landmarks[:BOARD_KEYPOINT_COUNT] = assigned
    return BoardPoseObservation(
        corners_px=assigned,
        confidence=observation.confidence,
        keypoint_confidences=observation.keypoint_confidences.copy(),
        box_xyxy=observation.box_xyxy,
        landmarks_px=landmarks,
    )


def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float, float, float]:
    """Resize with symmetric padding; return image, scale, pad_x, pad_y."""
    h, w = frame.shape[:2]
    scale = min(size / float(w), size / float(h))
    out_w = max(1, int(round(w * scale)))
    out_h = max(1, int(round(h * scale)))
    resized = cv2.resize(frame, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    left = (size - out_w) // 2
    top = (size - out_h) // 2
    canvas[top:top + out_h, left:left + out_w] = resized
    return canvas, scale, float(left), float(top)


def _rows_from_output(output: np.ndarray, channels: int) -> np.ndarray:
    arr = np.asarray(output, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        raise ValueError(f"YOLO pose output must be rank 2/3, got {arr.shape}")
    if arr.shape[0] == channels:
        arr = arr.T
    elif arr.shape[1] != channels:
        raise ValueError(
            f"YOLO pose output has {arr.shape}; expected one axis of {channels} channels"
        )
    return np.ascontiguousarray(arr, dtype=np.float32)


def decode_yolo_pose_output(
    output: np.ndarray,
    *,
    frame_size: tuple[int, int],
    input_size: int,
    scale: float,
    pad_x: float,
    pad_y: float,
    num_classes: int = 1,
    class_id: int = 0,
    confidence_threshold: float = 0.45,
    keypoint_threshold: float = 0.35,
    nms_iou_threshold: float = 0.45,
    keypoint_count: int = BOARD_KEYPOINT_COUNT,
) -> BoardPoseObservation | None:
    """Decode a raw Ultralytics-style pose tensor into one board observation.

    Export with NMS disabled.  Embedded-NMS/end-to-end tensors intentionally
    fail closed because their layouts differ between model generations.
    """
    keypoint_count = int(keypoint_count)
    if keypoint_count < BOARD_KEYPOINT_COUNT:
        raise ValueError("board pose requires at least four keypoints")
    channels = 4 + int(num_classes) + keypoint_count * 3
    rows = _rows_from_output(output, channels)
    if not 0 <= class_id < num_classes:
        raise ValueError("class_id is outside num_classes")
    if scale <= 0.0:
        raise ValueError("letterbox scale must be positive")

    score_offset = 4
    keypoint_offset = 4 + num_classes
    scores_all = rows[:, score_offset + class_id]
    keypoints_all = rows[:, keypoint_offset:].reshape(-1, keypoint_count, 3)
    visible_all = keypoints_all[:, :, 2] >= keypoint_threshold
    required_visible = BOARD_KEYPOINT_COUNT if keypoint_count == 4 else 6
    valid = (
        np.isfinite(scores_all)
        & (scores_all >= confidence_threshold)
        & np.all(np.isfinite(rows[:, :4]), axis=1)
        & (rows[:, 2] > 0.0)
        & (rows[:, 3] > 0.0)
        & np.all(np.isfinite(keypoints_all), axis=(1, 2))
        & np.all(visible_all[:, :BOARD_KEYPOINT_COUNT], axis=1)
        & (np.count_nonzero(visible_all, axis=1) >= required_visible)
    )
    if not np.any(valid):
        return None
    candidate_rows = rows[valid]
    candidate_keypoints = keypoints_all[valid]
    scores = scores_all[valid]
    boxes = np.column_stack(
        [
            candidate_rows[:, 0] - candidate_rows[:, 2] / 2.0,
            candidate_rows[:, 1] - candidate_rows[:, 3] / 2.0,
            candidate_rows[:, 2],
            candidate_rows[:, 3],
        ]
    )
    keep = cv2.dnn.NMSBoxes(
        boxes.tolist(), scores.tolist(), confidence_threshold, nms_iou_threshold
    )
    if len(keep) == 0:
        return None
    indices = np.asarray(keep).reshape(-1)
    best_index = max((int(i) for i in indices), key=lambda i: float(scores[i]))
    selected_keypoints = candidate_keypoints[best_index]
    points = selected_keypoints[:, :2].astype(np.float64)
    kp_conf = selected_keypoints[:, 2].astype(np.float64)
    points[:, 0] = (points[:, 0] - pad_x) / scale
    points[:, 1] = (points[:, 1] - pad_y) / scale

    frame_w, frame_h = frame_size
    # Permit a small prediction overshoot, but reject a model that has clearly
    # localized a different object outside the source frame.
    margin = 0.05 * max(frame_w, frame_h)
    if (
        np.any(points[:, 0] < -margin)
        or np.any(points[:, 0] > frame_w + margin)
        or np.any(points[:, 1] < -margin)
        or np.any(points[:, 1] > frame_h + margin)
    ):
        return None
    points[:, 0] = np.clip(points[:, 0], 0.0, max(frame_w - 1.0, 0.0))
    points[:, 1] = np.clip(points[:, 1], 0.0, max(frame_h - 1.0, 0.0))

    box = boxes[best_index]
    x1 = (box[0] - pad_x) / scale
    y1 = (box[1] - pad_y) / scale
    x2 = (box[0] + box[2] - pad_x) / scale
    y2 = (box[1] + box[3] - pad_y) / scale
    return BoardPoseObservation(
        corners_px=points[:BOARD_KEYPOINT_COUNT],
        confidence=float(np.clip(float(scores[best_index]), 0.0, 1.0)),
        keypoint_confidences=kp_conf,
        box_xyxy=(float(x1), float(y1), float(x2), float(y2)),
        landmarks_px=points if keypoint_count > BOARD_KEYPOINT_COUNT else None,
    )


class OpenCvYoloPoseLocator:
    """Ordered YOLO Pose inference through ``cv2.dnn``."""

    def __init__(
        self,
        model_path: Path | str,
        *,
        input_size: int = 960,
        confidence_threshold: float = 0.45,
        keypoint_threshold: float = 0.35,
        nms_iou_threshold: float = 0.45,
        num_classes: int = 1,
        class_id: int = 0,
        keypoint_count: int = BOARD_KEYPOINT_COUNT,
    ) -> None:
        self.model_path = Path(model_path)
        self.input_size = int(input_size)
        self.confidence_threshold = float(confidence_threshold)
        self.keypoint_threshold = float(keypoint_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.num_classes = int(num_classes)
        self.class_id = int(class_id)
        self.keypoint_count = int(keypoint_count)
        self._net = None
        self._warned = False
        self._load()

    def _load(self) -> None:
        if not self.model_path.is_file():
            log.warning(
                "YOLO pose model is absent at %s; hybrid detector will use the feature pipeline",
                self.model_path,
            )
            return
        try:
            self._net = cv2.dnn.readNetFromONNX(str(self.model_path))
            self._net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self._net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
            log.info("loaded YOLO board-pose ONNX model from %s", self.model_path)
        except cv2.error as exc:
            log.warning("cannot load YOLO pose model %s: %s", self.model_path, exc)
            self._net = None

    @property
    def available(self) -> bool:
        return self._net is not None

    def locate(self, frame_bgr: np.ndarray) -> BoardPoseObservation | None:
        return self._locate(frame_bgr)

    def locate_candidate(self, frame_bgr: np.ndarray, confidence_threshold: float) -> BoardPoseObservation | None:
        """Return an unverified candidate without changing the normal gate."""
        return self._locate(frame_bgr, confidence_threshold)

    def _locate(self, frame_bgr: np.ndarray, candidate_threshold=None) -> BoardPoseObservation | None:
        if self._net is None or frame_bgr is None or frame_bgr.size == 0:
            return None
        h, w = frame_bgr.shape[:2]
        image, scale, pad_x, pad_y = _letterbox(frame_bgr, self.input_size)
        blob = cv2.dnn.blobFromImage(
            image, scalefactor=1.0 / 255.0,
            size=(self.input_size, self.input_size), swapRB=True, crop=False,
        )
        try:
            self._net.setInput(blob)
            raw = self._net.forward()
            return decode_yolo_pose_output(
                raw,
                frame_size=(w, h),
                input_size=self.input_size,
                scale=scale,
                pad_x=pad_x,
                pad_y=pad_y,
                num_classes=self.num_classes,
                class_id=self.class_id,
                confidence_threshold=self.confidence_threshold if candidate_threshold is None else float(candidate_threshold),
                keypoint_threshold=self.keypoint_threshold,
                nms_iou_threshold=self.nms_iou_threshold,
                keypoint_count=self.keypoint_count,
            )
        except (cv2.error, ValueError) as exc:
            if not self._warned:
                log.warning("YOLO pose inference failed; using fallback pipeline: %s", exc)
                self._warned = True
            return None

    def close(self) -> None:
        self._net = None


class DirectMlYoloPoseLocator:
    """Ordered YOLO Pose inference through ONNX Runtime DirectML.

    DirectML requires sequential execution and disabled memory-pattern
    optimization.  Import remains lazy so deployments that choose the
    OpenCV runtime do not need ONNX Runtime at import time.
    """

    def __init__(
        self,
        model_path: Path | str,
        *,
        device_id: int = 0,
        input_size: int = 960,
        confidence_threshold: float = 0.45,
        keypoint_threshold: float = 0.35,
        nms_iou_threshold: float = 0.45,
        num_classes: int = 1,
        class_id: int = 0,
        keypoint_count: int = BOARD_KEYPOINT_COUNT,
    ) -> None:
        self.model_path = Path(model_path)
        self.device_id = int(device_id)
        self.input_size = int(input_size)
        self.confidence_threshold = float(confidence_threshold)
        self.keypoint_threshold = float(keypoint_threshold)
        self.nms_iou_threshold = float(nms_iou_threshold)
        self.num_classes = int(num_classes)
        self.class_id = int(class_id)
        self.keypoint_count = int(keypoint_count)
        self._session = None
        self._input_name: str | None = None
        self._warned = False
        self._load()

    def _load(self) -> None:
        if not self.model_path.is_file():
            log.warning("YOLO pose model is absent at %s", self.model_path)
            return
        try:
            import onnxruntime as ort

            if "DmlExecutionProvider" not in ort.get_available_providers():
                log.warning("ONNX Runtime DirectML provider is unavailable")
                return
            options = ort.SessionOptions()
            options.enable_mem_pattern = False
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(self.model_path),
                sess_options=options,
                providers=[
                    ("DmlExecutionProvider", {"device_id": str(self.device_id)}),
                    "CPUExecutionProvider",
                ],
            )
            if "DmlExecutionProvider" not in self._session.get_providers():
                log.warning("DirectML session fell back to CPU during model load")
                self._session = None
                return
            self._input_name = self._session.get_inputs()[0].name
            log.info(
                "loaded YOLO board-pose model with DirectML device %d from %s",
                self.device_id,
                self.model_path,
            )
        except Exception as exc:
            log.warning("cannot load DirectML YOLO pose model %s: %s", self.model_path, exc)
            self._session = None
            self._input_name = None

    @property
    def available(self) -> bool:
        return self._session is not None and self._input_name is not None

    def locate(self, frame_bgr: np.ndarray) -> BoardPoseObservation | None:
        if not self.available or frame_bgr is None or frame_bgr.size == 0:
            return None
        h, w = frame_bgr.shape[:2]
        image, scale, pad_x, pad_y = _letterbox(frame_bgr, self.input_size)
        blob = cv2.dnn.blobFromImage(
            image,
            scalefactor=1.0 / 255.0,
            size=(self.input_size, self.input_size),
            swapRB=True,
            crop=False,
        )
        try:
            raw = self._session.run(None, {self._input_name: blob})[0]
            return decode_yolo_pose_output(
                raw,
                frame_size=(w, h),
                input_size=self.input_size,
                scale=scale,
                pad_x=pad_x,
                pad_y=pad_y,
                num_classes=self.num_classes,
                class_id=self.class_id,
                confidence_threshold=self.confidence_threshold,
                keypoint_threshold=self.keypoint_threshold,
                nms_iou_threshold=self.nms_iou_threshold,
                keypoint_count=self.keypoint_count,
            )
        except Exception as exc:
            if not self._warned:
                log.warning("DirectML YOLO pose inference failed: %s", exc)
                self._warned = True
            return None

    def close(self) -> None:
        self._session = None
        self._input_name = None


def create_yolo_pose_locator(
    model_path: Path | str,
    *,
    runtime_backend: str = "opencv",
    directml_device_id: int = 0,
    cuda_device_id: int = 0,
    eye_variant: bool = False,
    **kwargs,
) -> BoardPoseLocator:
    """Create the requested runtime, falling back to OpenCV when necessary."""
    if eye_variant:
        from app.vision.eye_model import EyeModelLocator
        options = dict(runtime_backend=runtime_backend, directml_device_id=directml_device_id,
                       cuda_device_id=cuda_device_id, **kwargs)
        original = create_yolo_pose_locator(model_path, **options)
        return EyeModelLocator(original, create_yolo_pose_locator, model_path, options)
    backend = str(runtime_backend).strip().lower()
    if backend == 'cuda':
        from app.vision.cuda_pose import CudaYoloPoseLocator
        return CudaYoloPoseLocator(model_path, device_id=cuda_device_id, **kwargs)
    if backend == "directml":
        accelerated = DirectMlYoloPoseLocator(
            model_path,
            device_id=directml_device_id,
            **kwargs,
        )
        if accelerated.available:
            return accelerated
        accelerated.close()
        log.warning("falling back to OpenCV-DNN for YOLO board pose")
    elif backend != "opencv":
        raise ValueError(f"unknown YOLO runtime backend {runtime_backend!r}")
    return OpenCvYoloPoseLocator(model_path, **kwargs)
