# -*- coding: utf-8 -*-
"""Render the deterministic synthetic top-view reference image for the
Arduino UNO Q profile, plus a verification overlay.

Outputs (into profiles/boards/arduino-uno-q/):
  reference_synthetic.png  - ~35 px/mm orthographic top view
  verify_overlay.png       - reference + every pin circled & labelled from board.json

Also (re-)embeds the exact mm->px homography into board.json's reference block
and asserts ORB(nfeatures=1500) finds >= 800 keypoints on the reference.

Run:  .venv python tools/render_reference.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from uno_q_geometry import (  # noqa: E402
    BOARD_JSON,
    BOTTOM_ROW_PINS,
    MM_TO_PX_SYNTHETIC,
    MOUNTING_HOLES_MM,
    MOUNTING_HOLE_DRILL_MM,
    OUTLINE_POLY_MM,
    PROFILE_DIR,
    PX_PER_MM,
    REF_HEIGHT_PX,
    REF_IMAGE_NAME,
    REF_WIDTH_PX,
    TOP_ROW_PINS,
    TOP_ROW_Y_MM,
    BOTTOM_ROW_Y_MM,
    validate_board_json,
)

S = PX_PER_MM

# BGR palette
BG = (22, 22, 22)
PCB = (78, 42, 16)           # dark navy blue
PCB_EDGE = (100, 58, 26)
TRACE = (110, 64, 30)
VIA_RING = (140, 96, 60)
SILK = (242, 246, 246)
HEADER_BODY = (26, 26, 26)
HEADER_EDGE = (52, 52, 52)
HOLE_DARK = (8, 8, 8)
PIN_METAL = (150, 145, 138)
CAN_METAL = (152, 150, 146)
CAN_EDGE = (86, 86, 86)
CHIP_BLACK = (24, 24, 24)
USB_METAL = (165, 162, 156)
HOLE_RING = (146, 142, 136)
PAD_METAL = (128, 124, 118)
LED_DOT = (96, 64, 40)


def mm(v: float) -> int:
    return int(round(v * S))


def mm_pt(x: float, y: float) -> tuple[int, int]:
    return mm(x), mm(y)


def draw_text(img, text, center_xy_px, height_px, color=SILK, angle=0, thickness=None):
    """Draw text centered at center_xy_px, optionally rotated by 90/-90/180 deg."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = height_px / 22.0  # HERSHEY cap height ~22 px at scale 1.0
    if thickness is None:
        thickness = max(1, int(round(scale * 2)))
    (tw, th), base = cv2.getTextSize(text, font, scale, thickness)
    pad = thickness + 2
    canvas = np.zeros((th + base + 2 * pad, tw + 2 * pad), np.uint8)
    cv2.putText(canvas, text, (pad, pad + th), font, scale, 255, thickness, cv2.LINE_AA)
    if angle == 90:
        canvas = cv2.rotate(canvas, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif angle == -90:
        canvas = cv2.rotate(canvas, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        canvas = cv2.rotate(canvas, cv2.ROTATE_180)
    ch, cw = canvas.shape
    cx, cy = int(round(center_xy_px[0])), int(round(center_xy_px[1]))
    x0, y0 = cx - cw // 2, cy - ch // 2
    x1, y1 = x0 + cw, y0 + ch
    sx0, sy0 = max(0, -x0), max(0, -y0)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.shape[1], x1), min(img.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return
    patch = canvas[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
    region = img[y0:y1, x0:x1]
    alpha = patch.astype(np.float32) / 255.0
    for c in range(3):
        region[:, :, c] = (region[:, :, c] * (1 - alpha) + color[c] * alpha).astype(np.uint8)


def pcb_mask() -> np.ndarray:
    mask = np.zeros((REF_HEIGHT_PX, REF_WIDTH_PX), np.uint8)
    poly = np.array([mm_pt(x, y) for x, y in OUTLINE_POLY_MM], np.int32)
    cv2.fillPoly(mask, [poly], 255, cv2.LINE_AA)
    return mask


def render_reference() -> np.ndarray:
    rng = np.random.RandomState(42)  # deterministic
    img = np.full((REF_HEIGHT_PX, REF_WIDTH_PX, 3), BG, np.uint8)

    # --- PCB body -----------------------------------------------------------
    mask = pcb_mask()
    img[mask > 0] = PCB
    poly = np.array([mm_pt(x, y) for x, y in OUTLINE_POLY_MM], np.int32)
    cv2.polylines(img, [poly], True, PCB_EDGE, 3, cv2.LINE_AA)

    # --- deterministic fine detail: traces, vias, passives -------------------
    def inside_detail_zone(x, y):
        # keep clear of header strips / label bands and outside-board area
        return 7.0 < y < 46.0 and 2.0 < x < 66.0

    # traces: 2-3 segment polylines with 45-degree bends
    for _ in range(80):
        x = rng.uniform(3, 63)
        y = rng.uniform(8, 44)
        pts = [(x, y)]
        ang = rng.choice([0, 45, 90, 135, 180, 225, 270, 315])
        for _seg in range(rng.randint(2, 4)):
            length = rng.uniform(2.5, 9.0)
            rad = np.deg2rad(ang)
            x2 = x + length * np.cos(rad)
            y2 = y + length * np.sin(rad)
            if not inside_detail_zone(x2, y2):
                break
            pts.append((x2, y2))
            x, y = x2, y2
            ang = (ang + rng.choice([-45, 45])) % 360
        if len(pts) >= 2:
            arr = np.array([mm_pt(px, py) for px, py in pts], np.int32)
            cv2.polylines(img, [arr], False, TRACE, max(2, mm(0.25)), cv2.LINE_AA)

    # vias
    for _ in range(90):
        x, y = rng.uniform(3, 65), rng.uniform(8, 45)
        if not inside_detail_zone(x, y):
            continue
        c = mm_pt(x, y)
        cv2.circle(img, c, mm(0.4), VIA_RING, -1, cv2.LINE_AA)
        cv2.circle(img, c, mm(0.18), HOLE_DARK, -1, cv2.LINE_AA)

    # passive footprints (0603/0805-ish) with reference designators
    for i in range(38):
        x, y = rng.uniform(4, 62), rng.uniform(9, 44)
        if not inside_detail_zone(x, y):
            continue
        horiz = rng.rand() < 0.5
        w, h = (1.6, 0.8) if horiz else (0.8, 1.6)
        p0 = mm_pt(x - w / 2, y - h / 2)
        p1 = mm_pt(x + w / 2, y + h / 2)
        cv2.rectangle(img, p0, p1, PAD_METAL, -1, cv2.LINE_AA)
        body0 = mm_pt(x - w / 2 + 0.35, y - h / 2 + 0.15) if horiz else mm_pt(
            x - w / 2 + 0.15, y - h / 2 + 0.35)
        body1 = mm_pt(x + w / 2 - 0.35, y + h / 2 - 0.15) if horiz else mm_pt(
            x + w / 2 - 0.15, y + h / 2 - 0.35)
        cv2.rectangle(img, body0, body1, (40, 40, 46), -1, cv2.LINE_AA)
        if i % 3 == 0:
            ref = ("R" if i % 2 else "C") + str(i)
            draw_text(img, ref, mm_pt(x, y - 1.4), mm(0.75), SILK)

    # --- USB-C stub on the left edge (centered ~y=15.2mm like the R3 USB) ----
    cv2.rectangle(img, mm_pt(-1.0, 11.0), mm_pt(4.6, 19.5), USB_METAL, -1, cv2.LINE_AA)
    cv2.rectangle(img, mm_pt(-1.0, 11.0), mm_pt(4.6, 19.5), (90, 90, 90), 3, cv2.LINE_AA)
    cv2.rectangle(img, mm_pt(0.4, 12.2), mm_pt(3.8, 18.3), (60, 60, 60), 2, cv2.LINE_AA)
    draw_text(img, "USB-C", mm_pt(6.8, 15.2), mm(1.0), SILK, angle=90)

    # --- SoC shield can (QRB2210) --------------------------------------------
    cv2.rectangle(img, mm_pt(17.5, 17.0), mm_pt(37.5, 37.0), CAN_METAL, -1, cv2.LINE_AA)
    cv2.rectangle(img, mm_pt(17.5, 17.0), mm_pt(37.5, 37.0), CAN_EDGE, 4, cv2.LINE_AA)
    # brushed-metal texture lines (deterministic)
    for k in range(10):
        yy = 18.2 + k * 1.8
        cv2.line(img, mm_pt(18.2, yy), mm_pt(36.8, yy), (140, 138, 134), 1, cv2.LINE_AA)
    draw_text(img, "QUALCOMM", mm_pt(27.5, 25.6), mm(1.5), (70, 70, 70))
    draw_text(img, "QRB2210", mm_pt(27.5, 28.4), mm(1.5), (70, 70, 70))

    # --- STM32 chip -----------------------------------------------------------
    cv2.rectangle(img, mm_pt(41.0, 30.0), mm_pt(49.0, 38.0), CHIP_BLACK, -1, cv2.LINE_AA)
    cv2.rectangle(img, mm_pt(41.0, 30.0), mm_pt(49.0, 38.0), (70, 70, 70), 2, cv2.LINE_AA)
    # QFP pin stubs
    for k in range(12):
        xx = 41.6 + k * 0.62
        cv2.line(img, mm_pt(xx, 29.4), mm_pt(xx, 30.0), PIN_METAL, 2, cv2.LINE_AA)
        cv2.line(img, mm_pt(xx, 38.0), mm_pt(xx, 38.6), PIN_METAL, 2, cv2.LINE_AA)
    for k in range(12):
        yy = 30.6 + k * 0.62
        cv2.line(img, mm_pt(40.4, yy), mm_pt(41.0, yy), PIN_METAL, 2, cv2.LINE_AA)
        cv2.line(img, mm_pt(49.0, yy), mm_pt(49.6, yy), PIN_METAL, 2, cv2.LINE_AA)
    cv2.circle(img, mm_pt(42.1, 31.1), mm(0.35), (90, 90, 90), -1, cv2.LINE_AA)  # pin-1 dot
    draw_text(img, "STM32", mm_pt(45.0, 33.4), mm(1.1), (200, 200, 200))
    draw_text(img, "U585", mm_pt(45.0, 35.2), mm(1.1), (200, 200, 200))

    # --- 8x13 LED matrix dot grid (right-center, like the UNO Q) -------------
    m_x0, m_y0, pitch = 51.0, 22.0, 1.3
    cv2.rectangle(img, mm_pt(m_x0 - 1.0, m_y0 - 1.0),
                  mm_pt(m_x0 + 12 * pitch + 1.0, m_y0 + 7 * pitch + 1.0),
                  (58, 30, 10), -1, cv2.LINE_AA)
    for r in range(8):
        for c in range(13):
            cv2.circle(img, mm_pt(m_x0 + c * pitch, m_y0 + r * pitch),
                       mm(0.32), LED_DOT, -1, cv2.LINE_AA)
    draw_text(img, "LED MATRIX 8x13", mm_pt(m_x0 + 6 * pitch, m_y0 + 7 * pitch + 2.4),
              mm(0.9), SILK)

    # --- branding -------------------------------------------------------------
    draw_text(img, "ARDUINO", mm_pt(30.0, 10.5), mm(3.2), SILK, thickness=6)
    draw_text(img, "UNO Q", mm_pt(30.0, 14.2), mm(2.4), SILK, thickness=5)
    draw_text(img, "R", mm_pt(40.5, 9.2), mm(1.0), SILK)  # (R) mark stand-in
    cv2.circle(img, mm_pt(40.5, 9.25), mm(0.85), SILK, 2, cv2.LINE_AA)

    # --- mounting holes ---------------------------------------------------------
    r_hole = MOUNTING_HOLE_DRILL_MM / 2.0
    for hx, hy in MOUNTING_HOLES_MM.values():
        c = mm_pt(hx, hy)
        cv2.circle(img, c, mm(r_hole + 1.05), HOLE_RING, -1, cv2.LINE_AA)
        cv2.circle(img, c, mm(r_hole), BG, -1, cv2.LINE_AA)
        cv2.circle(img, c, mm(r_hole), (60, 60, 60), 2, cv2.LINE_AA)

    # --- header strips with per-pin holes ---------------------------------------
    def header_strip(x_first, x_last, y_row):
        p0 = mm_pt(x_first - 1.27, y_row - 1.27)
        p1 = mm_pt(x_last + 1.27, y_row + 1.27)
        cv2.rectangle(img, p0, p1, HEADER_BODY, -1, cv2.LINE_AA)
        cv2.rectangle(img, p0, p1, HEADER_EDGE, 2, cv2.LINE_AA)

    def pin_hole(x, y):
        half = 0.5  # 1.0 mm square opening
        cv2.rectangle(img, mm_pt(x - half, y - half), mm_pt(x + half, y + half),
                      HOLE_DARK, -1, cv2.LINE_AA)
        # metal contact glint inside the opening
        cv2.rectangle(img, mm_pt(x - 0.22, y - 0.22), mm_pt(x + 0.22, y + 0.22),
                      PIN_METAL, -1, cv2.LINE_AA)

    top = TOP_ROW_PINS
    bot = BOTTOM_ROW_PINS
    header_strip(top[0][1], top[9][1], TOP_ROW_Y_MM)     # SCL..D8
    header_strip(top[10][1], top[17][1], TOP_ROW_Y_MM)   # D7..D0
    header_strip(bot[0][1], bot[7][1], BOTTOM_ROW_Y_MM)  # NC..VIN
    header_strip(bot[8][1], bot[13][1], BOTTOM_ROW_Y_MM)  # A0..A5
    for _pid, x in top:
        pin_hole(x, TOP_ROW_Y_MM)
    for _pid, x in bot:
        pin_hole(x, BOTTOM_ROW_Y_MM)

    # --- silkscreen pin labels ----------------------------------------------
    board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    silk_by_id = {p["id"]: p["silkscreen"] for p in board["pins"]}
    for pid, x in top:
        label = silk_by_id.get(pid, pid)
        if label:
            draw_text(img, label, mm_pt(x, TOP_ROW_Y_MM + 3.55), mm(1.0), SILK, angle=-90)
    for pid, x in bot:
        label = silk_by_id.get(pid, pid)
        if label:
            draw_text(img, label, mm_pt(x, BOTTOM_ROW_Y_MM - 3.55), mm(1.0), SILK, angle=-90)
    # small header names (kept clear of the pin-label bands)
    draw_text(img, "JDIGITAL", mm_pt(8.5, 5.6), mm(0.9), SILK)
    draw_text(img, "JANALOG", mm_pt(22.5, 47.5), mm(0.9), SILK)

    return img


def render_overlay(ref: np.ndarray) -> np.ndarray:
    """reference + every pin circled & labelled straight from board.json."""
    board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    H = np.array(board["reference"]["mm_to_px"], np.float64)
    overlay = ref.copy()

    for p in board["pins"]:
        x, y, _z = p["pos_mm"]
        v = H @ np.array([x, y, 1.0])
        px, py = v[0] / v[2], v[1] / v[2]
        c = (int(round(px)), int(round(py)))
        cv2.circle(overlay, c, 22, (60, 220, 60), 3, cv2.LINE_AA)
        cv2.circle(overlay, c, 3, (60, 220, 60), -1, cv2.LINE_AA)
        if p["header"] == "JDIGITAL":
            # vertical ids on/below the top strip
            draw_text(overlay, p["id"], (px, py + 34), 26, (80, 240, 240), angle=-90)
        else:
            # horizontal ids below the bottom strip, staggered on two lines
            ty = py + 45 if p["index"] % 2 == 0 else py + 75
            draw_text(overlay, p["id"], (px, ty), 22, (80, 240, 240))

    for name, (hx, hy) in MOUNTING_HOLES_MM.items():
        v = H @ np.array([hx, hy, 1.0])
        c = (int(round(v[0] / v[2])), int(round(v[1] / v[2])))
        cv2.drawMarker(overlay, c, (0, 120, 255), cv2.MARKER_CROSS, 44, 3, cv2.LINE_AA)
        tx = c[0] - 130 if hx > 60.0 else c[0]
        draw_text(overlay, name, (tx, c[1] - 40), 22, (0, 120, 255))

    # board-frame corners (outline quad convention)
    w_mm, h_mm = board["board"]["outline_mm"]
    for cx, cy in [(0, 0), (w_mm, 0), (w_mm, h_mm), (0, h_mm)]:
        v = H @ np.array([cx, cy, 1.0])
        c = (int(round(v[0] / v[2])), int(round(v[1] / v[2])))
        cv2.drawMarker(overlay, c, (255, 80, 255), cv2.MARKER_TILTED_CROSS, 36, 3, cv2.LINE_AA)
    return overlay


def main() -> None:
    ref = render_reference()

    ref_path = PROFILE_DIR / REF_IMAGE_NAME
    ok = cv2.imwrite(str(ref_path), ref)
    assert ok, f"failed to write {ref_path}"
    print(f"[render] wrote {ref_path} ({ref.shape[1]}x{ref.shape[0]})")

    # Embed the exact reference block into board.json.
    board = json.loads(BOARD_JSON.read_text(encoding="utf-8"))
    board["reference"] = {
        "image": REF_IMAGE_NAME,
        "width_px": int(ref.shape[1]),
        "height_px": int(ref.shape[0]),
        "mm_to_px": MM_TO_PX_SYNTHETIC,
    }
    BOARD_JSON.write_text(
        json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert ref.shape[1] == REF_WIDTH_PX and ref.shape[0] == REF_HEIGHT_PX
    print(f"[render] embedded mm_to_px (pure scale {PX_PER_MM} px/mm) into board.json")

    # Overlay from board.json (round-trips the stored homography).
    overlay = render_overlay(ref)
    overlay_path = PROFILE_DIR / "verify_overlay.png"
    ok = cv2.imwrite(str(overlay_path), overlay)
    assert ok, f"failed to write {overlay_path}"
    print(f"[render] wrote {overlay_path}")

    # ORB feature richness check.
    gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=1500)
    kps = orb.detect(gray, None)
    print(f"[render] ORB(nfeatures=1500) keypoints on reference: {len(kps)}")
    assert len(kps) >= 800, f"reference too feature-poor for ORB: {len(kps)} < 800"

    validate_board_json(BOARD_JSON)


if __name__ == "__main__":
    main()
