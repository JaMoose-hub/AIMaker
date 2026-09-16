# -*- coding: utf-8 -*-
"""Collect Raspberry Pi 5 hand/wire occlusion hard examples from Board Vision.

The collector reads the backend's raw MJPEG stream (never the browser canvas)
and listens to pose telemetry on ``/ws/detections``.  It saves automatic hard
cases and operator-tagged frames to an isolated inbox for later 8-keypoint
review; it never mutates train/val/test datasets directly.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import shutil
import threading
import time
from typing import Any

import cv2
import numpy as np
import websockets

from pi5_occlusion_policy import hard_case_reasons, pin_motion_in_pitch


def _source(value: str):
    return int(value) if value.isdecimal() else value


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "capture"


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temporary.replace(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _small_gray(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    target_width = 160
    target_height = max(1, int(round(height * target_width / max(width, 1))))
    small = cv2.resize(frame, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)


def _mean_abs_diff(a: np.ndarray | None, b: np.ndarray) -> float | None:
    if a is None or a.shape != b.shape:
        return None
    return float(np.mean(cv2.absdiff(a, b)))


def _open_capture(source_value, description: str) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(source_value)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open capture source: {description}")
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _telemetry_subset(message: dict[str, Any] | None) -> dict[str, Any] | None:
    if message is None:
        return None
    keys = (
        "board_id",
        "runtime_revision",
        "frame_id",
        "ts_ms",
        "tracking",
        "confidence",
        "video_size",
        "outline",
        "pins",
        "pose_mode",
        "pose_landmarks_visible",
        "pose_quality",
        "geometry",
    )
    return {key: deepcopy(message[key]) for key in keys if key in message}


@dataclass(frozen=True)
class DetectionEvent:
    received_at: float
    message: dict[str, Any]
    reasons: tuple[str, ...]


class DetectionFeed:
    """Background WebSocket reader with a bounded hard-case event queue."""

    def __init__(
        self,
        url: str,
        board_id: str,
        *,
        cooldown_s: float,
        confidence_drop: float,
        motion_pitch: float,
        min_visible_fraction: float,
        visible_fraction_drop: float,
        min_landmarks: int,
        auto_enabled: bool,
    ) -> None:
        self.url = url
        self.board_id = board_id
        self.cooldown_s = max(0.05, float(cooldown_s))
        self.confidence_drop = max(0.0, float(confidence_drop))
        self.motion_pitch = max(0.0, float(motion_pitch))
        self.min_visible_fraction = float(min_visible_fraction)
        self.visible_fraction_drop = max(0.0, float(visible_fraction_drop))
        self.min_landmarks = max(1, int(min_landmarks))
        self.events: queue.Queue[DetectionEvent] = queue.Queue(maxsize=8)
        self._lock = threading.Lock()
        self._latest: dict[str, Any] | None = None
        self._latest_received_at: float | None = None
        self._connected = False
        self._last_error = "waiting"
        self._auto_enabled = bool(auto_enabled)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._thread_main, name="pi5-occlusion-ws", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def set_auto(self, enabled: bool) -> None:
        with self._lock:
            self._auto_enabled = bool(enabled)

    def auto_enabled(self) -> bool:
        with self._lock:
            return self._auto_enabled

    def snapshot(self) -> tuple[dict[str, Any] | None, float | None, bool, str]:
        with self._lock:
            return (
                deepcopy(self._latest),
                self._latest_received_at,
                self._connected,
                self._last_error,
            )

    def _set_connection(self, connected: bool, error: str = "") -> None:
        with self._lock:
            self._connected = connected
            self._last_error = error

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:  # pragma: no cover - defensive thread boundary
            self._set_connection(False, f"ws stopped: {exc}")

    async def _run(self) -> None:
        previous: dict[str, Any] | None = None
        previous_revision: int | None = None
        last_event_at = float("-inf")
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self.url,
                    open_timeout=3.0,
                    close_timeout=1.0,
                    ping_interval=20.0,
                    ping_timeout=20.0,
                    max_size=4 * 1024 * 1024,
                ) as socket:
                    self._set_connection(True, "")
                    async for raw in socket:
                        if self._stop.is_set():
                            break
                        try:
                            message = json.loads(raw)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if message.get("type") != "detection":
                            continue
                        if str(message.get("board_id")) != self.board_id:
                            self._set_connection(
                                True,
                                f"waiting for {self.board_id}; current={message.get('board_id')}",
                            )
                            previous = None
                            continue

                        revision = int(message.get("runtime_revision", 0) or 0)
                        if previous_revision is not None and revision != previous_revision:
                            previous = None
                        previous_revision = revision
                        received_at = time.monotonic()
                        reasons = hard_case_reasons(
                            previous,
                            message,
                            confidence_drop=self.confidence_drop,
                            motion_pitch=self.motion_pitch,
                            min_visible_fraction=self.min_visible_fraction,
                            visible_fraction_drop=self.visible_fraction_drop,
                            min_landmarks=self.min_landmarks,
                        )
                        with self._lock:
                            self._latest = message
                            self._latest_received_at = received_at
                            auto_enabled = self._auto_enabled
                            self._last_error = ""
                        if reasons and auto_enabled and received_at - last_event_at >= self.cooldown_s:
                            last_event_at = received_at
                            event = DetectionEvent(received_at, deepcopy(message), tuple(reasons))
                            if self.events.full():
                                try:
                                    self.events.get_nowait()
                                except queue.Empty:
                                    pass
                            try:
                                self.events.put_nowait(event)
                            except queue.Full:
                                pass
                        previous = message
            except Exception as exc:
                self._set_connection(False, str(exc))
                previous = None
                previous_revision = None
                await asyncio.sleep(0.5)


class CaptureSessionWriter:
    """Own one isolated inbox session and provide recoverable undo."""

    def __init__(self, output_root: Path, session_name: str, metadata: dict[str, Any]) -> None:
        self.session_dir = output_root.resolve() / _safe_slug(session_name)
        if self.session_dir.exists() and any(self.session_dir.iterdir()):
            raise FileExistsError(f"capture session already exists and is not empty: {self.session_dir}")
        self.image_dir = self.session_dir / "images"
        self.undo_dir = self.session_dir / "_undo"
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.undo_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.session_dir / "manifest.jsonl"
        self.metadata_path = self.session_dir / "metadata.json"
        self.undo_log_path = self.session_dir / "undo.jsonl"
        self.records: list[dict[str, Any]] = []
        self.metadata = dict(metadata)
        self.metadata["session"] = self.session_dir.name
        self.metadata["session_dir"] = str(self.session_dir)
        _write_json(self.metadata_path, self.metadata)
        _write_jsonl(self.manifest_path, self.records)

    def save(
        self,
        frame: np.ndarray,
        *,
        source_kind: str,
        occluder_label: str,
        reasons: list[str] | tuple[str, ...],
        telemetry: dict[str, Any] | None,
        telemetry_age_ms: float | None,
        jpeg_quality: int,
    ) -> dict[str, Any]:
        index = len(self.records) + 1
        reason_slug = _safe_slug("-".join(reasons) if reasons else occluder_label)
        timestamp_slug = datetime.now().strftime("%H%M%S-%f")[:-3]
        filename = f"frame_{index:06d}_{source_kind}_{reason_slug}_{timestamp_slug}.jpg"
        image_path = self.image_dir / filename
        if not cv2.imwrite(
            str(image_path),
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(max(1, min(100, jpeg_quality)))],
        ):
            raise IOError(f"failed to write {image_path}")

        normalized_motion = pin_motion_in_pitch(
            self.records[-1].get("telemetry") if self.records else None,
            telemetry or {},
        )
        record = {
            "captured_at": _utc_now(),
            "index": index,
            "image": str(image_path.relative_to(self.session_dir)).replace("\\", "/"),
            "video_size": [int(frame.shape[1]), int(frame.shape[0])],
            "source_kind": source_kind,
            "occluder_label": occluder_label,
            "auto_reasons": list(reasons),
            "label_status": "needs_8kpt_review",
            "telemetry_age_ms": None if telemetry_age_ms is None else round(float(telemetry_age_ms), 1),
            "pin_motion_from_previous_saved_pitch": (
                None if normalized_motion is None else round(normalized_motion, 4)
            ),
            "telemetry": _telemetry_subset(telemetry),
            "notes": (
                "Raw backend MJPEG frame without browser overlays. Telemetry is nearest local "
                "WebSocket observation and must be reviewed before dataset promotion."
            ),
        }
        self.records.append(record)
        _write_jsonl(self.manifest_path, self.records)
        return record

    def undo_last(self) -> dict[str, Any] | None:
        if not self.records:
            return None
        record = self.records.pop()
        image_path = self.session_dir / record["image"]
        moved_to = None
        if image_path.exists():
            moved_path = self.undo_dir / image_path.name
            if moved_path.exists():
                moved_path = self.undo_dir / f"{int(time.time() * 1000)}-{image_path.name}"
            shutil.move(str(image_path), str(moved_path))
            moved_to = str(moved_path.relative_to(self.session_dir)).replace("\\", "/")
        _write_jsonl(self.manifest_path, self.records)
        _append_jsonl(
            self.undo_log_path,
            {"undone_at": _utc_now(), "record": record, "moved_to": moved_to},
        )
        return record

    def finish(self, *, started_at: float, skipped_similar: int) -> None:
        counts = Counter(record["occluder_label"] for record in self.records)
        sources = Counter(record["source_kind"] for record in self.records)
        summary = {
            **self.metadata,
            "finished_at": _utc_now(),
            "runtime_s": round(time.monotonic() - started_at, 2),
            "saved": len(self.records),
            "counts_by_occluder": dict(counts),
            "counts_by_source": dict(sources),
            "auto_skipped_near_duplicate": skipped_similar,
        }
        _write_json(self.metadata_path, summary)


def _draw_preview(
    frame: np.ndarray,
    *,
    width: int,
    feed: DetectionFeed,
    saved: int,
    max_samples: int,
    last_status: str,
) -> np.ndarray:
    height, frame_width = frame.shape[:2]
    scale = min(1.0, width / max(frame_width, 1))
    preview = cv2.resize(
        frame,
        (max(1, int(round(frame_width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )
    telemetry, received_at, connected, error = feed.snapshot()
    tracking = str((telemetry or {}).get("tracking", "waiting"))
    confidence = float((telemetry or {}).get("confidence", 0.0) or 0.0)
    age_ms = None if received_at is None else max(0.0, (time.monotonic() - received_at) * 1000.0)
    auto_label = "ON" if feed.auto_enabled() else "OFF"
    lines = [
        f"Pi5 OCCLUSION CAPTURE | WS={'OK' if connected else 'WAIT'} | AUTO={auto_label}",
        f"saved={saved}/{max_samples if max_samples > 0 else '-'} | pose={tracking} {confidence:.2f} | age={age_ms:.0f}ms" if age_ms is not None else f"saved={saved}/{max_samples if max_samples > 0 else '-'} | pose=waiting",
        "H hand | W wire | B hand+wire | C clean | N no-Pi | A auto | U undo | Q quit",
        f"last: {last_status}",
    ]
    if error:
        lines.append(f"ws: {error[:100]}")
    overlay_height = 16 + 28 * len(lines)
    cv2.rectangle(preview, (0, 0), (preview.shape[1], overlay_height), (8, 12, 18), -1)
    for index, line in enumerate(lines):
        color = (90, 230, 120) if index == 0 and connected else (235, 235, 235)
        cv2.putText(
            preview,
            line,
            (14, 28 + index * 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            1,
            cv2.LINE_AA,
        )
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8100/ws/detections")
    parser.add_argument("--out", default="datasets/pi5-occlusion-inbox")
    parser.add_argument("--session", default="")
    parser.add_argument("--board-id", default="raspberry-pi-5")
    parser.add_argument("--max-samples", type=int, default=160)
    parser.add_argument("--max-runtime-s", type=float, default=0.0)
    parser.add_argument("--cooldown-s", type=float, default=0.8)
    parser.add_argument("--confidence-drop", type=float, default=0.18)
    parser.add_argument("--motion-pitch", type=float, default=0.45)
    parser.add_argument("--min-visible-fraction", type=float, default=0.75)
    parser.add_argument("--visible-fraction-drop", type=float, default=0.18)
    parser.add_argument("--min-landmarks", type=int, default=4)
    parser.add_argument(
        "--min-mean-diff",
        type=float,
        default=4.0,
        help=(
            "Mean grayscale difference required for a repeated automatic sample. "
            "The first event is always saved; 4.0 filters C920 exposure-only duplicates."
        ),
    )
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--preview-width", type=int, default=1280)
    parser.add_argument("--no-auto", action="store_true")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    if args.max_samples <= 0 and args.max_runtime_s <= 0:
        raise SystemExit("set --max-samples or --max-runtime-s so capture has a stopping point")
    if args.headless and args.no_auto:
        raise SystemExit("headless mode requires automatic capture")

    session_name = _safe_slug(args.session) if args.session else f"{_stamp()}-pi5-occlusion"
    metadata = {
        "created_at": _utc_now(),
        "source": args.source,
        "websocket_url": args.ws_url,
        "board_id": args.board_id,
        "format": "raw_mjpeg_frames_no_browser_overlay",
        "dataset_stage": "isolated_hard_example_inbox",
        "label_status": "needs_8kpt_review",
        "intended_use": ["hard_example_review", "future_train", "future_val_or_test"],
        "promotion_rule": "Do not copy to train/val/test until 8-keypoint review and session-level split.",
        "trigger_thresholds": {
            "cooldown_s": args.cooldown_s,
            "confidence_drop": args.confidence_drop,
            "motion_pitch": args.motion_pitch,
            "min_visible_fraction": args.min_visible_fraction,
            "visible_fraction_drop": args.visible_fraction_drop,
            "min_landmarks": args.min_landmarks,
            "min_mean_diff": args.min_mean_diff,
        },
        "manual_keys": {
            "H": "hand",
            "W": "wire",
            "B": "hand_wire",
            "C_or_space": "clean",
            "N": "no_pi",
            "A": "toggle_auto",
            "U": "recoverable_undo",
            "Q_or_ESC": "quit",
        },
    }
    try:
        writer = CaptureSessionWriter(Path(args.out), session_name, metadata)
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc

    feed = DetectionFeed(
        args.ws_url,
        args.board_id,
        cooldown_s=args.cooldown_s,
        confidence_drop=args.confidence_drop,
        motion_pitch=args.motion_pitch,
        min_visible_fraction=args.min_visible_fraction,
        visible_fraction_drop=args.visible_fraction_drop,
        min_landmarks=args.min_landmarks,
        auto_enabled=not args.no_auto,
    )
    feed.start()
    source_value = _source(args.source)
    try:
        capture = _open_capture(source_value, args.source)
    except RuntimeError as exc:
        feed.stop()
        raise SystemExit(str(exc)) from exc

    started_at = time.monotonic()
    last_auto_gray: np.ndarray | None = None
    skipped_similar = 0
    failed_reads = 0
    last_status = f"ready -> {writer.session_dir}"
    window_name = "Board Vision - Pi5 Occlusion Capture"

    def save_frame(
        frame: np.ndarray,
        *,
        source_kind: str,
        label: str,
        reasons: list[str] | tuple[str, ...],
        telemetry: dict[str, Any] | None,
        received_at: float | None,
    ) -> dict[str, Any]:
        age_ms = None if received_at is None else max(0.0, (time.monotonic() - received_at) * 1000.0)
        return writer.save(
            frame,
            source_kind=source_kind,
            occluder_label=label,
            reasons=reasons,
            telemetry=telemetry,
            telemetry_age_ms=age_ms,
            jpeg_quality=args.jpeg_quality,
        )

    print(f"capture session: {writer.session_dir}")
    print("Saved images are raw /video frames; browser UI is not included.")
    print("Keys: H=hand W=wire B=hand+wire C/Space=clean N=no-Pi A=auto U=undo Q/Esc=quit")
    try:
        while True:
            if args.max_samples > 0 and len(writer.records) >= args.max_samples:
                last_status = "maximum sample count reached"
                break
            if args.max_runtime_s > 0 and time.monotonic() - started_at >= args.max_runtime_s:
                last_status = "maximum runtime reached"
                break

            ok, frame = capture.read()
            if not ok or frame is None:
                failed_reads += 1
                if failed_reads >= 10:
                    capture.release()
                    time.sleep(0.2)
                    capture = _open_capture(source_value, args.source)
                    failed_reads = 0
                    last_status = "MJPEG reconnected"
                continue
            failed_reads = 0

            while True:
                try:
                    event = feed.events.get_nowait()
                except queue.Empty:
                    break
                current_gray = _small_gray(frame)
                difference = _mean_abs_diff(last_auto_gray, current_gray)
                if difference is not None and difference < max(0.0, args.min_mean_diff):
                    skipped_similar += 1
                    last_status = f"auto skipped duplicate ({difference:.2f})"
                    continue
                record = save_frame(
                    frame,
                    source_kind="auto",
                    label="needs_review",
                    reasons=event.reasons,
                    telemetry=event.message,
                    received_at=event.received_at,
                )
                last_auto_gray = current_gray
                last_status = f"saved #{record['index']} auto: {','.join(event.reasons)}"
                print(last_status)

            key = -1
            if not args.headless:
                preview = _draw_preview(
                    frame,
                    width=max(480, args.preview_width),
                    feed=feed,
                    saved=len(writer.records),
                    max_samples=args.max_samples,
                    last_status=last_status,
                )
                cv2.imshow(window_name, preview)
                key = cv2.waitKey(1) & 0xFF

            if key in (27, ord("q"), ord("Q")):
                last_status = "stopped by operator"
                break
            if key in (ord("a"), ord("A")):
                feed.set_auto(not feed.auto_enabled())
                last_status = f"automatic capture {'ON' if feed.auto_enabled() else 'OFF'}"
                continue
            if key in (ord("u"), ord("U")):
                undone = writer.undo_last()
                last_status = "nothing to undo" if undone is None else f"undid #{undone['index']} (moved to _undo)"
                print(last_status)
                continue

            manual_label = None
            if key in (ord("h"), ord("H")):
                manual_label = "hand"
            elif key in (ord("w"), ord("W")):
                manual_label = "wire"
            elif key in (ord("b"), ord("B")):
                manual_label = "hand_wire"
            elif key in (ord("c"), ord("C"), 32):
                manual_label = "clean"
            elif key in (ord("n"), ord("N")):
                manual_label = "no_pi"
            if manual_label is not None:
                telemetry, received_at, _, _ = feed.snapshot()
                if manual_label == "no_pi":
                    telemetry = None
                    received_at = None
                record = save_frame(
                    frame,
                    source_kind="manual",
                    label=manual_label,
                    reasons=[manual_label],
                    telemetry=telemetry,
                    received_at=received_at,
                )
                last_status = f"saved #{record['index']} manual: {manual_label}"
                print(last_status)
    except KeyboardInterrupt:
        last_status = "interrupted"
        print(last_status)
    finally:
        capture.release()
        feed.stop()
        if not args.headless:
            cv2.destroyWindow(window_name)
        writer.finish(started_at=started_at, skipped_similar=skipped_similar)

    print(f"complete: saved={len(writer.records)}, skipped_similar={skipped_similar}")
    print(f"output: {writer.session_dir}")


if __name__ == "__main__":
    main()
