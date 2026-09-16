"""Capture a small, replayable wire-truth session from the live MJPEG stream.

The tool deliberately keeps the annotation protocol small:

* one scene starts with four clicks on each configured header row
  (first, second, penultimate, last pin);
* a console line declares the visible wire endpoints and color;
* fifteen JPEG frames are captured for that declaration;
* a blank declaration repeats the previous one, which is useful for temporal
  stability; ``!`` records an empty scene and ``~`` records a resting/draped
  wire rather than silently treating it as inserted.

Example::

    backend\\.venv\\Scripts\\python.exe tools\\capture_groundtruth.py \
      --out datasets\\wire-truth\\s01 --rows JDIGITAL,JANALOG

Declarations follow the accuracy plan, e.g. ``D8-GND_D blue; A0 red``,
``~IOREF,A0 blue``, ``!`` and ``%hand``.  The tool only writes below the
explicit ``--out`` directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.vision.wire_tracer import (  # noqa: E402
    MAX_WIRE_HALF_WIDTH_PX,
    MIN_BRANCH_LENGTH,
    MIN_MASK_PIXELS,
    SNAP_RADIUS_PX,
    WIRE_COLOR_BANDS,
)
from app.profiles.store import ProfileStore  # noqa: E402
from app.vision.factory import create_detector  # noqa: E402
from wire_trace_debug import grab_frame  # noqa: E402


DEFAULT_MIN_CAPTURE_PITCH_PX = 18.0
DEFAULT_RECOMMENDED_CAPTURE_PITCH_PX = 20.0


def _scale_report(
    pitch_px: float,
    *,
    min_pitch_px: float = DEFAULT_MIN_CAPTURE_PITCH_PX,
    recommended_pitch_px: float = DEFAULT_RECOMMENDED_CAPTURE_PITCH_PX,
) -> dict[str, Any]:
    """Return explicit scale metadata for a ground-truth scene.

    The replay metric is normalized by pitch, but a tiny physical pin pitch
    still destroys segmentation and pose quality.  Keep both facts visible:
    normalized metrics remain useful, while the capture itself is marked low
    scale instead of being mistaken for the physical 8--10 px/mm target.
    """
    pitch = max(float(pitch_px), 0.0)
    px_per_mm = pitch / 2.54 if pitch > 0 else 0.0
    if pitch < float(min_pitch_px):
        status = "reject"
    elif pitch < float(recommended_pitch_px):
        status = "below_recommended"
    else:
        status = "ok"
    return {
        "pitch_px": round(pitch, 3),
        "px_per_mm": round(px_per_mm, 4),
        "status": status,
        "min_pitch_px": float(min_pitch_px),
        "recommended_pitch_px": float(recommended_pitch_px),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit_row(points: list[tuple[float, float]], indices: list[int]) -> dict[str, Any]:
    """Fit the 1-D projective pin-row model described in the accuracy plan."""
    if len(points) < 3 or len(points) != len(indices):
        raise ValueError("a row needs at least three clicked points")
    rows: list[list[float]] = []
    values: list[float] = []
    for (x, y), u in zip(points, indices):
        uf = float(u)
        rows.append([uf, 1.0, 0.0, 0.0, -x * uf])
        values.append(float(x))
        rows.append([0.0, 0.0, uf, 1.0, -y * uf])
        values.append(float(y))
    coeff, _, _, _ = np.linalg.lstsq(np.asarray(rows), np.asarray(values), rcond=None)
    a, b, d, e, c = (float(value) for value in coeff)

    def project(index: int) -> tuple[float, float]:
        den = c * float(index) + 1.0
        if abs(den) < 1e-8:
            raise ValueError("clicked row fit is degenerate")
        return ((a * index + b) / den, (d * index + e) / den)

    residuals = [
        float(np.hypot(project(index)[0] - point[0], project(index)[1] - point[1]))
        for point, index in zip(points, indices)
    ]
    return {
        "clicks": [{"index": int(index), "px": [float(point[0]), float(point[1])]} for point, index in zip(points, indices)],
        "coefficients": {"a": a, "b": b, "c": c, "d": d, "e": e},
        "fit_residual_px": {
            "max": max(residuals),
            "median": float(np.median(np.asarray(residuals))),
        },
        "pins_px": {str(index): list(project(index)) for index in range(max(indices) + 1)},
    }


def _parse_declaration(raw: str) -> dict[str, Any]:
    text = raw.strip()
    result: dict[str, Any] = {
        "raw_input": raw,
        "empty_scene": False,
        "hands_in_frame": False,
        "connections": [],
        "draped": [],
    }
    if not text:
        return result
    for item in (part.strip() for part in text.split(";") if part.strip()):
        if item == "!":
            result["empty_scene"] = True
            continue
        if item.startswith("%"):
            result["hands_in_frame"] = True
            continue
        resting = item.startswith("~")
        if resting:
            item = item[1:].strip()
        match = re.fullmatch(r"(.+?)\s+([A-Za-z][A-Za-z0-9_-]*)", item)
        if not match:
            raise ValueError(f"invalid declaration segment: {item!r}")
        endpoint_text, color = match.groups()
        if color not in WIRE_COLOR_BANDS:
            raise ValueError(f"unknown wire color {color!r}; use one of {sorted(WIRE_COLOR_BANDS)}")
        if resting and "," in endpoint_text:
            result["draped"].append({
                "near_pins": [pin.strip() for pin in endpoint_text.split(",") if pin.strip()],
                "color": color,
            })
            continue
        if "-" in endpoint_text:
            first, second = (value.strip() for value in endpoint_text.split("-", 1))
            endpoints = [first, second]
        else:
            endpoints = [endpoint_text.strip()]
        connection = {"color": color, "endpoints": [{"pin_id": pin} for pin in endpoints if pin]}
        if resting:
            result["draped"].append(connection)
        else:
            result["connections"].append(connection)
    return result


def _load_rows(profile_path: Path, row_names: list[str]) -> dict[str, list[tuple[str, int]]]:
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    rows: dict[str, list[tuple[str, int]]] = {}
    for pin in payload["pins"]:
        rows.setdefault(pin["header"], []).append((pin["id"], int(pin["index"])))
    for row in rows.values():
        row.sort(key=lambda value: value[1])
    missing = [name for name in row_names if name not in rows]
    if missing:
        raise ValueError(f"unknown header row(s): {', '.join(missing)}; available: {', '.join(rows)}")
    return {name: rows[name] for name in row_names}


def _click_row(frame: np.ndarray, row_name: str, pins: list[tuple[str, int]], scene_id: str) -> dict[str, Any]:
    selected = [0, 1, max(0, len(pins) - 2), len(pins) - 1]
    selected = list(dict.fromkeys(selected))
    clicks: list[tuple[float, float]] = []
    window = f"groundtruth {scene_id} / {row_name}"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    def on_mouse(event: int, x: int, y: int, _flags: int, _userdata: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < len(selected):
            clicks.append((float(x), float(y)))

    cv2.setMouseCallback(window, on_mouse)
    try:
        while len(clicks) < len(selected):
            view = frame.copy()
            cv2.putText(
                view,
                f"{row_name}: click "
                + ", ".join(pins[index][0] for index in selected[len(clicks):]),
                (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2,
            )
            for number, (x, y) in enumerate(clicks, start=1):
                cv2.circle(view, (round(x), round(y)), 7, (0, 255, 0), 2)
                cv2.putText(view, str(number), (round(x) + 8, round(y) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(window, view)
            if cv2.waitKey(30) & 0xFF == ord("q"):
                raise KeyboardInterrupt
    finally:
        cv2.destroyWindow(window)
    return _fit_row(clicks, [pins[index][1] for index in selected])


def _detection_record(result: Any) -> dict[str, Any]:
    """Serialize the detector output needed by replay's recorded-pose mode.

    The values stay in source-frame pixels, exactly like the live WS contract.
    Keeping the detector result beside each JPEG lets the replay harness
    measure wire tracing without silently replacing live pose with clicked
    pin truth.
    """
    return {
        "pose_mode": "recorded",
        "tracking": result.tracking,
        "confidence": float(result.confidence),
        "rvec": list(result.rvec) if result.rvec is not None else None,
        "tvec": list(result.tvec) if result.tvec is not None else None,
        "pins": [
            {
                "id": pin.pin_id,
                "x": float(pin.x),
                "y": float(pin.y),
                "c": float(pin.confidence),
                "v": bool(pin.visible),
                "header": pin.header,
                "index": pin.index,
            }
            for pin in result.pins
        ],
        "outline": [list(point) for point in result.outline_px]
        if result.outline_px is not None else None,
        "wire_exclusion": [list(point) for point in result.wire_exclusion_px]
        if result.wire_exclusion_px is not None else None,
    }


def _capture_burst(
    url: str,
    output: Path,
    declaration: dict[str, Any],
    count: int,
    interval_s: float,
    *,
    profile: Any | None = None,
    profile_dir: Path | None = None,
    horizontal_fov_deg: float | None = 70.42,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "truth.json").write_text(json.dumps(declaration, ensure_ascii=False, indent=2), encoding="utf-8")
    pose_path = output / "pose.jsonl"
    detector = None
    if profile is not None and profile_dir is not None:
        detector = create_detector(
            "pipeline", profile, profile_dir,
            horizontal_fov_deg=horizontal_fov_deg,
        )
    with pose_path.open("w", encoding="utf-8") as pose:
        try:
            for frame_id in range(count):
                frame = grab_frame(url)
                filename = f"f{frame_id:03d}.jpg"
                target = output / filename
                if not cv2.imwrite(str(target), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                    raise RuntimeError(f"failed to write {target}")
                ts_ms = time.monotonic() * 1000.0
                record = {
                    "frame_id": frame_id,
                    "source": filename,
                    "ts_ms": ts_ms,
                    "video_size": [int(frame.shape[1]), int(frame.shape[0])],
                }
                if detector is None:
                    record["pose_mode"] = "not_recorded"
                    record["tracking"] = "not_recorded"
                else:
                    result = detector.detect(frame, frame_id, ts_ms)
                    record.update(_detection_record(result))
                pose.write(json.dumps(record, ensure_ascii=False) + "\n")
                pose.flush()
                print(f"  captured {filename} ({record['tracking']})")
                if frame_id + 1 < count:
                    time.sleep(interval_s)
        finally:
            if detector is not None:
                detector.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="new session directory; must not already exist")
    parser.add_argument("--url", default="http://127.0.0.1:8100/video")
    parser.add_argument("--profile", default=str(ROOT / "profiles" / "boards" / "arduino-uno-q" / "board.json"))
    parser.add_argument("--rows", default="", help="comma-separated header rows; default: first two rows in board.json")
    parser.add_argument("--burst", type=int, default=15)
    parser.add_argument("--interval", type=float, default=1 / 3)
    parser.add_argument(
        "--horizontal-fov-deg", type=float, default=70.42,
        help="fallback FOV for recorded pose when camera.json is absent (default: C920 70.42)",
    )
    parser.add_argument(
        "--no-record-pose", action="store_true",
        help="skip offline PipelineDetector pose records (legacy capture mode)",
    )
    parser.add_argument(
        "--min-pitch-px", type=float, default=DEFAULT_MIN_CAPTURE_PITCH_PX,
        help="mark scenes below this pin pitch as reject-scale (default: 18px)",
    )
    parser.add_argument(
        "--recommended-pitch-px", type=float,
        default=DEFAULT_RECOMMENDED_CAPTURE_PITCH_PX,
        help="mark scenes below this pitch below-recommended (default: 20px)",
    )
    args = parser.parse_args()

    output = Path(args.out).resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output directory: {output}")
    profile_path = Path(args.profile).resolve()
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    board_id = str(payload["board"]["id"])
    pose_profile = None
    pose_profile_dir: Path | None = None
    if not args.no_record_pose:
        # Resolve the profile through the same validator used by the backend.
        # The normal layout is <profiles>/boards/<id>/board.json; the fallback
        # also supports the flat fixture layout used by tests.
        roots = [profile_path.parent.parent, profile_path.parent]
        for root in roots:
            store = ProfileStore(root)
            if store.has(board_id):
                pose_profile = store.profile(board_id)
                pose_profile_dir = store.board_dir(board_id)
                break
        if pose_profile is None or pose_profile_dir is None:
            raise SystemExit(
                f"could not load validated profile for pose recording: {profile_path}"
            )
    all_rows = list(dict.fromkeys(pin["header"] for pin in payload["pins"]))
    row_names = [name.strip() for name in args.rows.split(",") if name.strip()] or all_rows[:2]
    if not row_names:
        raise SystemExit("board profile has no header rows")
    if args.min_pitch_px <= 0 or args.recommended_pitch_px < args.min_pitch_px:
        raise SystemExit("require 0 < --min-pitch-px <= --recommended-pitch-px")
    rows = _load_rows(profile_path, row_names)
    output.mkdir(parents=True)
    profile_snapshot = output / "profile"
    profile_snapshot.mkdir()
    for source in profile_path.parent.iterdir():
        if source.name == profile_path.name or source.suffix.lower() in {".jpg", ".jpeg", ".png", ".npz", ".json"}:
            if ".bak-" not in source.name:
                target = profile_snapshot / source.name
                if source.is_file():
                    shutil.copy2(source, target)
    scenes: list[dict[str, Any]] = []
    print("Press Enter to start a scene, q to finish.")
    while True:
        command = input("scene> ").strip().lower()
        if command == "q":
            break
        scene_id = f"scene-{len(scenes) + 1:02d}"
        frame = grab_frame(args.url)
        print(f"{scene_id}: captured annotation frame {frame.shape[1]}x{frame.shape[0]}")
        fitted_rows = {name: _click_row(frame, name, row, scene_id) for name, row in rows.items()}
        pins_px: dict[str, list[float]] = {}
        for name, fit in fitted_rows.items():
            index_to_id = {index: pin_id for pin_id, index in rows[name]}
            for index, point in fit["pins_px"].items():
                if int(index) in index_to_id:
                    pins_px[index_to_id[int(index)]] = point
        pitch_px = float(np.median([
            np.linalg.norm(np.asarray(fitted_rows[name]["pins_px"][str(row[1])])
                           - np.asarray(fitted_rows[name]["pins_px"][str(row[1] - 1)]))
            for name in row_names
            for row in rows[name][1:]
            if str(row[1]) in fitted_rows[name]["pins_px"]
            and str(row[1] - 1) in fitted_rows[name]["pins_px"]
        ] or [0.0]))
        scale = _scale_report(
            pitch_px,
            min_pitch_px=args.min_pitch_px,
            recommended_pitch_px=args.recommended_pitch_px,
        )
        scene = {
            "scene_id": scene_id,
            "video_size": [int(frame.shape[1]), int(frame.shape[0])],
            "rows": fitted_rows,
            "pins_px": pins_px,
            "pitch_px": scale["pitch_px"],
            "px_per_mm": scale["px_per_mm"],
            "scale": scale,
        }
        if scale["status"] == "reject":
            print(
                f"WARNING: {scene_id} pin pitch is {scale['pitch_px']:.1f}px "
                f"({scale['px_per_mm']:.2f}px/mm), below the capture minimum "
                f"of {args.min_pitch_px:.1f}px; do not use it as a physical accuracy gate."
            )
        elif scale["status"] == "below_recommended":
            print(
                f"NOTE: {scene_id} pin pitch is {scale['pitch_px']:.1f}px "
                f"({scale['px_per_mm']:.2f}px/mm), below the recommended "
                f"{args.recommended_pitch_px:.1f}px."
            )
        scene_dir = output / scene_id
        scene_dir.mkdir()
        (scene_dir / "pin_truth.json").write_text(json.dumps(scene, ensure_ascii=False, indent=2), encoding="utf-8")
        previous = ""
        while True:
            raw = input("declare (blank=replay previous, g=new scene, q=finish): ")
            command = raw.strip().lower()
            if command == "q":
                scenes.append({"scene_id": scene_id})
                break
            if command == "g":
                scenes.append({"scene_id": scene_id})
                break
            if not raw.strip() and not previous:
                print("first declaration cannot be blank")
                continue
            declaration = _parse_declaration(raw if raw.strip() else previous)
            previous = raw if raw.strip() else previous
            config_id = f"cfg-{len(list(scene_dir.glob('cfg-*'))) + 1:02d}"
            print(f"capturing {scene_id}/{config_id}: {declaration['raw_input']}")
            _capture_burst(
                args.url, scene_dir / config_id, declaration,
                args.burst, args.interval,
                profile=pose_profile,
                profile_dir=pose_profile_dir,
                horizontal_fov_deg=args.horizontal_fov_deg,
            )
            if not raw.strip():
                print("replayed previous declaration")
        if command == "q":
            break
    manifest = {
        "format": "wire-truth/v1",
        "created_at_ms": time.time() * 1000.0,
        "video_url": args.url,
        "profile_source": str(profile_path),
        "pose_recording": "disabled" if args.no_record_pose else "offline_pipeline",
        "profile_snapshot": {"board.json_sha256": _sha256(profile_snapshot / "board.json")},
        "rows": row_names,
        "code_constants": {
            "snap_radius_px_legacy": SNAP_RADIUS_PX,
            "max_wire_half_width_px": MAX_WIRE_HALF_WIDTH_PX,
            "min_branch_length": MIN_BRANCH_LENGTH,
            "min_mask_pixels": MIN_MASK_PIXELS,
        },
        "capture_scale_policy": {
            "min_pitch_px": float(args.min_pitch_px),
            "recommended_pitch_px": float(args.recommended_pitch_px),
            "target_px_per_mm": [8.0, 10.0],
        },
        "scenes": scenes,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    cv2.destroyAllWindows()
    print(f"wrote {output / 'manifest.json'}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        cv2.destroyAllWindows()
        raise SystemExit("capture cancelled")
