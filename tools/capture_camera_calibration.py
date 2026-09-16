# -*- coding: utf-8 -*-
"""Capture reviewed 9x6 checkerboard views from the live 1080p camera stream."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from calibrate_camera import _corners


def _source(value: str):
    return int(value) if value.isdecimal() else value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument("--out", type=Path, default=Path("calibration/c920-views"))
    parser.add_argument("--pattern-cols", type=int, default=9)
    parser.add_argument("--pattern-rows", type=int, default=6)
    parser.add_argument("--min-views", type=int, default=20)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()

    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    existing = sorted(output.glob("c920_*.jpg"))
    next_index = len(existing) + 1
    capture = cv2.VideoCapture(_source(args.source))
    if not capture.isOpened():
        raise SystemExit(f"cannot open source: {args.source}")

    window = "C920 calibration: SPACE capture | U delete last | ESC finish"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    saved = list(existing)
    try:
        while True:
            ok, frame = capture.read()
            if not ok or frame is None:
                if cv2.waitKey(30) & 0xFF == 27:
                    break
                continue
            height, width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners = _corners(gray, (args.pattern_cols, args.pattern_rows))
            preview = frame.copy()
            if corners is not None:
                cv2.drawChessboardCorners(
                    preview,
                    (args.pattern_cols, args.pattern_rows),
                    corners,
                    True,
                )
            resolution_ok = (width, height) == (args.width, args.height)
            status = (
                f"views {len(saved)}/{args.min_views} | {width}x{height} | "
                f"checkerboard={'READY' if corners is not None else 'NOT FOUND'}"
            )
            color = (70, 230, 90) if corners is not None and resolution_ok else (40, 190, 255)
            cv2.putText(preview, status, (24, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
            if not resolution_ok:
                cv2.putText(
                    preview,
                    f"Expected {args.width}x{args.height}; do not capture this mode",
                    (24, 82),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (30, 30, 255),
                    2,
                )
            cv2.imshow(window, preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            if key in (ord("u"), ord("U")) and saved:
                last = saved.pop()
                last.unlink(missing_ok=True)
                next_index = max(1, next_index - 1)
                print(f"deleted {last.name}")
                continue
            if key not in (32, ord("c"), ord("C")):
                continue
            if corners is None:
                print("not captured: all checkerboard corners must be visible")
                continue
            if not resolution_ok:
                print(f"not captured: expected {args.width}x{args.height}, got {width}x{height}")
                continue
            path = output / f"c920_{next_index:03d}.jpg"
            if not cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 98]):
                raise IOError(f"failed to write {path}")
            saved.append(path)
            next_index += 1
            print(f"saved {path.name} ({len(saved)}/{args.min_views})")
    finally:
        capture.release()
        cv2.destroyAllWindows()
    print(f"captured {len(saved)} valid view(s) in {output}")
    if len(saved) < args.min_views:
        print(f"need {args.min_views - len(saved)} more view(s) before solving")


if __name__ == "__main__":
    main()
