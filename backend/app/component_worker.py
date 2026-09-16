"""Independent YOLO-Pose worker for small component pin overlays.

Legacy component models locate four semantic PCB corners and project profile
pin positions through a homography.  Newer models may append ordered pin
landmarks after that four-corner prefix; a component vision profile maps those
landmarks to pin IDs.  Keeping this inference on its own cadence prevents the
component model from reducing the controller pose/video frame rate.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import permutations
import json
import logging
from pathlib import Path
import threading
import time
from typing import Callable

import cv2
import numpy as np

from app.capture.bus import FrameBus, FrameSlot
from app.vision.yolo_pose import BoardPoseLocator, BoardPoseObservation, create_yolo_pose_locator
from app.vision.body_tracking import body_observation
from app.vision.scale_recovery import ComponentScaleRecovery

log = logging.getLogger(__name__)

_FRAME_WAIT_TIMEOUT_S = 0.1


@dataclass(frozen=True)
class ComponentPinPosition:
    id: str
    x: float
    y: float
    confidence: float
    visible: bool = True


@dataclass(frozen=True)
class ComponentPoseResult:
    component_id: str
    frame_id: int
    ts_ms: float
    tracking: str
    confidence: float
    video_size: tuple[int, int]
    outline_px: np.ndarray | None
    pins: tuple[ComponentPinPosition, ...]
    stability: str
    motion_px: float = 0.0
    visible_fraction: float | None = None
    diagnostic_box_px: tuple[float, float, float, float] | None = None
    diagnostic_pins: tuple[ComponentPinPosition, ...] = ()
    diagnostic_reason: str | None = None
    motion_outline_px: np.ndarray | None = None
    hand_fraction: float | None = None
    visibility_baseline: float | None = None
    tracking_reason: str | None = None
    reset_count: int = 0
    reset_reason: str | None = None
    model_confidence: float | None = None
    orientation_input: dict | None = None
    corner_refinement: dict | None = None
    body: dict | None = None
    reference_evidence: dict | None = None
    reacquire_evidence: dict | None = None
    visual_continuity: dict | None = None


class ComponentPoseState:
    """Thread-safe latest-value holder for the component pose worker."""

    def __init__(self, primary_component_id: str | None = None) -> None:
        self._lock = threading.Lock()
        self._result: ComponentPoseResult | None = None
        self._results: dict[str, ComponentPoseResult] = {}
        self._primary_component_id = primary_component_id
        self._slots: dict[str, FrameSlot] = {}

    def set(self, result: ComponentPoseResult, slot: FrameSlot | None = None) -> None:
        with self._lock:
            self._results[result.component_id] = result
            self._slots.pop(result.component_id, None)
            if slot is not None and slot.frame_id == result.frame_id:
                self._slots[result.component_id] = slot
            if (
                self._primary_component_id is None
                or result.component_id == self._primary_component_id
                or self._result is None
            ):
                self._result = result

    def get(self, component_id: str | None = None) -> ComponentPoseResult | None:
        with self._lock:
            if component_id is not None:
                return self._results.get(component_id)
            if self._primary_component_id is not None:
                return self._results.get(self._primary_component_id, self._result)
            return self._result

    def all(self) -> tuple[ComponentPoseResult, ...]:
        with self._lock:
            return tuple(self._results.values())

    def clear(self, component_id: str | None = None) -> None:
        with self._lock:
            if component_id is None:
                self._result = None
                self._results.clear()
                self._slots.clear()
            else:
                self._results.pop(component_id, None)
                self._slots.pop(component_id, None)
                if self._result is not None and self._result.component_id == component_id:
                    self._result = self._results.get(self._primary_component_id)
                    if self._result is None:
                        self._result = next(iter(self._results.values()), None)

    def get_synchronized(self, component_id: str):
        with self._lock:
            slot = self._slots.get(component_id)
            result = self._results.get(component_id)
            return (slot, result) if slot is not None and result is not None else None


@dataclass(frozen=True)
class ComponentVisionProfile:
    component_id: str
    pins: tuple[tuple[str, float, float], ...]
    keypoint_count: int = 4
    pin_keypoint_indices: tuple[int | None, ...] = ()
    orientation_keypoint_indices: tuple[int, int] | None = None
    corner_refinement: str = "blue_pcb"
    pin_row_orientation: bool = False
    display_outline: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (1.0, 0.0),
        (1.0, 1.0),
        (0.0, 1.0),
    )

    @classmethod
    def load(cls, path: Path | str) -> "ComponentVisionProfile":
        profile_path = Path(path)
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        keypoint_count = int(data.get("keypoint_count", 4))
        if keypoint_count < 4:
            raise ValueError("component vision profile requires at least four keypoints")
        pins = tuple(
            (str(pin["id"]), float(pin["x_norm"]), float(pin["y_norm"]))
            for pin in data["pins"]
        )
        if not pins:
            raise ValueError("component vision profile contains no pins")
        pin_keypoint_indices = tuple(
            int(pin["keypoint_index"]) if pin.get("keypoint_index") is not None else None
            for pin in data["pins"]
        )
        populated = [index for index in pin_keypoint_indices if index is not None]
        if any(index < 4 or index >= keypoint_count for index in populated):
            raise ValueError(
                "component pin keypoint_index must follow the four corners and "
                "remain below keypoint_count"
            )
        if len(populated) != len(set(populated)):
            raise ValueError("component pin keypoint_index values must be unique")
        raw_orientation = data.get("orientation_keypoint_indices")
        orientation_keypoint_indices: tuple[int, int] | None = None
        if raw_orientation is not None:
            if not isinstance(raw_orientation, list) or len(raw_orientation) != 2:
                raise ValueError(
                    "orientation_keypoint_indices must contain two keypoint indices"
                )
            orientation_keypoint_indices = (
                int(raw_orientation[0]),
                int(raw_orientation[1]),
            )
            if (
                orientation_keypoint_indices[0] == orientation_keypoint_indices[1]
                or any(
                    index < 4 or index >= keypoint_count
                    for index in orientation_keypoint_indices
                )
            ):
                raise ValueError(
                    "orientation keypoints must be distinct appended landmarks"
                )
        corner_refinement = str(data.get("corner_refinement", "blue_pcb"))
        if corner_refinement not in {"blue_pcb", "mounting_holes", "none"}:
            raise ValueError(
                "component corner_refinement must be 'blue_pcb', "
                "'mounting_holes', or 'none'"
            )
        pin_row_orientation = data.get("pin_row_orientation", False)
        if not isinstance(pin_row_orientation, bool):
            raise ValueError("component pin_row_orientation must be a boolean")
        if pin_row_orientation and (
            keypoint_count != 4
            or len(pins) < 4
            or not np.all(np.isfinite(np.asarray([pin[1:] for pin in pins])))
            or any(not 0.04 <= x <= 0.96 for _, x, _ in pins)
            or any(not 0.80 <= y <= 0.96 for _, _, y in pins)
            or not np.allclose([pin[2] for pin in pins], pins[0][2])
            or not np.all(np.diff([pin[1] for pin in pins]) > 0.06)
        ):
            raise ValueError(
                "pin_row_orientation requires a four-corner model and an ordered "
                "horizontal pin row near the canonical bottom edge"
            )
        raw_outline = data.get("display_outline")
        display_outline = (
            tuple(
                (float(point["x_norm"]), float(point["y_norm"]))
                for point in raw_outline
            )
            if raw_outline is not None
            else ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        )
        if (
            len(display_outline) != 4
            or not np.all(np.isfinite(np.asarray(display_outline, dtype=np.float64)))
        ):
            raise ValueError("component display_outline requires four finite points")
        return cls(
            component_id=str(data["id"]),
            pins=pins,
            keypoint_count=keypoint_count,
            pin_keypoint_indices=pin_keypoint_indices,
            orientation_keypoint_indices=orientation_keypoint_indices,
            corner_refinement=corner_refinement,
            pin_row_orientation=pin_row_orientation,
            display_outline=display_outline,
        )


def refine_component_corners_from_pcb(
    frame_bgr: np.ndarray,
    observation: BoardPoseObservation,
    *,
    orientation_keypoint_indices: tuple[int, int] | None = None,
) -> BoardPoseObservation | None:
    """Snap a YOLO component pose to the blue rectangular PCB boundary.

    YOLO remains responsible for object identity and semantic corner order.
    The local color contour only sharpens the physical rectangle inside the
    YOLO ROI; conservative area, aspect and displacement gates fail closed.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    predicted = np.asarray(observation.corners_px, dtype=np.float64)
    if predicted.shape != (4, 2) or not np.all(np.isfinite(predicted)):
        return None

    height, width = frame_bgr.shape[:2]
    box_x1, box_y1, box_x2, box_y2 = (float(value) for value in observation.box_xyxy)
    box_width, box_height = box_x2 - box_x1, box_y2 - box_y1
    if box_width < 12.0 or box_height < 12.0:
        return None
    margin = 0.12 * max(box_width, box_height)
    x1 = max(0, int(np.floor(box_x1 - margin)))
    y1 = max(0, int(np.floor(box_y1 - margin)))
    x2 = min(width, int(np.ceil(box_x2 + margin)))
    y2 = min(height, int(np.ceil(box_y2 + margin)))
    if x2 - x1 < 12 or y2 - y1 < 12:
        return None

    hsv = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    short_box_side = min(box_width, box_height)
    close_size = max(3, int(round(short_box_side * 0.035)))
    close_size += 1 - close_size % 2
    # Keep the same zero context as the old full-frame mask. Closing followed
    # by opening can depend on pixels up to close_size + 1 away. A clipped
    # halo preserves both that context and OpenCV's actual frame-edge rules.
    halo = close_size + 2
    mask_x1, mask_y1 = max(0, x1 - halo), max(0, y1 - halo)
    mask_x2, mask_y2 = min(width, x2 + halo), min(height, y2 + halo)
    contour_offset = np.array([mask_x1, mask_y1], dtype=np.int32)
    contours: list[np.ndarray] = []
    # The strict mask avoids merging a normally lit PCB with nearby objects;
    # the low-light mask recovers the same dark-blue board under hand shadow.
    for lower, upper in (
        ((80, 45, 20), (140, 255, 255)),
        ((75, 30, 12), (145, 255, 255)),
    ):
        blue = cv2.inRange(
            hsv,
            np.array(lower, dtype=np.uint8),
            np.array(upper, dtype=np.uint8),
        )
        mask = np.zeros((mask_y2 - mask_y1, mask_x2 - mask_x1), dtype=np.uint8)
        mask[y1 - mask_y1:y2 - mask_y1, x1 - mask_x1:x2 - mask_x1] = blue
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            np.ones((close_size, close_size), dtype=np.uint8),
        )
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((3, 3), dtype=np.uint8)
        )
        current_contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        contours.extend(contour + contour_offset for contour in current_contours)

    predicted_area = abs(float(cv2.contourArea(predicted.astype(np.float32))))
    predicted_center = predicted.mean(axis=0)
    predicted_diagonal = max(
        float(np.linalg.norm(predicted[2] - predicted[0])),
        float(np.linalg.norm(predicted[3] - predicted[1])),
        1.0,
    )
    box_area = max(box_width * box_height, 1.0)
    box_diagonal = max(float(np.hypot(box_width, box_height)), 1.0)
    candidates: list[tuple[float, np.ndarray]] = []
    orientation_candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        contour_area = float(cv2.contourArea(contour))
        if contour_area < 100.0:
            continue
        rectangle = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float64)
        refined_area = abs(float(cv2.contourArea(rectangle.astype(np.float32))))
        if refined_area <= 100.0:
            continue
        edges = np.linalg.norm(rectangle - np.roll(rectangle, -1, axis=0), axis=1)
        short_edge, long_edge = float(np.min(edges)), float(np.max(edges))
        if short_edge <= 8.0 or not 1.35 <= long_edge / short_edge <= 4.5:
            continue
        center_distance = float(np.linalg.norm(rectangle.mean(axis=0) - predicted_center))
        fill_ratio = contour_area / refined_area
        if fill_ratio < 0.22:
            continue
        score = contour_area - center_distance * max(short_edge, 1.0)
        if (
            predicted_area > 100.0
            and contour_area >= max(100.0, 0.25 * predicted_area)
            and 0.45 <= refined_area / predicted_area <= 1.80
            and center_distance <= 0.25 * predicted_diagonal
            and fill_ratio >= 0.35
        ):
            candidates.append((score, rectangle))
        box_center = np.array(
            [(box_x1 + box_x2) * 0.5, (box_y1 + box_y2) * 0.5],
            dtype=np.float64,
        )
        box_center_distance = float(np.linalg.norm(rectangle.mean(axis=0) - box_center))
        if (
            contour_area >= max(100.0, 0.05 * box_area)
            and 0.10 <= refined_area / box_area <= 0.72
            and box_center_distance <= 0.35 * box_diagonal
        ):
            orientation_score = (
                contour_area - box_center_distance * max(short_edge, 1.0)
            )
            orientation_candidates.append((orientation_score, rectangle))

    assigned: np.ndarray | None = None
    if candidates:
        rectangle = max(candidates, key=lambda item: item[0])[1]
        legacy_assigned = np.asarray(
            min(
                permutations(rectangle),
                key=lambda points: float(
                    np.linalg.norm(np.asarray(points) - predicted, axis=1).sum()
                ),
            ),
            dtype=np.float64,
        )
        if (
            float(np.max(np.linalg.norm(legacy_assigned - predicted, axis=1)))
            <= 0.30 * predicted_diagonal
        ):
            assigned = legacy_assigned

    raw_landmarks = (
        np.asarray(observation.landmarks_px, dtype=np.float64)
        if observation.landmarks_px is not None
        else None
    )
    if (
        assigned is None
        and orientation_candidates
        and orientation_keypoint_indices is not None
        and raw_landmarks is not None
        and raw_landmarks.ndim == 2
        and raw_landmarks.shape[1] == 2
    ):
        start_index, end_index = orientation_keypoint_indices
        if end_index < raw_landmarks.shape[0] and start_index < raw_landmarks.shape[0]:
            start = raw_landmarks[start_index]
            end = raw_landmarks[end_index]
            low, high = sorted((start_index, end_index))
            header_points = raw_landmarks[low : high + 1]
            direction = end - start
            direction_length = float(np.linalg.norm(direction))
            point_confidences = np.asarray(
                observation.keypoint_confidences, dtype=np.float64
            ).reshape(-1)
            confidence_ok = (
                end_index < point_confidences.size
                and start_index < point_confidences.size
                and min(
                    float(point_confidences[start_index]),
                    float(point_confidences[end_index]),
                )
                >= 0.15
            )
            if (
                confidence_ok
                and direction_length >= 0.04 * box_diagonal
                and np.all(np.isfinite(header_points))
            ):
                header_center = header_points.mean(axis=0)
                edge_candidates: list[
                    tuple[float, float, float, int, np.ndarray]
                ] = []
                for _, rectangle in orientation_candidates:
                    max_edge = max(
                        float(
                            np.linalg.norm(
                                rectangle[(index + 1) % 4] - rectangle[index]
                            )
                        )
                        for index in range(4)
                    )
                    for index in range(4):
                        first = rectangle[index]
                        second = rectangle[(index + 1) % 4]
                        edge = second - first
                        edge_length = float(np.linalg.norm(edge))
                        if edge_length < 0.80 * max_edge:
                            continue
                        cosine = abs(
                            float(np.dot(edge, direction))
                            / max(edge_length * direction_length, 1e-6)
                        )
                        relative = header_center - first
                        ratio = float(
                            np.clip(
                                np.dot(relative, edge) / max(edge_length**2, 1e-6),
                                0.0,
                                1.0,
                            )
                        )
                        nearest = first + ratio * edge
                        distance = float(np.linalg.norm(header_center - nearest))
                        edge_candidates.append(
                            (
                                distance / box_diagonal + (1.0 - cosine) * 0.80,
                                distance,
                                cosine,
                                index,
                                rectangle,
                            )
                        )
                if edge_candidates:
                    _, edge_distance, cosine, edge_index, rectangle = min(
                        edge_candidates,
                        key=lambda item: item[0],
                    )
                    first = rectangle[edge_index]
                    second = rectangle[(edge_index + 1) % 4]
                    if edge_distance <= 0.08 * box_diagonal and cosine >= 0.72:
                        if float(np.dot(first - start, direction)) <= float(
                            np.dot(second - start, direction)
                        ):
                            bottom_left, bottom_right = first, second
                        else:
                            bottom_left, bottom_right = second, first
                        remaining = [
                            rectangle[index]
                            for index in range(4)
                            if index not in (edge_index, (edge_index + 1) % 4)
                        ]
                        if float(np.linalg.norm(remaining[0] - bottom_left)) <= float(
                            np.linalg.norm(remaining[1] - bottom_left)
                        ):
                            top_left, top_right = remaining[0], remaining[1]
                        else:
                            top_left, top_right = remaining[1], remaining[0]
                        assigned = np.asarray(
                            [top_left, top_right, bottom_right, bottom_left],
                            dtype=np.float64,
                        )

    if assigned is None:
        return None
    landmarks = None
    if observation.landmarks_px is not None:
        landmarks = np.asarray(observation.landmarks_px, dtype=np.float64).copy()
        if landmarks.ndim == 2 and landmarks.shape[0] >= 4 and landmarks.shape[1] == 2:
            landmarks[:4] = assigned
        else:
            landmarks = None
    return BoardPoseObservation(
        corners_px=assigned,
        confidence=observation.confidence,
        keypoint_confidences=observation.keypoint_confidences.copy(),
        box_xyxy=observation.box_xyxy,
        landmarks_px=landmarks,
    )


