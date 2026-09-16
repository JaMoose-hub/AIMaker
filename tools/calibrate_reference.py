# -*- coding: utf-8 -*-
"""Calibrate a real board photo as the profile reference image.

Computes the board-mm -> photo-px homography from the four UNO mounting
holes, updates board.json's reference block (backing up board.json first),
pre-computes ORB + SIFT keypoints/descriptors into features.npz next to
board.json (including the ``xy_mm``/``desc`` board-mm arrays consumed as a
feature cache by the backend's PipelineDetector), and renders a verification
overlay PNG.

Interactive mode (default, needs a display):
    .venv python tools/calibrate_reference.py --photo path\\to\\photo.jpg
  A window opens; click the 4 mounting holes IN THIS ORDER (USB-C on the
  left, viewed from above):
    1. top_left      (15.24,  2.54) mm  - next to the top header, USB side
    2. top_right     (66.04, 17.78) mm  - right edge, upper hole
    3. bottom_right  (66.04, 45.72) mm  - right edge, lower hole
    4. bottom_left   (13.97, 50.80) mm  - next to the bottom header, USB side
  Keys: u = undo last click, ENTER = accept (after 4 clicks), ESC = abort.

Headless mode:
    .venv python tools/calibrate_reference.py --photo photo.jpg ^
        --holes "x1,y1 x2,y2 x3,y3 x4,y4"
  Pixel coordinates in the same TL,TR,BR,BL order.

Options:
    --board-json PATH   profile to update (default: arduino-uno-q)
    --dry-run           compute + report + write overlay, but do not touch
                        board.json / features.npz
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from uno_q_geometry import (  # noqa: E402
    BOARD_JSON,
    MOUNTING_HOLES_MM,
    MOUNTING_HOLE_ORDER,
    validate_board_json,
)
from scale_quality import (  # noqa: E402
    DEFAULT_MARGIN_FRAC,
    DEFAULT_MIN_PIN_PITCH_PX,
    DEFAULT_MIN_PX_PER_MM,
    filter_reference_features,
    profile_pin_geometry,
    reference_scale_report,
)

MIN_FEATURE_COUNT = 200

CLICK_HELP = " -> ".join(MOUNTING_HOLE_ORDER)


def collect_clicks_interactive(img: np.ndarray) -> list[tuple[float, float]]:
    clicks: list[tuple[float, float]] = []
    win = "calibrate: click mounting holes (" + CLICK_HELP + ")"

    def redraw():
        vis = img.copy()
        for i, (x, y) in enumerate(clicks):
            c = (int(round(x)), int(round(y)))
            cv2.drawMarker(vis, c, (0, 120, 255), cv2.MARKER_CROSS, 30, 2)
            cv2.putText(vis, f"{i + 1}:{MOUNTING_HOLE_ORDER[i]}", (c[0] + 12, c[1] - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 120, 255), 2, cv2.LINE_AA)
        nxt = (MOUNTING_HOLE_ORDER[len(clicks)] if len(clicks) < 4
               else "ENTER to accept / u to undo")
        cv2.putText(vis, f"click {len(clicks)}/4 - next: {nxt}", (16, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (60, 220, 60), 2, cv2.LINE_AA)
        cv2.imshow(win, vis)

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < 4:
            clicks.append((float(x), float(y)))
            redraw()

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(win, on_mouse)
    redraw()
    while True:
        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            cv2.destroyAllWindows()
            raise SystemExit("aborted by user")
        if key == ord("u") and clicks:
            clicks.pop()
            redraw()
        if key in (10, 13) and len(clicks) == 4:  # ENTER
            break
    cv2.destroyAllWindows()
    return clicks


def parse_holes_arg(arg: str) -> list[tuple[float, float]]:
    pts = []
    for token in arg.replace(";", " ").split():
        x_s, y_s = token.split(",")
        pts.append((float(x_s), float(y_s)))
    if len(pts) != 4:
        raise SystemExit(f'--holes needs exactly 4 "x,y" pairs ({CLICK_HELP}), got {len(pts)}')
    return pts


def compute_homography(hole_px: list[tuple[float, float]]) -> np.ndarray:
    src = np.array([MOUNTING_HOLES_MM[k] for k in MOUNTING_HOLE_ORDER], np.float64)
    dst = np.array(hole_px, np.float64)
    H = cv2.getPerspectiveTransform(src.astype(np.float32), dst.astype(np.float32))
    H = H.astype(np.float64)
    H /= H[2, 2]
    return H


def project(H: np.ndarray, pts_mm: np.ndarray) -> np.ndarray:
    ones = np.ones((pts_mm.shape[0], 1))
    v = (H @ np.hstack([pts_mm, ones]).T).T
    return v[:, :2] / v[:, 2:3]


def compute_features(img: np.ndarray, mm_to_px: np.ndarray) -> dict[str, np.ndarray]:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    out: dict[str, np.ndarray] = {
        "image_shape": np.array(img.shape[:2], np.int32),  # (h, w)
    }
    orb = cv2.ORB_create(nfeatures=4000)
    kps, desc = orb.detectAndCompute(gray, None)
    out["orb_pts"] = np.array([k.pt for k in kps], np.float32).reshape(-1, 2)
    out["orb_size"] = np.array([k.size for k in kps], np.float32)
    out["orb_angle"] = np.array([k.angle for k in kps], np.float32)
    out["orb_response"] = np.array([k.response for k in kps], np.float32)
    out["orb_octave"] = np.array([k.octave for k in kps], np.int32)
    out["orb_desc"] = desc if desc is not None else np.zeros((0, 32), np.uint8)

    # Keys consumed by app.vision.pipeline_detector's feature cache loader:
    # ORB keypoints mapped from photo-px into board-mm via the inverse of the
    # mm_to_px homography, plus their descriptors.
    px_to_mm = np.linalg.inv(np.asarray(mm_to_px, np.float64))
    if len(out["orb_pts"]):
        out["xy_mm"] = project(px_to_mm, out["orb_pts"].astype(np.float64))
    else:
        out["xy_mm"] = np.zeros((0, 2), np.float64)
    out["desc"] = np.asarray(out["orb_desc"], np.uint8)

    sift = cv2.SIFT_create()
    kps, desc = sift.detectAndCompute(gray, None)
    out["sift_pts"] = np.array([k.pt for k in kps], np.float32).reshape(-1, 2)
    out["sift_size"] = np.array([k.size for k in kps], np.float32)
    out["sift_angle"] = np.array([k.angle for k in kps], np.float32)
    out["sift_response"] = np.array([k.response for k in kps], np.float32)
    out["sift_octave"] = np.array([k.octave for k in kps], np.int32)
    out["sift_desc"] = desc if desc is not None else np.zeros((0, 128), np.float32)
    return out


def render_overlay(img: np.ndarray, H: np.ndarray, board: dict,
                   hole_px: list[tuple[float, float]]) -> np.ndarray:
    vis = img.copy()
    pts = np.array([[p["pos_mm"][0], p["pos_mm"][1]] for p in board["pins"]], np.float64)
    proj = project(H, pts)
    for p, (px, py) in zip(board["pins"], proj):
        c = (int(round(px)), int(round(py)))
        cv2.circle(vis, c, 10, (60, 220, 60), 2, cv2.LINE_AA)
        cv2.putText(vis, p["id"], (c[0] + 8, c[1] - 8), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (80, 240, 240), 1, cv2.LINE_AA)
    for name, (x, y) in zip(MOUNTING_HOLE_ORDER, hole_px):
        c = (int(round(x)), int(round(y)))
        cv2.drawMarker(vis, c, (0, 120, 255), cv2.MARKER_CROSS, 28, 2, cv2.LINE_AA)
        cv2.putText(vis, name, (c[0] + 10, c[1] + 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (0, 120, 255), 1, cv2.LINE_AA)
    w_mm, h_mm = board["board"]["outline_mm"]
    corners = project(H, np.array([[0, 0], [w_mm, 0], [w_mm, h_mm], [0, h_mm]], np.float64))
    cv2.polylines(vis, [corners.astype(np.int32)], True, (255, 80, 255), 2, cv2.LINE_AA)
    return vis


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photo", required=True, help="board photo to calibrate")
    ap.add_argument("--board-json", default=str(BOARD_JSON),
                    help=f"board.json to update (default: {BOARD_JSON})")
    ap.add_argument("--holes", default=None,
                    help=f'headless mode: 4 "x,y" px pairs in order {CLICK_HELP}')
    ap.add_argument("--dry-run", action="store_true",
                    help="report + overlay only; do not modify board.json/features.npz")
    ap.add_argument("--min-pin-pitch-px", type=float, default=DEFAULT_MIN_PIN_PITCH_PX,
                    help="reject writes below this projected adjacent-pin pitch")
    ap.add_argument("--min-px-per-mm", type=float, default=DEFAULT_MIN_PX_PER_MM,
                    help="reject writes below this projected board scale")
    ap.add_argument("--margin-frac", type=float, default=DEFAULT_MARGIN_FRAC,
                    help="board-mm feature-cache margin (default: 0.08)")
    ap.add_argument("--min-features", type=int, default=MIN_FEATURE_COUNT,
                    help="reject writes below this many board-region ORB features")
    args = ap.parse_args()

    if (args.min_pin_pitch_px <= 0 or args.min_px_per_mm <= 0
            or args.margin_frac < 0 or args.min_features <= 0):
        ap.error("scale thresholds, margin, and min-features must be positive")

    board_json = Path(args.board_json).resolve()
    profile_dir = board_json.parent
    board = json.loads(board_json.read_text(encoding="utf-8"))

    photo_path = Path(args.photo).resolve()
    img = cv2.imread(str(photo_path), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read photo: {photo_path}")
    h_px, w_px = img.shape[:2]
    print(f"[calibrate] photo {photo_path.name} ({w_px}x{h_px})")

    if args.holes:
        hole_px = parse_holes_arg(args.holes)
    else:
        hole_px = collect_clicks_interactive(img)
    for name, (x, y) in zip(MOUNTING_HOLE_ORDER, hole_px):
        print(f"[calibrate]   {name:13s} px=({x:.2f}, {y:.2f})")

    H = compute_homography(hole_px)
    print("[calibrate] mm_to_px homography:")
    for row in H:
        print(f"[calibrate]   [{row[0]: .6f}, {row[1]: .6f}, {row[2]: .6f}]")

    # Residuals at the calibration points (exact-4-point fit -> ~0 by design;
    # nonzero would mean a degenerate click set).
    src = np.array([MOUNTING_HOLES_MM[k] for k in MOUNTING_HOLE_ORDER], np.float64)
    resid = np.linalg.norm(project(H, src) - np.array(hole_px), axis=1)
    print(f"[calibrate] hole reprojection residuals px: "
          + ", ".join(f"{r:.4f}" for r in resid))

    # Compare against the profile's previous homography, if any (round-trip check).
    pins_mm = np.array([[p["pos_mm"][0], p["pos_mm"][1]] for p in board["pins"]], np.float64)
    old = board.get("reference", {}).get("mm_to_px")
    if old is not None:
        H_old = np.array(old, np.float64)
        delta = np.linalg.norm(project(H, pins_mm) - project(H_old, pins_mm), axis=1)
        print(f"[calibrate] max pin position delta vs previous reference: "
              f"{delta.max():.4f} px (mean {delta.mean():.4f})")

    scale = reference_scale_report(
        H,
        profile_pin_geometry(board),
        min_pin_pitch_px=args.min_pin_pitch_px,
        min_px_per_mm=args.min_px_per_mm,
    )
    print(
        f"[calibrate] projected pin scale: {scale['pitch_px']:.2f}px/pitch, "
        f"{scale['px_per_mm']:.2f}px/mm ({scale['status']})"
    )

    overlay = render_overlay(img, H, board, hole_px)
    overlay_path = profile_dir / "calibration_overlay.png"
    cv2.imwrite(str(overlay_path), overlay)
    print(f"[calibrate] wrote {overlay_path}")

    feats = compute_features(img, H)
    filtered_feats, board_feature_count = filter_reference_features(
        feats,
        tuple(board["board"]["outline_mm"]),
        margin_frac=args.margin_frac,
    )
    print(
        f"[calibrate] board-region ORB cache: {board_feature_count} features "
        f"(minimum {args.min_features})"
    )

    if scale["status"] != "ok" and not args.dry_run:
        raise SystemExit(
            "[calibrate] refusing to update profile: projected scale is below "
            f"the physical gate ({scale['pitch_px']:.2f}px/pitch, "
            f"{scale['px_per_mm']:.2f}px/mm)"
        )
    if board_feature_count < args.min_features and not args.dry_run:
        raise SystemExit(
            "[calibrate] refusing to update profile: board-region feature "
            f"count {board_feature_count} is below {args.min_features}"
        )

    if args.dry_run:
        print("[calibrate] dry run - board.json and features.npz untouched")
        return

    # Back up board.json, then update its reference block.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = board_json.with_suffix(f".json.bak-{stamp}")
    shutil.copy2(board_json, backup)
    print(f"[calibrate] backed up board.json -> {backup.name}")

    # The reference image must live in the profile folder (referenced by filename).
    if photo_path.parent != profile_dir:
        ref_name = "reference_photo" + photo_path.suffix.lower()
        shutil.copy2(photo_path, profile_dir / ref_name)
        print(f"[calibrate] copied photo into profile as {ref_name}")
    else:
        ref_name = photo_path.name

    board["reference"] = {
        "image": ref_name,
        "width_px": int(w_px),
        "height_px": int(h_px),
        "mm_to_px": [[float(v) for v in row] for row in H],
    }
    board_json.write_text(
        json.dumps(board, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[calibrate] updated reference block in {board_json.name}")

    feats_path = profile_dir / "features.npz"
    np.savez_compressed(feats_path, **filtered_feats)
    print(f"[calibrate] wrote {feats_path.name} "
          f"(ORB {len(filtered_feats.get('orb_pts', []))} kp, "
          f"SIFT {len(filtered_feats.get('sift_pts', []))} kp, "
          f"pipeline cache xy_mm/desc {len(filtered_feats.get('xy_mm', []))} kp)")

    validate_board_json(board_json)


if __name__ == "__main__":
    main()
