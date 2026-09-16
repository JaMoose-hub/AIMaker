# -*- coding: utf-8 -*-
"""Auto-capture clean live camera frames from the Board Vision MJPEG stream.

This intentionally writes an unlabeled hard-example pool, not a YOLO dataset.
Use it to collect powered LED, plugged-wire, hand-nearby, reflection, and other
real desk cases without training the browser overlay into the model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any

import cv2
import numpy as np


def _source(value: str):
    return int(value) if value.isdecimal() else value


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "capture"


def _open_capture(source_value, description: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(source_value)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open capture source: {description}")
    return capture


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _small_gray(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= 0 or height <= 0:
        return np.zeros((1, 1), dtype=np.uint8)
    target_width = 160
    target_height = max(1, int(round(height * target_width / width)))
    small = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _mean_abs_diff(a: np.ndarray | None, b: np.ndarray) -> float | None:
    if a is None:
        return None
    if a.shape != b.shape:
        return None
    return float(np.mean(cv2.absdiff(a, b)))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument("--out", default="datasets/live-captures")
    parser.add_argument("--scenario", default="powered_led")
    parser.add_argument("--session", default="")
    parser.add_argument("--max-samples", type=int, default=60)
    parser.add_argument("--interval-s", type=float, default=0.75)
    parser.add_argument("--warmup-frames", type=int, default=8)
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument(
        "--min-mean-diff",
        type=float,
        default=0.8,
        help="Skip near-duplicate frames unless --max-similar-skip is reached. Use 0 to save every interval.",
    )
    parser.add_argument(
        "--max-similar-skip",
        type=int,
        default=4,
        help="Force-save one frame after this many similar interval samples.",
    )
    parser.add_argument(
        "--max-runtime-s",
        type=float,
        default=0.0,
        help="Optional safety timeout. 0 means run until --max-samples or Ctrl+C.",
    )
    args = parser.parse_args()

    if args.max_samples <= 0 and args.max_runtime_s <= 0:
        raise SystemExit("set --max-samples or --max-runtime-s so capture has a stopping point")

    scenario = _safe_slug(args.scenario)
    session_name = _safe_slug(args.session) if args.session else f"{_stamp()}-{scenario}"
    session_dir = Path(args.out).resolve() / scenario / session_name
    image_dir = session_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = session_dir / "manifest.jsonl"
    metadata_path = session_dir / "metadata.json"

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "scenario": scenario,
        "session": session_name,
        "format": "raw_mjpeg_frames_no_browser_overlay",
        "label_status": "needs_label",
        "intended_use": ["test", "hard_case_pool", "train_after_labeling"],
        "sampling": {
            "max_samples": args.max_samples,
            "interval_s": args.interval_s,
            "warmup_frames": args.warmup_frames,
            "min_mean_diff": args.min_mean_diff,
            "max_similar_skip": args.max_similar_skip,
            "jpeg_quality": args.jpeg_quality,
            "max_runtime_s": args.max_runtime_s,
        },
    }
    _write_json(metadata_path, metadata)

    source_value = _source(args.source)
    try:
        capture = _open_capture(source_value, args.source)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    saved = 0
    read_count = 0
    failed_reads = 0
    similar_skips = 0
    interval_skips = 0
    last_saved_small: np.ndarray | None = None
    next_capture_at = time.monotonic()
    started_at = time.monotonic()

    print(f"capture session: {session_dir}")
    print("Collecting clean frames from the backend MJPEG stream; browser UI is not included.")
    try:
        while True:
            if args.max_samples > 0 and saved >= args.max_samples:
                break
            if args.max_runtime_s > 0 and time.monotonic() - started_at >= args.max_runtime_s:
                break

            ok, frame = capture.read()
            if not ok or frame is None:
                failed_reads += 1
                if failed_reads >= 10:
                    capture.release()
                    time.sleep(0.25)
                    capture = _open_capture(source_value, args.source)
                    failed_reads = 0
                    print("reconnected live stream after read failures")
                continue
            failed_reads = 0
            read_count += 1
            if read_count <= args.warmup_frames:
                continue

            now = time.monotonic()
            if now < next_capture_at:
                continue
            next_capture_at = now + max(0.0, args.interval_s)

            small = _small_gray(frame)
            mean_diff = _mean_abs_diff(last_saved_small, small)
            changed = mean_diff is None or args.min_mean_diff <= 0 or mean_diff >= args.min_mean_diff
            force_similar = (
                not changed
                and args.max_similar_skip >= 0
                and similar_skips >= args.max_similar_skip
            )
            if not changed and not force_similar:
                similar_skips += 1
                interval_skips += 1
                continue

            saved += 1
            stem = f"frame_{saved:06d}"
            image_path = image_dir / f"{stem}.jpg"
            if not cv2.imwrite(
                str(image_path),
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), int(args.jpeg_quality)],
            ):
                raise IOError(f"failed to write {image_path}")

            reason = "first" if mean_diff is None else "changed" if changed else "max_similar_skip"
            record = {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "index": saved,
                "source": args.source,
                "scenario": scenario,
                "image": str(image_path.relative_to(session_dir)).replace("\\", "/"),
                "video_size": [int(frame.shape[1]), int(frame.shape[0])],
                "label_status": "needs_label",
                "mean_abs_diff_from_previous_saved": mean_diff,
                "saved_reason": reason,
                "notes": "Raw backend /video frame; no browser overlay, pin dots, labels, or guide card.",
            }
            _append_jsonl(manifest_path, record)
            last_saved_small = small
            similar_skips = 0
            print(
                f"saved {stem}.jpg size={frame.shape[1]}x{frame.shape[0]} "
                f"reason={reason} diff={mean_diff if mean_diff is not None else '-'}"
            )
    except KeyboardInterrupt:
        print("capture interrupted by user")
    finally:
        capture.release()

    summary = {
        **metadata,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "saved": saved,
        "interval_skips_near_duplicate": interval_skips,
        "session_dir": str(session_dir),
    }
    _write_json(metadata_path, summary)
    print(f"complete: saved={saved}, skipped_similar={interval_skips}")
    print(f"output: {session_dir}")


if __name__ == "__main__":
    main()
