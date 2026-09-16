# -*- coding: utf-8 -*-
"""Evaluate Pi 5 8-point ONNX by projected 40-pin error, not only pose mAP."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.profiles.store import ProfileStore  # noqa: E402
from app.vision.camera_model import load_camera, project_board  # noqa: E402
from app.vision.wire_tracer import projected_pin_pitch  # noqa: E402
from app.vision.yolo_pose import OpenCvYoloPoseLocator  # noqa: E402
from app.vision.yolo_profile_detector import solve_landmark_pose  # noqa: E402


def _solve(profile, camera, points: np.ndarray, visibility: np.ndarray, threshold: float):
    observation = SimpleNamespace(
        landmarks_px=np.asarray(points, dtype=np.float64),
        keypoint_confidences=np.asarray(visibility, dtype=np.float64),
    )
    return solve_landmark_pose(
        profile,
        observation,
        camera,
        keypoint_threshold=threshold,
        ransac_reprojection_error_px=5.0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("models/board-pose-pi5-8kpt.onnx"))
    parser.add_argument("--dataset", type=Path, default=Path("datasets/board-pose-pi5-8kpt"))
    parser.add_argument("--split", choices=("train", "val", "test"), default="test")
    parser.add_argument("--profiles", type=Path, default=Path("profiles"))
    parser.add_argument("--camera", type=Path, default=Path("calibration/c920-1080p.json"))
    parser.add_argument("--input-size", type=int, default=960)
    parser.add_argument("--confidence", type=float, default=0.30)
    parser.add_argument("--keypoint-confidence", type=float, default=0.35)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    profile = ProfileStore(args.profiles.resolve()).profile("raspberry-pi-5")
    dataset = args.dataset.resolve()
    image_dir = dataset / "images" / args.split
    label_dir = dataset / "labels" / args.split
    locator = OpenCvYoloPoseLocator(
        args.model.resolve(),
        input_size=args.input_size,
        confidence_threshold=args.confidence,
        keypoint_threshold=args.keypoint_confidence,
        keypoint_count=8,
    )
    if not locator.available:
        raise SystemExit(f"cannot load 8-point ONNX: {args.model.resolve()}")

    records: list[dict[str, object]] = []
    all_errors_pitch: list[float] = []
    images = sorted(image_dir.glob("*.jpg"))
    try:
        for image_path in images:
            label_path = label_dir / f"{image_path.stem}.txt"
            text = label_path.read_text(encoding="utf-8").strip() if label_path.is_file() else ""
            if not text:  # negative sample: detection must remain absent
                frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                detected = locator.locate(frame) is not None if frame is not None else False
                records.append({"image": image_path.name, "negative": True, "false_positive": detected})
                continue
            values = np.asarray([float(value) for value in text.split()], dtype=np.float64)
            if values.size != 29:
                raise SystemExit(f"expected one 8-keypoint label in {label_path}")
            frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise SystemExit(f"cannot read image: {image_path}")
            height, width = frame.shape[:2]
            camera = load_camera((width, height), args.camera.resolve())
            if not camera.calibrated:
                raise SystemExit(f"camera calibration is missing/rejected: {args.camera.resolve()}")
            truth_raw = values[5:].reshape(8, 3)
            truth_points = truth_raw[:, :2] * np.array([width, height], dtype=np.float64)
            truth_pose = _solve(profile, camera, truth_points, truth_raw[:, 2], 1.0)
            observation = locator.locate(frame)
            record: dict[str, object] = {"image": image_path.name, "detected": observation is not None}
            if truth_pose is None:
                record["truth_pose_valid"] = False
                records.append(record)
                continue
            if observation is None:
                records.append(record)
                continue
            predicted_pose = _solve(
                profile,
                camera,
                observation.all_points_px,
                observation.keypoint_confidences,
                args.keypoint_confidence,
            )
            if predicted_pose is None:
                record["pose_valid"] = False
                records.append(record)
                continue
            truth_pins, _ = project_board(profile, camera, truth_pose[0], truth_pose[1])
            predicted_pins, _ = project_board(profile, camera, predicted_pose[0], predicted_pose[1])
            pitch = projected_pin_pitch(truth_pins)
            errors_px = np.linalg.norm(
                np.asarray([(pin.x, pin.y) for pin in predicted_pins])
                - np.asarray([(pin.x, pin.y) for pin in truth_pins]),
                axis=1,
            )
            errors_pitch = errors_px / max(pitch, 1e-9)
            median_pitch = float(np.median(errors_pitch))
            p95_pitch = float(np.percentile(errors_pitch, 95))
            passed = bool(pitch >= 8.0 and median_pitch <= 0.25 and p95_pitch <= 0.5)
            all_errors_pitch.extend(float(value) for value in errors_pitch)
            record.update(
                pose_valid=True,
                pitch_px=float(pitch),
                median_pin_error_px=float(np.median(errors_px)),
                p95_pin_error_px=float(np.percentile(errors_px, 95)),
                median_pin_error_pitch=median_pitch,
                p95_pin_error_pitch=p95_pitch,
                passed=passed,
            )
            records.append(record)
    finally:
        locator.close()

    positive = [record for record in records if not record.get("negative")]
    passed = sum(bool(record.get("passed")) for record in positive)
    negatives = [record for record in records if record.get("negative")]
    summary = {
        "model": str(args.model.resolve()),
        "split": args.split,
        "positive_images": len(positive),
        "passing_images": passed,
        "frame_pass_rate": passed / len(positive) if positive else 0.0,
        "acceptance_frame_pass_rate": 0.95,
        "all_pin_error_pitch": {
            "median": float(np.median(all_errors_pitch)) if all_errors_pitch else None,
            "p95": float(np.percentile(all_errors_pitch, 95)) if all_errors_pitch else None,
        },
        "negative_images": len(negatives),
        "negative_false_positives": sum(bool(item.get("false_positive")) for item in negatives),
        "accepted": bool(positive and passed / len(positive) >= 0.95),
        "records": records,
    }
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
