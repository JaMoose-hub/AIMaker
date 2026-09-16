# -*- coding: utf-8 -*-
"""Create a visual geometry profile for a four-pin photoresistor module.

Place the module component-side up with its four header pins pointing down.
Press C/SPACE to freeze, then click PCB TL, TR, BR, BL, VCC, GND, AO.
The DO header exists physically but is intentionally not part of this guide.
The resulting homography-normalized pin locations are used to project stable
pin markers from a four-corner sensor pose.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import cv2
import numpy as np


POINT_NAMES = ("pcb_TL", "pcb_TR", "pcb_BR", "pcb_BL", "VCC", "GND", "AO")
MIN_PROFILE_PIN_PITCH_PX = 20.0


def _source(value: str):
    return int(value) if value.isdecimal() else value


def _ordered_corners(points: np.ndarray) -> list[tuple[float, float]]:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    sums = points.sum(axis=1)
    differences = points[:, 1] - points[:, 0]
    ordered = (
        points[int(np.argmin(sums))],
        points[int(np.argmin(differences))],
        points[int(np.argmax(sums))],
        points[int(np.argmax(differences))],
    )
    return [(float(x), float(y)) for x, y in ordered]


def _detect_blue_pcb_corners(frame: np.ndarray) -> list[tuple[float, float]] | None:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.asarray((85, 45, 25), dtype=np.uint8),
        np.asarray((145, 255, 255), dtype=np.uint8),
    )
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8), iterations=2
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < 500.0:
            continue
        _x, _y, width, height = cv2.boundingRect(contour)
        short, long = sorted((width, height))
        if short < 25 or not (1.3 <= long / max(1, short) <= 4.0):
            continue
        candidates.append((area, contour))
    if not candidates:
        return None
    contour = max(candidates, key=lambda item: item[0])[1]
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    polygon = cv2.approxPolyDP(hull, 0.02 * perimeter, True).reshape(-1, 2)
    if len(polygon) != 4:
        polygon = cv2.boxPoints(cv2.minAreaRect(contour))
    return _ordered_corners(polygon)


def _annotate(
    frame: np.ndarray,
    preset_corners: list[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    window = "Photoresistor profile: PCB TL TR BR BL, then VCC GND AO"
    auto_corners = list(preset_corners or [])
    clicks: list[tuple[float, float]] = list(auto_corners)
    message = "blue PCB corners auto-snapped; click VCC, GND, AO" if auto_corners else ""

    def redraw() -> None:
        view = frame.copy()
        overlay = view.copy()
        cv2.rectangle(overlay, (0, 0), (view.shape[1], 76), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.65, view, 0.35, 0, view)
        next_name = POINT_NAMES[len(clicks)] if len(clicks) < len(POINT_NAMES) else "ENTER to save"
        cv2.putText(
            view,
            f"next: {next_name} | click | U undo pin | R reset | M manual | ENTER save",
            (16, 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68,
            (60, 235, 90),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            view,
            "Blue PCB corners only | pins DOWN | skip DO when marking VCC/GND/AO.",
            (16, 59),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (0, 200, 255),
            2,
            cv2.LINE_AA,
        )
        if len(clicks) >= 2:
            pcb_points = np.asarray(clicks[: min(4, len(clicks))], dtype=np.int32)
            cv2.polylines(view, [pcb_points], len(clicks) >= 4, (70, 220, 70), 2, cv2.LINE_AA)
        for index, (x, y) in enumerate(clicks):
            point = (int(round(x)), int(round(y)))
            color = (70, 220, 70) if index < 4 else (0, 170, 255)
            cv2.drawMarker(view, point, color, cv2.MARKER_CROSS, 24, 2)
            cv2.putText(
                view,
                f"{index + 1}:{POINT_NAMES[index]}",
                (point[0] + 9, point[1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.56,
                color,
                2,
                cv2.LINE_AA,
            )
        if message:
            cv2.putText(
                view,
                message,
                (16, view.shape[0] - 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (40, 40, 255),
                2,
                cv2.LINE_AA,
            )
        cv2.imshow(window, view)

    def on_mouse(event, x, y, _flags, _param) -> None:
        nonlocal message
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < len(POINT_NAMES):
            clicks.append((float(x), float(y)))
            message = ""
            redraw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    while True:
        key = cv2.waitKey(30) & 0xFF
        if key == 27:
            cv2.destroyWindow(window)
            raise KeyboardInterrupt
        if key in (ord("u"), ord("U")) and clicks:
            if auto_corners and len(clicks) <= 4:
                message = "auto PCB corners are locked; press M for manual corner mode"
            else:
                clicks.pop()
                message = ""
            redraw()
        elif key in (ord("r"), ord("R")):
            clicks[:] = auto_corners
            message = "reset to auto PCB corners" if auto_corners else ""
            redraw()
        elif key in (ord("m"), ord("M")):
            auto_corners.clear()
            clicks.clear()
            message = "manual mode: click all four PCB corners, then VCC/GND/AO"
            redraw()
        elif key in (10, 13):
            if len(clicks) != len(POINT_NAMES):
                message = "all 7 points are required"
                redraw()
                continue
            corners = np.asarray(clicks[:4], dtype=np.float64)
            area = 0.5 * abs(
                float(
                    np.dot(corners[:, 0], np.roll(corners[:, 1], -1))
                    - np.dot(corners[:, 1], np.roll(corners[:, 0], -1))
                )
            )
            if area < 400:
                message = "PCB corner polygon is too small"
                redraw()
                continue
            pins = np.asarray(clicks[4:], dtype=np.float64)
            pin_pitch = min(
                float(np.linalg.norm(pins[0] - pins[1])),
                float(np.linalg.norm(pins[1] - pins[2])),
            )
            if pin_pitch < MIN_PROFILE_PIN_PITCH_PX:
                message = (
                    f"sensor too small / pin points too close: {pin_pitch:.1f}px "
                    f"(need {MIN_PROFILE_PIN_PITCH_PX:.0f}px)"
                )
                redraw()
                continue
            cv2.destroyWindow(window)
            return clicks


def _normalized_pin_positions(
    corners: list[tuple[float, float]],
    pins: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    source = np.asarray(corners, dtype=np.float32)
    unit = np.asarray(((0, 0), (1, 0), (1, 1), (0, 1)), dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source, unit)
    points = np.asarray(pins, dtype=np.float32).reshape(-1, 1, 2)
    normalized = cv2.perspectiveTransform(points, homography).reshape(-1, 2)
    return [(float(x), float(y)) for x, y in normalized]


def _overlay(frame: np.ndarray, clicks: list[tuple[float, float]]) -> np.ndarray:
    view = frame.copy()
    corners = np.asarray(clicks[:4], dtype=np.int32)
    cv2.polylines(view, [corners], True, (70, 220, 70), 3, cv2.LINE_AA)
    for index, (x, y) in enumerate(clicks):
        point = (int(round(x)), int(round(y)))
        color = (70, 220, 70) if index < 4 else (0, 170, 255)
        cv2.drawMarker(view, point, color, cv2.MARKER_CROSS, 28, 2)
        cv2.putText(
            view,
            f"{index + 1}:{POINT_NAMES[index]}",
            (point[0] + 9, point[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            color,
            2,
            cv2.LINE_AA,
        )
    return view


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="http://127.0.0.1:8100/video")
    parser.add_argument(
        "--out",
        default="profiles/components/photoresistor-module",
        help="component profile directory",
    )
    args = parser.parse_args()

    cap = cv2.VideoCapture(_source(args.source))
    if not cap.isOpened():
        raise SystemExit(f"cannot open capture source: {args.source}")
    window = "Photoresistor profile capture: C/SPACE freeze, ESC quit"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    frozen: np.ndarray | None = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                key = cv2.waitKey(30) & 0xFF
                if key == 27:
                    raise KeyboardInterrupt
                continue
            preview = frame.copy()
            cv2.putText(
                preview,
                "4 pins DOWN, component side UP | move sensor close | C/SPACE freeze",
                (16, 34),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (60, 235, 90),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window, preview)
            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                raise KeyboardInterrupt
            if key in (ord("c"), ord("C"), 32):
                frozen = frame.copy()
                break
    except KeyboardInterrupt:
        cap.release()
        cv2.destroyAllWindows()
        return
    finally:
        cap.release()
    cv2.destroyWindow(window)
    if frozen is None:
        return

    try:
        clicks = _annotate(frozen, _detect_blue_pcb_corners(frozen))
    except KeyboardInterrupt:
        cv2.destroyAllWindows()
        return
    normalized_pins = _normalized_pin_positions(clicks[:4], clicks[4:])
    output_dir = Path(args.out).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = output_dir / "reference.jpg"
    overlay_path = output_dir / "reference_overlay.jpg"
    profile_path = output_dir / "vision_profile.json"
    if not cv2.imwrite(str(reference_path), frozen, [cv2.IMWRITE_JPEG_QUALITY, 96]):
        raise IOError(f"failed to write {reference_path}")
    if not cv2.imwrite(str(overlay_path), _overlay(frozen, clicks), [cv2.IMWRITE_JPEG_QUALITY, 96]):
        raise IOError(f"failed to write {overlay_path}")
    profile = {
        "schema_version": "1.0",
        "id": "photoresistor-module",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonical_orientation": "component side up; four header pins pointing down",
        "corner_order": list(POINT_NAMES[:4]),
        "pins": [
            {"id": name, "x_norm": round(position[0], 8), "y_norm": round(position[1], 8)}
            for name, position in zip(POINT_NAMES[4:], normalized_pins)
        ],
        "reference_size": [frozen.shape[1], frozen.shape[0]],
        "reference_corners_px": [[round(x, 3), round(y, 3)] for x, y in clicks[:4]],
        "reference_pins_px": {
            name: [round(x, 3), round(y, 3)]
            for name, (x, y) in zip(POINT_NAMES[4:], clicks[4:])
        },
    }
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"vision profile: {profile_path}")
    print(f"reference overlay: {overlay_path}")


if __name__ == "__main__":
    main()
