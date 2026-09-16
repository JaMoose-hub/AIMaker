"""YOLO Pose label I/O and review-safe dataset helpers for Board Vision."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
from typing import Any, Iterable

import cv2
import numpy as np

from component_dataset import (
    IMAGE_SUFFIXES,
    label_root_for,
    load_dataset_yaml,
    resolve_split_path,
)


@dataclass
class PoseKeypoint:
    x: float
    y: float
    visibility: int = 2
    confidence: float | None = None

    def clone(self) -> "PoseKeypoint":
        return PoseKeypoint(self.x, self.y, self.visibility, self.confidence)


@dataclass
class PoseAnnotation:
    class_id: int
    box_xywh: tuple[float, float, float, float]
    keypoints: list[PoseKeypoint]
    confidence: float | None = None
    source: str = "manual"

    def clone(self) -> "PoseAnnotation":
        return PoseAnnotation(
            self.class_id,
            tuple(self.box_xywh),
            [point.clone() for point in self.keypoints],
            self.confidence,
            self.source,
        )


def clone_pose_annotations(values: Iterable[PoseAnnotation]) -> list[PoseAnnotation]:
    return [value.clone() for value in values]


def _normalized(value: float, *, name: str) -> float:
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be normalized to 0..1")
    return number


def _tensor_values(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value


def box_from_keypoints(
    keypoints: Iterable[PoseKeypoint],
    *,
    fallback: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    visible = [(point.x, point.y) for point in keypoints if point.visibility > 0]
    if len(visible) >= 2:
        xs = [point[0] for point in visible]
        ys = [point[1] for point in visible]
        x1, x2 = min(xs), max(xs)
        y1, y2 = min(ys), max(ys)
        if x2 - x1 > 1e-6 and y2 - y1 > 1e-6:
            return ((x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1)
    if fallback is not None:
        return tuple(float(value) for value in fallback)
    return 0.5, 0.5, 1e-6, 1e-6


def load_pose_annotations(
    label_path: Path | str,
    *,
    class_count: int,
    keypoint_count: int,
) -> list[PoseAnnotation]:
    path = Path(label_path)
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    expected = 5 + keypoint_count * 3
    annotations: list[PoseAnnotation] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        fields = line.split()
        if len(fields) != expected:
            raise ValueError(
                f"{path}:{line_number}: expected {expected} values for "
                f"{keypoint_count} keypoints, got {len(fields)}"
            )
        try:
            class_id = int(fields[0])
            values = [float(value) for value in fields[1:]]
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid pose value") from exc
        if not 0 <= class_id < class_count:
            raise ValueError(f"{path}:{line_number}: class id {class_id} is out of range")
        box = tuple(
            _normalized(value, name=f"box[{index}]")
            for index, value in enumerate(values[:4])
        )
        if box[2] <= 0.0 or box[3] <= 0.0:
            raise ValueError(f"{path}:{line_number}: pose box width/height must be positive")
        keypoints: list[PoseKeypoint] = []
        raw_points = np.asarray(values[4:], dtype=np.float64).reshape(keypoint_count, 3)
        for index, (x, y, raw_visibility) in enumerate(raw_points):
            if not math.isfinite(raw_visibility) or raw_visibility not in (0.0, 1.0, 2.0):
                raise ValueError(
                    f"{path}:{line_number}: keypoint {index + 1} visibility must be 0, 1 or 2"
                )
            visibility = int(raw_visibility)
            if visibility <= 0:
                x_value = y_value = 0.0
            else:
                x_value = _normalized(x, name=f"keypoint[{index}].x")
                y_value = _normalized(y, name=f"keypoint[{index}].y")
            keypoints.append(PoseKeypoint(x_value, y_value, visibility))
        annotations.append(PoseAnnotation(class_id, box, keypoints, source="existing"))
    return annotations


def pose_annotation_to_yolo(annotation: PoseAnnotation, *, keypoint_count: int) -> str:
    if not 0 <= annotation.class_id:
        raise ValueError("class id must be non-negative")
    if len(annotation.keypoints) != keypoint_count:
        raise ValueError(
            f"annotation has {len(annotation.keypoints)} keypoints; expected {keypoint_count}"
        )
    box = box_from_keypoints(annotation.keypoints, fallback=annotation.box_xywh)
    if box[2] <= 0.0 or box[3] <= 0.0:
        raise ValueError("pose box width/height must be positive")
    values: list[float] = [float(value) for value in box]
    for index, point in enumerate(annotation.keypoints):
        visibility = int(point.visibility)
        if visibility not in (0, 1, 2):
            raise ValueError(f"keypoint {index + 1} visibility must be 0, 1 or 2")
        if visibility <= 0:
            values.extend((0.0, 0.0, 0.0))
        else:
            values.extend(
                (
                    _normalized(point.x, name=f"keypoint[{index}].x"),
                    _normalized(point.y, name=f"keypoint[{index}].y"),
                    float(visibility),
                )
            )
    return " ".join([str(annotation.class_id), *(f"{value:.8f}" for value in values)])


def save_pose_annotations(
    label_path: Path | str,
    annotations: Iterable[PoseAnnotation],
    *,
    keypoint_count: int,
    backup_path: Path | None = None,
) -> Path:
    target = Path(label_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and backup_path is not None and not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
    rows = [
        pose_annotation_to_yolo(annotation, keypoint_count=keypoint_count)
        for annotation in annotations
    ]
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    temporary.replace(target)
    return target


def pose_geometry_issues(annotation: PoseAnnotation | None) -> list[str]:
    if annotation is None:
        return ["no board annotation"]
    missing = [index for index, point in enumerate(annotation.keypoints) if point.visibility <= 0]
    issues: list[str] = []
    if missing:
        issues.append("missing keypoints: " + ", ".join(str(index + 1) for index in missing))
    if len(annotation.keypoints) >= 4 and not any(index < 4 for index in missing):
        corners = np.asarray(
            [(point.x, point.y) for point in annotation.keypoints[:4]], dtype=np.float32
        )
        edges = np.roll(corners, -1, axis=0) - corners
        cross = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] \
            - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
        if not (np.all(cross > 0.0) or np.all(cross < 0.0)):
            issues.append("first four points are crossed or non-convex")
        if abs(float(cv2.contourArea(corners))) < 0.001:
            issues.append("board quadrilateral is too small")
    return issues


class _ReviewStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[str, dict[str, Any]] = {}
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    self.records = {
                        str(key): value for key, value in payload.items() if isinstance(value, dict)
                    }
            except (OSError, json.JSONDecodeError):
                self.records = {}

    def status(self, key: str) -> str:
        return str(self.records.get(key, {}).get("status", "existing"))

    def set(self, key: str, status: str, **details: Any) -> None:
        self.records[key] = {
            "status": status,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            **details,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


def _keypoint_names(payload: dict[str, Any], count: int) -> list[str]:
    raw = payload.get("kpt_names")
    if isinstance(raw, dict):
        raw = raw.get(0, raw.get("0"))
    if isinstance(raw, list) and len(raw) == count:
        names = [str(value).strip() for value in raw]
        if all(names):
            return names
    if count == 4:
        return ["profile_TL", "profile_TR", "profile_BR", "profile_BL"]
    return [f"keypoint_{index + 1}" for index in range(count)]


def _dataset_root(data_yaml: Path, image_roots: dict[str, Path | None]) -> Path:
    existing = [str(path) for path in image_roots.values() if path is not None]
    if not existing:
        return data_yaml.parent
    common = Path(os.path.commonpath(existing))
    if common.name.lower() in {"train", "val", "valid", "test"} and common.parent.name.lower() == "images":
        return common.parent.parent
    if common.name.lower() == "images":
        return common.parent
    return data_yaml.parent


class PoseLabelDataset:
    def __init__(self, data_yaml: Path | str) -> None:
        self.data_yaml, self.payload, self.class_names = load_dataset_yaml(data_yaml)
        shape = self.payload.get("kpt_shape")
        if not (
            isinstance(shape, (list, tuple))
            and len(shape) == 2
            and int(shape[0]) > 0
            and int(shape[1]) == 3
        ):
            raise ValueError("pose data.yaml must define kpt_shape: [count, 3]")
        self.keypoint_count = int(shape[0])
        self.keypoint_names = _keypoint_names(self.payload, self.keypoint_count)
        self.image_roots: dict[str, Path | None] = {
            split: resolve_split_path(self.data_yaml, self.payload, split)
            for split in ("train", "val", "test")
        }
        self.dataset_root = _dataset_root(self.data_yaml, self.image_roots)
        self.state_root = self.dataset_root / ".pose-label-studio"
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.backup_root = self.state_root / "backups" / self.session_id
        self.review = _ReviewStore(self.state_root / "review.json")

    def images(self, split: str) -> list[Path]:
        root = self.image_roots.get(split)
        if root is None or not root.is_dir():
            return []
        return sorted(
            path for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )

    def label_path(self, image: Path, split: str) -> Path:
        image_root = self.image_roots.get(split)
        if image_root is None:
            raise ValueError(f"split has no image root: {split}")
        return (label_root_for(image_root) / image.relative_to(image_root)).with_suffix(".txt")

    def key(self, image: Path, split: str) -> str:
        root = self.image_roots.get(split)
        return (
            f"{split}/{image.relative_to(root).as_posix()}"
            if root is not None else f"{split}/{image.name}"
        )

    def backup_path(self, image: Path, split: str) -> Path:
        root = self.image_roots.get(split)
        if root is None:
            raise ValueError(f"split has no image root: {split}")
        label = self.label_path(image, split)
        return self.backup_root / split / label.relative_to(label_root_for(root))

    def load(self, image: Path, split: str) -> list[PoseAnnotation]:
        return load_pose_annotations(
            self.label_path(image, split),
            class_count=len(self.class_names),
            keypoint_count=self.keypoint_count,
        )

    def save(
        self,
        image: Path,
        split: str,
        annotations: Iterable[PoseAnnotation],
        *,
        status: str,
        **details: Any,
    ) -> Path:
        values = list(annotations)
        target = save_pose_annotations(
            self.label_path(image, split),
            values,
            keypoint_count=self.keypoint_count,
            backup_path=self.backup_path(image, split),
        )
        self.review.set(
            self.key(image, split), status, annotation_count=len(values), **details
        )
        return target

    def progress(self, split: str) -> dict[str, int]:
        result = {
            "total": 0,
            "labeled": 0,
            "reviewed": 0,
            "auto_pending": 0,
            "unlabeled": 0,
        }
        for image in self.images(split):
            result["total"] += 1
            label_exists = self.label_path(image, split).is_file()
            result["labeled" if label_exists else "unlabeled"] += 1
            status = self.review.status(self.key(image, split))
            if status in ("reviewed", "negative"):
                result["reviewed"] += 1
            elif status == "auto_pending":
                result["auto_pending"] += 1
        return result


def annotations_from_ultralytics_pose_result(
    result: Any,
    dataset_class_names: list[str],
    *,
    keypoint_count: int,
    keypoint_threshold: float = 0.25,
) -> tuple[list[PoseAnnotation], list[str]]:
    boxes = getattr(result, "boxes", None)
    keypoints = getattr(result, "keypoints", None)
    if boxes is None or keypoints is None:
        return [], []
    classes = _tensor_values(getattr(boxes, "cls", None)) or []
    confidences = _tensor_values(getattr(boxes, "conf", None)) or []
    boxes_xywhn = _tensor_values(getattr(boxes, "xywhn", None)) or []
    points_xyn = _tensor_values(getattr(keypoints, "xyn", None)) or []
    point_confidences = _tensor_values(getattr(keypoints, "conf", None))
    result_names = getattr(result, "names", {}) or {}
    target_ids = {name.casefold(): index for index, name in enumerate(dataset_class_names)}
    annotations: list[PoseAnnotation] = []
    skipped: list[str] = []
    for index, raw_class in enumerate(classes):
        model_class_id = int(raw_class)
        model_name = str(
            result_names.get(model_class_id, model_class_id)
            if isinstance(result_names, dict) else result_names[model_class_id]
        )
        target_class_id = target_ids.get(model_name.casefold())
        if target_class_id is None:
            skipped.append(model_name)
            continue
        if index >= len(points_xyn) or len(points_xyn[index]) != keypoint_count:
            skipped.append(f"{model_name}:keypoint-count")
            continue
        pose_points: list[PoseKeypoint] = []
        for point_index, raw_point in enumerate(points_xyn[index]):
            x, y = float(raw_point[0]), float(raw_point[1])
            confidence = None
            if point_confidences is not None and index < len(point_confidences):
                confidence = float(point_confidences[index][point_index])
            valid = math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            if not valid:
                pose_points.append(PoseKeypoint(0.0, 0.0, 0, confidence))
            else:
                visibility = 2 if confidence is None or confidence >= keypoint_threshold else 1
                pose_points.append(PoseKeypoint(x, y, visibility, confidence))
        box_values = tuple(float(value) for value in boxes_xywhn[index])
        annotations.append(
            PoseAnnotation(
                target_class_id,
                box_values,
                pose_points,
                float(confidences[index]),
                "auto",
            )
        )
    annotations.sort(key=lambda item: item.confidence or 0.0, reverse=True)
    return annotations, sorted(set(skipped))
