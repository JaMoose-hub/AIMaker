from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from build_hc_sr04_robust_training_set import (  # noqa: E402
    add_perspective_occlusion,
    build_dataset,
    place_pi5_distractor,
)
from pi5_robustness_test import PoseLabel  # noqa: E402


def _label(points: list[tuple[float, float]], *, box=(0.5, 0.5, 0.4, 0.4)) -> PoseLabel:
    keypoints = np.asarray([[x, y, 2.0] for x, y in points], dtype=np.float64)
    values = ["0", *(f"{value:.6f}" for value in box)]
    values.extend(f"{value:.6f}" for value in keypoints.reshape(-1))
    return PoseLabel(
        raw=" ".join(values) + "\n",
        class_id=0,
        box=np.asarray(box, dtype=np.float64),
        keypoints=keypoints,
    )


def _write_item(root: Path, split: str, name: str, image: np.ndarray, label: PoseLabel) -> None:
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(image_dir / f"{name}.jpg"), image)
    (label_dir / f"{name}.txt").write_text(label.raw, encoding="utf-8")


def _sensor_fixture() -> tuple[np.ndarray, PoseLabel]:
    image = np.full((360, 640, 3), 185, dtype=np.uint8)
    points = [(0.38, 0.35), (0.62, 0.35), (0.62, 0.65), (0.38, 0.65)]
    pixel = np.rint(np.asarray(points) * np.array([640, 360])).astype(np.int32)
    cv2.fillConvexPoly(image, pixel, (150, 75, 25))
    cv2.circle(image, (285, 180), 42, (190, 190, 190), -1)
    cv2.circle(image, (355, 180), 42, (190, 190, 190), -1)
    return image, _label(points)


def _pi5_fixture() -> tuple[np.ndarray, PoseLabel]:
    image = np.full((360, 640, 3), 215, dtype=np.uint8)
    points = [
        (0.18, 0.20), (0.82, 0.20), (0.82, 0.80), (0.18, 0.80),
        (0.70, 0.24), (0.74, 0.24), (0.74, 0.76), (0.70, 0.76),
    ]
    pixel = np.rint(np.asarray(points[:4]) * np.array([640, 360])).astype(np.int32)
    cv2.fillConvexPoly(image, pixel, (45, 145, 55))
    return image, _label(points, box=(0.5, 0.5, 0.68, 0.64))


def test_pi5_distractor_is_kept_outside_sensor_pose() -> None:
    sensor, sensor_label = _sensor_fixture()
    pi5, pi5_label = _pi5_fixture()

    result, report = place_pi5_distractor(
        sensor, sensor_label, pi5, pi5_label, np.random.default_rng(7)
    )

    assert result.shape == sensor.shape
    assert report["sensor_overlap_fraction"] <= 0.005
    assert report["foreground_fraction"] > 0.01
    assert np.mean(np.abs(result.astype(float) - sensor.astype(float))) > 1.0


def test_perspective_occlusion_marks_covered_corner_as_inferred() -> None:
    sensor, sensor_label = _sensor_fixture()

    result, updated, report = add_perspective_occlusion(
        sensor, sensor_label, np.random.default_rng(11), kind="hand_wire"
    )

    assert result.shape == sensor.shape
    assert report["occlusion_fraction"] > 0.02
    assert report["covered_keypoints"]
    assert np.count_nonzero(updated.keypoints[:, 2] == 1) >= 1
    assert np.allclose(updated.keypoints[:, :2], sensor_label.keypoints[:, :2])


def test_robust_dataset_keeps_clean_val_and_builds_stress_test(tmp_path: Path) -> None:
    source = tmp_path / "hc"
    pi5_source = tmp_path / "pi5"
    sensor, sensor_label = _sensor_fixture()
    pi5, pi5_label = _pi5_fixture()
    _write_item(source, "train", "sensor-train", sensor, sensor_label)
    _write_item(source, "val", "sensor-val", sensor, sensor_label)
    _write_item(pi5_source, "train", "pi5-train", pi5, pi5_label)
    _write_item(pi5_source, "val", "pi5-val", pi5, pi5_label)

    output = tmp_path / "robust"
    report = build_dataset(
        source=source,
        pi5_source=pi5_source,
        output=output,
        seed=19,
        pi5_negatives=1,
        preview_count=2,
    )

    assert report["final_counts"] == {"train": 6, "val": 1, "test": 4}
    assert (output / "images" / "val" / "sensor-val.jpg").read_bytes() == (
        source / "images" / "val" / "sensor-val.jpg"
    ).read_bytes()
    assert (output / "labels" / "train" / "pi5_only_negative_001.txt").read_text() == ""
    assert report["generated_counts"]["pi5_coexist"] == 2
    assert report["generated_counts"]["hand_occlusion"] == 2
