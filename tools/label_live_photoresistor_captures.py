# -*- coding: utf-8 -*-
"""Label selected live-capture frames into the photoresistor YOLO Pose dataset."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from capture_yolo_photoresistor_pose import (  # noqa: E402
    Keypoint,
    _annotate,
    _next_index,
    _write_sample,
)


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
    selected_indices: list[int] = []
    seen: set[int] = set()
    for index in range(max_samples):
        chosen = int(round(index * last / (max_samples - 1)))
        if chosen not in seen:
            selected_indices.append(chosen)
            seen.add(chosen)
    candidate = 0
    while len(selected_indices) < max_samples and candidate < len(paths):
        if candidate not in seen:
            selected_indices.append(candidate)
            seen.add(candidate)
        candidate += 1
    return [paths[index] for index in sorted(selected_indices[:max_samples])]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", help="live-captures session or image directory")
    parser.add_argument("--out", default="datasets/photoresistor-pose")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--scenario", default="powered_led")
    parser.add_argument(
        "--reference",
        default="profiles/components/photoresistor-module/reference_overlay.jpg",
    )
    parser.add_argument("--max-samples", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    root = Path(args.out).resolve()
    images = _select_evenly(_images_in(source_dir), args.max_samples)
    if not images:
        raise SystemExit(f"no images found in {source_dir}")

    if args.dry_run:
        print(f"selected {len(images)} image(s) from {source_dir}")
        for path in images:
            print(path)
        return

    reference_path = Path(args.reference).resolve()
    reference = cv2.imread(str(reference_path)) if reference_path.is_file() else None
    if reference is None:
        raise SystemExit(
            f"reference overlay not found: {reference_path}; run profile calibration first"
        )

    image_dir = root / "images" / args.split
    image_dir.mkdir(parents=True, exist_ok=True)
    (root / "labels" / args.split).mkdir(parents=True, exist_ok=True)
    next_index = _next_index(image_dir)
    previous: list[Keypoint] | None = None
    saved = 0
    skipped = 0

    print(f"labeling {len(images)} image(s) into {root / 'images' / args.split}")
    print("Click corners in reference order: TL, TR, BR, BL.")
    print("Shortcuts: L reuse previous | U undo | R reset | ENTER save | N skip | ESC quit")
    try:
        for ordinal, image_path in enumerate(images, 1):
            frame = cv2.imread(str(image_path))
            if frame is None:
                print(f"skip unreadable image: {image_path}")
                skipped += 1
                continue
            print(f"[{ordinal}/{len(images)}] {image_path.name}")
            points = _annotate(frame.copy(), args.scenario, previous, reference)
            if points is None:
                skipped += 1
                print("skipped")
                continue
            _write_sample(
                root,
                args.split,
                next_index,
                frame,
                points,
                args.scenario,
                str(image_path),
            )
            previous = points
            saved += 1
            print(f"saved {args.split}/sensor_{next_index:06d} from {image_path.name}")
            next_index += 1
    except KeyboardInterrupt:
        print("labeling interrupted")
    finally:
        cv2.destroyAllWindows()
    print(f"complete: saved={saved}, skipped={skipped}")


if __name__ == "__main__":
    main()
