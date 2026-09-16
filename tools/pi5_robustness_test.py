# -*- coding: utf-8 -*-
"""Build and evaluate a synthetic Raspberry Pi 5 pose robustness set.

This is a stress test, not a replacement for a real, session-separated test
set. Geometry is unchanged, so original YOLO Pose labels are copied exactly
while backgrounds and photometric conditions vary.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import sys
from typing import Iterable

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
BACKGROUND_KINDS = ("white_desk", "wood", "dark_mat", "metal", "cluttered_bench")


@dataclass(frozen=True)
class PoseLabel:
    raw: str
    class_id: int
    box: np.ndarray
    keypoints: np.ndarray


def read_pose_label(path: Path) -> PoseLabel | None:
    raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    stripped = raw.strip()
    if not stripped:
        return None
    lines = [line for line in stripped.splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError(f"expected one board instance in {path}")
    values = np.asarray([float(value) for value in lines[0].split()], dtype=np.float64)
    if values.size < 17 or (values.size - 5) % 3 != 0:
        raise ValueError(f"invalid YOLO Pose label in {path}: {values.size} values")
    keypoints = values[5:].reshape(-1, 3)
    if keypoints.shape[0] not in (4, 8):
        raise ValueError(f"expected 4 or 8 keypoints in {path}")
    return PoseLabel(
        raw=raw,
        class_id=int(round(values[0])),
        box=values[1:5].copy(),
        keypoints=keypoints,
    )


def _low_frequency_noise(
    height: int, width: int, rng: np.random.Generator, *, strength: float = 1.0
) -> np.ndarray:
    small_h = max(2, height // 90)
    small_w = max(2, width // 90)
    field = rng.normal(0.0, strength, (small_h, small_w)).astype(np.float32)
    return cv2.resize(field, (width, height), interpolation=cv2.INTER_CUBIC)


def procedural_background(
    kind: str, height: int, width: int, rng: np.random.Generator
) -> np.ndarray:
    """Generate a deterministic, license-free desk texture in BGR."""
    if kind not in BACKGROUND_KINDS:
        raise ValueError(f"unknown background kind: {kind}")
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    low = _low_frequency_noise(height, width, rng, strength=1.0)

    if kind == "white_desk":
        base = np.array([229.0, 232.0, 235.0], dtype=np.float32)
        gradient = ((xx / max(width - 1, 1)) - 0.5) * rng.uniform(-10.0, 10.0)
        image = base[None, None, :] + gradient[..., None] + 5.0 * low[..., None]
    elif kind == "wood":
        base = np.array([92.0, 142.0, 181.0], dtype=np.float32)
        angle = rng.uniform(-0.25, 0.25)
        axis = xx * math.cos(angle) + yy * math.sin(angle)
        grain = 10.0 * np.sin(axis / rng.uniform(12.0, 26.0))
        grain += 4.0 * np.sin(axis / rng.uniform(2.5, 6.0))
        image = base[None, None, :] + (grain + 8.0 * low)[..., None]
        image[..., 2] += 5.0
    elif kind == "dark_mat":
        base = np.array([31.0, 33.0, 35.0], dtype=np.float32)
        fine = rng.normal(0.0, 3.0, (height, width)).astype(np.float32)
        image = base[None, None, :] + (4.0 * low + fine)[..., None]
    elif kind == "metal":
        base = np.array([151.0, 154.0, 157.0], dtype=np.float32)
        brush = rng.normal(0.0, 4.0, (height, 1)).astype(np.float32)
        brush = cv2.GaussianBlur(brush, (1, 0), sigmaX=0, sigmaY=2.0)
        highlight = 18.0 * np.exp(
            -((xx - rng.uniform(0.2, 0.8) * width) / max(width * 0.16, 1)) ** 2
        )
        image = base[None, None, :] + brush[:, :, None] + highlight[..., None]
        image += 3.0 * low[..., None]
    else:
        image = procedural_background(
            "wood" if rng.random() < 0.5 else "white_desk", height, width, rng
        ).astype(np.float32)
        palette = [
            (34, 39, 46), (52, 68, 90), (38, 95, 160),
            (126, 96, 65), (180, 180, 182), (30, 125, 65),
        ]
        for _ in range(int(rng.integers(8, 18))):
            x1 = int(rng.integers(-width // 10, width))
            y1 = int(rng.integers(-height // 10, height))
            x2 = x1 + int(rng.integers(max(12, width // 30), max(20, width // 7)))
            y2 = y1 + int(rng.integers(max(8, height // 40), max(16, height // 8)))
            color = palette[int(rng.integers(0, len(palette)))]
            cv2.rectangle(image, (x1, y1), (x2, y2), color, -1, cv2.LINE_AA)
        for _ in range(int(rng.integers(2, 6))):
            points = np.column_stack(
                [rng.integers(0, width, 4), rng.integers(0, height, 4)]
            ).astype(np.int32)
            cv2.polylines(
                image, [points], False,
                palette[int(rng.integers(0, len(palette)))],
                int(rng.integers(2, 7)), cv2.LINE_AA,
            )
        image = cv2.GaussianBlur(image, (0, 0), sigmaX=0.55)

    return np.clip(image, 0, 255).astype(np.uint8)


def _cover_background_asset(
    path: Path, height: int, width: int, rng: np.random.Generator
) -> np.ndarray:
    source = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if source is None:
        raise ValueError(f"cannot read background image: {path}")
    source_h, source_w = source.shape[:2]
    scale = max(width / source_w, height / source_h) * float(rng.uniform(1.0, 1.35))
    resized = cv2.resize(
        source,
        (max(width, int(round(source_w * scale))), max(height, int(round(source_h * scale)))),
        interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR,
    )
    max_x = resized.shape[1] - width
    max_y = resized.shape[0] - height
    x = int(rng.integers(0, max_x + 1)) if max_x > 0 else 0
    y = int(rng.integers(0, max_y + 1)) if max_y > 0 else 0
    return resized[y:y + height, x:x + width].copy()


def _board_seed(label: PoseLabel, height: int, width: int) -> np.ndarray:
    points = label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    points = np.rint(points).astype(np.int32)
    seed = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(seed, points, 255, cv2.LINE_AA)
    return seed


def _connected_to_board(candidate: np.ndarray, board_seed: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    connected = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, kernel, iterations=2)
    connected = cv2.dilate(connected, kernel, iterations=1)
    connected[board_seed > 0] = 255
    count, labels = cv2.connectedComponents((connected > 0).astype(np.uint8), 8)
    if count <= 1:
        return board_seed.copy()
    board_ids = np.unique(labels[cv2.dilate(board_seed, kernel, iterations=2) > 0])
    board_ids = board_ids[board_ids != 0]
    keep = np.isin(labels, board_ids).astype(np.uint8) * 255
    keep[board_seed > 0] = 255
    return keep


def _skin_foreground_candidate(image: np.ndarray) -> np.ndarray:
    """Return filled skin regions so hands do not become hollow cut-outs."""
    ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    cr = ycrcb[..., 1]
    cb = ycrcb[..., 2]
    hue = hsv[..., 0]
    saturation = hsv[..., 1]
    value = hsv[..., 2]
    skin_hue = (hue <= 28) | (hue >= 165)
    candidate = (
        (cr >= 125)
        & (cr <= 190)
        & (cb >= 65)
        & (cb <= 150)
        & skin_hue
        & (saturation >= 16)
        & (value >= 38)
    ).astype(np.uint8) * 255
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, close_kernel, iterations=2)
    contours, _ = cv2.findContours(candidate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(candidate)
    min_area = image.shape[0] * image.shape[1] * 0.0004
    for contour in contours:
        if cv2.contourArea(contour) >= min_area:
            cv2.drawContours(filled, [contour], -1, 255, -1, cv2.LINE_AA)
    return filled


def _auto_foreground_mask(image: np.ndarray, label: PoseLabel) -> np.ndarray:
    height, width = image.shape[:2]
    border = max(8, int(round(min(height, width) * 0.035)))
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    border_pixels = np.concatenate(
        [
            lab[:border].reshape(-1, 3), lab[-border:].reshape(-1, 3),
            lab[:, :border].reshape(-1, 3), lab[:, -border:].reshape(-1, 3),
        ],
        axis=0,
    )
    center = np.median(border_pixels, axis=0)
    border_distance = np.linalg.norm(border_pixels - center, axis=1)
    median = float(np.median(border_distance))
    mad = float(np.median(np.abs(border_distance - median)))
    threshold = max(12.0, median + 4.5 * max(mad, 1.0))
    distance = np.linalg.norm(lab - center[None, None, :], axis=2)
    candidate = (distance >= threshold).astype(np.uint8) * 255
    edges = cv2.Canny(image, 45, 120)
    candidate = cv2.bitwise_or(candidate, cv2.dilate(edges, np.ones((3, 3), np.uint8)))
    skin = _skin_foreground_candidate(image)

    # Border modelling can classify a monitor, tripod or distant desk texture as
    # foreground.  Limit generic colour/edge evidence to a board-centric area.
    # Skin remains allowed outside that area so hands actually holding the board
    # are preserved, while unrelated distant objects cannot become connected
    # through faint desk scratches.
    board_points = label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    x_min, y_min = np.floor(board_points.min(axis=0)).astype(int)
    x_max, y_max = np.ceil(board_points.max(axis=0)).astype(int)
    board_width = max(x_max - x_min, 1)
    board_height = max(y_max - y_min, 1)
    pad_x = max(int(round(board_width * 1.35)), int(round(width * 0.035)))
    pad_y = max(int(round(board_height * 1.35)), int(round(height * 0.035)))
    focus = np.zeros((height, width), dtype=np.uint8)
    cv2.rectangle(
        focus,
        (max(0, x_min - pad_x), max(0, y_min - pad_y)),
        (min(width - 1, x_max + pad_x), min(height - 1, y_max + pad_y)),
        255,
        -1,
    )
    candidate = cv2.bitwise_and(candidate, focus)
    candidate = cv2.bitwise_or(candidate, skin)
    board_seed = _board_seed(label, height, width)
    connected = _connected_to_board(candidate, board_seed)
    allowed = cv2.bitwise_or(
        focus,
        cv2.dilate(
            skin,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)),
            iterations=1,
        ),
    )
    connected = cv2.bitwise_and(connected, allowed)
    connected[board_seed > 0] = 255
    return connected


def _clean_plate_mask(image: np.ndarray, clean_plate: np.ndarray, label: PoseLabel) -> np.ndarray:
    height, width = image.shape[:2]
    plate = cv2.resize(clean_plate, (width, height), interpolation=cv2.INTER_AREA)
    current_lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB).astype(np.float32)
    plate_lab = cv2.cvtColor(plate, cv2.COLOR_BGR2LAB).astype(np.float32)
    distance = np.linalg.norm(current_lab - plate_lab, axis=2)
    threshold = max(10.0, float(np.percentile(distance, 55)) + 5.0)
    candidate = (distance >= threshold).astype(np.uint8) * 255
    return _connected_to_board(candidate, _board_seed(label, height, width))


def _board_hand_foreground_mask(image: np.ndarray, label: PoseLabel) -> np.ndarray:
    """Keep the labelled PCB plus skin components that are touching it.

    This mode is intentionally conservative for pose training.  The four board
    corners provide a trustworthy foreground seed, while colour-based desk
    segmentation is avoided because scratches and camera mounts can otherwise
    create large connected cut-out artefacts.
    """
    height, width = image.shape[:2]
    board_seed = _board_seed(label, height, width)
    board_points = label.keypoints[:4, :2] * np.array([width, height], dtype=np.float64)
    diagonal = float(np.linalg.norm(board_points.max(axis=0) - board_points.min(axis=0)))
    margin = max(5, int(round(diagonal * 0.025)))
    if margin % 2 == 0:
        margin += 1
    board_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin, margin))
    board_support = cv2.dilate(board_seed, board_kernel, iterations=1)

    skin = _skin_foreground_candidate(image)
    contact_radius = max(15, int(round(diagonal * 0.16)))
    if contact_radius % 2 == 0:
        contact_radius += 1
    contact_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (contact_radius, contact_radius)
    )
    contact_zone = cv2.dilate(board_seed, contact_kernel, iterations=1)
    count, components = cv2.connectedComponents((skin > 0).astype(np.uint8), 8)
    touching_skin = np.zeros_like(board_seed)
    for component_id in range(1, count):
        component = components == component_id
        if np.any(component & (contact_zone > 0)):
            touching_skin[component] = 255

    mask = cv2.bitwise_or(board_support, touching_skin)
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=1)
    mask[board_seed > 0] = 255
    return mask


def _pose_only_foreground_mask(image: np.ndarray, label: PoseLabel) -> np.ndarray:
    """Keep deterministic board and raised J8 geometry from reviewed pose points."""
    height, width = image.shape[:2]
    scale = np.array([width, height], dtype=np.float64)
    board_points = np.rint(label.keypoints[:4, :2] * scale).astype(np.int32)
    seed = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(seed, board_points, 255, cv2.LINE_AA)
    if label.keypoints.shape[0] >= 8:
        j8_points = np.rint(label.keypoints[4:8, :2] * scale).astype(np.int32)
        cv2.fillConvexPoly(seed, j8_points, 255, cv2.LINE_AA)
    diagonal = float(
        np.linalg.norm(board_points.max(axis=0) - board_points.min(axis=0))
    )
    margin = max(7, int(round(diagonal * 0.045)))
    if margin % 2 == 0:
        margin += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (margin, margin))
    mask = cv2.dilate(seed, kernel, iterations=1)
    mask[_board_seed(label, height, width) > 0] = 255
    return mask


def foreground_mask(
    image: np.ndarray,
    label: PoseLabel,
    *,
    mode: str,
    mask_path: Path | None = None,
    clean_plate: np.ndarray | None = None,
) -> tuple[np.ndarray, dict[str, object]]:
    height, width = image.shape[:2]
    board_seed = _board_seed(label, height, width)
    warnings: list[str] = []

    if mask_path is not None and mask_path.is_file():
        loaded = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if loaded is None:
            raise ValueError(f"cannot read foreground mask: {mask_path}")
        mask = cv2.resize(loaded, (width, height), interpolation=cv2.INTER_NEAREST)
        mask = (mask >= 128).astype(np.uint8) * 255
        source = "sidecar_mask"
    elif mode == "mask":
        raise ValueError(f"foreground mode 'mask' requires a sidecar mask for {mask_path}")
    elif mode == "clean-plate":
        if clean_plate is None:
            raise ValueError("foreground mode 'clean-plate' requires --clean-plate")
        mask = _clean_plate_mask(image, clean_plate, label)
        source = "clean_plate"
    elif mode == "board-hand":
        mask = _board_hand_foreground_mask(image, label)
        source = "board_polygon_plus_touching_skin"
    elif mode == "pose-only":
        mask = _pose_only_foreground_mask(image, label)
        source = "reviewed_board_and_j8_pose_polygon"
    elif mode == "auto":
        mask = _auto_foreground_mask(image, label)
        source = "auto_border_model"
        warnings.append("auto_mask_requires_visual_review")
    else:
        raise ValueError(f"unknown foreground mode: {mode}")

    board_pixels = max(int(np.count_nonzero(board_seed)), 1)
    board_coverage = float(np.count_nonzero((mask > 0) & (board_seed > 0))) / board_pixels
    foreground_fraction = float(np.count_nonzero(mask)) / float(height * width)
    if board_coverage < 0.98:
        raise ValueError(f"foreground mask covers only {board_coverage:.1%} of the board")
    if foreground_fraction <= 0.005 or foreground_fraction >= 0.80:
        raise ValueError(f"implausible foreground fraction: {foreground_fraction:.1%}")
    return mask, {
        "source": source,
        "board_coverage": round(board_coverage, 6),
        "foreground_fraction": round(foreground_fraction, 6),
        "warnings": warnings,
    }


def composite_foreground(
    foreground: np.ndarray,
    foreground_mask_u8: np.ndarray,
    background: np.ndarray,
    rng: np.random.Generator,
) -> tuple[np.ndarray, dict[str, object]]:
    height, width = foreground.shape[:2]
    if background.shape[:2] != (height, width):
        background = cv2.resize(background, (width, height), interpolation=cv2.INTER_LINEAR)
    light_azimuth = float(rng.uniform(0.0, 360.0))
    shadow_angle = math.radians(light_azimuth + 180.0)
    distance = float(rng.uniform(0.008, 0.035) * min(width, height))
    shadow_dx = int(round(math.cos(shadow_angle) * distance))
    shadow_dy = int(round(math.sin(shadow_angle) * distance))
    shadow_blur = float(rng.uniform(5.0, 18.0))
    shadow_strength = float(rng.uniform(0.12, 0.34))
    transform = np.float32([[1, 0, shadow_dx], [0, 1, shadow_dy]])
    shifted = cv2.warpAffine(
        foreground_mask_u8, transform, (width, height),
        flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0,
    )
    shadow = cv2.GaussianBlur(shifted.astype(np.float32) / 255.0, (0, 0), shadow_blur)
    background_f = background.astype(np.float32) * (1.0 - shadow_strength * shadow[..., None])

    feather_sigma = float(rng.uniform(0.8, 2.2))
    alpha = cv2.GaussianBlur(
        foreground_mask_u8.astype(np.float32) / 255.0, (0, 0), feather_sigma
    )
    alpha = np.clip(alpha, 0.0, 1.0)[..., None]
    result = foreground.astype(np.float32) * alpha + background_f * (1.0 - alpha)
    return np.clip(result, 0, 255).astype(np.uint8), {
        "light_azimuth_deg": round(light_azimuth, 3),
        "shadow_dx": shadow_dx,
        "shadow_dy": shadow_dy,
        "shadow_blur_sigma": round(shadow_blur, 3),
        "shadow_strength": round(shadow_strength, 4),
        "edge_feather_sigma": round(feather_sigma, 3),
    }


def _soft_hand_shadow(
    height: int, width: int, rng: np.random.Generator
) -> tuple[np.ndarray, dict[str, object]]:
    """Create a blurred palm-and-fingers shadow mask."""
    mask = np.zeros((height, width), dtype=np.float32)
    center = np.array(
        [rng.uniform(0.18, 0.82) * width, rng.uniform(0.15, 0.85) * height],
        dtype=np.float64,
    )
    angle_deg = float(rng.uniform(0.0, 360.0))
    angle = math.radians(angle_deg)
    forward = np.array([math.cos(angle), math.sin(angle)], dtype=np.float64)
    sideways = np.array([-forward[1], forward[0]], dtype=np.float64)
    palm_axes = (
        max(4, int(rng.uniform(0.055, 0.105) * width)),
        max(4, int(rng.uniform(0.065, 0.125) * height)),
    )
    cv2.ellipse(
        mask,
        tuple(np.rint(center).astype(int)),
        palm_axes,
        angle_deg,
        0,
        360,
        1.0,
        -1,
        cv2.LINE_AA,
    )
    finger_count = int(rng.integers(3, 6))
    finger_thickness = max(3, int(rng.uniform(0.018, 0.034) * min(width, height)))
    for index in range(finger_count):
        lateral = (index - (finger_count - 1) / 2.0) * finger_thickness * 1.15
        start = center + forward * palm_axes[1] * 0.35 + sideways * lateral
        length = rng.uniform(0.08, 0.19) * min(width, height)
        end = start + forward * length
        cv2.line(
            mask,
            tuple(np.rint(start).astype(int)),
            tuple(np.rint(end).astype(int)),
            1.0,
            finger_thickness,
            cv2.LINE_AA,
        )
    blur_sigma = float(rng.uniform(15.0, 50.0))
    mask = cv2.GaussianBlur(mask, (0, 0), blur_sigma)
    return np.clip(mask, 0.0, 1.0), {
        "shape": "soft_hand",
        "center_px": [int(round(center[0])), int(round(center[1]))],
        "angle_deg": round(angle_deg, 3),
        "finger_count": finger_count,
        "blur_sigma": round(blur_sigma, 3),
    }


def apply_photometric_stress(
    image: np.ndarray,
    rng: np.random.Generator,
    *,
    color_cast_override: str | None = None,
) -> tuple[bytes, dict[str, object]]:
    height, width = image.shape[:2]
    gamma = float(rng.uniform(0.65, 1.45))
    exposure = float(rng.uniform(0.70, 1.30))
    if color_cast_override not in (None, "warm", "cool", "neutral"):
        raise ValueError(f"unknown color cast: {color_cast_override}")
    color_cast = color_cast_override or (
        "warm", "cool", "neutral"
    )[int(rng.integers(0, 3))]
    if color_cast == "warm":
        gains = np.array(
            [rng.uniform(0.82, 0.98), rng.uniform(0.98, 1.06), rng.uniform(1.06, 1.20)],
            dtype=np.float32,
        )
    elif color_cast == "cool":
        gains = np.array(
            [rng.uniform(1.06, 1.20), rng.uniform(0.98, 1.06), rng.uniform(0.82, 0.98)],
            dtype=np.float32,
        )
    else:
        gains = np.ones(3, dtype=np.float32)

    result = np.clip(image.astype(np.float32) / 255.0, 0.0, 1.0)
    result = np.power(result, gamma) * exposure
    result *= gains[None, None, :]

    local_shadow_strength = float(rng.uniform(0.0, 0.38))
    local_shadow, local_shadow_params = _soft_hand_shadow(height, width, rng)
    result *= 1.0 - local_shadow_strength * local_shadow[..., None]

    reflection_strength = float(rng.uniform(0.0, 0.28))
    reflection = np.zeros((height, width), dtype=np.float32)
    cv2.ellipse(
        reflection,
        (int(rng.uniform(0.10, 0.90) * width), int(rng.uniform(0.10, 0.90) * height)),
        (int(rng.uniform(0.025, 0.12) * width), int(rng.uniform(0.015, 0.08) * height)),
        float(rng.uniform(0, 180)), 0, 360, 1.0, -1,
    )
    reflection = cv2.GaussianBlur(
        reflection, (0, 0), float(rng.uniform(4.0, 18.0))
    )
    result += (1.0 - result) * reflection_strength * reflection[..., None]

    blur_sigma = float(rng.uniform(0.0, 1.25))
    result_u8 = np.rint(np.clip(result, 0.0, 1.0) * 255.0).astype(np.uint8)
    if blur_sigma >= 0.12:
        result_u8 = cv2.GaussianBlur(result_u8, (0, 0), blur_sigma)
    noise_sigma = float(rng.uniform(0.0, 7.0))
    if noise_sigma > 0.05:
        noise = rng.normal(0.0, noise_sigma, result_u8.shape).astype(np.float32)
        result_u8 = np.clip(result_u8.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    jpeg_quality = int(rng.integers(58, 96))
    ok, encoded = cv2.imencode(
        ".jpg", result_u8, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]
    )
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return encoded.tobytes(), {
        "gamma": round(gamma, 5),
        "exposure": round(exposure, 5),
        "color_cast": color_cast,
        "bgr_gains": [round(float(value), 5) for value in gains],
        "local_shadow_strength": round(local_shadow_strength, 5),
        "local_shadow": local_shadow_params,
        "reflection_strength": round(reflection_strength, 5),
        "blur_sigma": round(blur_sigma, 5),
        "noise_sigma": round(noise_sigma, 5),
        "jpeg_quality": jpeg_quality,
    }


def _mask_path(mask_dir: Path | None, split: str, image_path: Path) -> Path | None:
    if mask_dir is None:
        return None
    direct = mask_dir / split / f"{image_path.stem}.png"
    return direct if direct.is_file() else mask_dir / f"{image_path.stem}.png"


def _source_images(dataset: Path, split: str, max_images: int) -> list[Path]:
    image_dir = dataset / "images" / split
    if not image_dir.is_dir():
        raise ValueError(f"image split does not exist: {image_dir}")
    images = sorted(
        path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    return images[:max_images] if max_images > 0 else images


def generate_stress_set(
    *,
    dataset: Path,
    split: str,
    output: Path,
    variants: int,
    seed: int,
    max_images: int = 0,
    foreground_mode: str = "auto",
    mask_dir: Path | None = None,
    clean_plate_path: Path | None = None,
    background_dir: Path | None = None,
) -> list[dict[str, object]]:
    if output.exists():
        if not output.is_dir():
            raise ValueError(f"output path is not a directory: {output}")
        if any(output.iterdir()):
            raise ValueError(f"output directory is not empty: {output}")
    image_out = output / "images" / "synthetic"
    label_out = output / "labels" / "synthetic"
    mask_out = output / "masks" / "synthetic"
    image_out.mkdir(parents=True, exist_ok=True)
    label_out.mkdir(parents=True, exist_ok=True)
    mask_out.mkdir(parents=True, exist_ok=True)
    images = _source_images(dataset, split, max_images)
    if not images:
        raise ValueError(f"no images found in {dataset / 'images' / split}")
    if variants <= 0:
        raise ValueError("variants must be positive")

    clean_plate = None
    if clean_plate_path is not None:
        clean_plate = cv2.imread(str(clean_plate_path), cv2.IMREAD_COLOR)
        if clean_plate is None:
            raise ValueError(f"cannot read clean plate: {clean_plate_path}")
    background_assets = []
    if background_dir is not None and background_dir.is_dir():
        background_assets = sorted(
            path for path in background_dir.rglob("*") if path.suffix.lower() in IMAGE_SUFFIXES
        )

    rng = np.random.default_rng(seed)
    manifest: list[dict[str, object]] = []
    for image_index, image_path in enumerate(images):
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"cannot read source image: {image_path}")
        label_path = dataset / "labels" / split / f"{image_path.stem}.txt"
        label = read_pose_label(label_path)
        if label is None:
            continue
        selected_mask_path = _mask_path(mask_dir, split, image_path)
        mask, mask_report = foreground_mask(
            image,
            label,
            mode=foreground_mode,
            mask_path=selected_mask_path,
            clean_plate=clean_plate,
        )
        generated_mask = mask_out / f"{image_path.stem}.png"
        if not cv2.imwrite(str(generated_mask), mask):
            raise RuntimeError(f"cannot write foreground mask: {generated_mask}")
        for variant in range(variants):
            sequence = image_index * variants + variant
            kind = BACKGROUND_KINDS[sequence % len(BACKGROUND_KINDS)]
            if background_assets and sequence % 3 == 2:
                asset = background_assets[int(rng.integers(0, len(background_assets)))]
                background = _cover_background_asset(
                    asset, image.shape[0], image.shape[1], rng
                )
                background_name = f"asset:{asset.name}"
            else:
                background = procedural_background(kind, image.shape[0], image.shape[1], rng)
                background_name = kind
            composite, shadow_params = composite_foreground(image, mask, background, rng)
            jpeg, light_params = apply_photometric_stress(composite, rng)
            stem = f"{image_path.stem}__v{variant:02d}__{kind}"
            generated_image = image_out / f"{stem}.jpg"
            generated_label = label_out / f"{stem}.txt"
            generated_image.write_bytes(jpeg)
            shutil.copyfile(label_path, generated_label)
            manifest.append(
                {
                    "source_image": str(image_path.resolve()),
                    "source_label": str(label_path.resolve()),
                    "generated_image": str(generated_image.resolve()),
                    "generated_label": str(generated_label.resolve()),
                    "generated_mask": str(generated_mask.resolve()),
                    "variant": variant,
                    "background": background_name,
                    "mask": mask_report,
                    "shadow": shadow_params,
                    "lighting": light_params,
                }
            )
    if not manifest:
        raise ValueError(
            f"no positive board labels found in {dataset / 'labels' / split}"
        )
    manifest_path = output / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in manifest),
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        "Synthetic robustness stress set only. Do not merge its score with the real test set.\n",
        encoding="utf-8",
    )
    return manifest


def _percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else None


def metric_summary(records: list[dict[str, object]]) -> dict[str, object]:
    positives = [record for record in records if bool(record.get("positive"))]
    negatives = [record for record in records if not bool(record.get("positive"))]
    detected = [record for record in positives if bool(record.get("detected"))]
    pixel_errors = [
        float(value) for record in detected for value in record.get("errors_px", [])
    ]
    normalized_errors = [
        float(value) for record in detected for value in record.get("errors_diagonal", [])
    ]
    false_positives = sum(bool(record.get("detected")) for record in negatives)
    return {
        "images": len(records),
        "positives": len(positives),
        "detected": len(detected),
        "detection_rate": len(detected) / len(positives) if positives else None,
        "negatives": len(negatives),
        "false_positives": false_positives,
        "false_positive_rate": false_positives / len(negatives) if negatives else None,
        "keypoint_error_px": {
            "mean": float(np.mean(pixel_errors)) if pixel_errors else None,
            "median": _percentile(pixel_errors, 50),
            "p95": _percentile(pixel_errors, 95),
        },
        "keypoint_error_board_diagonal": {
            "mean": float(np.mean(normalized_errors)) if normalized_errors else None,
            "median": _percentile(normalized_errors, 50),
            "p95": _percentile(normalized_errors, 95),
        },
    }


def _evaluate_items(locator, items: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in items:
        image_path = Path(str(item["image"]))
        label_path = Path(str(item["label"]))
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError(f"cannot read evaluation image: {image_path}")
        label = read_pose_label(label_path)
        observation = locator.locate(frame)
        record: dict[str, object] = {
            "image": str(image_path),
            "positive": label is not None,
            "detected": observation is not None,
            "background": item.get("background"),
            "color_cast": item.get("color_cast"),
        }
        if label is not None and observation is not None:
            height, width = frame.shape[:2]
            truth = label.keypoints[:, :2] * np.array([width, height], dtype=np.float64)
            visible = label.keypoints[:, 2] > 0
            predicted = np.asarray(observation.all_points_px, dtype=np.float64)
            usable = min(len(predicted), len(truth))
            valid = visible[:usable]
            errors = np.linalg.norm(predicted[:usable][valid] - truth[:usable][valid], axis=1)
            diagonal = max(float(np.linalg.norm(truth[2] - truth[0])), 1e-9)
            record.update(
                confidence=float(observation.confidence),
                errors_px=errors.tolist(),
                errors_diagonal=(errors / diagonal).tolist(),
            )
        records.append(record)
    return records


def evaluate_stress_set(
    *,
    model: Path,
    dataset: Path,
    split: str,
    manifest: list[dict[str, object]],
    input_size: int,
    confidence: float,
    keypoint_confidence: float,
    min_detection_rate: float,
    max_median_diagonal_error: float,
    max_p95_diagonal_error: float,
    max_detection_drop: float,
) -> dict[str, object]:
    from app.vision.yolo_pose import OpenCvYoloPoseLocator

    source_paths = sorted({str(item["source_image"]) for item in manifest})
    source_items = [
        {
            "image": path,
            "label": str(dataset / "labels" / split / f"{Path(path).stem}.txt"),
            "background": "real_source",
            "color_cast": "real_source",
        }
        for path in source_paths
    ]
    first_label = next(
        (
            label
            for item in source_items
            if (label := read_pose_label(Path(str(item["label"])))) is not None
        ),
        None,
    )
    if first_label is None:
        raise ValueError("evaluation requires at least one positive Pose label")
    locator = OpenCvYoloPoseLocator(
        model,
        input_size=input_size,
        confidence_threshold=confidence,
        keypoint_threshold=keypoint_confidence,
        keypoint_count=len(first_label.keypoints),
    )
    if not locator.available:
        raise ValueError(f"cannot load ONNX model: {model}")
    try:
        baseline_records = _evaluate_items(locator, source_items)
        synthetic_items = [
            {
                "image": item["generated_image"],
                "label": item["generated_label"],
                "background": item["background"],
                "color_cast": item["lighting"]["color_cast"],
            }
            for item in manifest
        ]
        synthetic_records = _evaluate_items(locator, synthetic_items)
    finally:
        locator.close()

    baseline = metric_summary(baseline_records)
    synthetic = metric_summary(synthetic_records)
    by_background = {
        name: metric_summary(
            [record for record in synthetic_records if record["background"] == name]
        )
        for name in sorted({str(record["background"]) for record in synthetic_records})
    }
    by_color_cast = {
        name: metric_summary(
            [record for record in synthetic_records if record["color_cast"] == name]
        )
        for name in sorted({str(record["color_cast"]) for record in synthetic_records})
    }
    baseline_rate = float(baseline["detection_rate"] or 0.0)
    synthetic_rate = float(synthetic["detection_rate"] or 0.0)
    median_error = synthetic["keypoint_error_board_diagonal"]["median"]
    p95_error = synthetic["keypoint_error_board_diagonal"]["p95"]
    checks = {
        "detection_rate": synthetic_rate >= min_detection_rate,
        "detection_drop": baseline_rate - synthetic_rate <= max_detection_drop,
        "median_diagonal_error": (
            median_error is not None and median_error <= max_median_diagonal_error
        ),
        "p95_diagonal_error": p95_error is not None and p95_error <= max_p95_diagonal_error,
    }
    return {
        "scope": "synthetic_robustness_only_not_real_acceptance",
        "model": str(model.resolve()),
        "dataset": str(dataset.resolve()),
        "split": split,
        "baseline": baseline,
        "synthetic": synthetic,
        "by_background": by_background,
        "by_color_cast": by_color_cast,
        "records": {
            "baseline": baseline_records,
            "synthetic": synthetic_records,
        },
        "gates": {
            "thresholds": {
                "min_detection_rate": min_detection_rate,
                "max_detection_drop": max_detection_drop,
                "max_median_diagonal_error": max_median_diagonal_error,
                "max_p95_diagonal_error": max_p95_diagonal_error,
            },
            "checks": checks,
            "passed": all(checks.values()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("datasets/board-pose-pi5"))
    parser.add_argument("--split", choices=("train", "val", "test"), default="val")
    parser.add_argument(
        "--model", type=Path, default=Path("models/board-pose-pi5-handheld-v2.onnx")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260828)
    parser.add_argument("--max-images", type=int, default=0)
    parser.add_argument(
        "--foreground-mode", choices=("auto", "mask", "clean-plate"), default="auto"
    )
    parser.add_argument("--mask-dir", type=Path, default=None)
    parser.add_argument("--clean-plate", type=Path, default=None)
    parser.add_argument("--background-dir", type=Path, default=None)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--input-size", type=int, default=960)
    parser.add_argument("--confidence", type=float, default=0.30)
    parser.add_argument("--keypoint-confidence", type=float, default=0.35)
    parser.add_argument("--min-detection-rate", type=float, default=0.90)
    parser.add_argument("--max-detection-drop", type=float, default=0.10)
    parser.add_argument("--max-median-diagonal-error", type=float, default=0.10)
    parser.add_argument("--max-p95-diagonal-error", type=float, default=0.25)
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    dataset = args.dataset.resolve()
    output = args.output.resolve()
    manifest = generate_stress_set(
        dataset=dataset,
        split=args.split,
        output=output,
        variants=args.variants,
        seed=args.seed,
        max_images=args.max_images,
        foreground_mode=args.foreground_mode,
        mask_dir=args.mask_dir.resolve() if args.mask_dir else None,
        clean_plate_path=args.clean_plate.resolve() if args.clean_plate else None,
        background_dir=args.background_dir.resolve() if args.background_dir else None,
    )
    print(f"generated {len(manifest)} synthetic images at {output}")
    if args.generate_only:
        return
    report = evaluate_stress_set(
        model=args.model.resolve(),
        dataset=dataset,
        split=args.split,
        manifest=manifest,
        input_size=args.input_size,
        confidence=args.confidence,
        keypoint_confidence=args.keypoint_confidence,
        min_detection_rate=args.min_detection_rate,
        max_median_diagonal_error=args.max_median_diagonal_error,
        max_p95_diagonal_error=args.max_p95_diagonal_error,
        max_detection_drop=args.max_detection_drop,
    )
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    console_report = {key: value for key, value in report.items() if key != "records"}
    print(json.dumps(console_report, ensure_ascii=False, indent=2))
    print(f"report: {report_path}")
    if not report["gates"]["passed"] and not args.no_fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
