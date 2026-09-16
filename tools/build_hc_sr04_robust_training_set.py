# -*- coding: utf-8 -*-
"""Build an HC-SR04 Pose dataset for controller, occlusion and light robustness.

The reviewed HC-SR04 geometry is never edited.  Train variants preserve the
four semantic PCB corners while adding three independent stressors:

* a real Raspberry Pi 5 cut-out placed outside the HC-SR04 footprint;
* perspective-aligned hand or jumper-wire occlusion over the sensor;
* whole-frame exposure, colour-cast, shadow, reflection and codec stress.

Clean validation images are copied byte-for-byte.  Synthetic stress variants
are written to ``test`` so the deployed model and each candidate can be
compared on exactly the same transformations.  Pi-only frames are valid hard
negatives for the HC-SR04 class and are added to train with empty labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
from typing import Any

import cv2
import numpy as np

from pi5_robustness_test import (
    IMAGE_SUFFIXES,
    PoseLabel,
    apply_photometric_stress,
    foreground_mask,
    read_pose_label,
)


MARKER_NAME = ".hc-sr04-robust-derived.json"
SENSOR_KEYPOINT_NAMES = ("pcb_TL", "pcb_TR", "pcb_BR", "pcb_BL")
WIRE_COLORS_BGR = (
    (38, 38, 210),   # red
    (35, 125, 225),  # orange
    (35, 205, 235),  # yellow
    (55, 135, 70),   # green
    (190, 90, 35),   # blue
    (32, 32, 32),    # black
    (42, 72, 105),   # brown
)


def _images(dataset: Path, split: str) -> list[Path]:
    directory = dataset / "images" / split
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _label_path(dataset: Path, split: str, image: Path) -> Path:
    return dataset / "labels" / split / f"{image.stem}.txt"


def _positive_items(
    dataset: Path, split: str, *, keypoint_count: int | None = None
) -> list[tuple[Path, Path, PoseLabel]]:
    result: list[tuple[Path, Path, PoseLabel]] = []
    for image in _images(dataset, split):
        label_path = _label_path(dataset, split, image)
        if not label_path.is_file():
            raise ValueError(f"missing label for {image}")
        label = read_pose_label(label_path)
        if label is not None:
            if keypoint_count is not None and label.keypoints.shape != (keypoint_count, 3):
                raise ValueError(
                    f"expected {keypoint_count} keypoints in source label: {label_path}"
                )
            result.append((image, label_path, label))
    return result


def _write_pose_label(path: Path, label: PoseLabel) -> None:
    values: list[float] = [float(label.class_id), *label.box.tolist()]
    values.extend(label.keypoints.reshape(-1).tolist())
    rendered = [str(int(round(values[0])))]
    rendered.extend(f"{float(value):.8g}" for value in values[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(" ".join(rendered) + "\n", encoding="utf-8")


def _copy_clean_split(source: Path, output: Path, split: str) -> int:
    count = 0
    for image in _images(source, split):
        label = _label_path(source, split, image)
        if not label.is_file():
            raise ValueError(f"missing label for {image}")
        image_output = output / "images" / split / image.name
        label_output = output / "labels" / split / label.name
        image_output.parent.mkdir(parents=True, exist_ok=True)
        label_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image, image_output)
        shutil.copy2(label, label_output)
        count += 1
    return count


def _marker_name(component_name: str) -> str:
    return MARKER_NAME if component_name == "hc-sr04" else ".component-pose-robust-derived.json"


def _prepare_output(output: Path, *, overwrite: bool, marker_name: str) -> None:
    if not output.exists() or not any(output.iterdir()):
        output.mkdir(parents=True, exist_ok=True)
        return
    if not overwrite:
        raise ValueError(f"output directory is not empty: {output}")
    marker = output / marker_name
    if not marker.is_file():
        raise ValueError(f"refusing to replace unmarked directory: {output}")
    shutil.rmtree(output)
    output.mkdir(parents=True)


def _decode_jpeg(payload: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("cannot decode generated JPEG")
    return image


def _box_from_corners(label: PoseLabel, width: int, height: int) -> tuple[int, int, int, int]:
    points = label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    low = np.floor(points.min(axis=0)).astype(int)
    high = np.ceil(points.max(axis=0)).astype(int)
    diagonal = float(np.linalg.norm(high - low))
    margin = max(8, int(round(diagonal * 0.10)))
    return (
        max(0, low[0] - margin),
        max(0, low[1] - margin),
        min(width, high[0] + margin),
        min(height, high[1] + margin),
    )


def _rect_intersection_fraction(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> float:
    x1 = max(first[0], second[0])
    y1 = max(first[1], second[1])
    x2 = min(first[2], second[2])
    y2 = min(first[3], second[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = max(1, (first[2] - first[0]) * (first[3] - first[1]))
    return float(intersection) / float(first_area)


def _rotate_bound(
    image: np.ndarray, mask: np.ndarray, angle_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cosine = abs(float(matrix[0, 0]))
    sine = abs(float(matrix[0, 1]))
    out_width = max(1, int(math.ceil(height * sine + width * cosine)))
    out_height = max(1, int(math.ceil(height * cosine + width * sine)))
    matrix[0, 2] += out_width / 2.0 - center[0]
    matrix[1, 2] += out_height / 2.0 - center[1]
    rotated_image = cv2.warpAffine(
        image,
        matrix,
        (out_width, out_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    rotated_mask = cv2.warpAffine(
        mask,
        matrix,
        (out_width, out_height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )
    return rotated_image, rotated_mask


def _pi5_cutout(image: np.ndarray, label: PoseLabel) -> tuple[np.ndarray, np.ndarray]:
    mask, _ = foreground_mask(image, label, mode="pose-only")
    ys, xs = np.nonzero(mask >= 16)
    if xs.size == 0:
        raise ValueError("Pi 5 foreground mask is empty")
    padding = max(4, int(round(min(image.shape[:2]) * 0.006)))
    x1 = max(0, int(xs.min()) - padding)
    x2 = min(image.shape[1], int(xs.max()) + padding + 1)
    y1 = max(0, int(ys.min()) - padding)
    y2 = min(image.shape[0], int(ys.max()) + padding + 1)
    return image[y1:y2, x1:x2].copy(), mask[y1:y2, x1:x2].copy()


def place_pi5_distractor(
    frame: np.ndarray,
    sensor_label: PoseLabel,
    pi5_image: np.ndarray,
    pi5_label: PoseLabel,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Place a feathered real Pi 5 outside the labelled HC-SR04 footprint."""
    height, width = frame.shape[:2]
    cutout, cutout_mask = _pi5_cutout(pi5_image, pi5_label)
    cutout, cutout_mask = _rotate_bound(
        cutout, cutout_mask, float(rng.uniform(-180.0, 180.0))
    )
    target_width = int(round(rng.uniform(0.20, 0.31) * width))
    scale = target_width / max(cutout.shape[1], 1)
    target_height = max(1, int(round(cutout.shape[0] * scale)))
    max_height = int(round(height * 0.48))
    if target_height > max_height:
        scale *= max_height / target_height
        target_width = max(1, int(round(cutout.shape[1] * scale)))
        target_height = max(1, int(round(cutout.shape[0] * scale)))
    cutout = cv2.resize(cutout, (target_width, target_height), interpolation=cv2.INTER_AREA)
    cutout_mask = cv2.resize(
        cutout_mask, (target_width, target_height), interpolation=cv2.INTER_LINEAR
    )
    sensor_rect = _box_from_corners(sensor_label, width, height)
    margin = max(4, int(round(min(width, height) * 0.01)))
    candidates: list[tuple[int, int, float]] = []
    for _ in range(120):
        x = int(rng.integers(margin, max(margin + 1, width - target_width - margin + 1)))
        y = int(rng.integers(margin, max(margin + 1, height - target_height - margin + 1)))
        rect = (x, y, x + target_width, y + target_height)
        overlap = _rect_intersection_fraction(sensor_rect, rect)
        candidates.append((x, y, overlap))
        if overlap <= 0.005:
            break
    x, y, overlap = min(candidates, key=lambda item: item[2])
    full_mask = np.zeros((height, width), dtype=np.float32)
    full_layer = np.zeros_like(frame)
    full_mask[y : y + target_height, x : x + target_width] = (
        cutout_mask.astype(np.float32) / 255.0
    )
    full_layer[y : y + target_height, x : x + target_width] = cutout

    shadow_dx = int(round(rng.uniform(-0.012, 0.012) * width))
    shadow_dy = int(round(rng.uniform(0.006, 0.025) * height))
    shadow_transform = np.float32([[1, 0, shadow_dx], [0, 1, shadow_dy]])
    shadow = cv2.warpAffine(full_mask, shadow_transform, (width, height))
    shadow = cv2.GaussianBlur(shadow, (0, 0), float(rng.uniform(5.0, 14.0)))
    result = frame.astype(np.float32) * (1.0 - 0.24 * shadow[..., None])
    alpha = cv2.GaussianBlur(full_mask, (0, 0), float(rng.uniform(0.7, 1.8)))
    alpha = np.clip(alpha, 0.0, 1.0)[..., None]
    result = full_layer.astype(np.float32) * alpha + result * (1.0 - alpha)
    return np.clip(result, 0, 255).astype(np.uint8), {
        "rect_px": [x, y, x + target_width, y + target_height],
        "sensor_overlap_fraction": round(overlap, 6),
        "foreground_fraction": round(float(np.mean(full_mask > 0.05)), 6),
    }


