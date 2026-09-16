"""M15 debug tool: grab one live frame from the running backend's MJPEG
stream, run the Stage A-C wire tracer (backend/app/vision/wire_tracer.py),
and write a debug image overlaying the color mask + skeleton + detected
branch endpoints so the pipeline can be visually verified against a real
dupont wire before any pin-snapping (M16) is built.

Usage:
    backend\\.venv\\Scripts\\python.exe tools\\wire_trace_debug.py [--color red] [--url http://127.0.0.1:8100/video] [--out path.jpg]
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.vision.wire_tracer import WIRE_COLOR_BANDS, segment_color, skeletonize_mask, trace_branches  # noqa: E402

BRANCH_COLORS_BGR = [
    (0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 128, 255), (255, 128, 0),
]


def grab_frame(url: str, timeout: float = 8.0) -> np.ndarray:
    resp = urllib.request.urlopen(url, timeout=timeout)
    buf = b""
    try:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                raise RuntimeError("stream ended before a full JPEG frame arrived")
            buf += chunk
            start = buf.find(b"\xff\xd8")
            if start < 0:
                continue
            end = buf.find(b"\xff\xd9", start + 2)
            if end >= 0:
                jpg = buf[start : end + 2]
                img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    raise RuntimeError("failed to decode captured JPEG frame")
                return img
    finally:
        resp.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", default="red", choices=list(WIRE_COLOR_BANDS.keys()))
    parser.add_argument("--url", default="http://127.0.0.1:8100/video")
    parser.add_argument("--out", default=None, help="output debug image path (default: <repo>/wire_trace_debug_<color>.jpg)")
    parser.add_argument("--frame-in", default=None, help="use an existing image file instead of grabbing from --url")
    args = parser.parse_args()

    if args.frame_in:
        frame = cv2.imread(args.frame_in)
        if frame is None:
            raise SystemExit(f"could not read image: {args.frame_in}")
    else:
        print(f"grabbing one frame from {args.url} ...")
        frame = grab_frame(args.url)

    print(f"frame size: {frame.shape[1]}x{frame.shape[0]}")

    mask = segment_color(frame, args.color)
    mask_px = int(cv2.countNonZero(mask))
    print(f"[{args.color}] mask pixels: {mask_px}")

    skeleton = skeletonize_mask(mask)
    skel_px = int(cv2.countNonZero(skeleton))
    print(f"[{args.color}] skeleton pixels: {skel_px}")

    branches = trace_branches(skeleton, args.color) if skel_px else []
    print(f"[{args.color}] branches found: {len(branches)}")
    for i, b in enumerate(branches):
        p0, p1 = b.points[0], b.points[-1]
        print(f"  branch {i}: {len(b.points)} pts, endpoints {p0} <-> {p1}")

    debug = frame.copy()
    overlay = np.zeros_like(debug)
    overlay[mask > 0] = (60, 60, 60)
    debug = cv2.addWeighted(debug, 1.0, overlay, 0.5, 0)

    for i, b in enumerate(branches):
        col = BRANCH_COLORS_BGR[i % len(BRANCH_COLORS_BGR)]
        for x, y in b.points:
            debug[y, x] = col
        for ex, ey in (b.points[0], b.points[-1]):
            cv2.circle(debug, (ex, ey), 6, col, 2)

    out_path = args.out or str(Path(__file__).resolve().parent.parent / f"wire_trace_debug_{args.color}.jpg")
    cv2.imwrite(out_path, debug)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
