# -*- coding: utf-8 -*-
"""Capture four-corner YOLO Pose data for a photoresistor module.

The four semantic corners follow the calibrated component reference, not the
current screen orientation.  Left-click records a visible corner (v=2), while
right-click records an estimated hand-occluded corner (v=1).

Live keys: 1 clear, 2 partial cover, 3 heavy cover, 0 negative, ESC quit.
Annotation: left/right click, L reuse previous corners, 1-4 toggle visibility,
U undo, R reset, ENTER save, N skip, ESC quit.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Final

import cv2
import numpy as np


POINT_NAMES: Final[tuple[str, ...]] = ("sensor_TL", "sensor_TR", "sensor_BR", "sensor_BL")
SCENARIOS: Final[dict[int, str]] = {
    ord("1"): "clear",
    ord("2"): "hand_partial",
    ord("3"): "hand_heavy",
    ord("0"): "negative",
}


@dataclass(frozen=True)
class Keypoint:
    x: float
    y: float
    visibility: int


def _source(value: str):
    return int(value) if value.isdecimal() else value


def _window_visible(name: str) -> bool:
    try:
        return cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) >= 1.0
    except cv2.error:
        return False


def _close_window(name: str) -> None:
    if _window_visible(name):
        cv2.destroyWindow(name)


def _open_capture(source_value, description: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(source_value)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open capture source: {description}")
    return capture


def _next_index(image_dir: Path) -> int:
    indices: list[int] = []
    for path in image_dir.glob("sensor_*.jpg"):
        try:
            indices.append(int(path.stem.split("_")[-1]))
        except ValueError:
            continue
    return max(indices, default=0) + 1


def _quad_ok(points: list[Keypoint], size: tuple[int, int]) -> bool:
    if len(points) != 4:
        return False
    pts = np.asarray([(point.x, point.y) for point in points], dtype=np.float64)
    edges = np.roll(pts, -1, axis=0) - pts
    cross = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] \
        - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
    if not (np.all(cross > 0.0) or np.all(cross < 0.0)):
        return False
    area = 0.5 * abs(
        float(
            np.dot(pts[:, 0], np.roll(pts[:, 1], -1))
            - np.dot(pts[:, 1], np.roll(pts[:, 0], -1))
        )
    )
    return area >= max(225.0, 0.00025 * float(size[0] * size[1]))


def _label(points: list[Keypoint], size: tuple[int, int]) -> str:
    if len(points) != 4:
        raise ValueError("exactly four keypoints are required")
    width, height = (float(value) for value in size)
    pts = np.asarray([(point.x, point.y) for point in points], dtype=np.float64)
    x1, y1 = pts.min(axis=0)
    x2, y2 = pts.max(axis=0)
    values = [
        ((x1 + x2) / 2.0) / width,
        ((y1 + y2) / 2.0) / height,
        (x2 - x1) / width,
        (y2 - y1) / height,
    ]
    for point in points:
        values.extend([point.x / width, point.y / height, float(point.visibility)])
    return "0 " + " ".join(f"{value:.8f}" for value in values) + "\n"


def _reference_inset(reference: np.ndarray | None, max_width: int = 250) -> np.ndarray | None:
    if reference is None or reference.size == 0:
        return None
    scale = min(1.0, max_width / reference.shape[1])
    width = max(1, int(round(reference.shape[1] * scale)))
    height = max(1, int(round(reference.shape[0] * scale)))
    return cv2.resize(reference, (width, height), interpolation=cv2.INTER_AREA)


def _annotate(
    frame: np.ndarray,
    scenario: str,
    previous: list[Keypoint] | None,
    reference: np.ndarray | None,
) -> list[Keypoint] | None:
    window = "Photoresistor pose annotation"
    points: list[Keypoint] = []
    message = ""
    inset = _reference_inset(reference)

    def redraw() -> None:
        view = frame.copy()
        overlay = view.copy()
        cv2.rectangle(overlay, (0, 0), (view.shape[1], 88), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.68, view, 0.32, 0, view)
        next_name = POINT_NAMES[len(points)] if len(points) < 4 else "ENTER to save"
        cv2.putText(
            view,
            f"scenario={scenario} | next={next_name}",
            (16, 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.67,
            (65, 235, 95),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            view,
            "LEFT visible | RIGHT occluded | L last | 1-4 toggle | U undo | R reset",
            (16, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (235, 235, 235),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            view,
            "Follow the SAME physical corner order shown in the reference inset.",
            (16, 79),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (0, 200, 255),
            1,
            cv2.LINE_AA,
        )
        if len(points) >= 2:
            poly = np.asarray([(point.x, point.y) for point in points], dtype=np.int32)
            cv2.polylines(view, [poly], len(points) == 4, (70, 220, 70), 2, cv2.LINE_AA)
        for index, point in enumerate(points):
            pixel = (int(round(point.x)), int(round(point.y)))
            color = (70, 220, 70) if point.visibility == 2 else (0, 200, 255)
            marker = cv2.MARKER_CROSS if point.visibility == 2 else cv2.MARKER_TILTED_CROSS
            cv2.drawMarker(view, pixel, color, marker, 26, 2)
            visibility = "visible" if point.visibility == 2 else "occluded"
            cv2.putText(
                view,
                f"{index + 1}:{POINT_NAMES[index]}:{visibility}",
                (pixel[0] + 8, pixel[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                2,
                cv2.LINE_AA,
            )
        if inset is not None:
            inset_height, inset_width = inset.shape[:2]
            x1 = max(0, view.shape[1] - inset_width - 10)
            y1 = 96
            y2 = min(view.shape[0], y1 + inset_height)
            x2 = min(view.shape[1], x1 + inset_width)
            if y2 > y1 and x2 > x1:
                view[y1:y2, x1:x2] = inset[: y2 - y1, : x2 - x1]
                cv2.rectangle(view, (x1, y1), (x2 - 1, y2 - 1), (255, 255, 255), 1)
                cv2.putText(
                    view,
                    "REFERENCE ORDER",
                    (x1 + 5, y1 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 255, 255),
                    1,
                    cv2.LINE_AA,
                )
        if message:
            cv2.putText(
                view,
                message,
                (16, view.shape[0] - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.60,
                (40, 40, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imshow(window, view)

    def on_mouse(event, x, y, _flags, _param) -> None:
        nonlocal message
        if len(points) >= 4:
            return
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append(Keypoint(float(x), float(y), 2))
            message = ""
            redraw()
        elif event == cv2.EVENT_RBUTTONDOWN:
            points.append(Keypoint(float(x), float(y), 1))
            message = ""
            redraw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    while True:
        # Clicking the annotation window's X means "cancel this frame".  The
        # old behavior kept waiting on an already-destroyed HighGUI window,
        # which made the live preview appear permanently frozen.
        if not _window_visible(window):
            return None
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            _close_window(window)
            raise KeyboardInterrupt
        if key in (ord("n"), ord("N")):
            _close_window(window)
            return None
        if key in (ord("u"), ord("U")) and points:
            points.pop()
            message = ""
            redraw()
        elif key in (ord("r"), ord("R")):
            points.clear()
            message = ""
            redraw()
        elif key in (ord("l"), ord("L")):
            if previous is None:
                message = "no previous pose"
            else:
                points[:] = [Keypoint(point.x, point.y, 2) for point in previous]
                message = "reused previous coordinates; toggle hidden corners with 1-4"
            redraw()
        elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
            index = key - ord("1")
            if index >= len(points):
                message = f"corner {index + 1} has not been placed"
            else:
                point = points[index]
                points[index] = Keypoint(point.x, point.y, 1 if point.visibility == 2 else 2)
                message = ""
            redraw()
        elif key in (10, 13):
            if not _quad_ok(points, (frame.shape[1], frame.shape[0])):
                message = "invalid/non-convex or too-small corner polygon"
                redraw()
                continue
            if scenario == "clear" and any(point.visibility != 2 for point in points):
                message = "clear scenario requires all corners visible"
                redraw()
                continue
            if scenario == "hand_heavy" and all(point.visibility == 2 for point in points):
                message = "heavy cover needs at least one occluded corner (right-click or toggle 1-4)"
                redraw()
                continue
            _close_window(window)
            return points


def _write_sample(
    root: Path,
    split: str,
    index: int,
    frame: np.ndarray,
    points: list[Keypoint] | None,
    scenario: str,
    source: str,
) -> None:
    image_dir = root / "images" / split
    label_dir = root / "labels" / split
    image_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    stem = f"sensor_{index:06d}"
    image_path = image_dir / f"{stem}.jpg"
    label_path = label_dir / f"{stem}.txt"
    if not cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise IOError(f"failed to write {image_path}")
    label_path.write_text(
        "" if points is None else _label(points, (frame.shape[1], frame.shape[0])),
        encoding="utf-8",
    )
    record = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "split": split,
        "scenario": scenario,
        "image": str(image_path.relative_to(root)).replace("\\", "/"),
        "label": str(label_path.relative_to(root)).replace("\\", "/"),
        "video_size": [frame.shape[1], frame.shape[0]],
        "keypoint_order": list(POINT_NAMES),
        "keypoints_px": None if points is None else [
            [round(point.x, 3), round(point.y, 3), point.visibility] for point in points
        ],
    }
    with (root / "capture-manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="datasets/photoresistor-pose")
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument(
        "--reference",
        default="profiles/components/photoresistor-module/reference_overlay.jpg",
    )
    parser.add_argument("--max-samples", type=int, default=0)
    args = parser.parse_args()

    root = Path(args.out).resolve()
    image_dir = root / "images" / args.split
    image_dir.mkdir(parents=True, exist_ok=True)
    (root / "labels" / args.split).mkdir(parents=True, exist_ok=True)
    next_index = _next_index(image_dir)
    reference_path = Path(args.reference).resolve()
    reference = cv2.imread(str(reference_path)) if reference_path.is_file() else None
    if reference is None:
        raise SystemExit(
            f"reference overlay not found: {reference_path}; run profile calibration first"
        )

    source_value = _source(args.source)
    try:
        cap = _open_capture(source_value, args.source)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    window = "Photoresistor pose capture"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    counts = {name: 0 for name in SCENARIOS.values()}
    saved = 0
    previous: list[Keypoint] | None = None
    failed_reads = 0

    def restore_live_capture() -> None:
        nonlocal cap, failed_reads
        cap.release()
        cap = _open_capture(source_value, args.source)
        failed_reads = 0
        if not _window_visible(window):
            cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    print("Keep UNO Q and the photoresistor module in the same frame.")
    print("Live keys: 1 clear | 2 partial cover | 3 heavy cover | 0 negative | ESC quit")
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                failed_reads += 1
                if failed_reads >= 10:
                    try:
                        restore_live_capture()
                        print("live capture reconnected after read failure")
                    except RuntimeError:
                        failed_reads = 0
                key = cv2.waitKey(30) & 0xFF
                if key == 27:
                    break
                continue
            failed_reads = 0
            preview = frame.copy()
            overlay = preview.copy()
            cv2.rectangle(overlay, (0, 0), (preview.shape[1], 72), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.62, preview, 0.38, 0, preview)
            cv2.putText(
                preview,
                "1 clear | 2 partial hand | 3 heavy hand | 0 negative | ESC quit",
                (16, 29),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.67,
                (65, 235, 95),
                2,
                cv2.LINE_AA,
            )
            count_text = " | ".join(f"{name}:{value}" for name, value in counts.items())
            cv2.putText(
                preview,
                f"session={saved} | {count_text}",
                (16, 58),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (230, 230, 230),
                1,
                cv2.LINE_AA,
            )
            cv2.imshow(window, preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            scenario = SCENARIOS.get(key)
            if scenario is None:
                continue
            if scenario == "negative":
                points = None
            else:
                points = _annotate(frame.copy(), scenario, previous, reference)
                if points is None:
                    restore_live_capture()
                    print("frame cancelled; live capture restored")
                    continue
            _write_sample(root, args.split, next_index, frame, points, scenario, args.source)
            if points is not None:
                previous = points
            counts[scenario] += 1
            saved += 1
            print(f"saved {args.split}/sensor_{next_index:06d} scenario={scenario}")
            next_index += 1
            if scenario != "negative":
                # The HTTP MJPEG source is not consumed while the annotation
                # dialog is open. Reconnect so a full socket buffer or stale
                # response can never freeze the live preview.
                restore_live_capture()
            if args.max_samples > 0 and saved >= args.max_samples:
                break
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"session complete: saved={saved}, counts={counts}")


if __name__ == "__main__":
    main()