def _canonical_occluder(
    kind: str, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if kind not in {"hand", "wire", "hand_wire"}:
        raise ValueError(f"unknown occluder kind: {kind}")
    board_width, board_height, margin = 480, 240, 100
    canvas_width = board_width + 2 * margin
    canvas_height = board_height + 2 * margin
    layer = np.zeros((canvas_height, canvas_width, 3), dtype=np.uint8)
    mask = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    details: dict[str, Any] = {"kind": kind}
    corners = np.array(
        [
            [margin, margin],
            [margin + board_width, margin],
            [margin + board_width, margin + board_height],
            [margin, margin + board_height],
        ],
        dtype=np.float64,
    )

    if kind in {"hand", "hand_wire"}:
        corner_index = int(rng.integers(0, 4))
        target = corners[corner_index]
        center = np.array(
            [margin + board_width / 2.0, margin + board_height / 2.0], dtype=np.float64
        )
        outward = target - center
        outward /= max(float(np.linalg.norm(outward)), 1.0)
        start = target + outward * rng.uniform(90.0, 150.0)
        # Push a realistically wide fingertip well inside the PCB.  The first
        # draft covered only ~5% of this very small board and was too easy.
        end = target - outward * rng.uniform(95.0, 155.0)
        thickness = int(rng.integers(92, 142))
        skin = np.array(
            [rng.integers(75, 135), rng.integers(120, 178), rng.integers(165, 225)],
            dtype=np.uint8,
        )
        cv2.line(
            mask, tuple(np.rint(start).astype(int)), tuple(np.rint(end).astype(int)),
            255, thickness, cv2.LINE_AA,
        )
        cv2.circle(mask, tuple(np.rint(end).astype(int)), thickness // 2, 255, -1, cv2.LINE_AA)
        layer[mask > 0] = skin
        texture = rng.normal(0.0, 4.0, layer.shape).astype(np.float32)
        layer = np.clip(layer.astype(np.float32) + texture * (mask[..., None] > 0), 0, 255).astype(np.uint8)
        details.update(hand_target_corner=corner_index, hand_thickness=thickness)

    if kind in {"wire", "hand_wire"}:
        wire_mask = np.zeros_like(mask)
        wire_layer = np.zeros_like(layer)
        corner_index = int(rng.integers(0, 4))
        target = corners[corner_index]
        # Include the selected semantic corner explicitly so every generated
        # wire case teaches inference through a genuine endpoint occlusion.
        if corner_index in (0, 3):
            before_x, after_x = -30.0, canvas_width + 30.0
        else:
            before_x, after_x = canvas_width + 30.0, -30.0
        base_y = float(target[1])
        points = np.asarray(
            [
                [before_x, base_y + rng.uniform(-65.0, 65.0)],
                [(before_x + target[0]) * 0.5, base_y + rng.uniform(-35.0, 35.0)],
                target,
                [(after_x + target[0]) * 0.5, base_y + rng.uniform(-35.0, 35.0)],
                [after_x, base_y + rng.uniform(-65.0, 65.0)],
            ],
            dtype=np.int32,
        )
        thickness = int(rng.integers(13, 23))
        color = WIRE_COLORS_BGR[int(rng.integers(0, len(WIRE_COLORS_BGR)))]
        cv2.polylines(wire_mask, [points], False, 255, thickness + 4, cv2.LINE_AA)
        cv2.polylines(wire_layer, [points], False, color, thickness, cv2.LINE_AA)
        layer[wire_mask > 0] = wire_layer[wire_mask > 0]
        mask = cv2.max(mask, wire_mask)
        details.update(wire_target_corner=corner_index, wire_thickness=thickness)
    return layer, mask, details


def add_perspective_occlusion(
    frame: np.ndarray,
    label: PoseLabel,
    rng: np.random.Generator,
    *,
    kind: str,
) -> tuple[np.ndarray, PoseLabel, dict[str, Any]]:
    """Add a board-aligned occluder and mark covered corners as inferred (v=1)."""
    height, width = frame.shape[:2]
    board_width, board_height, margin = 480, 240, 100
    layer, mask, details = _canonical_occluder(kind, rng)
    source = np.array(
        [
            [margin, margin],
            [margin + board_width, margin],
            [margin + board_width, margin + board_height],
            [margin, margin + board_height],
        ],
        dtype=np.float32,
    )
    destination = (
        label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    ).astype(np.float32)
    transform = cv2.getPerspectiveTransform(source, destination)
    warped_layer = cv2.warpPerspective(
        layer, transform, (width, height), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0),
    )
    warped_mask = cv2.warpPerspective(
        mask, transform, (width, height), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    ).astype(np.float32) / 255.0
    shadow = cv2.warpAffine(
        warped_mask,
        np.float32([[1, 0, 5], [0, 1, 8]]),
        (width, height),
        flags=cv2.INTER_LINEAR,
    )
    shadow = cv2.GaussianBlur(shadow, (0, 0), 7.0)
    result = frame.astype(np.float32) * (1.0 - 0.22 * shadow[..., None])
    alpha = cv2.GaussianBlur(warped_mask, (0, 0), 1.0)[..., None]
    result = warped_layer.astype(np.float32) * alpha + result * (1.0 - alpha)

    keypoints = label.keypoints.copy()
    covered: list[int] = []
    for index, point in enumerate(destination):
        x = int(np.clip(round(float(point[0])), 0, width - 1))
        y = int(np.clip(round(float(point[1])), 0, height - 1))
        if warped_mask[y, x] >= 0.18:
            keypoints[index, 2] = 1.0
            covered.append(index)
    board_mask = cv2.warpPerspective(
        np.full((board_height, board_width), 255, dtype=np.uint8),
        cv2.getPerspectiveTransform(
            np.array(
                [[0, 0], [board_width - 1, 0], [board_width - 1, board_height - 1], [0, board_height - 1]],
                dtype=np.float32,
            ),
            destination,
        ),
        (width, height),
    )
    board_pixels = max(1, int(np.count_nonzero(board_mask)))
    occlusion_fraction = float(np.count_nonzero((warped_mask >= 0.18) & (board_mask > 0))) / board_pixels
    updated = PoseLabel(
        raw=label.raw,
        class_id=label.class_id,
        box=label.box.copy(),
        keypoints=keypoints,
    )
    details.update(
        covered_keypoints=covered,
        occlusion_fraction=round(occlusion_fraction, 6),
    )
    return np.clip(result, 0, 255).astype(np.uint8), updated, details


def _save_generated(
    image: np.ndarray,
    label: PoseLabel,
    image_path: Path,
    label_path: Path,
    rng: np.random.Generator,
    *,
    cast: str | None = None,
) -> dict[str, Any]:
    payload, lighting = apply_photometric_stress(
        image, rng, color_cast_override=cast
    )
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(payload)
    _write_pose_label(label_path, label)
    return lighting


def _draw_pose(image: np.ndarray, label: PoseLabel, caption: str) -> np.ndarray:
    result = image.copy()
    height, width = image.shape[:2]
    points = label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    cv2.polylines(result, [np.rint(points).astype(np.int32)], True, (50, 235, 90), 4, cv2.LINE_AA)
    for index, point in enumerate(points):
        color = (30, 190, 255) if label.keypoints[index, 2] == 1 else (50, 235, 90)
        cv2.circle(result, tuple(np.rint(point).astype(int)), 8, color, -1, cv2.LINE_AA)
    cv2.rectangle(result, (0, 0), (width, max(42, height // 20)), (8, 8, 8), -1)
    cv2.putText(result, caption, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.85, (80, 220, 255), 2, cv2.LINE_AA)
    return result


def _fit_panel(image: np.ndarray, size: tuple[int, int] = (480, 270)) -> np.ndarray:
    width, height = size
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(
        image,
        (max(1, int(round(image.shape[1] * scale))), max(1, int(round(image.shape[0] * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
    )
    panel = np.full((height, width, 3), 20, dtype=np.uint8)
    x = (width - resized.shape[1]) // 2
    y = (height - resized.shape[0]) // 2
    panel[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
    return panel


def _write_review_pages(
    manifest: list[dict[str, Any]], review_root: Path, preview_count: int
) -> list[str]:
    items = [item for item in manifest if item.get("label") and item["split"] == "train"]
    if not items or preview_count <= 0:
        return []
    indices = np.linspace(0, len(items) - 1, min(preview_count, len(items)), dtype=int)
    panels: list[np.ndarray] = []
    for index in indices:
        item = items[int(index)]
        image = cv2.imread(str(item["image"]), cv2.IMREAD_COLOR)
        label = read_pose_label(Path(str(item["label"])))
        if image is None or label is None:
            continue
        panels.append(_fit_panel(_draw_pose(image, label, str(item["kind"]))))
    pages: list[str] = []
    review_root.mkdir(parents=True, exist_ok=True)
    for page_index in range(0, len(panels), 12):
        chunk = panels[page_index : page_index + 12]
        rows: list[np.ndarray] = []
        for row_index in range(0, len(chunk), 3):
            row = chunk[row_index : row_index + 3]
            while len(row) < 3:
                row.append(np.zeros_like(chunk[0]))
            rows.append(np.hstack(row))
        page = np.vstack(rows)
        path = review_root / f"review-{page_index // 12 + 1:02d}.jpg"
        if not cv2.imwrite(str(path), page, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
            raise RuntimeError(f"cannot write review page: {path}")
        pages.append(str(path.resolve()))
    return pages


def build_dataset(
    *,
    source: Path,
    pi5_source: Path,
    output: Path,
    seed: int = 20260831,
    pi5_negatives: int = 50,
    preview_count: int = 24,
    overwrite: bool = False,
    component_name: str = "hc-sr04",
) -> dict[str, Any]:
    source = source.resolve()
    pi5_source = pi5_source.resolve()
    output = output.resolve()
    component_name = component_name.strip().lower()
    if not component_name:
        raise ValueError("component_name must not be empty")
    marker_name = _marker_name(component_name)
    _prepare_output(output, overwrite=overwrite, marker_name=marker_name)
    rng = np.random.default_rng(seed)
    clean_counts = {
        "train": _copy_clean_split(source, output, "train"),
        "val": _copy_clean_split(source, output, "val"),
    }
    hc_train = _positive_items(source, "train", keypoint_count=4)
    hc_val = _positive_items(source, "val", keypoint_count=4)
    pi5_train = _positive_items(pi5_source, "train", keypoint_count=8)
    pi5_val = _positive_items(pi5_source, "val", keypoint_count=8)
    if not hc_train or not hc_val or not pi5_train or not pi5_val:
        raise ValueError("HC-SR04 and Pi 5 train/val positives are required")

    manifest: list[dict[str, Any]] = []

    def generate_variants(
        items: list[tuple[Path, Path, PoseLabel]],
        pi5_items: list[tuple[Path, Path, PoseLabel]],
        split: str,
    ) -> None:
        for index, (image_path, _source_label_path, label) in enumerate(items):
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"cannot read HC-SR04 source image: {image_path}")
            pi5_image_path, _pi5_label_path, pi5_label = pi5_items[index % len(pi5_items)]
            pi5_frame = cv2.imread(str(pi5_image_path), cv2.IMREAD_COLOR)
            if pi5_frame is None:
                raise ValueError(f"cannot read Pi 5 source image: {pi5_image_path}")
            variants: list[tuple[str, np.ndarray, PoseLabel, dict[str, Any]]] = []

            variants.append(("lighting", frame.copy(), label, {}))
            coexist, coexist_report = place_pi5_distractor(
                frame, label, pi5_frame, pi5_label, rng
            )
            variants.append(("pi5_coexist", coexist, label, {"pi5": coexist_report}))
            hand, hand_label, hand_report = add_perspective_occlusion(
                frame, label, rng, kind="hand"
            )
            variants.append(("hand_occlusion", hand, hand_label, {"occlusion": hand_report}))
            coexist_wire, coexist_wire_report = place_pi5_distractor(
                frame, label, pi5_frame, pi5_label, rng
            )
            coexist_wire, wire_label, wire_report = add_perspective_occlusion(
                coexist_wire, label, rng, kind="hand_wire" if index % 2 else "wire"
            )
            variants.append(
                (
                    "pi5_wire_occlusion",
                    coexist_wire,
                    wire_label,
                    {"pi5": coexist_wire_report, "occlusion": wire_report},
                )
            )

            for variant_index, (kind, generated, generated_label, report) in enumerate(variants):
                stem = f"{image_path.stem}__{kind}"
                target_image = output / "images" / split / f"{stem}.jpg"
                target_label = output / "labels" / split / f"{stem}.txt"
                cast = ("warm", "cool", "neutral")[(index + variant_index) % 3]
                lighting = _save_generated(
                    generated,
                    generated_label,
                    target_image,
                    target_label,
                    rng,
                    cast=cast,
                )
                manifest.append(
                    {
                        "split": split,
                        "kind": kind,
                        "source": str(image_path.resolve()),
                        "pi5_source": str(pi5_image_path.resolve()) if "pi5" in report else None,
                        "image": str(target_image.resolve()),
                        "label": str(target_label.resolve()),
                        "lighting": lighting,
                        **report,
                    }
                )

    generate_variants(hc_train, pi5_train, "train")
    generate_variants(hc_val, pi5_val, "test")

    negative_candidates = [item[0] for item in pi5_train]
    if pi5_negatives > len(negative_candidates):
        pi5_negatives = len(negative_candidates)
    selected_indices = np.linspace(
        0, len(negative_candidates) - 1, pi5_negatives, dtype=int
    ) if pi5_negatives else np.array([], dtype=int)
    for number, source_image in enumerate(
        [negative_candidates[int(index)] for index in selected_indices], start=1
    ):
        target_image = output / "images" / "train" / f"pi5_only_negative_{number:03d}.jpg"
        target_label = output / "labels" / "train" / f"pi5_only_negative_{number:03d}.txt"
        shutil.copy2(source_image, target_image)
        target_label.write_text("", encoding="utf-8")
        manifest.append(
            {
                "split": "train",
                "kind": "pi5_only_negative",
                "source": str(source_image.resolve()),
                "image": str(target_image.resolve()),
                "label": str(target_label.resolve()),
            }
        )

    review_root = output / ".synthetic-review"
    review_root.mkdir(parents=True, exist_ok=True)
    manifest_path = review_root / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in manifest),
        encoding="utf-8",
    )
    review_pages = _write_review_pages(manifest, review_root, preview_count)
    final_counts = {
        split: len(_images(output, split)) for split in ("train", "val", "test")
    }
    kind_counts = Counter(str(item["kind"]) for item in manifest)
    summary: dict[str, Any] = {
        "scope": f"{component_name}_controller_occlusion_lighting_robustness",
        "component_name": component_name,
        "source_dataset": str(source),
        "pi5_source_dataset": str(pi5_source),
        "output_dataset": str(output),
        "seed": seed,
        "clean_counts": clean_counts,
        "final_counts": final_counts,
        "generated_counts": dict(sorted(kind_counts.items())),
        "pi5_negative_count": int(kind_counts.get("pi5_only_negative", 0)),
        "review_pages": review_pages,
        "validation_policy": "clean val copied unchanged; synthetic stress is test-only",
        "test_limitation": "synthetic test derives from clean val and is not a session-independent real test",
    }
    (review_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / marker_name).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "README.txt").write_text(
        f"{component_name} robust Pose dataset.\n"
        "Train contains reviewed clean images, Pi 5 coexistence, hand/wire occlusion, "
        "photometric stress and true Pi-only negatives.\n"
        "Validation is copied unchanged. Test contains deterministic synthetic stress "
        "variants and is for candidate comparison, not a substitute for a new real session.\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("datasets/hc-sr04-corner-pose-v2")
    )
    parser.add_argument(
        "--pi5-source", type=Path, default=Path("datasets/board-pose-pi5-8kpt")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("datasets/hc-sr04-corner-pose-v3-robust")
    )
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--pi5-negatives", type=int, default=50)
    parser.add_argument("--preview-count", type=int, default=24)
    parser.add_argument("--component-name", default="hc-sr04")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    summary = build_dataset(
        source=args.source,
        pi5_source=args.pi5_source,
        output=args.output,
        seed=args.seed,
        pi5_negatives=max(0, args.pi5_negatives),
        preview_count=max(0, args.preview_count),
        overwrite=args.overwrite,
        component_name=args.component_name,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
