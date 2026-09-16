from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pose_labeling import (  # noqa: E402
    PoseAnnotation,
    PoseKeypoint,
    PoseLabelDataset,
    box_from_keypoints,
)
from pose_registration import ReviewedPoseRegistrar  # noqa: E402


def _dataset(tmp_path: Path) -> tuple[PoseLabelDataset, Path, Path]:
    root = tmp_path / "pose-data"
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    data = tmp_path / "pose.yaml"
    data.write_text(
        yaml.safe_dump(
            {
                "path": str(root),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "kpt_shape": [8, 3],
                "names": {0: "sensor"},
                "kpt_names": {
                    0: [
                        "pcb_TL",
                        "pcb_TR",
                        "pcb_BR",
                        "pcb_BL",
                        "pin_VCC",
                        "pin_TRIG",
                        "pin_ECHO",
                        "pin_GND",
                    ]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return (
        PoseLabelDataset(data),
        root / "images" / "train" / "source.png",
        root / "images" / "train" / "target.png",
    )


def _textured_sensor() -> tuple[np.ndarray, np.ndarray]:
    image = np.full((480, 640, 3), 145, dtype=np.uint8)
    cv2.rectangle(image, (180, 150), (460, 280), (170, 75, 25), -1)
    cv2.rectangle(image, (180, 150), (460, 280), (230, 210, 180), 3)
    cv2.circle(image, (250, 210), 45, (220, 220, 220), -1)
    cv2.circle(image, (390, 210), 45, (210, 210, 210), -1)
    cv2.circle(image, (250, 210), 27, (30, 30, 30), 3)
    cv2.circle(image, (390, 210), 27, (30, 30, 30), 3)
    cv2.putText(
        image,
        "HC-SR04",
        (278, 180),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )
    rng = np.random.default_rng(42)
    for x, y in rng.integers((190, 158), (450, 272), size=(90, 2)):
        cv2.circle(image, (int(x), int(y)), 1, (20, 20, 20), -1)
    points = np.asarray(
        [
            (180, 150),
            (460, 150),
            (460, 280),
            (180, 280),
            (292, 279),
            (310, 279),
            (328, 279),
            (346, 279),
        ],
        dtype=np.float32,
    )
    return image, points


def test_reviewed_homography_prelabels_only_as_pending(tmp_path: Path):
    dataset, source_path, target_path = _dataset(tmp_path)
    source, source_points = _textured_sensor()
    source_path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(source_path), source)

    rotation = cv2.getRotationMatrix2D((320, 215), 11.0, 0.94)
    rotation[:, 2] += (35.0, 28.0)
    homography = np.vstack((rotation, (0.0, 0.0, 1.0))).astype(np.float32)
    target = cv2.warpPerspective(
        source,
        homography,
        (640, 480),
        flags=cv2.INTER_LINEAR,
        borderValue=(145, 145, 145),
    )
    assert cv2.imwrite(str(target_path), target)

    points = [
        PoseKeypoint(float(x / 640), float(y / 480), 2)
        for x, y in source_points
    ]
    annotation = PoseAnnotation(0, box_from_keypoints(points), points)
    dataset.save(source_path, "train", [annotation], status="reviewed")

    registrar = ReviewedPoseRegistrar(dataset)
    dry_run = registrar.prelabel_unlabelled(target_splits=("train",), apply=False)
    assert dry_run.saved == 1
    assert not dataset.label_path(target_path, "train").exists()

    applied = registrar.prelabel_unlabelled(target_splits=("train",), apply=True)
    assert applied.saved == 1
    assert dataset.review.status(dataset.key(target_path, "train")) == "auto_pending"
    projected = cv2.perspectiveTransform(
        source_points.reshape(-1, 1, 2), homography
    ).reshape(-1, 2)
    loaded = dataset.load(target_path, "train")[0]
    predicted = np.asarray(
        [(point.x * 640, point.y * 480) for point in loaded.keypoints],
        dtype=np.float32,
    )
    assert np.median(np.linalg.norm(predicted - projected, axis=1)) < 2.0
    record = dataset.review.records[dataset.key(target_path, "train")]
    assert record["method"] == "reviewed_homography"
    assert record["registration_inliers"] >= 8


def test_registration_rejects_image_without_sensor_features(tmp_path: Path):
    dataset, source_path, target_path = _dataset(tmp_path)
    source, source_points = _textured_sensor()
    assert cv2.imwrite(str(source_path), source)
    assert cv2.imwrite(str(target_path), np.full_like(source, 145))
    points = [
        PoseKeypoint(float(x / 640), float(y / 480), 2)
        for x, y in source_points
    ]
    dataset.save(
        source_path,
        "train",
        [PoseAnnotation(0, box_from_keypoints(points), points)],
        status="reviewed",
    )

    summary = ReviewedPoseRegistrar(dataset).prelabel_unlabelled(
        target_splits=("train",), apply=True
    )

    assert summary.no_registration == 1
    assert not dataset.label_path(target_path, "train").exists()

