# -*- coding: utf-8 -*-
"""Human-review migration from the preserved Pi 5 4-point set to 8 points.

The four board corners are loaded from each old label and locked. Reviewers
only add J8_P1, J8_P2, J8_P40, J8_P39. U undoes the previous supplemental
point, V marks the current point occluded (visibility=0), S skips the frame,
and R clears only the four new points. Output is always a separate dataset.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

import cv2
import numpy as np


OLD_NAMES = ("board_TL", "board_TR", "board_BR", "board_BL")
NEW_NAMES = ("J8_P1", "J8_P2", "J8_P40", "J8_P39")
ALL_NAMES = OLD_NAMES + NEW_NAMES
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _read_old_label(path: Path) -> tuple[list[float], list[tuple[float, float, float]]] | None:
    if not path.is_file() or not path.read_text(encoding="utf-8").strip():
        return None
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != 1:
        raise ValueError(f"expected exactly one board row in {path}")
    values = [float(value) for value in rows[0].split()]
    if len(values) != 17:
        raise ValueError(f"expected a 4-keypoint label (17 values) in {path}")
    return values[:5], [tuple(point) for point in np.asarray(values[5:]).reshape(4, 3)]


def _write_label(
    path: Path,
    box: list[float],
    keypoints: list[tuple[float, float, float]],
) -> None:
    values = box + [value for point in keypoints for value in point]
    path.write_text(" ".join(f"{value:.8f}" for value in values) + "\n", encoding="utf-8")


def _annotate(
    frame: np.ndarray,
    old_keypoints: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]] | None:
    window = "Pi 5 8-point upgrade: add J8 P1, P2, P40, P39"
    height, width = frame.shape[:2]
    added: list[tuple[float, float, float]] = []

    def redraw(message: str = "") -> None:
        view = frame.copy()
        for index, (x_norm, y_norm, visibility) in enumerate(old_keypoints):
            if visibility <= 0:
                continue
            point = (int(round(x_norm * width)), int(round(y_norm * height)))
            cv2.drawMarker(view, point, (0, 185, 255), cv2.MARKER_CROSS, 24, 2)
            cv2.putText(view, f"{index + 1}:{OLD_NAMES[index]}", (point[0] + 8, point[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 185, 255), 2)
        for offset, (x_norm, y_norm, visibility) in enumerate(added):
            label = NEW_NAMES[offset]
            if visibility > 0:
                point = (int(round(x_norm * width)), int(round(y_norm * height)))
                cv2.drawMarker(view, point, (255, 220, 40), cv2.MARKER_TILTED_CROSS, 26, 2)
                origin = (point[0] + 8, point[1] - 8)
            else:
                origin = (18, 92 + offset * 24)
            cv2.putText(view, f"{offset + 5}:{label}{' hidden' if visibility <= 0 else ''}", origin, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 220, 40), 2)
        next_name = NEW_NAMES[len(added)] if len(added) < len(NEW_NAMES) else "ENTER to save"
        cv2.putText(view, f"next: {next_name} | U undo | V hidden | R reset | S skip", (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (70, 240, 90), 2)
        if message:
            cv2.putText(view, message, (18, 66), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (40, 40, 255), 2)
        cv2.imshow(window, view)

    def on_mouse(event, x, y, _flags, _param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(added) < len(NEW_NAMES):
            added.append((x / float(width), y / float(height), 2.0))
            redraw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    while True:
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            cv2.destroyWindow(window)
            raise KeyboardInterrupt
        if key in (ord("s"), ord("S")):
            cv2.destroyWindow(window)
            return None
        if key in (ord("u"), ord("U")) and added:
            added.pop()
            redraw()
        elif key in (ord("r"), ord("R")):
            added.clear()
            redraw()
        elif key in (ord("v"), ord("V")) and len(added) < len(NEW_NAMES):
            added.append((0.0, 0.0, 0.0))
            redraw()
        elif key in (10, 13) and len(added) == len(NEW_NAMES):
            cv2.destroyWindow(window)
            return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("datasets/board-pose-pi5"))
    parser.add_argument("--out", type=Path, default=Path("datasets/board-pose-pi5-8kpt"))
    parser.add_argument("--splits", nargs="+", choices=("train", "val", "test"), default=("train", "val", "test"))
    parser.add_argument("--session-id", required=True, help="video/time-session id used to audit split leakage")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    output = args.out.resolve()
    if source == output:
        raise SystemExit("--out must differ from --source; the four-point dataset is preserved")
    manifest_path = output / "migration-manifest.jsonl"
    saved = skipped = negatives = 0
    try:
        for split in args.splits:
            source_images = source / "images" / split
            source_labels = source / "labels" / split
            if not source_images.is_dir():
                continue
            target_images = output / "images" / split
            target_labels = output / "labels" / split
            target_images.mkdir(parents=True, exist_ok=True)
            target_labels.mkdir(parents=True, exist_ok=True)
            images = sorted(path for path in source_images.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
            for ordinal, image_path in enumerate(images, 1):
                target_image = target_images / image_path.name
                target_label = target_labels / f"{image_path.stem}.txt"
                if args.resume and target_label.exists() and target_image.exists():
                    continue
                frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                if frame is None:
                    print(f"skip unreadable {image_path}")
                    skipped += 1
                    continue
                old = _read_old_label(source_labels / f"{image_path.stem}.txt")
                if old is None:
                    shutil.copy2(image_path, target_image)
                    target_label.write_text("", encoding="utf-8")
                    negatives += 1
                    continue
                box, old_keypoints = old
                print(f"[{split} {ordinal}/{len(images)}] {image_path.name}")
                added = _annotate(frame, old_keypoints)
                if added is None:
                    skipped += 1
                    continue
                shutil.copy2(image_path, target_image)
                _write_label(target_label, box, old_keypoints + added)
                output.mkdir(parents=True, exist_ok=True)
                with manifest_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "migrated_at": datetime.now(timezone.utc).isoformat(),
                        "session_id": args.session_id,
                        "split": split,
                        "source_image": str(image_path),
                        "image": str(target_image.relative_to(output)).replace("\\", "/"),
                        "label": str(target_label.relative_to(output)).replace("\\", "/"),
                        "keypoint_order": list(ALL_NAMES),
                        "visible": [int(point[2] > 0) for point in old_keypoints + added],
                        "human_reviewed": True,
                    }, ensure_ascii=False) + "\n")
                saved += 1
    except KeyboardInterrupt:
        print("migration interrupted; rerun with --resume")
    finally:
        cv2.destroyAllWindows()
    print(f"complete: saved={saved}, negatives={negatives}, skipped={skipped}, out={output}")


if __name__ == "__main__":
    main()
