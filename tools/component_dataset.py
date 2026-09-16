"""YOLO component-dataset discovery and quality gates.

This module has no Ultralytics dependency so dataset audits can run quickly in
tests, the training studio, and CI before a GPU process is started.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any

import yaml


IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".webp"})
SPLITS = ("train", "val", "test")


def _class_names(payload: dict[str, Any]) -> list[str]:
    names = payload.get("names")
    if isinstance(names, list):
        return [str(value).strip() for value in names]
    if isinstance(names, dict):
        pairs: list[tuple[int, str]] = []
        for key, value in names.items():
            try:
                class_id = int(key)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"dataset class key is not an integer: {key!r}") from exc
            pairs.append((class_id, str(value).strip()))
        pairs.sort()
        if pairs and [key for key, _ in pairs] != list(range(len(pairs))):
            raise ValueError("dataset class ids must be contiguous and start at 0")
        return [value for _, value in pairs]
    raise ValueError("data.yaml must contain names as a list or integer-keyed mapping")


def load_dataset_yaml(data_yaml: Path | str) -> tuple[Path, dict[str, Any], list[str]]:
    path = Path(data_yaml).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"dataset YAML not found: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("dataset YAML root must be a mapping")
    names = _class_names(payload)
    if not names or any(not name for name in names):
        raise ValueError("dataset must define at least one non-empty class name")
    if len(set(names)) != len(names):
        raise ValueError("dataset class names must be unique")
    return path, payload, names


def _dataset_root(data_yaml: Path, payload: dict[str, Any]) -> Path:
    configured = payload.get("path")
    if not configured:
        return data_yaml.parent.resolve()
    root = Path(str(configured)).expanduser()
    if not root.is_absolute():
        root = data_yaml.parent / root
    return root.resolve()


def _without_parent_prefix(path: Path) -> Path:
    parts = list(path.parts)
    while parts and parts[0] in (".", ".."):
        parts.pop(0)
    return Path(*parts) if parts else Path(".")


def resolve_split_path(
    data_yaml: Path,
    payload: dict[str, Any],
    split: str,
) -> Path | None:
    value = payload.get(split)
    if value is None and split == "val":
        value = payload.get("valid")
    if value is None:
        return None
    if isinstance(value, list):
        if len(value) != 1:
            raise ValueError(f"{split} uses multiple image roots; studio v1 expects one")
        value = value[0]
    raw = Path(str(value)).expanduser()
    if raw.is_absolute():
        return raw.resolve()

    root = _dataset_root(data_yaml, payload)
    candidates = [
        root / raw,
        data_yaml.parent / raw,
        root / _without_parent_prefix(raw),
        data_yaml.parent / _without_parent_prefix(raw),
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return candidates[0].resolve()


def label_root_for(image_root: Path) -> Path:
    parts = list(image_root.parts)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].lower() == "images":
            parts[index] = "labels"
            return Path(*parts)
    return image_root.parent / "labels"


def _images(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _label_for(image: Path, image_root: Path, label_root: Path) -> Path:
    return (label_root / image.relative_to(image_root)).with_suffix(".txt")


def _row_task(tokens: list[str]) -> str | None:
    if len(tokens) == 5:
        return "detect"
    if len(tokens) >= 7 and (len(tokens) - 1) % 2 == 0:
        return "segment"
    return None


def _parse_row(
    tokens: list[str],
    *,
    class_count: int,
) -> tuple[str | None, int | None, str | None]:
    task = _row_task(tokens)
    if task is None:
        return None, None, f"unsupported YOLO row with {len(tokens)} fields"
    try:
        class_id = int(tokens[0])
    except ValueError:
        return task, None, f"class id is not an integer: {tokens[0]!r}"
    if not 0 <= class_id < class_count:
        return task, class_id, f"class id {class_id} is outside 0..{class_count - 1}"
    try:
        coordinates = [float(value) for value in tokens[1:]]
    except ValueError:
        return task, class_id, "coordinates contain a non-number"
    if any(not isfinite(value) or value < 0.0 or value > 1.0 for value in coordinates):
        return task, class_id, "coordinates must be finite and normalized to 0..1"
    if task == "detect" and (coordinates[2] <= 0.0 or coordinates[3] <= 0.0):
        return task, class_id, "detection width and height must be positive"
    if task == "segment" and len(coordinates) < 6:
        return task, class_id, "segmentation polygon needs at least three points"
    return task, class_id, None


def _file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit_component_dataset(
    data_yaml: Path | str,
    *,
    minimum_train: int = 20,
    minimum_val: int = 5,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    yaml_path, payload, names = load_dataset_yaml(data_yaml)
    errors: list[str] = []
    warnings: list[str] = []
    task_counts: Counter[str] = Counter()
    digest_splits: defaultdict[str, set[str]] = defaultdict(set)
    splits: dict[str, Any] = {}
    dataset_fingerprint = sha256(yaml_path.read_bytes())

    for split in SPLITS:
        image_root = resolve_split_path(yaml_path, payload, split)
        if image_root is None:
            splits[split] = {
                "image_root": None,
                "label_root": None,
                "images": 0,
                "label_files": 0,
                "background_images": 0,
                "instances": 0,
                "class_instances": {name: 0 for name in names},
                "invalid_rows": 0,
            }
            continue
        label_root = label_root_for(image_root)
        images = _images(image_root)
        class_instances: Counter[int] = Counter()
        label_file_count = 0
        background_images = 0
        invalid_rows = 0
        instances = 0
        referenced_labels: set[Path] = set()

        if not image_root.is_dir():
            errors.append(f"{split} image directory does not exist: {image_root}")
        for image in images:
            label = _label_for(image, image_root, label_root)
            referenced_labels.add(label.resolve())
            if check_duplicates:
                try:
                    digest_splits[_file_digest(image)].add(split)
                except OSError as exc:
                    errors.append(f"cannot hash image {image}: {exc}")
            if not label.is_file():
                background_images += 1
                continue
            label_file_count += 1
            text = label.read_text(encoding="utf-8-sig").strip()
            dataset_fingerprint.update(label.relative_to(label_root).as_posix().encode())
            dataset_fingerprint.update(text.encode())
            if not text:
                background_images += 1
                continue
            for line_number, line in enumerate(text.splitlines(), 1):
                tokens = line.split()
                task, class_id, issue = _parse_row(tokens, class_count=len(names))
                if task is not None:
                    task_counts[task] += 1
                if issue is not None:
                    invalid_rows += 1
                    if len(errors) < 100:
                        errors.append(f"{label}:{line_number}: {issue}")
                    continue
                assert class_id is not None
                class_instances[class_id] += 1
                instances += 1

        orphan_labels = 0
        if label_root.is_dir():
            orphan_labels = sum(
                1 for path in label_root.rglob("*.txt")
                if path.resolve() not in referenced_labels
            )
        if orphan_labels:
            warnings.append(f"{split} has {orphan_labels} label files without matching images")
        if background_images:
            warnings.append(
                f"{split} has {background_images} background/unlabeled images; "
                "keep them only when they are intentional negatives"
            )
        splits[split] = {
            "image_root": str(image_root),
            "label_root": str(label_root),
            "images": len(images),
            "label_files": label_file_count,
            "background_images": background_images,
            "orphan_labels": orphan_labels,
            "instances": instances,
            "class_instances": {
                names[index]: int(class_instances[index]) for index in range(len(names))
            },
            "invalid_rows": invalid_rows,
        }

    if splits["train"]["images"] < minimum_train:
        errors.append(
            f"train has {splits['train']['images']} images; need at least {minimum_train}"
        )
    if splits["val"]["images"] < minimum_val:
        errors.append(f"val has {splits['val']['images']} images; need at least {minimum_val}")
    if splits["test"]["images"] == 0:
        warnings.append("test split is empty; final generalization cannot be measured independently")
    if not task_counts:
        errors.append("no valid component annotations were found")
        task = "unknown"
    elif len(task_counts) > 1:
        errors.append(f"mixed detection and segmentation rows: {dict(task_counts)}")
        task = "mixed"
    else:
        task = next(iter(task_counts))

    for name in names:
        if splits["train"]["class_instances"][name] == 0:
            errors.append(f"class {name!r} has no training instances")
        if splits["val"]["class_instances"][name] == 0:
            warnings.append(f"class {name!r} has no validation instances")
    maximum_train_instances = max(splits["train"]["class_instances"].values(), default=0)
    if maximum_train_instances >= 20:
        for name, count in splits["train"]["class_instances"].items():
            if 0 < count < maximum_train_instances * 0.50:
                warnings.append(
                    f"class {name!r} has {count} train instances, below 50% of the "
                    f"largest class ({maximum_train_instances}); add more varied samples"
                )

    duplicate_groups = [
        {"sha256": digest, "splits": sorted(found_splits)}
        for digest, found_splits in digest_splits.items()
        if len(found_splits) > 1
    ]
    if duplicate_groups:
        warnings.append(
            f"{len(duplicate_groups)} exact images appear in more than one split (data leakage)"
        )

    total_images = sum(int(splits[split]["images"]) for split in SPLITS)
    status = "fail" if errors else "warning" if warnings else "ok"
    return {
        "status": status,
        "ready_to_train": not errors,
        "data_yaml": str(yaml_path),
        "dataset_root": str(_dataset_root(yaml_path, payload)),
        "task": task,
        "class_names": names,
        "class_count": len(names),
        "total_images": total_images,
        "splits": splits,
        "annotation_rows": dict(task_counts),
        "cross_split_duplicate_groups": duplicate_groups,
        "fingerprint": dataset_fingerprint.hexdigest(),
        "errors": errors,
        "warnings": warnings,
    }


def normalized_training_yaml(report: dict[str, Any], destination: Path) -> Path:
    payload: dict[str, Any] = {
        "path": ".",
        "train": report["splits"]["train"]["image_root"],
        "val": report["splits"]["val"]["image_root"],
        "names": {index: name for index, name in enumerate(report["class_names"])},
        "nc": len(report["class_names"]),
    }
    if report["splits"]["test"]["image_root"]:
        payload["test"] = report["splits"]["test"]["image_root"]
    destination.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return destination


def format_audit_report(report: dict[str, Any]) -> str:
    lines = [
        f"status={report['status']} task={report['task']} classes={report['class_count']} "
        f"images={report['total_images']}",
        "classes: " + ", ".join(report["class_names"]),
    ]
    for split in SPLITS:
        item = report["splits"][split]
        lines.append(
            f"{split}: images={item['images']} labels={item['label_files']} "
            f"instances={item['instances']} background={item['background_images']}"
        )
    if report["errors"]:
        lines.append("errors:")
        lines.extend(f"  - {value}" for value in report["errors"])
    if report["warnings"]:
        lines.append("warnings:")
        lines.extend(f"  - {value}" for value in report["warnings"])
    return "\n".join(lines)


def write_audit_report(report: dict[str, Any], output: Path | str) -> Path:
    path = Path(output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