def _recover_hw123_boundary(frame_bgr: np.ndarray, observation: BoardPoseObservation) -> BoardPoseObservation | None:
    """Recover a blue PCB only inside a fresh model box, never from old pose.

    HW's model sometimes predicts chip corners while its box covers the PCB.
    The candidate must still pass the independent full-row orientation check.
    """
    box = np.asarray(observation.box_xyxy, dtype=float)
    if box.shape != (4,) or not np.isfinite(box).all():
        return None
    x1, y1 = np.floor(box[:2]).astype(int)
    x2, y2 = np.ceil(box[2:]).astype(int)
    h, w = frame_bgr.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h or min(x2-x1, y2-y1) < 24:
        return None
    predicted = np.asarray(observation.corners_px, dtype=np.float32)
    if predicted.shape != (4, 2) or not np.isfinite(predicted).all():
        return None
    collapsed = abs(cv2.contourArea(predicted)) / ((x2-x1)*(y2-y1)) < .18
    hsv = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.uint8([75, 45, 20]), np.uint8([145, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        rect = cv2.boxPoints(cv2.minAreaRect(contour)).astype(np.float32)
        area = abs(cv2.contourArea(rect))
        edges = np.linalg.norm(rect - np.roll(rect, 1, axis=0), axis=1)
        if not collapsed and np.any(np.ptp(rect, axis=0) < .85 * np.array([x2-x1, y2-y1])):
            # A non-collapsed pose can be skewed, but a partly covered PCB
            # must not shrink until an unrelated component row happens to fit.
            continue
        if (min(edges) < 20 or not 1.1 <= max(edges)/min(edges) <= 1.8
                or not .35 <= area / mask.size <= 1.05
                or cv2.contourArea(contour) / max(area, 1) < .35):
            continue
        candidates.append((area, rect + [x1, y1]))
    if len(candidates) != 1:
        return None
    return replace(observation, corners_px=candidates[0][1].astype(np.float64), landmarks_px=None)


def _recover_fragmented_hw_boundary(frame_bgr, observation, profile):
    # A dark blue PCB can have V<80 while its solder pads remain bright.
    # Preserve the existing bright-mask path first; a darker-blue proposal
    # must pass exactly the same full pad-row and two mounting-hole evidence.
    for low_light in (False, True):
        for padding in (0, .10):
            recovered = _recover_fragmented_hw_roi(frame_bgr, observation, profile, padding,
                                                   low_light=low_light)
            if recovered is not None:
                return recovered
    return None


def _recover_fragmented_hw_roi(frame_bgr, observation, profile, padding, *, low_light=False):
    """Strong blue fragments plus two mounting holes, not gray chroma noise."""
    box = np.asarray(observation.box_xyxy, dtype=float)
    if box.shape != (4,) or not np.isfinite(box).all():
        return None
    x1, y1 = np.floor(box[:2]).astype(int)
    x2, y2 = np.ceil(box[2:]).astype(int)
    h, w = frame_bgr.shape[:2]
    if x1 < 0 or y1 < 0 or x2 > w or y2 > h or min(x2-x1, y2-y1) < 24:
        return None
    # Detector boxes can cut through the PCB edge even with valid confidence.
    # Give segmentation a bounded local margin; retain full row/two-hole tests.
    margin = max(2, int(round(padding * min(x2-x1, y2-y1)))) if padding else 0
    x1, y1 = max(0, x1-margin), max(0, y1-margin)
    x2, y2 = min(w, x2+margin), min(h, y2+margin)
    roi = frame_bgr[y1:y2, x1:x2]
    mask = cv2.inRange(cv2.cvtColor(roi, cv2.COLOR_BGR2HSV),
                       np.uint8([90, 60, 25] if low_light else [85, 90, 80]),
                       np.uint8([130, 255, 255]))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    points = cv2.findNonZero(mask)
    if points is None or len(points) < 100:
        return None
    for group, isolated in _hw_blue_point_groups(mask, points, split=low_light):
        rectangle = cv2.boxPoints(cv2.minAreaRect(group))
        hull = cv2.convexHull(group)
        polygon = cv2.approxPolyDP(hull, .02 * cv2.arcLength(hull, True), True)
        proposals = []
        if len(polygon) == 4 and cv2.isContourConvex(polygon):
            # Preserve perspective edges rather than widening into background.
            rect = polygon.reshape(4, 2).astype(np.float32)
            if cv2.contourArea(rect, oriented=True) < 0:
                rect = rect[::-1].copy()
            proposals.append(rect)
        # Rounded/dark corners can truncate the hull across the first pads.
        # Both alternatives must pass independent row and mounting-hole checks.
        proposals.append(rectangle)
        for rect in proposals:
            area = abs(cv2.contourArea(rect))
            edges = np.linalg.norm(rect - np.roll(rect, 1, axis=0), axis=1)
            if (min(edges) < 20 or not 1.1 <= max(edges)/min(edges) <= 1.8
                    or not (.20 if low_light else .35) <= area / mask.size <= 1.05
                    or len(group)/max(area, 1) < .12):
                continue
            candidate = replace(observation, corners_px=(rect + [x1,y1]).astype(np.float64), landmarks_px=None)
            verified = _verify_hw_boundary_landmarks(
                frame_bgr, candidate, profile, strict_layout=isolated)
            if verified is not None:
                return verified
    return None


def _hw_blue_point_groups(mask, points, *, split):
    # Retain the existing all-fragment proposal first. Only after it fails,
    # separate a nearby blue wire from the PCB. Closing groups fragments
    # across small printed/component gaps, but its invented pixels are NEVER
    # used to estimate the boundary or satisfy the material fraction.
    yield points, False
    if not split:
        return
    size = max(3, min(31, int(round(min(mask.shape) * .06))))
    size += 1 - size % 2
    grouped = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(grouped)
    biggest = sorted(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA], reverse=True)[:2]
    for label in biggest:
        if stats[label, cv2.CC_STAT_AREA] < 100:
            continue
        original = cv2.findNonZero(cv2.bitwise_and(mask, np.uint8(labels == label) * 255))
        if original is not None and 100 <= len(original) < len(points):
            yield original, True


def _verify_hw_boundary_landmarks(frame_bgr, candidate, profile, *, strict_layout=False):
    """Full pad row plus both mounting holes; independent of blue brightness."""
    oriented = orient_component_corners_from_pin_row(
        frame_bgr, candidate, profile, allow_boundary_recovery=False)
    if oriented is None:
        return None
    matrix = cv2.getPerspectiveTransform(oriented.corners_px.astype(np.float32),
        np.float32([[0,0],[255,0],[255,255],[0,255]]))
    gray = cv2.cvtColor(cv2.warpPerspective(frame_bgr, matrix, (256,256)), cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours(cv2.inRange(gray, 0, 70), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    holes = []
    # Isolating color fragments can shrink a partly occluded PCB. In that
    # alternative path the two holes must occupy the actual upper mounting
    # row, not arbitrary circular chip/solder details farther into the board.
    hole_y_min, hole_y_max = (.06, .22) if strict_layout else (.03, .35)
    for contour in contours:
        a, perimeter = cv2.contourArea(contour), cv2.arcLength(contour, True)
        if not 100 <= a <= 2000 or perimeter <= 0 or 4*np.pi*a/perimeter**2 < .45:
            continue
        m = cv2.moments(contour)
        cx, cy = m['m10']/m['m00']/255, m['m01']/m['m00']/255
        if hole_y_min < cy < hole_y_max:
            holes.append((cx, cy))
    left_holes = [(x, y) for x, y in holes if .03 < x < .3]
    right_holes = [(x, y) for x, y in holes if .7 < x < .97]
    if not any(not strict_layout or abs(a[1] - b[1]) < .04
               for a in left_holes for b in right_holes):
        # A through-hole can show a bright desk: verify its circular rim,
        # not an assumption that the hole interior must always be black.
        circles = cv2.HoughCircles(cv2.GaussianBlur(gray[:90], (5,5), 0),
            cv2.HOUGH_GRADIENT, 1, 40, param1=80, param2=18, minRadius=9, maxRadius=28)
        if circles is None:
            return None
        circle_y_min, circle_y_max = (.06, .22) if strict_layout else (.03, .3)
        left = [c for c in circles[0] if .03 < c[0]/255 < .3 and circle_y_min < c[1]/255 < circle_y_max]
        right = [c for c in circles[0] if .7 < c[0]/255 < .97 and circle_y_min < c[1]/255 < circle_y_max]
        if not any(abs(a[1]-b[1]) < (10 if strict_layout else 18) and .7 < a[2]/b[2] < 1.43 for a in left for b in right):
            return None
    return oriented


def orient_component_corners_from_pin_row(
    frame_bgr: np.ndarray,
    observation: BoardPoseObservation,
    profile: ComponentVisionProfile,
    *, allow_boundary_recovery: bool = True,
) -> BoardPoseObservation | None:
    """Disambiguate a model's cyclic corner order using visible solder pads.

    The HW-123 corner model can rotate semantic corner IDs by a quarter turn
    on breadboards even when the PCB boundary is correct. Never fix this with
    a screen-space offset or a global profile rotation: other views already
    have the right order. Compare all four cyclic orders against the physical
    pin row instead. Bright pads must contrast with *both* neighbouring gaps
    on nearly every pin; a bright breadboard edge or a pair of mounting holes
    is not sufficient. Ambiguity returns None, so the existing tracker can
    hold stale coordinates briefly and then hide them, not publish a guess.

    This only establishes image geometry, never electrical connectivity.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    def recover_boundary():
        if allow_boundary_recovery and profile.component_id == 'hw-123':
            recovered = _recover_hw123_boundary(frame_bgr, observation)
            if recovered is not None:
                result = orient_component_corners_from_pin_row(
                    frame_bgr, recovered, profile, allow_boundary_recovery=False)
                if result is not None:
                    return result
            return _recover_fragmented_hw_boundary(frame_bgr, observation, profile)
        return None

    corners = np.asarray(observation.corners_px, dtype=np.float32)
    if (
        corners.shape != (4, 2)
        or not np.all(np.isfinite(corners))
        or not cv2.isContourConvex(corners)
        or cv2.contourArea(corners, oriented=True) < 100.0
        or len(profile.pins) < 4
    ):
        return recover_boundary()
    if np.any(corners < 0) or np.any(corners >= [frame_bgr.shape[1], frame_bgr.shape[0]]):
        # Warp padding is not visible board evidence and can fabricate contrast.
        return recover_boundary()
    destination = np.array([[0, 0], [255, 0], [255, 255], [0, 255]], np.float32)
    candidates: list[tuple[float, int]] = []
    for shift in range(4):
        ordered = np.roll(corners, shift, axis=0)
        transform = cv2.getPerspectiveTransform(ordered, destination)
        rectified = cv2.warpPerspective(frame_bgr, transform, (256, 256))
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)

        # Small model boundary errors otherwise move the first pads onto gaps.
        # Search a single shared row translation, never move each pad to its
        # favourite bright pixel. Pitch, contrast and orientation margin remain
        # unchanged; offsets only establish corner ORDER, not new pin geometry.
        locations = np.array([(x, y) for _, x, y in profile.pins] + [
            ((a[1] + b[1]) * .5, a[2]) for a, b in zip(profile.pins, profile.pins[1:])
        ])
        offsets = np.array([(x, y) for x in np.linspace(-.04, .04, 9)
                            for y in np.linspace(-.04, .04, 9)])
        centres = np.rint((locations[None, :, :] + offsets[:, None, :]) * 255).astype(int)
        valid_rows = ((centres >= 4) & (centres <= 251)).all(axis=(1, 2))
        centres = centres[valid_rows]
        integral = cv2.integral(gray)
        x, y = centres[:, :, 0], centres[:, :, 1]
        values = (integral[y + 5, x + 5] - integral[y - 4, x + 5]
                  - integral[y + 5, x - 4] + integral[y - 4, x - 4]) / 81.
        pads, gaps = values[:, :len(profile.pins)], values[:, len(profile.pins):]
        neighbours = np.maximum(np.column_stack([gaps[:, 0], gaps]),
                                np.column_stack([gaps, gaps[:, -1]]))
        contrasts = pads - neighbours
        # One obscured pad is tolerated; most of the actual row must be seen.
        valid = np.count_nonzero(contrasts >= 18.0, axis=1) >= len(profile.pins) - 1
        if valid.any():
            score = float(np.max(np.percentile(contrasts[valid], 25, axis=1)))
            if score >= 22.0:
                candidates.append((score, shift))
    candidates.sort(reverse=True)
    if not candidates or (
        len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 15.0
    ):
        return recover_boundary()
    shift = candidates[0][1]
    ordered = np.roll(corners, shift, axis=0).astype(np.float64)
    confidences = np.asarray(observation.keypoint_confidences).copy()
    confidences[:4] = np.roll(confidences[:4], shift)
    landmarks = (
        np.asarray(observation.landmarks_px).copy()
        if observation.landmarks_px is not None else None
    )
    if landmarks is not None:
        landmarks[:4] = ordered
    return replace(
        observation,
        corners_px=ordered,
        keypoint_confidences=confidences,
        landmarks_px=landmarks,
    )


def refine_component_corners_from_mounting_holes(
    frame_bgr: np.ndarray,
    observation: BoardPoseObservation,
    *,
    allow_three_anchors: bool = False,
    evidence: dict | None = None,
) -> BoardPoseObservation | None:
    """Snap four coarse pose landmarks to nearby circular mounting holes.

    The YOLO model supplies semantic order and a conservative search centre.
    Hough circle detection only searches a small ROI around each landmark, so
    screen edges and header pins cannot reorder the four points. The update is
    accepted only when all holes are found and the resulting quad remains
    convex with a plausible area relative to the coarse pose. Eye can opt into
    an affine correction of the current YOLO quad from exactly three observed
    rings; the missing ring is explicitly inferred, never retained from history.
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    predicted = np.asarray(observation.corners_px, dtype=np.float64)
    if predicted.shape != (4, 2) or not np.all(np.isfinite(predicted)):
        return None

    height, width = frame_bgr.shape[:2]
    x1, y1, x2, y2 = (float(value) for value in observation.box_xyxy)
    box_width, box_height = x2 - x1, y2 - y1
    if box_width < 40.0 or box_height < 40.0:
        return None
    search_radius = int(np.clip(0.20 * min(box_width, box_height), 28.0, 96.0))
    min_circle_radius = max(3, int(round(0.012 * min(box_width, box_height))))
    max_circle_radius = max(
        min_circle_radius + 3,
        int(round(0.060 * min(box_width, box_height))),
    )
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    refined: list[np.ndarray] = []
    observed_indices: list[int] = []
    for index, point in enumerate(predicted):
        px, py = float(point[0]), float(point[1])
        roi_x1 = max(0, int(np.floor(px - search_radius)))
        roi_y1 = max(0, int(np.floor(py - search_radius)))
        roi_x2 = min(width, int(np.ceil(px + search_radius)))
        roi_y2 = min(height, int(np.ceil(py + search_radius)))
        if roi_x2 - roi_x1 < 16 or roi_y2 - roi_y1 < 16:
            if allow_three_anchors:
                continue
            return None
        roi = cv2.GaussianBlur(
            gray[roi_y1:roi_y2, roi_x1:roi_x2], (7, 7), 1.5
        )
        circles = cv2.HoughCircles(
            roi,
            cv2.HOUGH_GRADIENT,
            dp=1.0,
            minDist=max(12.0, min_circle_radius * 2.0),
            param1=80.0,
            param2=18.0,
            minRadius=min_circle_radius,
            maxRadius=max_circle_radius,
        )
        if circles is None:
            if allow_three_anchors:
                continue
            return None
        candidates: list[tuple[float, np.ndarray]] = []
        for cx, cy, radius in circles[0]:
            center = np.array(
                [roi_x1 + float(cx), roi_y1 + float(cy)], dtype=np.float64
            )
            distance = float(np.linalg.norm(center - point))
            if distance > search_radius:
                continue
            # Prefer the nearest plausible circle; a small radius penalty keeps
            # tiny solder highlights from outranking the physical mounting ring.
            radius_penalty = abs(float(radius) - 0.032 * min(box_width, box_height))
            candidates.append((distance + 0.20 * radius_penalty, center))
        if not candidates:
            if allow_three_anchors:
                continue
            return None
        refined.append(min(candidates, key=lambda item: item[0])[1])
        observed_indices.append(index)

    assigned = np.asarray(refined, dtype=np.float64)
    inferred = 0
    if allow_three_anchors:
        if evidence is not None:
            evidence['observed'] = len(refined)
        if len(refined) < 3:
            return None
        if len(refined) == 3:
            source_triangle = predicted[observed_indices].astype(np.float32)
            if abs(cv2.contourArea(source_triangle)) <= 1e-6:
                return None
            transform = cv2.getAffineTransform(source_triangle, assigned.astype(np.float32))
            if (not np.isfinite(transform).all()
                    or abs(float(np.linalg.det(transform[:, :2]))) <= 1e-9):
                return None
            assigned = cv2.transform(predicted.reshape(1, 4, 2), transform).reshape(4, 2)
            # A missing ring cannot justify a larger move than a real ring.
            # This also bounds extrapolation from an ill-conditioned triangle.
            if (not np.isfinite(assigned).all()
                    or np.max(np.linalg.norm(assigned - predicted, axis=1)) > search_radius
                    or np.any(assigned < 0)
                    or np.any(assigned[:, 0] >= width)
                    or np.any(assigned[:, 1] >= height)):
                return None
            inferred = 1
    if not cv2.isContourConvex(assigned.astype(np.float32)):
        return None
    predicted_area = abs(float(cv2.contourArea(predicted.astype(np.float32))))
    refined_area = abs(float(cv2.contourArea(assigned.astype(np.float32))))
    if predicted_area < 100.0 or not 0.55 <= refined_area / predicted_area <= 1.45:
        return None
    if evidence is not None:
        evidence.update(observed=len(refined), inferred=inferred,
                        status='adjusted_three_anchors' if inferred else 'adjusted')

    landmarks = (
        np.asarray(observation.landmarks_px, dtype=np.float64).copy()
        if observation.landmarks_px is not None
        else None
    )
    if landmarks is not None and landmarks.ndim == 2 and landmarks.shape[0] >= 4:
        landmarks[:4] = assigned
    return BoardPoseObservation(
        corners_px=assigned,
        confidence=observation.confidence,
        keypoint_confidences=observation.keypoint_confidences.copy(),
        box_xyxy=observation.box_xyxy,
        landmarks_px=landmarks,
    )


def project_component_pins(
    profile: ComponentVisionProfile,
    corners_px: np.ndarray,
    confidence: float,
    video_size: tuple[int, int],
    *,
    landmarks_px: np.ndarray | None = None,
    keypoint_confidences: np.ndarray | None = None,
) -> tuple[ComponentPinPosition, ...]:
    """Resolve component pins from direct landmarks or the profile homography.

    Four-keypoint profiles use the projected fallback. Eight-point profiles can
    either map direct landmarks explicitly or use appended points only to
    resolve orientation while keeping profile-projected pins authoritative.
    """
    corners = np.asarray(corners_px, dtype=np.float32)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError("component corners must be finite (4, 2) points")
    source = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source, corners)
    normalized = np.array(
        [[[x_norm, y_norm]] for _, x_norm, y_norm in profile.pins], dtype=np.float32
    )
    projected = cv2.perspectiveTransform(normalized, transform).reshape(-1, 2)
    width, height = video_size
    landmarks = (
        np.asarray(landmarks_px, dtype=np.float64)
        if landmarks_px is not None
        else None
    )
    landmark_confidence = (
        np.asarray(keypoint_confidences, dtype=np.float64).reshape(-1)
        if keypoint_confidences is not None
        else None
    )
    pin_indices = profile.pin_keypoint_indices
    result: list[ComponentPinPosition] = []
    for pin_offset, ((pin_id, _, _), fallback) in enumerate(
        zip(profile.pins, projected)
    ):
        point = np.asarray(fallback, dtype=np.float64)
        pin_confidence = float(confidence)
        keypoint_index = (
            pin_indices[pin_offset] if pin_offset < len(pin_indices) else None
        )
        if (
            keypoint_index is not None
            and landmarks is not None
            and landmarks.ndim == 2
            and landmarks.shape[1] == 2
            and keypoint_index < landmarks.shape[0]
            and np.all(np.isfinite(landmarks[keypoint_index]))
        ):
            point = landmarks[keypoint_index]
            if (
                landmark_confidence is not None
                and keypoint_index < landmark_confidence.size
                and np.isfinite(landmark_confidence[keypoint_index])
            ):
                pin_confidence = min(
                    pin_confidence, float(landmark_confidence[keypoint_index])
                )
        result.append(
            ComponentPinPosition(
                id=pin_id,
                x=float(point[0]),
                y=float(point[1]),
                confidence=float(np.clip(pin_confidence, 0.0, 1.0)),
                visible=bool(0 <= point[0] < width and 0 <= point[1] < height),
            )
        )
    return tuple(result)


def project_component_outline(
    profile: ComponentVisionProfile,
    corners_px: np.ndarray,
) -> np.ndarray:
    """Project a visual PCB outline from the pose landmark quadrilateral.

    Most component models label the PCB corners, so the default unit-square
    outline is unchanged. Components such as MRD_TF240 label mounting-hole
    centres instead; their profile can extend beyond the unit square to draw
    the real PCB edge without changing tracking or pin projection geometry.
    """
    corners = np.asarray(corners_px, dtype=np.float32)
    if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
        raise ValueError("component corners must be finite (4, 2) points")
    source = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source, corners)
    normalized = np.asarray(profile.display_outline, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(normalized, transform).reshape(-1, 2).astype(np.float64)


def bound_hc_corner_refinement(
    profile: ComponentVisionProfile,
    model: BoardPoseObservation,
    refined: BoardPoseObservation | None,
    video_size: tuple[int, int],
) -> tuple[BoardPoseObservation, dict | None]:
    """Color is a fine adjustment, not a replacement for HC semantic corners.

    The two raised transducers fragment the blue PCB; on a noisy gray desk,
    minAreaRect can vary by tens of pixels while the model moves <2 pixels.
    Bound every corner AND projected pin correction to a quarter of the
    model-projected adjacent pin pitch. This is a correction budget, NOT an
    assertion that the model's absolute pin coordinates are accurate.
    Other modules and appended-landmark HC models keep their existing path.
    """
    if profile.component_id != "hc-sr04" or profile.keypoint_count != 4:
        return (refined if refined is not None else model), None
    evidence = {"status": "unavailable", "limit_px": None,
                "corner_shift_px": None, "pin_shift_px": None}
    if refined is None:
        return model, evidence
    raw = np.asarray(model.corners_px, dtype=np.float64)
    candidate = np.asarray(refined.corners_px, dtype=np.float64)
    if (not ComponentPoseTracker._valid_quad(raw, video_size)
            or not ComponentPoseTracker._valid_quad(candidate, video_size)):
        evidence["status"] = "invalid_geometry"
        return model, evidence
    raw_pins = np.array([(p.x, p.y) for p in project_component_pins(
        profile, raw, model.confidence, video_size)])
    new_pins = np.array([(p.x, p.y) for p in project_component_pins(
        profile, candidate, refined.confidence, video_size)])
    pitch = float(np.min(np.linalg.norm(np.diff(raw_pins, axis=0), axis=1))) if len(raw_pins) > 1 else 0.0
    limit = .25 * pitch
    corner_shift = float(np.max(np.linalg.norm(candidate - raw, axis=1)))
    pin_shift = float(np.max(np.linalg.norm(new_pins - raw_pins, axis=1)))
    accepted = bool(np.isfinite([limit, corner_shift, pin_shift]).all()
                    and limit > 0 and max(corner_shift, pin_shift) <= limit)
    evidence.update(status="bounded_adjustment" if accepted else "retained_model",
                    limit_px=round(limit, 3), corner_shift_px=round(corner_shift, 3),
                    pin_shift_px=round(pin_shift, 3))
    return (refined if accepted else model), evidence


def refine_eye_component_from_local_image(
    frame_bgr: np.ndarray,
    observation: BoardPoseObservation,
    profile: ComponentVisionProfile,
) -> tuple[BoardPoseObservation, dict | None]:
    """Refine Eye TFT holes using native pixels around its current YOLO box.

    Identity, confidence and semantic order remain from this frame's YOLO.
    The existing hole finder supplies optional geometry, never a second model
    or an observation retained from an older frame. HC's fragmented blue PCB
    and HW's small reflective header did not improve in the bounded Eye trial.
    """
    if (profile.component_id != 'mrd-tf240-8p-cs'
            or profile.corner_refinement != 'mounting_holes'
            or profile.keypoint_count != 4):
        return observation, None
    evidence = {'method': 'mounting_holes', 'status': 'unavailable',
                'scope': 'current_yolo_body_with_circle_support',
                'support_padding_px': None, 'max_corner_shift_px': None,
                'observed': 0, 'inferred': 0,
                'input_corners_px': np.asarray(observation.corners_px).tolist(),
                'input_box_xyxy': list(observation.box_xyxy)}
    box = np.asarray(observation.box_xyxy, dtype=np.float64)
    if box.shape != (4,) or not np.isfinite(box).all():
        return observation, evidence
    short_side = float(np.min(box[2:] - box[:2]))
    if short_side < 40:
        return observation, evidence
    # The YOLO box may cross an outer mounting ring. Preserve the maximum
    # radius accepted by the existing finder plus its 7x7 blur/edge halo.
    # The search centres/radii and one finder call stay unchanged; this only
    # stops the artificial crop boundary from deleting the circle's pixels.
    min_radius = max(3, int(round(.012 * short_side)))
    support = max(min_radius + 3, int(round(.060 * short_side))) + 4
    evidence['support_padding_px'] = support
    height, width = frame_bgr.shape[:2]
    x0, y0 = np.maximum(np.floor(box[:2] - support).astype(int), [0, 0])
    x1, y1 = np.minimum(np.ceil(box[2:] + support).astype(int), [width, height])
    if x1 - x0 < 40 or y1 - y0 < 40:
        return observation, evidence
    offset = np.array([x0, y0], dtype=np.float64)
    local = replace(observation,
        corners_px=np.asarray(observation.corners_px, dtype=np.float64) - offset,
        box_xyxy=tuple(box - [x0, y0, x0, y0]),
        landmarks_px=(np.asarray(observation.landmarks_px) - offset
                      if observation.landmarks_px is not None else None))
    try:
        refined = refine_component_corners_from_mounting_holes(
            frame_bgr[y0:y1, x0:x1], local,
            allow_three_anchors=True, evidence=evidence)
    except (ValueError, cv2.error):
        return observation, evidence
    if refined is None:
        return observation, evidence
    corners = np.asarray(refined.corners_px, dtype=np.float64) + offset
    landmarks = (np.asarray(observation.landmarks_px).copy()
                 if observation.landmarks_px is not None else None)
    if landmarks is not None:
        landmarks[:4] = corners
    evidence.update(max_corner_shift_px=round(float(
        np.max(np.linalg.norm(corners - observation.corners_px, axis=1))), 3))
    return replace(observation, corners_px=corners, landmarks_px=landmarks), evidence


def component_pose_message(result: ComponentPoseResult) -> dict:
    message = {
        "type": "component_pose",
        "component_id": result.component_id,
        "frame_id": result.frame_id,
        "ts_ms": result.ts_ms,
        "tracking": result.tracking,
        "confidence": round(float(result.confidence), 3),
        "video_size": [result.video_size[0], result.video_size[1]],
        "body": result.body,
        "outline": (
            [[round(float(x), 1), round(float(y), 1)] for x, y in result.outline_px]
            if result.outline_px is not None
            else None
        ),
        "pins": [
            {
                "id": pin.id,
                "x": round(float(pin.x), 1),
                "y": round(float(pin.y), 1),
                "c": round(float(pin.confidence), 3),
                "v": bool(pin.visible),
            }
            for pin in result.pins
        ],
        "pose_quality": {
            "stability": result.stability,
            "reason": result.tracking_reason,
            "hand_fraction": round(result.hand_fraction, 4) if result.hand_fraction is not None else None,
            "visibility_baseline": round(result.visibility_baseline, 4) if result.visibility_baseline is not None else None,
            "reset_count": result.reset_count,
            "reset_reason": result.reset_reason,
            "model_confidence": round(result.model_confidence, 4) if result.model_confidence is not None else None,
            "orientation_input": result.orientation_input,
            "motion_px": round(float(result.motion_px), 2),
            "visible_fraction": (
                round(float(result.visible_fraction), 4)
                if result.visible_fraction is not None
                else None
            ),
        },
    }
    if result.corner_refinement is not None:
        message["pose_quality"]["corner_refinement"] = result.corner_refinement
    if result.reference_evidence is not None:
        message["pose_quality"]["reference_recovery"] = result.reference_evidence
    if result.reacquire_evidence is not None:
        message["pose_quality"]["reacquisition"] = result.reacquire_evidence
    if result.visual_continuity is not None:
        message["pose_quality"]["visual_continuity"] = result.visual_continuity
    if result.diagnostic_reason is not None:
        message["diagnostic"] = {
            "detected": True,
            "reason": result.diagnostic_reason,
            "box": (
                [round(float(value), 1) for value in result.diagnostic_box_px]
                if result.diagnostic_box_px is not None
                else None
            ),
            "pins": [
                {
                    "id": pin.id,
                    "x": round(float(pin.x), 1),
                    "y": round(float(pin.y), 1),
                    "c": round(float(pin.confidence), 3),
                    "v": bool(pin.visible),
                }
                for pin in result.diagnostic_pins
            ],
        }
    return message


class ComponentPoseTracker:
    """Conservative geometry stabilizer with blue-PCB occlusion freezing."""

    def __init__(
        self,
        profile: ComponentVisionProfile,
        *,
        deadband_px: float = 2.0,
        deadband_exit_confirm_frames: int = 5,
        jump_threshold_fraction: float = 0.025,
        jump_confirm_frames: int = 3,
        occlusion_hold_s: float = 2.0,
        occlusion_visibility_ratio: float = 0.80,
        visibility_warmup_frames: int = 5,
        reacquire_confirm_frames: int = 4,
        reacquire_min_visible_fraction: float = 0.45,
        hand_fraction_threshold: float = 0.08,
        visual_continuity: bool = False,
        motion_handoff: bool = False,
    ) -> None:
        self.profile = profile
        self.deadband_px = float(deadband_px)
        self.deadband_exit_confirm_frames = max(1, int(deadband_exit_confirm_frames))
        self.jump_threshold_fraction = float(jump_threshold_fraction)
        self.jump_confirm_frames = int(jump_confirm_frames)
        self.occlusion_hold_s = float(occlusion_hold_s)
        self.occlusion_visibility_ratio = float(occlusion_visibility_ratio)
        self.visibility_warmup_frames = int(visibility_warmup_frames)
        self.reacquire_confirm_frames = max(2, int(reacquire_confirm_frames))
        self.reacquire_min_visible_fraction = float(reacquire_min_visible_fraction)
        self.hand_fraction_threshold = float(hand_fraction_threshold)
        from app.vision.pose_continuity import PoseContinuity
        self.visual_continuity = PoseContinuity() if visual_continuity or motion_handoff else None
        self.motion_handoff = bool(motion_handoff)
        self._pose_window = None
        self._reacquire_estimate = None
        self._geometry_previous = None
        self._visual_supported = False
        self._last_good: ComponentPoseResult | None = None
        self._last_good_ts_ms: float | None = None
        self._visibility_baseline: float | None = None
        self._visibility_samples = 0
        self._pending_jump: np.ndarray | None = None
        self._pending_jump_count = 0
        self._deadband_pending: np.ndarray | None = None
        self._deadband_pending_count = 0
        self._skip_deadband_once = False
        self._reacquire_pending: np.ndarray | None = None
        self._reacquire_motion = None
        self._reacquire_evidence = None
        self._reacquire_pending_count = 0
        self._reacquire_last_frame: int | None = None
        self._reacquire_last_ts_ms: float | None = None
        self._needs_reacquire = False
        self._last_input: tuple[int, float, tuple[int, int]] | None = None
        self._last_result: ComponentPoseResult | None = None
        self._hand_sample: float | None = None
        self._reset_count = 0
        self._reset_reason: str | None = None

    @staticmethod
    def _quad_motion(first: np.ndarray, second: np.ndarray) -> float:
        return float(np.mean(np.linalg.norm(first - second, axis=1)))

    @staticmethod
    def _quad_diagonal(corners: np.ndarray) -> float:
        return max(
            float(np.linalg.norm(corners[2] - corners[0])),
            float(np.linalg.norm(corners[3] - corners[1])),
            1.0,
        )

    def _clear_motion_candidates(self) -> None:
        self._pose_window = None
        self._reacquire_estimate = None
        self._reacquire_motion = None
        self._reacquire_evidence = None
        self._pending_jump = None
        self._pending_jump_count = 0
        self._deadband_pending = None
        self._deadband_pending_count = 0
        self._reacquire_pending = None
        self._reacquire_pending_count = 0
        self._reacquire_last_frame = None
        self._reacquire_last_ts_ms = None

    def _forget_pose(self, reason: str) -> None:
        self._geometry_previous = None
        # A stale color maximum and old coordinates must not veto the next
        # visible object forever. Reset only this worker, not other modules.
        self._last_good = None
        self._last_good_ts_ms = None
        self._visibility_baseline = None
        self._visibility_samples = 0
        self._skip_deadband_once = False
        self._clear_motion_candidates()
        self._needs_reacquire = True
        if self.visual_continuity is not None:
            self.visual_continuity.reset()
        self._reset_count += 1
        self._reset_reason = reason

    def reset_tracking(self) -> None:
        """Forget a previous camera even when its new frames have the same size."""
        self._forget_pose("camera_changed")
        self._last_input = None
        self._last_result = None
        self._hand_sample = None

    def _image_reacquisition_tolerance(self, corners):
        base = max(2.5, self.deadband_px * 1.5)
        if self.motion_handoff and self.profile.component_id == 'hc-sr04':
            # Allow small model residuals relative to apparent board size,
            # only after image alignment. Never relax raw/static consensus.
            return max(base, min(6.0, self._quad_diagonal(corners) * .015))
        return base

    def _confirm_reacquisition(self, corners: np.ndarray, frame_id: int, ts_ms: float, frame_bgr=None) -> bool:
        self._reacquire_estimate = None
        if self._reacquire_last_frame == frame_id:
            return False
        consistency_px = max(2.5, self.deadband_px * 1.5)
        image_consistency_px = self._image_reacquisition_tolerance(corners)
        window_evidence = None
        if self.motion_handoff and frame_bgr is not None:
            if self._pose_window is None:
                from app.vision.image_pose_window import ImagePoseWindow
                self._pose_window = ImagePoseWindow(self.reacquire_confirm_frames)
            self._reacquire_estimate = self._pose_window.update(
                frame_bgr, corners, frame_id, ts_ms, image_consistency_px,
                support_quad=project_component_outline(self.profile, corners))
            window_evidence = dict(self._pose_window.evidence)
            if self._reacquire_estimate is not None:
                self._reacquire_last_frame, self._reacquire_last_ts_ms = frame_id, ts_ms
                self._reacquire_evidence = window_evidence
                return True
        motion_agrees = False
        if frame_bgr is not None:
            if self._reacquire_motion is None:
                from app.vision.motion_consensus import MotionConsensus
                self._reacquire_motion = MotionConsensus()
            motion_agrees = self._reacquire_motion.compare(
                frame_bgr, corners, frame_id, ts_ms, image_consistency_px)
            self._reacquire_evidence = dict(self._reacquire_motion.evidence)
        if (
            self._reacquire_pending is None
            or self._reacquire_last_ts_ms is None
            or not 0 < ts_ms - self._reacquire_last_ts_ms <= 1000
            or (self._quad_motion(corners, self._reacquire_pending) > consistency_px and not motion_agrees)
        ):
            self._reacquire_pending = corners.copy()
            self._reacquire_pending_count = 1
        else:
            # A motion-supported sequence is compared in the current image's
            # coordinates, not averaged with a past physical board location.
            self._reacquire_pending = corners.copy() if motion_agrees else 0.5 * self._reacquire_pending + 0.5 * corners
            self._reacquire_pending_count += 1
        self._reacquire_last_frame = frame_id
        self._reacquire_last_ts_ms = ts_ms
        if self._reacquire_evidence is not None:
            self._reacquire_evidence.update(count=self._reacquire_pending_count, required=self.reacquire_confirm_frames)
            if window_evidence is not None:
                self._reacquire_evidence['image_window'] = window_evidence
        return self._reacquire_pending_count >= self.reacquire_confirm_frames

    def _confirm_deadband_exit(self, corners: np.ndarray) -> bool:
        consistency_px = max(0.75, self.deadband_px * 0.75)
        if (
            self._deadband_pending is None
            or self._quad_motion(corners, self._deadband_pending) > consistency_px
        ):
            self._deadband_pending = corners.copy()
            self._deadband_pending_count = 1
        else:
            self._deadband_pending = 0.5 * self._deadband_pending + 0.5 * corners
            self._deadband_pending_count += 1
        if self._deadband_pending_count < self.deadband_exit_confirm_frames:
            return False
        self._deadband_pending = None
        self._deadband_pending_count = 0
        return True

    @staticmethod
    def _valid_quad(corners: np.ndarray, video_size: tuple[int, int]) -> bool:
        if corners.shape != (4, 2) or not np.all(np.isfinite(corners)):
            return False
        area = abs(float(cv2.contourArea(corners.astype(np.float32))))
        width, height = video_size
        if area < max(100.0, 0.00015 * width * height):
            return False
        edges = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
        if float(np.min(edges)) < 8.0 or float(np.max(edges) / np.min(edges)) > 8.0:
            return False
        return bool(cv2.isContourConvex(corners.astype(np.float32)))

    @staticmethod
    def _material_roi(frame_bgr: np.ndarray, corners: np.ndarray):
        # Identical polygon pixels, but no full-frame HSV/mask allocations per
        # small module. Round before bounding so rasterization stays unchanged.
        polygon_points = np.rint(corners).astype(np.int32)
        x, y, width, height = cv2.boundingRect(polygon_points)
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(frame_bgr.shape[1], x + width), min(frame_bgr.shape[0], y + height)
        if x2 <= x1 or y2 <= y1:
            return None
        hsv = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
        polygon = np.zeros(hsv.shape[:2], dtype=np.uint8)
        cv2.fillConvexPoly(polygon, polygon_points - [x1, y1], 255)
        return hsv, polygon

    @staticmethod
    def _blue_fraction(frame_bgr: np.ndarray, corners: np.ndarray) -> float:
        region = ComponentPoseTracker._material_roi(frame_bgr, corners)
        if region is None:
            return 0.0
        hsv, polygon = region
        blue = cv2.inRange(
            hsv,
            np.array([75, 30, 12], dtype=np.uint8),
            np.array([145, 255, 255], dtype=np.uint8),
        )
        total = int(cv2.countNonZero(polygon))
        if total <= 0:
            return 0.0
        return float(cv2.countNonZero(cv2.bitwise_and(blue, polygon))) / total

    def _visible_fraction(self, frame_bgr: np.ndarray, corners: np.ndarray) -> float:
        """Component-specific visible-material fraction inside the pose quad.

        Small sensor boards are mostly blue PCB, so the historical blue-ratio
        gate is a good hand/occlusion guard.  The MRD display module is the
        opposite: a large black LCD intentionally covers most of the front
        face.  Treating only blue pixels as visible material makes a correctly
        detected screen look "occluded" and prevents it from locking.  For the
        display profile, accept either blue PCB or the dark LCD/header region.
        """
        if self.profile.component_id != "mrd-tf240-8p-cs":
            return self._blue_fraction(frame_bgr, corners)

        region = self._material_roi(frame_bgr, corners)
        if region is None:
            return 0.0
        hsv, polygon = region
        blue = cv2.inRange(
            hsv,
            np.array([75, 30, 12], dtype=np.uint8),
            np.array([145, 255, 255], dtype=np.uint8),
        )
        dark_lcd = cv2.inRange(
            hsv,
            np.array([0, 0, 0], dtype=np.uint8),
            np.array([179, 255, 95], dtype=np.uint8),
        )
        visible = cv2.bitwise_or(blue, dark_lcd)
        total = int(cv2.countNonZero(polygon))
        if total <= 0:
            return 0.0
        return float(cv2.countNonZero(cv2.bitwise_and(visible, polygon))) / total

    @staticmethod
    def _hc_transducers_visible(frame_bgr: np.ndarray, corners: np.ndarray, blue: float) -> bool:
        """Corroborate a blue-sparse HC with two currently visible metal rings.

        HC is not a solid blue rectangle. Rectify a bounded local patch and
        require two separated, similarly sized bright rims around darker cores.
        This supplements material visibility; it neither replaces model identity
        nor proves connector attachment or semantic pin numbering.
        """
        if blue < .12:
            return False
        mapping = cv2.getPerspectiveTransform(np.asarray(corners, np.float32),
            np.float32([[20, 20], [340, 20], [340, 180], [20, 180]]))
        patch = cv2.warpPerspective(frame_bgr, mapping, (360, 200))
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        circles = cv2.HoughCircles(cv2.GaussianBlur(gray, (5, 5), 1),
            cv2.HOUGH_GRADIENT, 1, 70, param1=80, param2=22,
            minRadius=28, maxRadius=62)
        if circles is None:
            return False
        yy, xx = np.ogrid[:200, :360]
        left, right = [], []
        for cx, cy, radius in circles[0]:
            if not 30 < cy < 130:
                continue
            side = left if 55 < cx < 120 else right if 235 < cx < 305 else None
            if side is None:
                continue
            distance = np.hypot(xx - cx, yy - cy)
            core = gray[distance < .55 * radius]
            rim = gray[(distance > .8 * radius) & (distance < 1.12 * radius)]
            contrast = float(np.percentile(rim, 75) - np.median(core))
            if contrast >= 25:
                side.append((float(cx), float(cy), float(radius), contrast))
        pairs = [(a, b) for a in left for b in right
                 if abs(a[1] - b[1]) <= 35 and .72 <= a[2] / b[2] <= 1.4
                 and 150 <= b[0] - a[0] <= 215]
        return bool(pairs)

    @staticmethod
    def _hand_fraction(frame_bgr: np.ndarray, corners: np.ndarray) -> float:
        x, y, width, height = cv2.boundingRect(np.rint(corners).astype(np.int32))
        x1, y1 = max(0, x), max(0, y)
        x2 = min(frame_bgr.shape[1], x + width)
        y2 = min(frame_bgr.shape[0], y + height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        roi = frame_bgr[y1:y2, x1:x2]
        ycrcb = cv2.cvtColor(roi, cv2.COLOR_BGR2YCrCb)
        skin = cv2.inRange(
            ycrcb,
            np.array([0, 133, 77], dtype=np.uint8),
            np.array([255, 180, 135], dtype=np.uint8),
        )
        # Chroma noise on reflective metal must not accumulate into a hand.
        # Require spatial support while retaining contiguous finger regions.
        # This is still only an occlusion heuristic, not a hand classifier.
        skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        # Only count pixels on the proposed component. The old expanded box
        # included warm desks / nearby fingers, preventing even first lock.
        polygon = np.zeros(skin.shape, dtype=np.uint8)
        cv2.fillConvexPoly(polygon, np.rint(corners - [x1, y1]).astype(np.int32), 255)
        return float(cv2.countNonZero(cv2.bitwise_and(skin, polygon))) / max(float(cv2.countNonZero(polygon)), 1.0)

    def _held(
        self,
        *,
        frame_id: int,
        ts_ms: float,
        video_size: tuple[int, int],
        stability: str,
        motion_px: float = 0.0,
        visible_fraction: float | None = None,
        reason: str | None = None,
    ) -> ComponentPoseResult:
        if (
            self._last_good is not None
            and self._last_good_ts_ms is not None
            and ts_ms - self._last_good_ts_ms <= self.occlusion_hold_s * 1000.0
        ):
            return replace(
                self._last_good,
                frame_id=frame_id,
                ts_ms=ts_ms,
                tracking="stale",
                stability=stability,
                motion_px=motion_px,
                visible_fraction=visible_fraction,
                tracking_reason=reason,
            )
        return ComponentPoseResult(
            component_id=self.profile.component_id,
            frame_id=frame_id,
            ts_ms=ts_ms,
            tracking="searching",
            confidence=0.0,
            video_size=video_size,
            outline_px=None,
            pins=(),
            stability=stability,
            visible_fraction=visible_fraction,
            motion_px=motion_px,
            tracking_reason=reason,
        )

    def update(
        self,
        frame_bgr: np.ndarray,
        observation: BoardPoseObservation | None,
        *,
        frame_id: int,
        ts_ms: float,
        reference_evidence: dict | None = None,
    ) -> ComponentPoseResult:
        video_size = (int(frame_bgr.shape[1]), int(frame_bgr.shape[0]))
        if self._last_input is not None:
            old_frame, old_ts, old_size = self._last_input
            if video_size != old_size or frame_id < old_frame or ts_ms < old_ts:
                self._forget_pose("camera_changed")
            elif (frame_id == old_frame or ts_ms == old_ts) and self._last_result is not None:
                # Re-reading one frame is not additional acquisition evidence.
                return self._last_result
            elif ts_ms - old_ts > 1000:
                self._clear_motion_candidates()
        if self._last_good_ts_ms is not None and ts_ms - self._last_good_ts_ms > self.occlusion_hold_s * 1000:
            # Expiring an old display anchor must not erase a *recent*
            # independent HC reference confirmation at the new location.
            # Camera/sequence resets above still clear all geometry evidence.
            recent_geometry = self._geometry_previous
            keep_recent_hc = (self.motion_handoff and self.profile.component_id in ('hc-sr04', 'mrd-tf240-8p-cs')
                and recent_geometry is not None and 0 < ts_ms-recent_geometry[1] <= 400)
            self._forget_pose("tracking_expired")
            if keep_recent_hc:
                self._geometry_previous = recent_geometry
        self._last_input = (frame_id, ts_ms, video_size)
        self._hand_sample = None
        self._reacquire_evidence = None
        self._visual_supported = False
        visual_evidence = None
        # Preserve independent current reference evidence before continuation
        # can replace its coordinates/source with an older anchor's flow.
        hc_reference = (observation if self.motion_handoff
            and self.profile.component_id == 'hc-sr04'
            and observation is not None and observation.source == 'hc_reference_sift' else None)
        hc_reference_confirmed = False
        tft_rings = (observation if self.motion_handoff
            and self.profile.component_id == 'mrd-tf240-8p-cs'
            and observation is not None and observation.source in ('tft_ring_geometry', 'tft_panel_geometry') else None)
        tft_rings_confirmed = False
        if self.visual_continuity is not None:
            continued = self.visual_continuity.propose(frame_bgr, observation, frame_id, ts_ms)
            visual_evidence = dict(self.visual_continuity.evidence)
            if continued is not None:
                observation = continued
                self._visual_supported = True
        if self.motion_handoff and self.profile.component_id in ('mrd-tf240-8p-cs','hc-sr04'):
            measured = hc_reference if hc_reference is not None else tft_rings
            current_rings = measured is not None
            previous = self._geometry_previous
            self._geometry_previous = (measured.corners_px.copy(), ts_ms) if current_rings else None
            if current_rings:
                quad = measured.corners_px
                geometry_confirmed = False
                if previous is not None and 0 < ts_ms-previous[1] <= 400:
                    old = previous[0]
                    ratio = abs(cv2.contourArea(quad.astype(np.float32)))/max(abs(cv2.contourArea(old.astype(np.float32))),1.)
                    geometry_confirmed = (.65 <= ratio <= 1.55 and
                        np.max(np.linalg.norm(quad-old,axis=1)) <= .35*self._quad_diagonal(old))
                # One *strong distributed current-image* match can reacquire
                # without waiting for a second sparse model cycle. Weak
                # references retain the existing two-image requirement.
                evidence = reference_evidence or {}
                strong_reference = (hc_reference is not None
                    and evidence.get('frame_id') == frame_id
                    and evidence.get('source') == 'reference_sift'
                    and evidence.get('accepted') is True
                    and evidence.get('inliers', 0) >= 32
                    and evidence.get('inlier_ratio', 0) >= .80
                    and evidence.get('coverage', 0) >= .30
                    and evidence.get('error_px', float('inf')) <= .8)
                geometry_confirmed = geometry_confirmed or strong_reference
                if geometry_confirmed:
                    self._visual_supported = True
                    visual_evidence = {'accepted':True, 'source':'current_tft_ring_geometry', 'observed_rings':4,
                                       'consecutive_images':2}
                    if tft_rings is not None:
                        observation = tft_rings
                        tft_rings_confirmed = True
                        if tft_rings.source == 'tft_panel_geometry':
                            visual_evidence = {'accepted': True, 'source': 'current_tft_panel_geometry',
                                'geometry': 'lcd_edges_and_at_least_three_rings', 'consecutive_images': 2}
                    if self.profile.component_id == 'hc-sr04':
                        observation = hc_reference
                        hc_reference_confirmed = True
                        visual_evidence = {'accepted':True, 'source':'current_hc_reference_geometry',
                            'consecutive_images':1 if strong_reference else 2,
                            'confirmation':'strong_current_match' if strong_reference else 'two_current_matches'}
                elif not self._visual_supported:
                    self._needs_reacquire = True
        result = self._update(frame_bgr, observation, frame_id=frame_id, ts_ms=ts_ms)
        if (self.visual_continuity is not None and result.tracking == 'locked'
                and (not self._visual_supported or hc_reference_confirmed or tft_rings_confirmed) and result.outline_px is not None):
            if hc_reference_confirmed or tft_rings_confirmed:
                # Old-flow agreement must not prevent the corrected reference
                # pose from becoming the next continuation anchor.
                self.visual_continuity.reset()
            self.visual_continuity.seed(frame_bgr, result.outline_px, frame_id, ts_ms,
                support_quad=project_component_outline(self.profile, result.outline_px) if self.motion_handoff else None)
        self._last_result = replace(result, hand_fraction=self._hand_sample,
            visual_continuity=visual_evidence,
            reacquire_evidence=self._reacquire_evidence,
            visibility_baseline=self._visibility_baseline,
            model_confidence=float(observation.confidence) if observation is not None else None,
            reset_count=self._reset_count, reset_reason=self._reset_reason)
        return self._last_result

    def _update(
        self, frame_bgr: np.ndarray, observation: BoardPoseObservation | None,
        *, frame_id: int, ts_ms: float,
    ) -> ComponentPoseResult:
        height, width = frame_bgr.shape[:2]
        video_size = (int(width), int(height))
        if observation is None:
            self._clear_motion_candidates()
            return self._held(
                frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                stability="occlusion_hold",
                reason="model_missing",
            )

        corners = np.asarray(observation.corners_px, dtype=np.float64)
        if not self._valid_quad(corners, video_size):
            self._clear_motion_candidates()
            held = self._held(
                frame_id=frame_id,
                ts_ms=ts_ms,
                video_size=video_size,
                stability="invalid_pose_hold",
                reason="invalid_quad",
            )
            if held.tracking == "stale":
                return held
            x1, y1, x2, y2 = observation.box_xyxy
            diagnostic_corners = np.array(
                [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.float64
            )
            diagnostic_pins = project_component_pins(
                self.profile,
                diagnostic_corners,
                float(observation.confidence),
                video_size,
                landmarks_px=observation.landmarks_px,
                keypoint_confidences=observation.keypoint_confidences,
            )
            return ComponentPoseResult(
                component_id=self.profile.component_id,
                frame_id=frame_id,
                ts_ms=ts_ms,
                tracking="searching",
                confidence=float(observation.confidence),
                video_size=video_size,
                outline_px=None,
                pins=(),
                stability="invalid_hold",
                diagnostic_box_px=tuple(float(value) for value in observation.box_xyxy),
                diagnostic_pins=diagnostic_pins,
                diagnostic_reason="invalid_quad",
            )

        # Measure the proposed PCB, not only the old location: a deliberate
        # component move should reacquire once the new quad contains a clear
        # blue board, while a hand-contaminated jump usually contains little
        # or no PCB evidence and is frozen below.
        visible_fraction = self._visible_fraction(frame_bgr, corners)
        hand_fraction = self._hand_fraction(frame_bgr, corners)
        self._hand_sample = hand_fraction
        # Webcam HC edge-grip: skin alone is not a whole-board occlusion.
        # Require both current transducer rings plus blue PCB and a strong
        # oriented model proposal; retain all geometry/reacquisition checks.
        edge_grip_supported = (
            self.motion_handoff and self.profile.component_id == 'hc-sr04'
            and self.hand_fraction_threshold <= hand_fraction < .20
            and visible_fraction >= .25 and float(observation.confidence) >= .60
            and self._hc_transducers_visible(frame_bgr, corners, visible_fraction)
        )
        hand_blocked = hand_fraction >= self.hand_fraction_threshold and not edge_grip_supported
        # Keep blue-fraction baselines comparable between frames. Ring evidence
        # corroborates acquisition separately; never mix a transient Hough
        # coverage score into the rolling occlusion baseline.
        hc_material_supported = (
            self.profile.component_id == "hc-sr04"
            and visible_fraction < self.reacquire_min_visible_fraction
            and not hand_blocked
            and self._hc_transducers_visible(frame_bgr, corners, visible_fraction)
        )
        if (not self._visual_supported and self._last_good is None and visible_fraction < self.reacquire_min_visible_fraction
                and not hc_material_supported):
            self._clear_motion_candidates()
            return self._held(frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                stability="occlusion_hold", visible_fraction=visible_fraction, reason="insufficient_material")
        baseline_ready = self._visibility_samples >= self.visibility_warmup_frames
        occluded = (
            baseline_ready
            and self._visibility_baseline is not None
            and visible_fraction < self._visibility_baseline * self.occlusion_visibility_ratio
        )

        motion_from_last = 0.0
        large_relocation = False
        if self._last_good is not None and self._last_good.outline_px is not None:
            previous = self._last_good.outline_px
            motion_from_last = self._quad_motion(corners, previous)
            previous_area = max(
                abs(float(cv2.contourArea(previous.astype(np.float32)))), 1.0
            )
            candidate_area = abs(float(cv2.contourArea(corners.astype(np.float32))))
            area_ratio = candidate_area / previous_area
            relocation_threshold = max(
                3.0,
                self.jump_threshold_fraction * self._quad_diagonal(previous),
            )
            large_relocation = (
                motion_from_last > relocation_threshold
                or not 0.88 <= area_ratio <= 1.14
            )

        # A deliberately moved Sensor can have a different blue-fill ratio
        # than the old pose. Do not lower the occlusion threshold globally;
        # instead require one clear, hand-free new pose to persist for several
        # low-frequency component ticks before re-locking there.
        force_reacquire = self._visual_supported
        baseline_floor = (
            (self._visibility_baseline or 0.0) * 0.70
            if baseline_ready else 0.0
        )
        if self._visual_supported:
            self._needs_reacquire = False
            self._clear_motion_candidates()
        elif large_relocation or self._needs_reacquire:
            clear_enough = (visible_fraction >= baseline_floor and
                (visible_fraction >= self.reacquire_min_visible_fraction or hc_material_supported))
            hand_free = not hand_blocked
            if not clear_enough or not hand_free:
                self._clear_motion_candidates()
                return self._held(
                    frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                    stability="occlusion_hold", motion_px=motion_from_last,
                    visible_fraction=visible_fraction,
                    reason="skin_on_component" if not hand_free else "material_below_baseline",
                )
            if not self._confirm_reacquisition(corners, frame_id, ts_ms, frame_bgr):
                return self._held(
                    frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                    stability="reacquire_hold", motion_px=motion_from_last,
                    visible_fraction=visible_fraction,
                    reason="awaiting_consensus",
                )
            force_reacquire = True
            if self._reacquire_estimate is not None:
                corners = self._reacquire_estimate
            self._needs_reacquire = False
            self._pending_jump = None
            self._pending_jump_count = 0
            self._deadband_pending = None
            self._deadband_pending_count = 0
            self._reacquire_pending = None
            self._reacquire_pending_count = 0
            self._visibility_baseline = visible_fraction
            self._visibility_samples = 1
        elif occluded or hand_blocked:
            self._clear_motion_candidates()
            return self._held(
                frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                stability="occlusion_hold", visible_fraction=visible_fraction,
                reason="skin_on_component" if hand_blocked else "material_below_baseline",
            )
        else:
            self._reacquire_pending = None
            self._reacquire_pending_count = 0

        motion_px = motion_from_last if force_reacquire else 0.0
        accepted = corners
        stability = "tracking" if self._visual_supported else "reacquired" if force_reacquire else "tracking"
        if (
            not force_reacquire
            and self._last_good is not None
            and self._last_good.outline_px is not None
        ):
            previous = self._last_good.outline_px
            motion_px = self._quad_motion(corners, previous)
            if motion_px <= self.deadband_px:
                accepted = previous.copy()
                stability = "deadband"
                self._clear_motion_candidates()
            else:
                previous_area = max(
                    abs(float(cv2.contourArea(previous.astype(np.float32)))), 1.0
                )
                candidate_area = abs(float(cv2.contourArea(corners.astype(np.float32))))
                area_ratio = candidate_area / previous_area
                jump_threshold = max(
                    3.0,
                    self.jump_threshold_fraction * self._quad_diagonal(previous),
                )
                is_large_motion = (
                    motion_px > jump_threshold or not 0.88 <= area_ratio <= 1.14
                )
                if is_large_motion:
                    consistency_limit = max(2.5, jump_threshold * 0.60)
                    if (
                        self._pending_jump is not None
                        and self._quad_motion(corners, self._pending_jump) <= consistency_limit
                    ):
                        self._pending_jump_count += 1
                        self._pending_jump = 0.5 * self._pending_jump + 0.5 * corners
                    else:
                        self._pending_jump = corners.copy()
                        self._pending_jump_count = 1
                    if self._pending_jump_count < self.jump_confirm_frames:
                        return self._held(
                            frame_id=frame_id, ts_ms=ts_ms, video_size=video_size,
                            stability="jump_hold", motion_px=motion_px,
                            visible_fraction=visible_fraction,
                        )
                    self._pending_jump = None
                    self._pending_jump_count = 0
                    self._deadband_pending = None
                    self._deadband_pending_count = 0
                    self._skip_deadband_once = True
                else:
                    self._pending_jump = None
                    self._pending_jump_count = 0

                bypass_deadband = self._skip_deadband_once
                self._skip_deadband_once = False
                if not bypass_deadband and not self._confirm_deadband_exit(corners):
                    accepted = previous.copy()
                    stability = "deadband"

        confidence = min(
            float(observation.confidence),
            float(np.min(observation.keypoint_confidences)),
        )
        reuse_held_pins = (
            self._last_good is not None
            and self._last_good.outline_px is not None
            and np.array_equal(accepted, self._last_good.outline_px)
        )
        pins = (
            self._last_good.pins
            if reuse_held_pins and self._last_good is not None
            else project_component_pins(
                self.profile,
                accepted,
                confidence,
                video_size,
                landmarks_px=observation.landmarks_px,
                keypoint_confidences=observation.keypoint_confidences,
            )
        )
        result = ComponentPoseResult(
            component_id=self.profile.component_id,
            frame_id=frame_id,
            ts_ms=ts_ms,
            tracking="locked",
            confidence=confidence,
            video_size=video_size,
            outline_px=np.asarray(accepted, dtype=np.float64),
            pins=pins,
            stability=stability,
            motion_px=motion_px,
            visible_fraction=visible_fraction,
        )
        self._last_good = result
        self._last_good_ts_ms = ts_ms
        if visible_fraction > 0.0 and not self._visual_supported:
            self._visibility_samples += 1
            # Track recent accepted appearance, not a lifetime maximum from a
            # different exposure/angle. Rejected frames never update this value.
            self._visibility_baseline = (visible_fraction if self._visibility_baseline is None
                else .9 * self._visibility_baseline + .1 * visible_fraction)
        return result


class ComponentPoseWorker:
    def __init__(
        self,
        *,
        bus: FrameBus,
        state: ComponentPoseState,
        model_path: Path | str,
        profile_path: Path | str,
        publish: Callable[[dict], None],
        interval_s: float = 0.30,
        input_size: int = 768,
        confidence_threshold: float = 0.35,
        keypoint_threshold: float = 0.25,
        nms_iou_threshold: float = 0.45,
        runtime_backend: str = "opencv",
        directml_device_id: int = 0,
        cuda_device_id: int = 0,
        deadband_px: float = 2.0,
        deadband_exit_confirm_frames: int = 5,
        jump_threshold_fraction: float = 0.025,
        jump_confirm_frames: int = 3,
        occlusion_hold_s: float = 2.0,
        occlusion_visibility_ratio: float = 0.80,
        visibility_warmup_frames: int = 5,
        reacquire_confirm_frames: int = 4,
        reacquire_min_visible_fraction: float = 0.45,
        hand_fraction_threshold: float = 0.08,
        webcam_motion_handoff: bool = False,
        locator: BoardPoseLocator | None = None,
    ) -> None:
        self._bus = bus
        self._state = state
        self._publish = publish
        self._interval_s = max(float(interval_s), 0.05)
        self._profile = ComponentVisionProfile.load(profile_path)
        self._scale_recovery = ComponentScaleRecovery(
            vertical_strips=self._profile.component_id == 'mrd-tf240-8p-cs')
        self._scale_recovery_enabled = False
        self._yolo_only = False
        self._confidence_threshold = float(confidence_threshold)
        from app.vision.tft_ring_geometry import TftRingAcquirer
        self._tft_rings = TftRingAcquirer()
        self._reset_eye_yolo_search()
        from app.vision.reference_recovery import ReferencePoseRecovery
        self._reference_recovery = ReferencePoseRecovery.from_component_profile(profile_path)
        self._locator = locator or create_yolo_pose_locator(
            model_path,
            eye_variant=True,
            runtime_backend=runtime_backend,
            directml_device_id=directml_device_id,
            cuda_device_id=cuda_device_id,
            input_size=input_size,
            confidence_threshold=confidence_threshold,
            keypoint_threshold=keypoint_threshold,
            nms_iou_threshold=nms_iou_threshold,
            keypoint_count=self._profile.keypoint_count,
        )
        self._tracker = ComponentPoseTracker(
            self._profile,
            deadband_px=deadband_px,
            deadband_exit_confirm_frames=deadband_exit_confirm_frames,
            jump_threshold_fraction=jump_threshold_fraction,
            jump_confirm_frames=jump_confirm_frames,
            occlusion_hold_s=occlusion_hold_s,
            occlusion_visibility_ratio=occlusion_visibility_ratio,
            visibility_warmup_frames=visibility_warmup_frames,
            reacquire_confirm_frames=reacquire_confirm_frames,
            reacquire_min_visible_fraction=reacquire_min_visible_fraction,
            hand_fraction_threshold=hand_fraction_threshold,
            motion_handoff=webcam_motion_handoff,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="component-pose-worker", daemon=True
        )
        self._thread.start()

    def stop(self, *, close_models: bool = True) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self._interval_s + 0.5))
            if self._thread.is_alive():
                raise RuntimeError("component worker did not stop")
            self._thread = None
        if close_models:
            try:
                self._locator.close()
            except Exception:
                log.exception("component pose locator close failed")

    def reset_tracking(self) -> None:
        """Call while stopped to retain the loaded model across camera changes."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("stop component worker before resetting tracking")
        self._tracker.reset_tracking()
        self._tft_rings.reset()
        self._scale_recovery.reset()
        self._reset_eye_yolo_search()
        self._state.clear(self._profile.component_id)
        if self._reference_recovery is not None:
            self._reference_recovery.evidence = {}
            self._reference_recovery.last_observation = None

    def set_scale_recovery(self, enabled: bool) -> None:
        """Enable Eye's HC-SR04/TFT search while stopped, without loading a model."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("stop component worker before configuring scale recovery")
        self._scale_recovery_enabled = bool(enabled) and self._profile.component_id in {'hc-sr04', 'mrd-tf240-8p-cs'}
        self._tft_rings.reset()
        self._scale_recovery.reset()
        self._reset_eye_yolo_search()

    def set_yolo_only(self, enabled: bool) -> None:
        """Use current YOLO keypoints plus profile pin geometry for Eye's MVP."""
        self.set_scale_recovery(enabled)
        self._yolo_only = bool(enabled)
        configure_locator = getattr(self._locator, 'set_yolo_only', None)
        if callable(configure_locator):
            configure_locator(bool(enabled))

    def _locate(self, frame: np.ndarray) -> BoardPoseObservation | None:
        candidate = None
        if self._tft_candidate_enabled():
            original = getattr(self._locator, 'original', self._locator)
            candidate = getattr(original, 'locate_candidate', None)
        observation = (candidate(frame, min(.08, self._confidence_threshold))
                       if callable(candidate) else self._locator.locate(frame))
        if self._scale_recovery_enabled and (observation is None or not self._outline_matches_box(observation)):
            recovered = self._scale_recovery.locate(frame, self._locator, accept=self._outline_matches_box)
            if recovered is not None:
                observation = recovered
        return observation

    def _tft_candidate_enabled(self) -> bool:
        return (not self._yolo_only and not self._scale_recovery_enabled
                and self._tracker.motion_handoff
                and self._profile.component_id == 'mrd-tf240-8p-cs'
                and self._profile.corner_refinement == 'mounting_holes')

    def _refine_tft_candidate(self, frame, observation, frame_id, ts_ms):
        ring_observation = self._tft_rings.locate(frame, observation, frame_id, ts_ms)
        evidence = dict(self._tft_rings.evidence)
        if ring_observation is not None:
            return ring_observation, evidence
        if observation is None or observation.confidence < self._confidence_threshold:
            evidence['fallback'] = 'unverified_candidate_rejected'
            return None, evidence
        evidence['fallback'] = 'current_model_pose_requires_consensus'
        return (refine_component_corners_from_mounting_holes(frame, observation) or observation), evidence

    def _reset_eye_yolo_search(self) -> None:
        self._eye_yolo_region = 0
        self._eye_yolo_shape = None

    def _locate_eye_yolo_once(self, frame: np.ndarray) -> BoardPoseObservation | None:
        """Spend one current-frame YOLO forward on full image or one crop.

        A successful region stays selected. A miss schedules the next region
        for the following frame, cycling back to full-frame after the existing
        HC quadrants or TFT strips. Only the region cursor survives a call;
        observations never do. The normal _locate path remains independent.
        """
        height, width = frame.shape[:2]
        if self._eye_yolo_shape != (height, width):
            self._reset_eye_yolo_search()
            self._eye_yolo_shape = (height, width)
        regions = [(0, 0, width, height)]
        vertical = self._profile.component_id == 'mrd-tf240-8p-cs'
        if self._scale_recovery_enabled and height >= 2 and width >= 2:
            # These are exactly ComponentScaleRecovery's existing source-pixel
            # crops; Eye schedules them across frames instead of after a second
            # full-image forward in the same frame.
            tile_width = (width + 1) // 2
            tile_height = height if vertical else (height + 1) // 2
            offsets = (((width - tile_width) // 2, 0), (0, 0), (width - tile_width, 0)) if vertical else (
                (0, 0), (width - tile_width, 0), (0, height - tile_height),
                (width - tile_width, height - tile_height))
            regions.extend((x, y, tile_width, tile_height) for x, y in offsets)
        index = self._eye_yolo_region % len(regions)
        x, y, region_width, region_height = regions[index]
        image = frame if index == 0 else frame[y:y + region_height, x:x + region_width]
        try:
            observation = self._locator.locate(image)
        except Exception:
            self._eye_yolo_region = (index + 1) % len(regions)
            raise
        if observation is not None and index:
            if vertical:
                bx1, _, bx2, _ = observation.box_xyxy
                # Retain the existing rejection of a TFT cut by an artificial
                # crop edge; its geometry is not an observation of a whole body.
                if (x > 0 and bx1 < 0) or (x + region_width < width and bx2 > region_width):
                    observation = None
            if observation is not None:
                offset = np.array([x, y], dtype=float)
                observation = replace(
                    observation,
                    corners_px=observation.corners_px + offset,
                    box_xyxy=tuple((np.asarray(observation.box_xyxy) + np.tile(offset, 2)).tolist()),
                    landmarks_px=(None if observation.landmarks_px is None
                                  else observation.landmarks_px + offset),
                    source='yolo_tile',
                )
        try:
            success = observation is not None and self._outline_matches_box(observation)
        except (ValueError, TypeError, cv2.error):
            success = False
        self._eye_yolo_region = index if success else (index + 1) % len(regions)
        # The existing TFT outline/box check only chooses the next search.
        # Preserve this frame's direct YOLO output even for its small quad.
        return observation

    def _outline_matches_box(self, observation: BoardPoseObservation) -> bool:
        if self._profile.component_id != 'mrd-tf240-8p-cs':
            return True
        outline = project_component_outline(self._profile, observation.corners_px)
        x1, y1, x2, y2 = observation.box_xyxy
        box_area = max(1., (x2 - x1) * (y2 - y1))
        outline_area = abs(float(cv2.contourArea(np.asarray(outline, np.float32))))
        return outline_area / box_area >= .20

    def _direct_yolo_result(self, slot: FrameSlot, observation: BoardPoseObservation | None) -> ComponentPoseResult:
        video_size = (slot.frame.shape[1], slot.frame.shape[0])
        confidence = float(observation.confidence) if observation is not None else 0.
        body = body_observation(observation, video_size)
        empty = ComponentPoseResult(self._profile.component_id, slot.frame_id, slot.ts_ms,
            'searching', 0., video_size, None, (), 'yolo_direct', body=body,
            model_confidence=confidence if observation is not None else None,
            tracking_reason='model_missing' if observation is None else 'invalid_quad')
        if observation is None:
            return empty
        corners = np.asarray(observation.corners_px, np.float32)
        if (corners.shape != (4, 2) or not np.isfinite(corners).all()
                or not cv2.isContourConvex(corners) or abs(cv2.contourArea(corners)) < 1.):
            return empty
        from app.vision.eye_geometry import clipped_corners
        if clipped_corners(corners, video_size, observation.box_xyxy):
            return replace(empty, body={**body, 'partial': True} if body else None,
                           tracking_reason='yolo_clipped')
        if self._yolo_only:
            observation, refinement = refine_eye_component_from_local_image(
                slot.frame, observation, self._profile)
            corners = np.asarray(observation.corners_px, np.float32)
            empty = replace(empty, corner_refinement=refinement)
        pins = project_component_pins(self._profile, corners, confidence, video_size,
            landmarks_px=observation.landmarks_px,
            keypoint_confidences=observation.keypoint_confidences)
        outline = project_component_outline(self._profile, corners)
        if not np.isfinite(outline).all() or not all(np.isfinite([pin.x, pin.y]).all() for pin in pins):
            return empty
        return replace(empty, tracking='locked', confidence=confidence, outline_px=outline,
                       pins=pins, motion_outline_px=outline, tracking_reason='yolo_direct')

    def detect_yolo_frame(self, slot: FrameSlot) -> ComponentPoseResult:
        """Infer and project one source frame without publishing or tracking state."""
        return self._direct_yolo_result(slot, self._locate_eye_yolo_once(slot.frame))

    def _publish_result(self, result: ComponentPoseResult, slot: FrameSlot | None = None) -> None:
        self._state.set(result, slot)
        self._publish(component_pose_message(result))

    def _run(self) -> None:
        last_seq = -1
        while not self._stop.is_set():
            slot = self._bus.get_latest(timeout=_FRAME_WAIT_TIMEOUT_S, newer_than=last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            cycle_started = time.monotonic()
            try:
                if self._yolo_only:
                    self._publish_result(self.detect_yolo_frame(slot), slot)
                    if self._stop.wait(self._interval_s):
                        break
                    continue
                observation = self._locate(slot.frame)
                body = body_observation(observation, (slot.frame.shape[1], slot.frame.shape[0]))
                model_confidence = float(observation.confidence) if observation is not None else None
                orientation_rejected = False
                refinement_evidence = None
                reference_evidence = None
                if self._tft_candidate_enabled():
                    observation, refinement_evidence = self._refine_tft_candidate(
                        slot.frame, observation, slot.frame_id, slot.ts_ms)
                    if observation is None:
                        body = None
                elif (
                    observation is not None
                    and self._profile.corner_refinement == "blue_pcb"
                ):
                    refined = refine_component_corners_from_pcb(
                        slot.frame, observation,
                        orientation_keypoint_indices=self._profile.orientation_keypoint_indices,
                    )
                    observation, refinement_evidence = bound_hc_corner_refinement(
                        self._profile, observation, refined,
                        (slot.frame.shape[1], slot.frame.shape[0]),
                    )
                elif (
                    observation is not None
                    and self._profile.corner_refinement == "mounting_holes"
                ):
                    if self._tracker.motion_handoff:
                        from app.vision.tft_ring_geometry import refine_tft_rings
                        refinement_evidence = {}
                        # Four visible rings can improve geometry, but a finger
                        # hiding one ring must not erase a current model pose.
                        # The fallback still passes orientation, image consensus
                        # and visibility gates; it is not a fabricated ring.
                        ring_observation = refine_tft_rings(slot.frame, observation, refinement_evidence)
                        if ring_observation is not None:
                            observation = ring_observation
                        else:
                            observation = (
                                refine_component_corners_from_mounting_holes(slot.frame, observation)
                                or observation
                            )
                            refinement_evidence['fallback'] = 'current_model_pose_requires_consensus'
                    else:
                        observation = (
                            refine_component_corners_from_mounting_holes(slot.frame, observation)
                            or observation
                        )
                if (observation is not None and self._tracker.motion_handoff
                        and self._profile.component_id == 'hc-sr04' and self._reference_recovery is not None):
                    matched = self._reference_recovery.locate(slot.frame, region=observation)
                    reference_evidence = dict(self._reference_recovery.evidence)
                    reference_evidence['frame_id'] = slot.frame_id
                    if matched is not None:
                        observation = replace(matched, source='hc_reference_sift')
                if observation is not None and self._profile.pin_row_orientation:
                    orientation_candidate = observation
                    # Intentionally no `or observation` fallback: unverified
                    # semantic order must not become a trusted pin overlay.
                    observation = orient_component_corners_from_pin_row(
                        slot.frame, observation, self._profile
                    )
                    recovery = getattr(self, '_reference_recovery', None)
                    if observation is None and recovery is not None:
                        # The detector box bounds a search, NOT the pin order.
                        # Distributed PCB features recover the calibrated order
                        # even when leads cover the solder row.
                        observation = recovery.locate(slot.frame, region=orientation_candidate)
                        reference_evidence = dict(recovery.evidence)
                    orientation_rejected = observation is None
                result = self._tracker.update(
                    slot.frame,
                    observation,
                    frame_id=slot.frame_id,
                    ts_ms=slot.ts_ms,
                    reference_evidence=reference_evidence,
                )
                result = replace(result, model_confidence=model_confidence, body=body,
                    reference_evidence=reference_evidence,
                    corner_refinement=refinement_evidence,
                    tracking_reason="pin_orientation_unverified" if orientation_rejected else result.tracking_reason)
                if orientation_rejected:
                    # Candidate found is not the same as a verified pin order.
                    # Never keep the old named pins when current order fails.
                    result = replace(result, tracking='searching', outline_px=None, pins=(),
                                     diagnostic_box_px=orientation_candidate.box_xyxy,
                                     diagnostic_pins=(), diagnostic_reason='pin_orientation_unverified',
                                     motion_outline_px=None,
                                     orientation_input={
                                         'corners': orientation_candidate.corners_px.tolist(),
                                         'box': list(orientation_candidate.box_xyxy),
                                         'confidence': float(orientation_candidate.confidence),
                                         'keypoint_confidences': orientation_candidate.keypoint_confidences.tolist(),
                                     })
                if observation is not None:
                    # Corroborate the same geometry the display tracks. TFT
                    # model landmarks are mounting holes, not outer PCB corners.
                    result = replace(result, motion_outline_px=project_component_outline(
                        self._profile, observation.corners_px,
                    ))
                if result.outline_px is not None:
                    result = replace(
                        result,
                        outline_px=project_component_outline(
                            self._profile, result.outline_px
                        ),
                    )
                self._publish_result(result, slot)
            except Exception:
                log.exception("component pose failed (frame_id=%d)", slot.frame_id)
            last_seq = self._wait_with_reacquisition_frames(last_seq,
                max(0., self._interval_s-(time.monotonic()-cycle_started)))

    def _wait_with_reacquisition_frames(self, last_seq, remaining_s=None):
        # Keep other modules and Eye on their existing cadence. Only the HC
        # reacquisition window consumes intervening images; no extra YOLO calls.
        wait_s = self._interval_s if remaining_s is None else max(0., remaining_s)
        if (self._yolo_only or not self._tracker.motion_handoff
                or self._profile.component_id != 'hc-sr04'):
            self._stop.wait(wait_s)
            return last_seq
        deadline = time.monotonic() + wait_s
        while not self._stop.is_set():
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                break
            slot = self._bus.get_latest(timeout=min(.05, remaining), newer_than=last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            window = self._tracker._pose_window
            if window is not None:
                try:
                    window.advance(slot.frame, slot.frame_id, slot.ts_ms)
                except Exception:
                    window.reset()
                    log.exception('HC intermediate acquisition frame failed')
        return last_seq
