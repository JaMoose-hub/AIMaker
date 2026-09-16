r"""Calibrate webcam intrinsics from checkerboard images.

Example (PowerShell):
    python tools/calibrate_camera.py .\calibration\checkerboard \
        --output profiles\boards\arduino-uno-q\camera.json

Take 20-30 sharp images of the same printed checkerboard at different
positions, rotations, and tilts.  The output format is consumed by
``backend/app/vision/camera_model.py`` and is intentionally plain JSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

DEFAULT_MIN_VIEWS = 20
DEFAULT_MAX_RMS_PX = 1.2
DEFAULT_MAX_VIEW_RMS_PX = 2.5
DEFAULT_MIN_COVERAGE = 0.30


def _images(folder: Path) -> list[Path]:
    suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)


def _corners(gray: np.ndarray, pattern: tuple[int, int]):
    # findChessboardCornersSB is more tolerant of perspective and lighting;
    # classic detection is retained for older OpenCV builds.
    if hasattr(cv2, "findChessboardCornersSB"):
        ok, corners = cv2.findChessboardCornersSB(gray, pattern, flags=cv2.CALIB_CB_EXHAUSTIVE)
        if ok:
            return corners.astype(np.float32)
    ok, corners = cv2.findChessboardCorners(
        gray, pattern,
        flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not ok:
        return None
    return cv2.cornerSubPix(
        gray, corners, (11, 11), (-1, -1),
        (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001),
    ).astype(np.float32)


def calibration_quality_report(
    image_size: tuple[int, int],
    object_points: list[np.ndarray],
    image_points: list[np.ndarray],
    rvecs: list[np.ndarray],
    tvecs: list[np.ndarray],
    camera_matrix: np.ndarray,
    distortion: np.ndarray,
    overall_rms_px: float,
    *,
    max_rms_px: float = DEFAULT_MAX_RMS_PX,
    max_view_rms_px: float = DEFAULT_MAX_VIEW_RMS_PX,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict[str, object]:
    """Return auditable quality metrics and a write/no-write decision."""
    if max_rms_px <= 0 or max_view_rms_px <= 0 or not 0 < min_coverage <= 1:
        raise ValueError("invalid camera calibration quality thresholds")
    width, height = float(image_size[0]), float(image_size[1])
    if width <= 0 or height <= 0 or not image_points:
        return {
            "quality_status": "reject",
            "coverage_fraction": 0.0,
            "max_view_rms_px": float("inf"),
            "view_rms_px": [],
            "quality_issues": ["no calibration views"],
        }

    all_corners = np.concatenate(
        [np.asarray(points, dtype=np.float64).reshape(-1, 2) for points in image_points],
        axis=0,
    )
    min_xy = all_corners.min(axis=0)
    max_xy = all_corners.max(axis=0)
    coverage = float(
        max(0.0, max_xy[0] - min_xy[0])
        * max(0.0, max_xy[1] - min_xy[1])
        / (width * height)
    )

    view_errors: list[float] = []
    for obj, observed, rvec, tvec in zip(object_points, image_points, rvecs, tvecs):
        projected, _ = cv2.projectPoints(
            np.asarray(obj, dtype=np.float64), rvec, tvec,
            np.asarray(camera_matrix, dtype=np.float64),
            np.asarray(distortion, dtype=np.float64),
        )
        delta = projected.reshape(-1, 2) - np.asarray(observed, dtype=np.float64).reshape(-1, 2)
        view_errors.append(float(np.sqrt(np.mean(np.sum(delta * delta, axis=1)))))

    max_view_rms = max(view_errors) if view_errors else float("inf")
    issues: list[str] = []
    if float(overall_rms_px) > float(max_rms_px):
        issues.append(f"overall RMS {float(overall_rms_px):.3f}px > {float(max_rms_px):.3f}px")
    if max_view_rms > float(max_view_rms_px):
        issues.append(f"worst-view RMS {max_view_rms:.3f}px > {float(max_view_rms_px):.3f}px")
    if coverage < float(min_coverage):
        issues.append(f"corner coverage {coverage:.3f} < {float(min_coverage):.3f}")

    return {
        "quality_status": "ok" if not issues else "reject",
        "coverage_fraction": coverage,
        "max_view_rms_px": float(max_view_rms),
        "view_rms_px": view_errors,
        "quality_issues": issues,
    }


def calibrate(
    folder: Path,
    output: Path,
    pattern: tuple[int, int],
    square_mm: float,
    *,
    min_views: int = DEFAULT_MIN_VIEWS,
    max_rms_px: float = DEFAULT_MAX_RMS_PX,
    max_view_rms_px: float = DEFAULT_MAX_VIEW_RMS_PX,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
) -> dict:
    paths = _images(folder)
    if not paths:
        raise SystemExit(f"no calibration images found in {folder}")
    cols, rows = pattern
    object_points = np.zeros((rows * cols, 3), np.float32)
    object_points[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2) * float(square_mm)

    obj: list[np.ndarray] = []
    img: list[np.ndarray] = []
    image_size: tuple[int, int] | None = None
    used: list[str] = []
    for path in paths:
        frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            continue
        size = (int(frame.shape[1]), int(frame.shape[0]))
        if image_size is None:
            image_size = size
        if size != image_size:
            print(f"skip {path.name}: size {size} != first image {image_size}")
            continue
        corners = _corners(frame, pattern)
        if corners is None:
            print(f"no board: {path.name}")
            continue
        obj.append(object_points.copy())
        img.append(corners)
        used.append(path.name)

    if min_views < 1:
        raise ValueError("min_views must be positive")
    if image_size is None or len(obj) < min_views:
        raise SystemExit(f"need at least {min_views} valid views; found {len(obj)}")
    rms, camera_matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(
        obj, img, image_size, None, None,
    )
    quality = calibration_quality_report(
        image_size, obj, img, rvecs, tvecs, camera_matrix, distortion, rms,
        max_rms_px=max_rms_px,
        max_view_rms_px=max_view_rms_px,
        min_coverage=min_coverage,
    )
    if quality["quality_status"] != "ok":
        issues = "; ".join(str(item) for item in quality["quality_issues"])
        raise SystemExit(f"camera calibration rejected: {issues}")
    dist = distortion.reshape(-1).tolist()
    result = {
        "fx": float(camera_matrix[0, 0]),
        "fy": float(camera_matrix[1, 1]),
        "cx": float(camera_matrix[0, 2]),
        "cy": float(camera_matrix[1, 2]),
        "dist": [float(v) for v in dist],
        "image_size": [image_size[0], image_size[1]],
        "rms_reprojection_error_px": float(rms),
        "quality_status": quality["quality_status"],
        "coverage_fraction": float(quality["coverage_fraction"]),
        "max_view_rms_px": float(quality["max_view_rms_px"]),
        "view_rms_px": [float(value) for value in quality["view_rms_px"]],
        "quality_issues": list(quality["quality_issues"]),
        "pattern": {"cols": cols, "rows": rows, "square_mm": float(square_mm)},
        "images_used": used,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image_dir", type=Path)
    parser.add_argument(
        "--output", type=Path,
        default=Path("calibration/c920-1080p.json"),
    )
    parser.add_argument("--pattern-cols", type=int, default=9,
                        help="inner checkerboard corners across (default: 9)")
    parser.add_argument("--pattern-rows", type=int, default=6,
                        help="inner checkerboard corners down (default: 6)")
    parser.add_argument("--square-mm", type=float, default=25.0)
    parser.add_argument("--min-views", type=int, default=DEFAULT_MIN_VIEWS,
                        help="minimum valid checkerboard views (default: 20)")
    parser.add_argument("--max-rms-px", type=float, default=DEFAULT_MAX_RMS_PX,
                        help="maximum overall reprojection RMS (default: 1.2px)")
    parser.add_argument("--max-view-rms-px", type=float, default=DEFAULT_MAX_VIEW_RMS_PX,
                        help="maximum single-view RMS (default: 2.5px)")
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                        help="minimum union corner bounding-box coverage (default: 0.30)")
    args = parser.parse_args()
    if (args.pattern_cols < 2 or args.pattern_rows < 2 or args.square_mm <= 0
            or args.min_views < 1 or args.max_rms_px <= 0
            or args.max_view_rms_px <= 0 or not 0 < args.min_coverage <= 1):
        parser.error("invalid checkerboard or quality thresholds")
    result = calibrate(
        args.image_dir, args.output,
        (args.pattern_cols, args.pattern_rows), args.square_mm,
        min_views=args.min_views,
        max_rms_px=args.max_rms_px,
        max_view_rms_px=args.max_view_rms_px,
        min_coverage=args.min_coverage,
    )
    print(
        f"wrote {args.output} using {len(result['images_used'])} views; "
        f"RMS reprojection error {result['rms_reprojection_error_px']:.3f}px; "
        f"coverage {result['coverage_fraction']:.3f}"
    )


if __name__ == "__main__":
    main()
