# -*- coding: utf-8 -*-
"""Evaluate the production OpenCV-DNN board-pose runtime on a YOLO split."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.yolo_pose import OpenCvYoloPoseLocator  # noqa: E402


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="models/board-pose.onnx")
    parser.add_argument("--dataset", default="datasets/board-pose")
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument("--input-size", type=int, default=960)
    parser.add_argument("--confidence", type=float, default=0.45)
    parser.add_argument("--keypoint-confidence", type=float, default=0.35)
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    dataset = Path(args.dataset).resolve()
    image_dir = dataset / "images" / args.split
    label_dir = dataset / "labels" / args.split
    locator = OpenCvYoloPoseLocator(
        Path(args.model).resolve(),
        input_size=args.input_size,
        confidence_threshold=args.confidence,
        keypoint_threshold=args.keypoint_confidence,
    )
    if not locator.available:
        raise SystemExit(f"cannot load ONNX model: {Path(args.model).resolve()}")

    corner_errors: list[float] = []
    normalized_errors: list[float] = []
    records: list[dict[str, object]] = []
    images = sorted(image_dir.glob("*.jpg"))
    for image_path in images:
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise SystemExit(f"cannot read image: {image_path}")
        label_path = label_dir / f"{image_path.stem}.txt"
        values = np.loadtxt(label_path, dtype=np.float64, ndmin=2)[0]
        if values.size != 17:
            raise SystemExit(f"expected one 4-keypoint label in {label_path}")
        height, width = frame.shape[:2]
        truth = values[5:].reshape(4, 3)[:, :2] * np.array([width, height])
        diagonal = float(np.linalg.norm(truth[2] - truth[0]))
        observation = locator.locate(frame)
        record: dict[str, object] = {"image": image_path.name, "detected": False}
        if observation is not None:
            errors = np.linalg.norm(observation.corners_px - truth, axis=1)
            normalized = errors / max(diagonal, 1e-9)
            corner_errors.extend(float(value) for value in errors)
            normalized_errors.extend(float(value) for value in normalized)
            record.update(
                detected=True,
                confidence=observation.confidence,
                keypoint_confidences=observation.keypoint_confidences.tolist(),
                corner_errors_px=errors.tolist(),
                mean_corner_error_px=float(errors.mean()),
                mean_corner_error_board_diagonal=float(normalized.mean()),
            )
        records.append(record)
    locator.close()

    detected = sum(bool(record["detected"]) for record in records)
    summary = {
        "model": str(Path(args.model).resolve()),
        "split": args.split,
        "images": len(records),
        "detected": detected,
        "detection_rate": detected / len(records) if records else 0.0,
        "corner_error_px": {
            "mean": float(np.mean(corner_errors)) if corner_errors else None,
            "median": _percentile(corner_errors, 50),
            "p95": _percentile(corner_errors, 95),
        },
        "corner_error_board_diagonal": {
            "mean": float(np.mean(normalized_errors)) if normalized_errors else None,
            "median": _percentile(normalized_errors, 50),
            "p95": _percentile(normalized_errors, 95),
        },
        "records": records,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        output_path = Path(args.output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
