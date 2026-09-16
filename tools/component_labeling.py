"""Core data model for the Board Vision component-labeling application."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable

import cv2
import numpy as np
import yaml

from component_dataset import (
    IMAGE_SUFFIXES,
    load_dataset_yaml,
    resolve_split_path,
    label_root_for,
)


@dataclass
class Annotation:
    class_id: int
    points: list[tuple[float, float]]
    confidence: float | None = None
    source: str = "manual"

    def clone(self) -> "Annotation":
        return Annotation(self.class_id, list(self.points), self.confidence, self.source)


def clone_annotations(values: Iterable[Annotation]) -> list[Annotation]:
    return [value.clone() for value in values]


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _rectangle_points(cx: float, cy: float, width: float, height: float) -> list[tuple[float, float]]:
    x1, x2 = _clamp(cx - width / 2.0), _clamp(cx + width / 2.0)
    y1, y2 = _clamp(cy - height / 2.0), _clamp(cy + height / 2.0)
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def load_yolo_annotations(
    label_path: Path | str,
    *,
    task: str,
    class_count: int,
) -> list[Annotation]:
    path = Path(label_path)
    if not path.is_file():
        return []
    annotations: list[Annotation] = []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return annotations
    for line_number, line in enumerate(text.splitlines(), 1):
        tokens = line.split()
        try:
            class_id = int(tokens[0])
        except (IndexError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: invalid class id") from exc
        if not 0 <= class_id < class_count:
            raise ValueError(f"{path}:{line_number}: class id {class_id} is out of range")
        try:
            coordinates = [_clamp(float(value)) for value in tokens[1:]]
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: invalid coordinate") from exc
        if task == "detect":
            if len(coordinates) != 4:
                raise ValueError(f"{path}:{line_number}: detection row needs 4 coordinates")
            points = _rectangle_points(*coordinates)
        elif task == "segment":
            if len(coordinates) < 6 or len(coordinates) % 2:
                raise ValueError(f"{path}:{line_number}: polygon needs at least 3 x/y points")
            points = list(zip(coordinates[0::2], coordinates[1::2]))
        else:
            raise ValueError(f"unsupported annotation task: {task}")
        annotations.append(Annotation(class_id, points, source="existing"))
    return annotations


def annotation_to_yolo(annotation: Annotation, task: str) -> str:
    if annotation.class_id < 0 or len(annotation.points) < 3:
        raise ValueError("annotation needs a valid class and at least three points")
    points = [(_clamp(x), _clamp(y)) for x, y in annotation.points]
    if task == "detect":
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        values = ((x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1)
    elif task == "segment":
        values = tuple(value for point in points for value in point)
    else:
        raise ValueError(f"unsupported annotation task: {task}")
    if task == "detect" and (values[2] <= 0.0 or values[3] <= 0.0):
        raise ValueError("annotation box has zero area")
    return " ".join([str(annotation.class_id), *(f"{value:.8f}" for value in values)])


def save_yolo_annotations(
    label_path: Path | str,
    annotations: Iterable[Annotation],
    *,
    task: str,
    backup_path: Path | None = None,
) -> Path:
    target = Path(label_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and backup_path is not None and not backup_path.exists():
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backup_path)
    lines = [annotation_to_yolo(annotation, task) for annotation in annotations]
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    temporary.replace(target)
    return target


def _infer_task(payload: dict[str, Any], image_roots: dict[str, Path | None]) -> str:
    studio = payload.get("component_label_studio")
    if isinstance(studio, dict) and studio.get("task") in ("segment", "detect"):
        return str(studio["task"])
    for split in ("train", "val", "test"):
        image_root = image_roots.get(split)
        if image_root is None:
            continue
        label_root = label_root_for(image_root)
        if not label_root.is_dir():
            continue
        for label in sorted(label_root.rglob("*.txt")):
            for line in label.read_text(encoding="utf-8-sig").splitlines():
                fields = line.split()
                if len(fields) == 5:
                    return "detect"
                if len(fields) >= 7 and (len(fields) - 1) % 2 == 0:
                    return "segment"
    return "segment"


class ReviewStore:
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
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


class ComponentLabelDataset:
    def __init__(self, data_yaml: Path | str) -> None:
        self.data_yaml, self.payload, self.class_names = load_dataset_yaml(data_yaml)
        self.image_roots: dict[str, Path | None] = {
            split: resolve_split_path(self.data_yaml, self.payload, split)
            for split in ("train", "val", "test")
        }
        self.task = _infer_task(self.payload, self.image_roots)
        self.state_root = self.data_yaml.parent / ".component-label-studio"
        self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.backup_root = self.state_root / "backups" / self.session_id
        self.review = ReviewStore(self.state_root / "review.json")

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
        image_root = self.image_roots.get(split)
        if image_root is None:
            return f"{split}/{image.name}"
        return f"{split}/{image.relative_to(image_root).as_posix()}"

    def backup_path(self, image: Path, split: str) -> Path:
        label = self.label_path(image, split)
        image_root = self.image_roots[split]
        assert image_root is not None
        return (self.backup_root / split / label.relative_to(label_root_for(image_root)))

    def load(self, image: Path, split: str) -> list[Annotation]:
        return load_yolo_annotations(
            self.label_path(image, split), task=self.task, class_count=len(self.class_names)
        )

    def save(
        self,
        image: Path,
        split: str,
        annotations: Iterable[Annotation],
        *,
        status: str,
        **review_details: Any,
    ) -> Path:
        target = save_yolo_annotations(
            self.label_path(image, split),
            annotations,
            task=self.task,
            backup_path=self.backup_path(image, split),
        )
        self.review.set(self.key(image, split), status, **review_details)
        return target

    def progress(self, split: str) -> dict[str, int]:
        values = self.images(split)
        statuses: dict[str, int] = {
            "total": len(values),
            "labeled": 0,
            "reviewed": 0,
            "auto_pending": 0,
            "unlabeled": 0,
        }
        for image in values:
            label_exists = self.label_path(image, split).is_file()
            status = self.review.status(self.key(image, split))
            if label_exists:
                statuses["labeled"] += 1
            else:
                statuses["unlabeled"] += 1
            if status in ("reviewed", "negative"):
                statuses["reviewed"] += 1
            elif status == "auto_pending":
                statuses["auto_pending"] += 1
        return statuses


def create_component_dataset(
    root: Path | str,
    class_names: list[str],
    *,
    task: str = "segment",
) -> Path:
    destination = Path(root).expanduser().resolve()
    if task not in ("segment", "detect"):
        raise ValueError("task must be segment or detect")
    clean_names = [name.strip() for name in class_names if name.strip()]
    if not clean_names or len(set(clean_names)) != len(clean_names):
        raise ValueError("class names must be non-empty and unique")
    destination.mkdir(parents=True, exist_ok=True)
    for split in ("train", "val", "test"):
        (destination / "images" / split).mkdir(parents=True, exist_ok=True)
        (destination / "labels" / split).mkdir(parents=True, exist_ok=True)
    data_yaml = destination / "data.yaml"
    if data_yaml.exists():
        raise FileExistsError(f"data.yaml already exists: {data_yaml}")
    payload = {
        "path": ".",
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {index: name for index, name in enumerate(clean_names)},
        "nc": len(clean_names),
        "component_label_studio": {"task": task},
    }
    data_yaml.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return data_yaml


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-._")
    return stem or "image"


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    for index in range(1, 100000):
        candidate = directory / f"{stem}-{index:04d}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot create a unique filename for {filename}")


def import_images(paths: Iterable[Path | str], destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for raw in paths:
        source = Path(raw).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        target = _unique_destination(destination, source.name)
        shutil.copy2(source, target)
        copied.append(target)
    return copied


def extract_video_frames(
    video_path: Path | str,
    destination: Path,
    *,
    interval_s: float = 0.5,
    max_frames: int = 300,
    min_mean_diff: float = 1.5,
) -> list[Path]:
    source = Path(video_path).expanduser().resolve()
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    step = max(1, int(round(max(0.01, interval_s) * max(fps, 1.0))))
    saved: list[Path] = []
    index = 0
    last_signature: np.ndarray | None = None
    stem = _safe_stem(source.stem)
    try:
        while len(saved) < max(1, max_frames):
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            if index % step:
                index += 1
                continue
            gray = cv2.cvtColor(
                cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA),
                cv2.COLOR_BGR2GRAY,
            )
            difference = (
                None if last_signature is None
                else float(np.mean(cv2.absdiff(last_signature, gray)))
            )
            if difference is None or difference >= max(0.0, min_mean_diff):
                filename = f"{stem}_frame_{index:07d}.jpg"
                target = _unique_destination(destination, filename)
                if not cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
                    raise IOError(f"failed to write extracted frame: {target}")
                saved.append(target)
                last_signature = gray
            index += 1
    finally:
        capture.release()
    return saved


def annotations_from_ultralytics_result(
    result: Any,
    dataset_class_names: list[str],
    *,
    task: str,
) -> tuple[list[Annotation], list[str]]:
    target_ids = {name.casefold(): index for index, name in enumerate(dataset_class_names)}
    result_names = getattr(result, "names", {}) or {}
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return [], []
    classes = boxes.cls.detach().cpu().tolist()
    confidences = boxes.conf.detach().cpu().tolist()
    xywhn = boxes.xywhn.detach().cpu().tolist()
    polygons = None
    masks = getattr(result, "masks", None)
    if masks is not None and getattr(masks, "xyn", None) is not None:
        polygons = list(masks.xyn)
    annotations: list[Annotation] = []
    skipped: list[str] = []
    for index, raw_class in enumerate(classes):
        model_class_id = int(raw_class)
        model_name = str(
            result_names.get(model_class_id, model_class_id)
            if isinstance(result_names, dict)
            else result_names[model_class_id]
        )
        target_class_id = target_ids.get(model_name.casefold())
        if target_class_id is None:
            skipped.append(model_name)
            continue
        polygon = polygons[index] if polygons is not None and index < len(polygons) else None
        if task == "segment" and polygon is not None and len(polygon) >= 3:
            points = [(_clamp(float(point[0])), _clamp(float(point[1]))) for point in polygon]
        else:
            points = _rectangle_points(*[float(value) for value in xywhn[index]])
        annotations.append(
            Annotation(
                target_class_id,
                points,
                confidence=float(confidences[index]),
                source="auto",
            )
        )
    return annotations, sorted(set(skipped))

