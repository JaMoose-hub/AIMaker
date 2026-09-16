# -*- coding: utf-8 -*-
"""Capture spaced, de-duplicated images from a live camera/MJPEG stream."""
from __future__ import annotations

import argparse
from datetime import datetime
import math
from pathlib import Path
import time

import cv2
import numpy as np


def _source(value: str) -> int | str:
    return int(value) if value.isdecimal() else value


def _signature(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(
        cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA),
        cv2.COLOR_BGR2GRAY,
    )


def _skin_fraction(frame: np.ndarray) -> float:
    """Estimate visible skin coverage for clean, hands-out capture sessions."""
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(
        ycrcb,
        np.array((0, 133, 77), dtype=np.uint8),
        np.array((255, 173, 127), dtype=np.uint8),
    )
    return float(np.count_nonzero(skin)) / float(skin.size)


def _guide_text(elapsed: float, duration: float, guide: str) -> str:
    if guide not in {"hc-sr04-train", "component-train"}:
        return "MOVE OBJECT BETWEEN CAPTURES"
    phase = min(3, int(4.0 * elapsed / max(duration, 0.001)))
    return (
        "FLAT: ROTATE SLOWLY",
        "MOVE: LEFT / RIGHT / NEAR / FAR",
        "TILT: LIFT EACH EDGE 10-25 DEG",
        "OCCLUDE: BRIEF PARTIAL HAND COVER",
    )[phase]


def _show_preview(
    frame: np.ndarray,
    *,
    title: str,
    headline: str,
    detail: str,
) -> bool:
    view = frame.copy()
    overlay = view.copy()
    cv2.rectangle(overlay, (0, 0), (view.shape[1], 132), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.72, view, 0.28, 0.0, view)
    cv2.putText(
        view,
        headline,
        (30, 52),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.25,
        (50, 230, 255),
        3,
        cv2.LINE_AA,
    )
    cv2.putText(
        view,
        detail,
        (30, 105),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (245, 245, 245),
        2,
        cv2.LINE_AA,
    )
    cv2.imshow(title, view)
    return (cv2.waitKey(1) & 0xFF) == 27


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument("--out", type=Path, default=Path("datasets/hc-sr04-pose"))
    parser.add_argument("--split", choices=("train", "val", "test"), default="train")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--interval", type=float, default=0.7)
    parser.add_argument("--max-frames", type=int, default=100)
    parser.add_argument("--min-mean-diff", type=float, default=0.8)
    parser.add_argument(
        "--max-skin-fraction",
        type=float,
        default=1.0,
        help="skip frames above this estimated skin-area ratio (1 disables)",
    )
    parser.add_argument("--warmup", type=float, default=1.0)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--prefix", default="hc_sr04_live")
    parser.add_argument("--display-name", default="HC-SR04")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--guide",
        choices=("none", "hc-sr04-train", "component-train"),
        default="none",
    )
    parser.add_argument("--countdown", type=float, default=3.0)
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0 or args.max_frames <= 0:
        raise SystemExit("duration, interval, and max-frames must be positive")
    if not 1 <= args.jpeg_quality <= 100:
        raise SystemExit("jpeg-quality must be between 1 and 100")
    if not 0 <= args.max_skin_fraction <= 1:
        raise SystemExit("max-skin-fraction must be between 0 and 1")

    image_dir = args.out.expanduser().resolve() / "images" / args.split
    image_dir.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(_source(args.source))
    if not capture.isOpened():
        capture.release()
        raise SystemExit(f"cannot open capture source: {args.source}")

    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    preview_title = f"Board Vision - {args.display_name} guided capture"
    if args.preview:
        cv2.namedWindow(preview_title, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(preview_title, 1280, 720)
        try:
            cv2.setWindowProperty(preview_title, cv2.WND_PROP_TOPMOST, 1)
        except cv2.error:
            pass
        countdown_started = time.monotonic()
        while time.monotonic() - countdown_started < max(0.0, args.countdown):
            ok, frame = capture.read()
            if not ok or frame is None:
                capture.release()
                raise SystemExit("camera stream stopped during countdown")
            remaining = max(
                1,
                int(math.ceil(args.countdown - (time.monotonic() - countdown_started))),
            )
            if _show_preview(
                frame,
                title=preview_title,
                headline=f"GET READY  {remaining}",
                detail="Keep the complete sensor inside the frame. ESC cancels.",
            ):
                capture.release()
                cv2.destroyWindow(preview_title)
                raise SystemExit("capture cancelled during countdown")

    started = time.monotonic()
    deadline = started + args.duration
    next_capture = started + max(0.0, args.warmup)
    next_report = started + 10.0
    previous: np.ndarray | None = None
    saved: list[Path] = []
    skipped_similar = 0
    skipped_skin = 0
    print(
        f"capture started: split={args.split} duration={args.duration:.1f}s "
        f"interval={args.interval:.2f}s",
        flush=True,
    )
    try:
        while time.monotonic() < deadline and len(saved) < args.max_frames:
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError("camera stream stopped while capturing")
            now = time.monotonic()
            if args.preview and _show_preview(
                frame,
                title=preview_title,
                headline=_guide_text(now - started, args.duration, args.guide),
                detail=(
                    f"TIME {now - started:04.1f}/{args.duration:.0f}s   "
                    f"SAVED {len(saved)}   ESC cancels"
                ),
            ):
                print("capture stopped by user", flush=True)
                break
            if now < next_capture:
                continue
            next_capture = now + args.interval
            if _skin_fraction(frame) > args.max_skin_fraction:
                skipped_skin += 1
                continue
            signature = _signature(frame)
            difference = (
                None
                if previous is None
                else float(np.mean(cv2.absdiff(previous, signature)))
            )
            if difference is not None and difference < max(0.0, args.min_mean_diff):
                skipped_similar += 1
                continue
            target = image_dir / f"{args.prefix}_{session}_{len(saved) + 1:04d}.jpg"
            if not cv2.imwrite(
                str(target),
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), args.jpeg_quality],
            ):
                raise IOError(f"failed to save frame: {target}")
            saved.append(target)
            previous = signature
            if now >= next_report:
                elapsed = now - started
                print(
                    f"progress: {elapsed:.0f}s saved={len(saved)} "
                    f"similar_skipped={skipped_similar} skin_skipped={skipped_skin}",
                    flush=True,
                )
                next_report = now + 10.0
    finally:
        capture.release()
        if args.preview:
            try:
                cv2.destroyWindow(preview_title)
            except cv2.error:
                pass

    print(
        f"capture complete: saved={len(saved)} similar_skipped={skipped_similar} "
        f"skin_skipped={skipped_skin} "
        f"folder={image_dir}",
        flush=True,
    )
    if not saved:
        raise SystemExit("no sufficiently different frames were saved")


if __name__ == "__main__":
    main()
