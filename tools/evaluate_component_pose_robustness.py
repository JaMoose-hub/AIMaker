# -*- coding: utf-8 -*-
"""Evaluate component Pose and profile-projected pins on a YOLO Pose split."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.component_worker import (  # noqa: E402
    ComponentVisionProfile,
    project_component_pins,
    refine_component_corners_from_pcb,
)
from app.vision.yolo_pose import OpenCvYoloPoseLocator  # noqa: E402
from pi5_robustness_test import IMAGE_SUFFIXES, read_pose_label  # noqa: E402


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "p95": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "mean": round(float(array.mean()), 6),
        "median": round(float(np.median(array)), 6),
        "p95": round(float(np.percentile(array, 95)), 6),
    }


def _kind(path: Path) -> str:
    if "__" in path.stem:
        return path.stem.rsplit("__", 1)[1]
    if path.stem.startswith("pi5_only_negative_"):
        return "pi5_only_negative"
    return "clean"


def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [record for record in records if record["positive"]]
    negatives = [record for record in records if not record["positive"]]
    detected = [record for record in positives if record["detected"]]
    return {
        "images": len(records),
        "positive_images": len(positives),
        "negative_images": len(negatives),
        "detected": len(detected),
        "detection_rate": round(len(detected) / len(positives), 6) if positives else None,
        "false_positives": sum(bool(record["detected"]) for record in negatives),
        "refinement_success_rate": round(
            sum(bool(record.get("refined")) for record in detected) / len(detected), 6
        ) if detected else None,
        "corner_error_px": _stats(
            [float(value) for record in detected for value in record["corner_errors_px"]]
        ),
        "pin_error_px": _stats(
            [float(value) for record in detected for value in record["pin_errors_px"]]
        ),
        "pin_error_pitch": _stats(
            [float(value) for record in detected for value in record["pin_errors_pitch"]]
        ),
        "confidence": _stats([float(record["confidence"]) for record in detected]),
    }


def evaluate(
    *,
    model: Path,
    dataset: Path,
    split: str,
    profile_path: Path,
    input_size: int,
    confidence: float,
    keypoint_confidence: float,
) -> dict[str, Any]:
    model = model.resolve()
    dataset = dataset.resolve()
    profile = ComponentVisionProfile.load(profile_path.resolve())
    locator = OpenCvYoloPoseLocator(
        model,
        input_size=input_size,
        confidence_threshold=confidence,
        keypoint_threshold=keypoint_confidence,
        keypoint_count=profile.keypoint_count,
    )
    if not locator.available:
        raise ValueError(f"cannot load component Pose model: {model}")
    image_dir = dataset / "images" / split
    label_dir = dataset / "labels" / split
    records: list[dict[str, Any]] = []
    try:
        for image_path in sorted(
            path for path in image_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ):
            label_path = label_dir / f"{image_path.stem}.txt"
            label = read_pose_label(label_path)
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError(f"cannot read image: {image_path}")
            observation = locator.locate(frame)
            record: dict[str, Any] = {
                "image": image_path.name,
                "kind": _kind(image_path),
                "positive": label is not None,
                "detected": observation is not None,
            }
            if label is not None and observation is not None:
                height, width = frame.shape[:2]
                truth = label.keypoints[:4, :2] * np.array([width, height])
                refined = refine_component_corners_from_pcb(frame, observation)
                used = refined or observation
                expected_pins = project_component_pins(
                    profile, truth, 1.0, (width, height)
                )
                predicted_pins = project_component_pins(
                    profile, used.corners_px, used.confidence, (width, height)
                )
                expected = np.asarray(
                    [(pin.x, pin.y) for pin in expected_pins], dtype=np.float64
                )
                predicted = np.asarray(
                    [(pin.x, pin.y) for pin in predicted_pins], dtype=np.float64
                )
                pitch = float(
                    np.median(np.linalg.norm(expected[1:] - expected[:-1], axis=1))
                )
                corner_errors = np.linalg.norm(used.corners_px - truth, axis=1)
                pin_errors = np.linalg.norm(predicted - expected, axis=1)
                record.update(
                    confidence=float(observation.confidence),
                    refined=refined is not None,
                    corner_errors_px=corner_errors.tolist(),
                    pin_errors_px=pin_errors.tolist(),
                    pin_errors_pitch=(pin_errors / max(pitch, 1e-6)).tolist(),
                )
            records.append(record)
    finally:
        locator.close()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["kind"])].append(record)
    return {
        "model": str(model),
        "dataset": str(dataset),
        "split": split,
        "profile": str(profile_path.resolve()),
        "overall": _summarize(records),
        "by_kind": {name: _summarize(items) for name, items in sorted(grouped.items())},
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument(
        "--profile", type=Path,
        default=Path("profiles/components/hc-sr04/vision_profile.json"),
    )
    parser.add_argument("--input-size", type=int, default=768)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--keypoint-confidence", type=float, default=0.20)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()
    report = evaluate(
        model=args.model,
        dataset=args.dataset,
        split=args.split,
        profile_path=args.profile,
        input_size=args.input_size,
        confidence=args.confidence,
        keypoint_confidence=args.keypoint_confidence,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
