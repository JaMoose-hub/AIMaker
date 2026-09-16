# -*- coding: utf-8 -*-
"""Build a reviewable Pose train-only synthetic augmentation dataset.

The source train split is copied unchanged and receives two geometry-preserving
variants per positive image (counts are configurable):

1. a whole-frame photometric variant, which preserves every hand and wire;
2. a foreground composite on a synthetic desk, followed by photometric stress.

Validation and test splits are copied byte-for-byte and are never augmented.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil

import cv2
import numpy as np

from pi5_robustness_test import (
    BACKGROUND_KINDS,
    IMAGE_SUFFIXES,
    apply_photometric_stress,
    composite_foreground,
    foreground_mask,
    procedural_background,
    read_pose_label,
)


KEYPOINT_NAMES = (
    "board_TL",
    "board_TR",
    "board_BR",
    "board_BL",
    "J8_P1",
    "J8_P2",
    "J8_P40",
    "J8_P39",
)
KEYPOINT_COLORS = (
    (255, 80, 80),
    (80, 220, 255),
    (80, 255, 120),
    (255, 100, 220),
    (40, 40, 255),
    (40, 220, 255),
    (255, 180, 40),
    (255, 255, 255),
)


def _images(root: Path, split: str) -> list[Path]:
    directory = root / "images" / split
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _copy_split(source: Path, output: Path, split: str) -> int:
    image_output = output / "images" / split
    label_output = output / "labels" / split
    image_output.mkdir(parents=True, exist_ok=True)
    label_output.mkdir(parents=True, exist_ok=True)
    count = 0
    for image_path in _images(source, split):
        label_path = source / "labels" / split / f"{image_path.stem}.txt"
        if not label_path.is_file():
            raise ValueError(f"missing label for {image_path}")
        shutil.copy2(image_path, image_output / image_path.name)
        shutil.copy2(label_path, label_output / label_path.name)
        count += 1
    return count


def _draw_keypoints(image: np.ndarray, label_path: Path) -> np.ndarray:
    result = image.copy()
    label = read_pose_label(label_path)
    if label is None:
        return result
    height, width = result.shape[:2]
    for index, point in enumerate(label.keypoints):
        if point[2] <= 0:
            continue
        x = int(round(float(point[0]) * width))
        y = int(round(float(point[1]) * height))
        color = KEYPOINT_COLORS[index % len(KEYPOINT_COLORS)]
        cv2.circle(result, (x, y), max(5, min(width, height) // 140), color, -1, cv2.LINE_AA)
        cv2.putText(
            result,
            str(index + 1),
            (x + 7, y - 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.45, min(width, height) / 1800.0),
            color,
            2,
            cv2.LINE_AA,
        )
    return result


def _fit_panel(image: np.ndarray, width: int = 384, height: int = 216) -> np.ndarray:
    source_h, source_w = image.shape[:2]
    scale = min(width / source_w, height / source_h)
    resized = cv2.resize(
        image,
        (max(1, int(round(source_w * scale))), max(1, int(round(source_h * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
    )
    panel = np.full((height, width, 3), 22, dtype=np.uint8)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    panel[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return panel


def _caption(image: np.ndarray, text: str) -> np.ndarray:
    result = image.copy()
    cv2.rectangle(result, (0, 0), (result.shape[1], 28), (8, 8, 8), -1)
    cv2.putText(
        result, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX,
        0.52, (90, 230, 255), 1, cv2.LINE_AA,
    )
    return result


def _write_review_pages(
    manifest: list[dict[str, object]],
    review_dir: Path,
    *,
    preview_count: int,
) -> list[str]:
    composite_items = [item for item in manifest if item["kind"] == "background"]
    if not composite_items or preview_count <= 0:
        return []
    indices = np.linspace(
        0, len(composite_items) - 1, min(preview_count, len(composite_items)), dtype=int
    )
    rows: list[np.ndarray] = []
    for index in indices:
        item = composite_items[int(index)]
        source_path = Path(str(item["source_image"]))
        generated_path = Path(str(item["generated_image"]))
        mask_path = Path(str(item["generated_mask"]))
        label_path = Path(str(item["source_label"]))
        source = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        generated = cv2.imread(str(generated_path), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if source is None or generated is None or mask is None:
            continue
        mask_panel = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        label = read_pose_label(label_path)
        keypoint_count = int(label.keypoints.shape[0]) if label is not None else 0
        source_panel = _caption(
            _fit_panel(_draw_keypoints(source, label_path)),
            f"SOURCE + {keypoint_count} KPTS",
        )
        mask_panel = _caption(_fit_panel(mask_panel), "AUTO FOREGROUND MASK")
        generated_panel = _caption(
            _fit_panel(_draw_keypoints(generated, label_path)),
            f"SYNTH: {item['background']} / {item['lighting']['color_cast']}",
        )
        rows.append(np.hstack([source_panel, mask_panel, generated_panel]))
    review_dir.mkdir(parents=True, exist_ok=True)
    pages: list[str] = []
    for page_index in range(0, len(rows), 4):
        page = np.vstack(rows[page_index:page_index + 4])
        path = review_dir / f"review-{page_index // 4 + 1:02d}.jpg"
        if not cv2.imwrite(str(path), page, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise RuntimeError(f"cannot write review page: {path}")
        pages.append(str(path.resolve()))
    return pages


def build_dataset(
    *,
    source: Path,
    output: Path,
    seed: int = 20260829,
    preview_count: int = 16,
    foreground_mode: str = "pose-only",
    photometric_variants: int = 1,
    background_variants: int = 1,
) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    if photometric_variants < 0 or background_variants < 0:
        raise ValueError("augmentation variant counts cannot be negative")
    if photometric_variants + background_variants <= 0:
        raise ValueError("at least one augmentation variant is required")
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"output path is not a directory: {output}")
        if any(output.iterdir()):
            raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    source_counts = {
        split: _copy_split(source, output, split)
        for split in ("train", "val", "test")
    }
    train_images = _images(source, "train")
    if not train_images:
        raise ValueError(f"no train images found in {source}")

    review_root = output / ".synthetic-review"
    mask_root = review_root / "masks"
    mask_root.mkdir(parents=True, exist_ok=True)
    image_output = output / "images" / "train"
    label_output = output / "labels" / "train"
    rng = np.random.default_rng(seed)
    manifest: list[dict[str, object]] = []

    for image_index, image_path in enumerate(train_images):
        label_path = source / "labels" / "train" / f"{image_path.stem}.txt"
        label = read_pose_label(label_path)
        if label is None:
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot read source image: {image_path}")

        casts = ("warm", "cool", "neutral")
        for variant_index in range(photometric_variants):
            cast = casts[(image_index + variant_index) % len(casts)]
            photo_bytes, photo_lighting = apply_photometric_stress(
                image, rng, color_cast_override=cast
            )
            photo_image = image_output / (
                f"{image_path.stem}__photo_v{variant_index + 1}__{cast}.jpg"
            )
            photo_label = label_output / f"{photo_image.stem}.txt"
            photo_image.write_bytes(photo_bytes)
            shutil.copy2(label_path, photo_label)
            manifest.append(
                {
                    "kind": "photometric",
                    "variant": variant_index + 1,
                    "source_image": str(image_path.resolve()),
                    "source_label": str(label_path.resolve()),
                    "generated_image": str(photo_image.resolve()),
                    "generated_label": str(photo_label.resolve()),
                    "generated_mask": None,
                    "background": "original",
                    "lighting": photo_lighting,
                }
            )

        if background_variants:
            mask, mask_report = foreground_mask(image, label, mode=foreground_mode)
            mask_path = mask_root / f"{image_path.stem}.png"
            if not cv2.imwrite(str(mask_path), mask):
                raise RuntimeError(f"cannot write mask: {mask_path}")
            for variant_index in range(background_variants):
                background_kind = BACKGROUND_KINDS[
                    (image_index * background_variants + variant_index)
                    % len(BACKGROUND_KINDS)
                ]
                cast = casts[(image_index + variant_index + 1) % len(casts)]
                background = procedural_background(
                    background_kind, image.shape[0], image.shape[1], rng
                )
                composite, shadow = composite_foreground(image, mask, background, rng)
                background_bytes, background_lighting = apply_photometric_stress(
                    composite, rng, color_cast_override=cast
                )
                background_image = image_output / (
                    f"{image_path.stem}__background_v{variant_index + 1}__"
                    f"{background_kind}__{cast}.jpg"
                )
                background_label = label_output / f"{background_image.stem}.txt"
                background_image.write_bytes(background_bytes)
                shutil.copy2(label_path, background_label)
                manifest.append(
                    {
                        "kind": "background",
                        "variant": variant_index + 1,
                        "source_image": str(image_path.resolve()),
                        "source_label": str(label_path.resolve()),
                        "generated_image": str(background_image.resolve()),
                        "generated_label": str(background_label.resolve()),
                        "generated_mask": str(mask_path.resolve()),
                        "background": background_kind,
                        "mask": mask_report,
                        "shadow": shadow,
                        "lighting": background_lighting,
                    }
                )

    manifest_path = review_root / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in manifest),
        encoding="utf-8",
    )
    review_pages = _write_review_pages(
        manifest, review_root, preview_count=preview_count
    )
    background_counts = Counter(str(item["background"]) for item in manifest)
    cast_counts = Counter(str(item["lighting"]["color_cast"]) for item in manifest)
    mask_items = [item for item in manifest if item.get("mask")]
    summary: dict[str, object] = {
        "scope": "train_only_synthetic_augmentation",
        "source_dataset": str(source),
        "output_dataset": str(output),
        "seed": seed,
        "photometric_variants_per_positive": photometric_variants,
        "background_variants_per_positive": background_variants,
        "source_counts": source_counts,
        "generated": len(manifest),
        "generated_photometric": sum(item["kind"] == "photometric" for item in manifest),
        "generated_background": sum(item["kind"] == "background" for item in manifest),
        "final_counts": {
            "train": len(_images(output, "train")),
            "val": len(_images(output, "val")),
            "test": len(_images(output, "test")),
        },
        "background_counts": dict(sorted(background_counts.items())),
        "color_cast_counts": dict(sorted(cast_counts.items())),
        "mask_min_board_coverage": min(
            float(item["mask"]["board_coverage"]) for item in mask_items
        ) if mask_items else None,
        "mask_max_foreground_fraction": max(
            float(item["mask"]["foreground_fraction"]) for item in mask_items
        ) if mask_items else None,
        "review_pages": review_pages,
        "validation_policy": "val/test copied unchanged; never synthesized",
    }
    (review_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "README.txt").write_text(
        "Pose train-only synthetic augmentation dataset.\n"
        "Original train images are retained; positive images receive configurable "
        "photometric and background-composite variants.\n"
        "Validation/test images and labels are copied unchanged. Synthetic results do not "
        "replace an independent real test set.\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("datasets/board-pose-pi5-8kpt")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("datasets/board-pose-pi5-8kpt-synth-v4")
    )
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--preview-count", type=int, default=16)
    parser.add_argument(
        "--foreground-mode",
        choices=("pose-only", "board-hand", "auto"),
        default="pose-only",
    )
    parser.add_argument("--photometric-variants", type=int, default=1)
    parser.add_argument("--background-variants", type=int, default=1)
    args = parser.parse_args()
    summary = build_dataset(
        source=args.source,
        output=args.output,
        seed=args.seed,
        preview_count=args.preview_count,
        foreground_mode=args.foreground_mode,
        photometric_variants=args.photometric_variants,
        background_variants=args.background_variants,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
