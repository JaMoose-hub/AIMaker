# -*- coding: utf-8 -*-
"""Add reviewed, train-only hard negatives to a Pi 5 Pose dataset.

The output is a separate copy of the input dataset. Negative images are chosen
deterministically with farthest-point sampling over low-resolution appearance
features, copied into the train split, and paired with empty YOLO label files.
Validation and test files remain byte-for-byte identical to the source.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class Candidate:
    category: str
    source: Path
    sha256: str
    feature: np.ndarray


def _images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _feature(image: np.ndarray) -> np.ndarray:
    """Return a compact feature that responds to layout, color, hands, and wires."""
    thumbnail = cv2.resize(image, (24, 14), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(thumbnail, cv2.COLOR_BGR2LAB).astype(np.float32) / 255.0
    gray = cv2.cvtColor(thumbnail, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 45, 130).astype(np.float32) / 255.0

    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    histogram = cv2.calcHist(
        [hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]
    ).astype(np.float32).reshape(-1)
    histogram /= max(float(histogram.sum()), 1.0)
    return np.concatenate(
        [lab.reshape(-1), edges.reshape(-1), histogram], dtype=np.float32
    )


def _load_candidates(
    category: str,
    directory: Path,
    *,
    excluded_hashes: set[str],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen_hashes = set(excluded_hashes)
    for path in _images(directory):
        digest = _sha256(path)
        if digest in seen_hashes:
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        candidates.append(
            Candidate(
                category=category,
                source=path.resolve(),
                sha256=digest,
                feature=_feature(image),
            )
        )
        seen_hashes.add(digest)
    return candidates


def _select_diverse(candidates: list[Candidate], count: int) -> list[Candidate]:
    if count < 0:
        raise ValueError("negative sample count must be non-negative")
    if len(candidates) < count:
        raise ValueError(
            f"requested {count} negatives but only {len(candidates)} unique images exist"
        )
    if count == 0:
        return []

    matrix = np.stack([candidate.feature for candidate in candidates]).astype(np.float64)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale[scale < 1e-6] = 1.0
    normalized = (matrix - mean) / scale

    first = int(np.argmax(np.linalg.norm(normalized, axis=1)))
    selected_indices = [first]
    min_distances = np.linalg.norm(normalized - normalized[first], axis=1)
    min_distances[first] = -1.0
    while len(selected_indices) < count:
        index = int(np.argmax(min_distances))
        selected_indices.append(index)
        distances = np.linalg.norm(normalized - normalized[index], axis=1)
        min_distances = np.minimum(min_distances, distances)
        min_distances[selected_indices] = -1.0
    return [candidates[index] for index in selected_indices]


def _copy_dataset(source: Path, output: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"source dataset does not exist: {source}")
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"output path is not a directory: {output}")
        if any(output.iterdir()):
            raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        destination = output / item.name
        if item.is_dir():
            shutil.copytree(item, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(item, destination)


def _tree_hashes(root: Path, split: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for kind in ("images", "labels"):
        directory = root / kind / split
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file():
                key = f"{kind}/{split}/{path.name}"
                result[key] = _sha256(path)
    return result


def _fit_panel(image: np.ndarray, width: int = 320, height: int = 180) -> np.ndarray:
    source_h, source_w = image.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized = cv2.resize(
        image,
        (max(1, int(round(source_w * scale))), max(1, int(round(source_h * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
    )
    panel = np.full((height, width, 3), 24, dtype=np.uint8)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    panel[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return panel


def _write_review_pages(
    manifest: list[dict[str, object]], review_dir: Path
) -> list[str]:
    panels: list[np.ndarray] = []
    for index, item in enumerate(manifest, start=1):
        image = cv2.imread(str(item["destination_image"]), cv2.IMREAD_COLOR)
        if image is None:
            continue
        panel = _fit_panel(image)
        cv2.rectangle(panel, (0, 0), (panel.shape[1], 28), (8, 8, 8), -1)
        caption = f"{index:02d} {item['category']} / EMPTY LABEL"
        cv2.putText(
            panel,
            caption,
            (7, 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (90, 230, 255),
            1,
            cv2.LINE_AA,
        )
        panels.append(panel)

    review_dir.mkdir(parents=True, exist_ok=True)
    pages: list[str] = []
    page_size = 25
    columns = 5
    for offset in range(0, len(panels), page_size):
        page_panels = panels[offset : offset + page_size]
        while len(page_panels) < page_size:
            page_panels.append(np.full_like(panels[0], 24))
        rows = [
            np.hstack(page_panels[row : row + columns])
            for row in range(0, page_size, columns)
        ]
        page = np.vstack(rows)
        page_path = review_dir / f"review-{offset // page_size + 1:02d}.jpg"
        if not cv2.imwrite(str(page_path), page, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise RuntimeError(f"cannot write review page: {page_path}")
        pages.append(str(page_path.resolve()))
    return pages


def _split_image_count(root: Path, split: str) -> int:
    return len(_images(root / "images" / split))


def add_negative_samples(
    *,
    source: Path,
    output: Path,
    uno_source: Path,
    sensor_source: Path,
    wiring_source: Path,
    uno_count: int = 20,
    sensor_count: int = 15,
    wiring_count: int = 15,
) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    sources = {
        "uno_q": uno_source.resolve(),
        "photoresistor": sensor_source.resolve(),
        "wiring_hand": wiring_source.resolve(),
    }
    requested = {
        "uno_q": uno_count,
        "photoresistor": sensor_count,
        "wiring_hand": wiring_count,
    }
    if sum(requested.values()) <= 0:
        raise ValueError("at least one negative sample is required")

    source_val_hashes = _tree_hashes(source, "val")
    source_test_hashes = _tree_hashes(source, "test")
    base_train_images = _images(source / "images" / "train")
    base_hashes = {_sha256(path) for path in base_train_images}
    _copy_dataset(source, output)

    selected: list[Candidate] = []
    candidate_counts: dict[str, int] = {}
    excluded_hashes = set(base_hashes)
    for category, directory in sources.items():
        candidates = _load_candidates(
            category, directory, excluded_hashes=excluded_hashes
        )
        candidate_counts[category] = len(candidates)
        chosen = _select_diverse(candidates, requested[category])
        selected.extend(chosen)
        excluded_hashes.update(candidate.sha256 for candidate in chosen)

    image_output = output / "images" / "train"
    label_output = output / "labels" / "train"
    image_output.mkdir(parents=True, exist_ok=True)
    label_output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for index, candidate in enumerate(selected, start=1):
        suffix = candidate.source.suffix.lower()
        filename = (
            f"negative__{candidate.category}__{index:03d}__"
            f"{candidate.sha256[:10]}{suffix}"
        )
        destination_image = image_output / filename
        destination_label = label_output / f"{destination_image.stem}.txt"
        shutil.copy2(candidate.source, destination_image)
        destination_label.write_bytes(b"")
        manifest.append(
            {
                "category": candidate.category,
                "source_image": str(candidate.source),
                "destination_image": str(destination_image.resolve()),
                "destination_label": str(destination_label.resolve()),
                "sha256": candidate.sha256,
                "label_policy": "empty_yolo_label_no_raspberry_pi_5",
            }
        )

    review_root = output / ".negative-review"
    review_root.mkdir(parents=True, exist_ok=True)
    (review_root / "manifest.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in manifest),
        encoding="utf-8",
    )
    review_pages = _write_review_pages(manifest, review_root)

    final_images = _images(output / "images" / "train")
    final_labels = list((output / "labels" / "train").glob("*.txt"))
    empty_labels = [path for path in final_labels if path.stat().st_size == 0]
    selected_hashes = [item["sha256"] for item in manifest]
    output_val_hashes = _tree_hashes(output, "val")
    output_test_hashes = _tree_hashes(output, "test")
    summary: dict[str, object] = {
        "scope": "train_only_reviewed_hard_negatives",
        "source_dataset": str(source),
        "output_dataset": str(output),
        "source_train_images": len(base_train_images),
        "requested": requested,
        "candidate_counts": candidate_counts,
        "added_negatives": len(manifest),
        "category_counts": dict(
            sorted(Counter(item["category"] for item in manifest).items())
        ),
        "final_counts": {
            "train": len(final_images),
            "val": _split_image_count(output, "val"),
            "test": _split_image_count(output, "test"),
        },
        "empty_train_labels": len(empty_labels),
        "image_label_parity": len(final_images) == len(final_labels),
        "unique_negative_hashes": len(set(selected_hashes)) == len(selected_hashes),
        "negative_hash_overlap_with_base": bool(set(selected_hashes) & base_hashes),
        "val_unchanged": source_val_hashes == output_val_hashes,
        "test_unchanged": source_test_hashes == output_test_hashes,
        "review_pages": review_pages,
        "validation_policy": "negative samples added to train only; val/test copied unchanged",
    }
    (review_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "README.txt").open("a", encoding="utf-8") as handle:
        handle.write(
            "\nThis dataset adds reviewed, real hard negatives to train only.\n"
            "Negative labels are intentionally empty. Validation/test remain unchanged.\n"
        )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("datasets/board-pose-pi5-8kpt-synth-v4"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("datasets/board-pose-pi5-8kpt-synth-v5"),
    )
    parser.add_argument(
        "--uno-source", type=Path, default=Path("datasets/board-pose/images/train")
    )
    parser.add_argument(
        "--sensor-source",
        type=Path,
        default=Path("datasets/photoresistor-pose/images/train"),
    )
    parser.add_argument(
        "--wiring-source",
        type=Path,
        default=Path(
            "datasets/live-captures/powered_led/"
            "20260807-092815-powered_led/images"
        ),
    )
    parser.add_argument("--uno-count", type=int, default=20)
    parser.add_argument("--sensor-count", type=int, default=15)
    parser.add_argument("--wiring-count", type=int, default=15)
    args = parser.parse_args()
    summary = add_negative_samples(
        source=args.source,
        output=args.output,
        uno_source=args.uno_source,
        sensor_source=args.sensor_source,
        wiring_source=args.wiring_source,
        uno_count=args.uno_count,
        sensor_count=args.sensor_count,
        wiring_count=args.wiring_count,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
