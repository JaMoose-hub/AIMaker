# -*- coding: utf-8 -*-
"""Capture and annotate one-board YOLO Pose images from a webcam/MJPEG feed.

Each saved image contains one board and one YOLO Pose label with four semantic
profile corners.  The click order is always board-profile TL, TR, BR, BL --
not the screen's current top-left order when the board is rotated.

Keys in live preview: C/SPACE = freeze and annotate, ESC = quit.
Keys while annotating: left click = point, U = undo, R = reset,
ENTER = save after four points, S = skip frame, ESC = quit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import cv2
import numpy as np


POINT_NAMES = ("profile_TL", "profile_TR", "profile_BR", "profile_BL")


def _source(value: str):
    return int(value) if value.isdecimal() else value


def _quad_ok(points: list[tuple[float, float]], size: tuple[int, int]) -> bool:
    if len(points) != 4:
        return False
    pts = np.asarray(points, dtype=np.float64)
    edges = np.roll(pts, -1, axis=0) - pts
    cross = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] \
        - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
    if not (np.all(cross > 0.0) or np.all(cross < 0.0)):
        return False
    area = 0.5 * abs(
        float(np.dot(pts[:, 0], np.roll(pts[:, 1], -1))
              - np.dot(pts[:, 1], np.roll(pts[:, 0], -1)))
    )
    return area >= 0.01 * float(size[0] * size[1])


def _label(points: list[tuple[float, float]], size: tuple[int, int]) -> str:
    width, height = (float(v) for v in size)
    pts = np.asarray(points, dtype=np.float64)
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    values = [
        0.0,
        ((x1 + x2) / 2.0) / width,
        ((y1 + y2) / 2.0) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    ]
    for x, y in pts:
        values.extend([x / width, y / height, 2.0])
    return "0 " + " ".join(f"{value:.8f}" for value in values[1:]) + "\n"


def _next_index(image_dir: Path) -> int:
    indices = []
    for path in image_dir.glob("board_*.jpg"):
        try:
            indices.append(int(path.stem.split("_")[-1]))
        except ValueError:
            continue
    return max(indices, default=0) + 1


def _annotate(
    frame: np.ndarray,
    initial_points: list[tuple[float, float]] | None = None,
    initial_message: str | None = None,
) -> list[tuple[float, float]] | None:
    window = "YOLO board pose: profile TL -> TR -> BR -> BL"
    clicks: list[tuple[float, float]] = []
    if initial_points is not None:
        candidate = [(float(x), float(y)) for x, y in initial_points]
        if _quad_ok(candidate, (frame.shape[1], frame.shape[0])):
            clicks.extend(candidate)
    status_message = initial_message

    def redraw(message: str | None = None) -> None:
        view = frame.copy()
        if len(clicks) >= 2:
            cv2.polylines(
                view, [np.asarray(clicks, dtype=np.int32)],
                len(clicks) == 4, (70, 220, 70), 2, cv2.LINE_AA,
            )
        for index, (x, y) in enumerate(clicks):
            point = (int(round(x)), int(round(y)))
            cv2.drawMarker(view, point, (0, 160, 255), cv2.MARKER_CROSS, 28, 2)
            cv2.putText(
                view, f"{index + 1}:{POINT_NAMES[index]}",
                (point[0] + 10, point[1] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (0, 160, 255), 2, cv2.LINE_AA,
            )
        next_name = POINT_NAMES[len(clicks)] if len(clicks) < 4 else "ENTER to save"
        cv2.putText(
            view, f"next: {next_name} | U undo | R reset | S skip | ESC quit",
            (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.72,
            (50, 240, 80), 2, cv2.LINE_AA,
        )
        visible_message = message or initial_message
        if visible_message:
            cv2.putText(
                view, visible_message, (18, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.72,
                (40, 40, 255), 2, cv2.LINE_AA,
            )
        cv2.imshow(window, view)

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((float(x), float(y)))
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
        if key in (ord("u"), ord("U")) and clicks:
            clicks.pop()
            status_message = None
            redraw()
        if key in (ord("r"), ord("R")):
            clicks.clear()
            status_message = None
            redraw()
        if key in (10, 13) and len(clicks) == 4:
            if _quad_ok(clicks, (frame.shape[1], frame.shape[0])):
                cv2.destroyWindow(window)
                return clicks
            redraw("invalid/non-convex or too-small quad; reset and click again")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="datasets/board-pose", help="YOLO dataset root")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument(
        "--source", default="http://127.0.0.1:8100/video",
        help="MJPEG URL or OpenCV camera index (default: live Board Vision /video)",
    )
    args = parser.parse_args()

    root = Path(args.out).resolve()
    image_dir = root / "images" / args.split
    label_dir = root / "labels" / args.split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    manifest = root / "capture-manifest.jsonl"
    next_index = _next_index(image_dir)

    cap = cv2.VideoCapture(_source(args.source))
    if not cap.isOpened():
        raise SystemExit(f"cannot open capture source: {args.source}")
    window = "YOLO board pose capture: C/SPACE capture, ESC quit"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    print("Canonical click order: profile TL -> TR -> BR -> BL (USB-C-left board frame).")
    print(f"Writing {args.split} samples under {root}")
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                key = cv2.waitKey(30) & 0xFF
                if key == 27:
                    break
                continue
            preview = frame.copy()
            cv2.putText(
                preview, "C/SPACE: annotate | ESC: quit", (18, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (50, 240, 80), 2, cv2.LINE_AA,
            )
            cv2.imshow(window, preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key not in (ord("c"), ord("C"), 32):
                continue
            points = _annotate(frame)
            if points is None:
                continue
            stem = f"board_{next_index:06d}"
            image_path = image_dir / f"{stem}.jpg"
            label_path = label_dir / f"{stem}.txt"
            if not cv2.imwrite(str(image_path), frame):
                raise IOError(f"failed to write {image_path}")
            label_path.write_text(
                _label(points, (frame.shape[1], frame.shape[0])), encoding="utf-8"
            )
            record = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source": args.source,
                "split": args.split,
                "image": str(image_path.relative_to(root)).replace("\\", "/"),
                "label": str(label_path.relative_to(root)).replace("\\", "/"),
                "video_size": [frame.shape[1], frame.shape[0]],
                "keypoint_order": list(POINT_NAMES),
                "corners_px": [[round(x, 3), round(y, 3)] for x, y in points],
            }
            with manifest.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"saved {args.split}/{stem}")
            next_index += 1
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
