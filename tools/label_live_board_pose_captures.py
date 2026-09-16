# -*- coding: utf-8 -*-
"""Review sampled video frames into the Raspberry Pi board-pose dataset.

The current production ONNX model pre-fills the four semantic board corners.
Press ENTER when the proposal is correct, or R and click profile TL, TR, BR,
BL to correct it.  This keeps model guesses human-reviewed instead of silently
turning prediction errors into training labels.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.vision.yolo_pose import OpenCvYoloPoseLocator  # noqa: E402
from capture_yolo_board_pose import _annotate, _label, _next_index  # noqa: E402


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _images_in(source_dir: Path) -> list[Path]:
    image_dir = source_dir / "images" if (source_dir / "images").is_dir() else source_dir
    if not image_dir.is_dir():
        raise SystemExit(f"image directory not found: {image_dir}")
    return sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)


def _select_evenly(paths: list[Path], max_samples: int) -> list[Path]:
    if max_samples <= 0 or max_samples >= len(paths):
        return list(paths)
    if max_samples == 1:
        return [paths[len(paths) // 2]]
    last = len(paths) - 1
    selected: list[Path] = []
    used: set[int] = set()
    for ordinal in range(max_samples):
        index = int(round(ordinal * last / (max_samples - 1)))
        if index not in used:
            selected.append(paths[index])
            used.add(index)
    for index, path in enumerate(paths):
        if len(selected) >= max_samples:
            break
        if index not in used:
            selected.append(path)
    return sorted(selected[:max_samples])


def _proposal_geometry_ok(
    observation,
    frame_shape: tuple[int, ...],
    *,
    min_quad_box_ratio: float = 0.35,
) -> bool:
    """Reject confident keypoints that collapse onto an inner component."""
    points = np.asarray(observation.corners_px, dtype=np.float32)
    if points.shape != (4, 2) or not np.all(np.isfinite(points)):
        return False
    height, width = (int(frame_shape[0]), int(frame_shape[1]))
    if width <= 0 or height <= 0:
        return False
    x1, y1, x2, y2 = (float(value) for value in observation.box_xyxy)
    box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    quad_area = abs(float(cv2.contourArea(points)))
    if box_area <= 1.0 or quad_area / float(width * height) < 0.005:
        return False
    return quad_area / box_area >= max(0.0, float(min_quad_box_ratio))


def _append_manifest(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", help="capture session or directory containing sampled frames")
    parser.add_argument("--out", default="datasets/board-pose-pi5")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--model", default="models/board-pose-pi5.onnx")
    parser.add_argument(
        "--reference",
        default="profiles/boards/raspberry-pi-5/reference_captured.jpg",
    )
    parser.add_argument("--max-samples", type=int, default=60)
    parser.add_argument("--input-size", type=int, default=960)
    parser.add_argument("--confidence", type=float, default=0.35)
    parser.add_argument("--keypoint-confidence", type=float, default=0.25)
    parser.add_argument(
        "--min-proposal-quad-box-ratio",
        type=float,
        default=0.35,
        help="reject model keypoints collapsed inside their detection box",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    paths = _select_evenly(_images_in(source_dir), args.max_samples)
    if not paths:
        raise SystemExit(f"no images found in {source_dir}")
    if args.dry_run:
        print(f"selected {len(paths)} image(s) from {source_dir}")
        for path in paths:
            print(path)
        return

    root = Path(args.out).resolve()
    image_dir = root / "images" / args.split
    label_dir = root / "labels" / args.split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "capture-manifest.jsonl"
    next_index = _next_index(image_dir)

    locator = OpenCvYoloPoseLocator(
        Path(args.model).resolve(),
        input_size=args.input_size,
        confidence_threshold=args.confidence,
        keypoint_threshold=args.keypoint_confidence,
    )
    if not locator.available:
        print("warning: pose model unavailable; all four corners must be clicked manually")

    reference = cv2.imread(str(Path(args.reference).resolve()), cv2.IMREAD_COLOR)
    if reference is not None:
        ref_width = 640
        ref_height = max(1, int(round(reference.shape[0] * ref_width / reference.shape[1])))
        reference = cv2.resize(reference, (ref_width, ref_height), interpolation=cv2.INTER_AREA)
        cv2.namedWindow("Pi 5 canonical profile: TL -> TR -> BR -> BL", cv2.WINDOW_NORMAL)
        cv2.imshow("Pi 5 canonical profile: TL -> TR -> BR -> BL", reference)

    print(f"reviewing {len(paths)} sampled frame(s) into {image_dir}")
    print("ENTER accept proposal | R reset | U undo | S skip | ESC stop")
    saved = 0
    skipped = 0
    try:
        for ordinal, source_path in enumerate(paths, 1):
            frame = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
            if frame is None:
                print(f"[{ordinal}/{len(paths)}] unreadable, skipped: {source_path.name}")
                skipped += 1
                continue

            raw_observation = locator.locate(frame) if locator.available else None
            proposal_rejected = bool(
                raw_observation is not None
                and not _proposal_geometry_ok(
                    raw_observation,
                    frame.shape,
                    min_quad_box_ratio=args.min_proposal_quad_box_ratio,
                )
            )
            observation = None if proposal_rejected else raw_observation
            initial_points = None
            message = (
                "model proposal rejected by geometry: click profile TL, TR, BR, BL"
                if proposal_rejected
                else "manual: click profile TL, TR, BR, BL"
            )
            confidence = None
            if observation is not None:
                initial_points = [tuple(float(v) for v in point) for point in observation.corners_px]
                confidence = float(observation.confidence)
                message = f"model proposal {confidence:.0%}: ENTER accept or R reset"

            print(
                f"[{ordinal}/{len(paths)}] {source_path.name} "
                f"proposal={confidence if confidence is not None else '-'}"
            )
            points = _annotate(frame, initial_points=initial_points, initial_message=message)
            if points is None:
                skipped += 1
                print("skipped")
                continue

            stem = f"board_{next_index:06d}"
            image_path = image_dir / f"{stem}.jpg"
            label_path = label_dir / f"{stem}.txt"
            if not cv2.imwrite(str(image_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95]):
                raise IOError(f"failed to write {image_path}")
            label_path.write_text(
                _label(points, (frame.shape[1], frame.shape[0])), encoding="utf-8"
            )
            _append_manifest(
                manifest_path,
                {
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "source": str(source_path),
                    "split": args.split,
                    "image": str(image_path.relative_to(root)).replace("\\", "/"),
                    "label": str(label_path.relative_to(root)).replace("\\", "/"),
                    "video_size": [int(frame.shape[1]), int(frame.shape[0])],
                    "keypoint_order": ["profile_TL", "profile_TR", "profile_BR", "profile_BL"],
                    "prelabel_model": str(Path(args.model).resolve()) if observation is not None else None,
                    "prelabel_confidence": confidence,
                    "prelabel_geometry_rejected": proposal_rejected,
                    "human_reviewed": True,
                },
            )
            print(f"saved {args.split}/{stem}")
            next_index += 1
            saved += 1
    except KeyboardInterrupt:
        print("labeling interrupted")
    finally:
        locator.close()
        cv2.destroyAllWindows()
    print(f"complete: saved={saved}, skipped={skipped}")


if __name__ == "__main__":
    main()
