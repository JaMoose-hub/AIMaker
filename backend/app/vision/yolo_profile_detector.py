"""YOLO board localization + profile-driven 6-DoF GPIO projection."""
from __future__ import annotations

from dataclasses import replace

import logging
from pathlib import Path

import cv2
import numpy as np

from app.vision.camera_model import (
    board_to_vision,
    board_outline_mm,
    load_camera,
    project_board,
    project_points,
    project_wire_exclusion,
)
from app.vision.interface import DetectionResult, PinDetection
from app.vision.body_tracking import body_observation
from app.vision.eye_board_search import EyeBoardYoloSearch
from app.vision.smoothing import PoseFilter
from app.vision.pi5_pin_stability import PinImageAnchor, PinUpdateGate
from app.vision.pi5_j8_geometry import align_pi5_j8
from app.vision.yolo_pose import (
    BoardPoseLocator,
    create_yolo_pose_locator,
    refine_board_corners_from_pcb,
)

log = logging.getLogger(__name__)


def _canonical_reference_board(profile, profile_dir: Path) -> np.ndarray | None:
    """Warp the profile reference into semantic TL/TR/BR/BL orientation."""
    try:
        reference_path = Path(profile_dir) / profile.reference.image
        image = cv2.imread(str(reference_path), cv2.IMREAD_COLOR)
        if image is None:
            return None
        transform_mm_to_px = np.asarray(profile.reference.mm_to_px, dtype=np.float64)
        if transform_mm_to_px.shape != (3, 3):
            return None
        outline = board_outline_mm(profile.board.outline_mm)[:, :2]
        homogeneous = np.column_stack([outline, np.ones(4, dtype=np.float64)])
        projected = homogeneous @ transform_mm_to_px.T
        if np.any(np.abs(projected[:, 2]) < 1e-9):
            return None
        source = np.ascontiguousarray(
            projected[:, :2] / projected[:, 2:], dtype=np.float32
        )
        width = 480
        board_w, board_h = (float(v) for v in profile.board.outline_mm)
        height = max(32, int(round(width * board_h / max(board_w, 1e-9))))
        destination = np.array(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )
        matrix = cv2.getPerspectiveTransform(source, destination)
        return cv2.warpPerspective(image, matrix, (width, height))
    except (AttributeError, TypeError, ValueError, cv2.error):
        log.warning("cannot build canonical board reference", exc_info=True)
        return None


def _ordered_quad_ok(points: np.ndarray, frame_size: tuple[int, int]) -> bool:
    pts = np.asarray(points, dtype=np.float64)
    if pts.shape != (4, 2) or not np.all(np.isfinite(pts)):
        return False
    edges = np.roll(pts, -1, axis=0) - pts
    next_edges = np.roll(edges, -1, axis=0)
    cross = edges[:, 0] * next_edges[:, 1] - edges[:, 1] * next_edges[:, 0]
    if not (np.all(cross > 0.0) or np.all(cross < 0.0)):
        return False
    area = 0.5 * abs(
        float(np.dot(pts[:, 0], np.roll(pts[:, 1], -1))
              - np.dot(pts[:, 1], np.roll(pts[:, 0], -1)))
    )
    frame_area = float(frame_size[0] * frame_size[1])
    return frame_area > 0.0 and 0.005 <= area / frame_area <= 0.95


def _quad_area(points: np.ndarray) -> float:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    return abs(float(cv2.contourArea(points)))


def _pi_corner_box_consistent(observation) -> bool:
    """Reject collapsed four-corner hypotheses before contour expansion.

    This is a geometry plausibility check, not board identity verification.
    The captured TFT false positives put a tiny quad inside a large box.
    Extremely foreshortened boards may need reacquisition; never expand such
    a hypothesis onto an unrelated blue PCB and call it confirmed Pi pins.
    """
    corners = np.asarray(observation.corners_px, dtype=np.float32)
    box = np.asarray(observation.box_xyxy, dtype=np.float64)
    if corners.shape != (4, 2) or box.shape != (4,):
        return False
    if not np.isfinite(corners).all() or not np.isfinite(box).all():
        return False
    width, height = box[2:] - box[:2]
    if width <= 0 or height <= 0 or not cv2.isContourConvex(corners):
        return False
    return 0.18 <= _quad_area(corners) / (width * height) <= 1.5


def _quad_motion_px(current: np.ndarray, previous: np.ndarray) -> float:
    """Median corresponding-corner displacement (robust to one bad corner)."""
    current = np.asarray(current, dtype=np.float64).reshape(4, 2)
    previous = np.asarray(previous, dtype=np.float64).reshape(4, 2)
    return float(np.median(np.linalg.norm(current - previous, axis=1)))


def _quad_diagonal_px(points: np.ndarray) -> float:
    points = np.asarray(points, dtype=np.float64).reshape(4, 2)
    return max(
        float(np.linalg.norm(points[2] - points[0])),
        float(np.linalg.norm(points[3] - points[1])),
        1.0,
    )


def _project_profile_on_observed_quad(
    profile,
    corners_px: np.ndarray,
    video_size: tuple[int, int],
    confidence: float,
) -> tuple[list[PinDetection], list[tuple[float, float]]]:
    """Project fixed profile pins directly through the observed board quad.

    The active webcam rig has a fallback FOV rather than a calibrated lens
    model. For a planar board, the observed four-corner homography is therefore
    the stable source of display coordinates; it avoids PnP focal-length error
    moving an otherwise correct 40-pin lattice away from the real holes.
    """
    corners = np.asarray(corners_px, dtype=np.float32).reshape(4, 2)
    width, height = (float(v) for v in profile.board.outline_mm)
    source = np.array([[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(source, corners)
    pin_coordinates: list[list[float]] = []
    for profile_pin in profile.pins:
        pin_x, pin_y = (float(v) for v in profile_pin.pos_mm[:2])
        pin_coordinates.append([pin_x, pin_y])
    pin_mm = np.asarray(pin_coordinates, dtype=np.float32)
    projected = cv2.perspectiveTransform(pin_mm.reshape(-1, 1, 2), transform).reshape(-1, 2)
    frame_w, frame_h = video_size
    pins = [
        PinDetection(
            pin_id=profile_pin.id,
            x=float(point[0]),
            y=float(point[1]),
            confidence=float(confidence),
            visible=bool(0.0 <= point[0] < frame_w and 0.0 <= point[1] < frame_h),
            header=profile_pin.header,
            index=profile_pin.index,
        )
        for profile_pin, point in zip(profile.pins, projected)
    ]
    outline = [(float(x), float(y)) for x, y in corners]
    return pins, outline


def _project_profile_height_on_observed_quad(
    profile,
    corners_px: np.ndarray,
    video_size: tuple[int, int],
    confidence: float,
    camera,
    rvec: np.ndarray,
    tvec: np.ndarray,
) -> tuple[list[PinDetection], list[tuple[float, float]]]:
    """Anchor x/y with the observed quad, then add true 3-D pin parallax.

    A pure homography is exact only for points on the PCB plane (z=0). Pi 5's
    J8 openings are 8.5 mm above that plane, so an oblique view visibly shifts
    them. Conversely, projecting every coordinate through an uncalibrated PnP
    pose can move the whole lattice when the fallback focal length is slightly
    wrong. The robust combination is:

      observed-homography(x, y) + PnP(x, y, z) - PnP(x, y, 0)

    The first term keeps the board-plane registration exact; only the
    height-dependent differential comes from the 6-DoF pose. With z=0 this
    reduces exactly to the previous planar projection.
    """
    planar_pins, outline = _project_profile_on_observed_quad(
        profile, corners_px, video_size, confidence
    )
    if not planar_pins:
        return planar_pins, outline

    pin_xyz = np.asarray([pin.pos_mm for pin in profile.pins], dtype=np.float64)
    pin_base = pin_xyz.copy()
    pin_base[:, 2] = 0.0
    try:
        base_px = project_points(
            board_to_vision(pin_base), camera, rvec, tvec
        )
        elevated_px = project_points(
            board_to_vision(pin_xyz), camera, rvec, tvec
        )
    except (cv2.error, TypeError, ValueError):
        return planar_pins, outline

    parallax = elevated_px - base_px
    board_diagonal_px = _quad_diagonal_px(np.asarray(corners_px, dtype=np.float64))
    # An 8.5 mm header cannot plausibly shift by a large fraction of an 85 mm
    # board. A bad/ambiguous fallback PnP must fail back to the planar anchor
    # rather than throw the GPIO lattice across the image.
    max_parallax_px = max(2.0, board_diagonal_px * 0.16)
    frame_w, frame_h = video_size
    projected: list[PinDetection] = []
    for profile_pin, planar_pin, delta in zip(profile.pins, planar_pins, parallax):
        if not np.all(np.isfinite(delta)) or float(np.linalg.norm(delta)) > max_parallax_px:
            delta = np.zeros(2, dtype=np.float64)
        x = float(planar_pin.x + delta[0])
        y = float(planar_pin.y + delta[1])
        projected.append(PinDetection(
            pin_id=profile_pin.id,
            x=x,
            y=y,
            confidence=float(confidence),
            visible=bool(0.0 <= x < frame_w and 0.0 <= y < frame_h),
            header=profile_pin.header,
            index=profile_pin.index,
        ))
    return projected, outline


def _correct_pi5_j8_from_image(
    frame_bgr: np.ndarray,
    profile,
    pins: list[PinDetection],
    video_size: tuple[int, int],
) -> list[PinDetection]:
    """Align the existing lattice using a full-length, image-supported J8 body."""
    return align_pi5_j8(frame_bgr, profile, pins, video_size)


def _anchor_profile_header_from_landmarks(
    profile,
    pins: list[PinDetection],
    observation,
    video_size: tuple[int, int],
    *,
    keypoint_threshold: float,
) -> list[PinDetection]:
    """Correct a projected header lattice with its observed endpoint landmarks.

    The uncalibrated Pi 5 path can estimate header-height parallax from the
    four PCB corners, but a small focal-length/tilt error moves the complete
    40-pin lattice away from the real J8 holes. An 8-keypoint model already
    observes the four J8 corner holes, so use their residuals to anchor each
    physical row while preserving the base projection's perspective spacing.

    This deliberately is a bounded correction rather than a homography fit to
    the very thin 2x20 header rectangle. Interpolating the two endpoint
    residuals of each row is numerically stable and leaves unrelated headers
    untouched. Any incomplete, crossed or implausibly displaced landmark set
    fails closed to ``pins``.
    """
    landmarks = getattr(observation, "landmarks_px", None)
    confidences = np.asarray(
        getattr(observation, "keypoint_confidences", ()), dtype=np.float64
    ).reshape(-1)
    if landmarks is None or not getattr(profile, "pose_landmarks", None):
        return pins

    points = np.asarray(landmarks, dtype=np.float64)
    resolved = profile.resolved_pose_landmarks()
    if (
        points.shape != (len(resolved), 2)
        or confidences.size != len(resolved)
        or len(profile.pose_landmarks) != len(resolved)
    ):
        return pins

    projected_by_id = {pin.pin_id: pin for pin in pins}
    profile_by_id = {pin.id: pin for pin in profile.pins}
    anchors: list[dict[str, object]] = []
    for index, (spec, (_landmark_id, position)) in enumerate(
        zip(profile.pose_landmarks, resolved)
    ):
        pin_id = getattr(spec, "pin_id", None)
        if getattr(spec, "role", None) != "header" or pin_id is None:
            continue
        if (
            not np.isfinite(confidences[index])
            or confidences[index] < float(keypoint_threshold)
            or not np.all(np.isfinite(points[index]))
            or pin_id not in projected_by_id
            or pin_id not in profile_by_id
        ):
            return pins
        base = projected_by_id[pin_id]
        anchors.append({
            "pin_id": pin_id,
            "header": profile_by_id[pin_id].header,
            "position": np.asarray(position, dtype=np.float64),
            "base": np.asarray([base.x, base.y], dtype=np.float64),
            "observed": points[index].copy(),
        })

    # Pi 5 supplies P1/P2/P40/P39. Requiring the complete rectangle avoids a
    # one-sided correction when a hand or connector hides one endpoint.
    if len(anchors) != 4:
        return pins
    header_ids = {str(anchor["header"]) for anchor in anchors}
    if len(header_ids) != 1:
        return pins

    base_quad = np.asarray([anchor["base"] for anchor in anchors], dtype=np.float64)
    observed_quad = np.asarray(
        [anchor["observed"] for anchor in anchors], dtype=np.float64
    )
    base_area = float(cv2.contourArea(base_quad.astype(np.float32), oriented=True))
    observed_area = float(
        cv2.contourArea(observed_quad.astype(np.float32), oriented=True)
    )
    if (
        abs(base_area) < 1.0
        or abs(observed_area) < 0.25 * abs(base_area)
        or abs(observed_area) > 3.0 * abs(base_area)
        or base_area * observed_area <= 0.0
    ):
        return pins

    header_length_px = max(
        float(np.linalg.norm(base_quad[i] - base_quad[j]))
        for i in range(len(base_quad))
        for j in range(i + 1, len(base_quad))
    )
    max_anchor_shift_px = max(12.0, 0.25 * header_length_px)
    if float(np.max(np.linalg.norm(observed_quad - base_quad, axis=1))) > max_anchor_shift_px:
        return pins

    # Group the four endpoints into the two physical rows by profile y. Each
    # row must have both ends; a rounded key tolerates harmless JSON decimals.
    rows: dict[tuple[str, float], list[dict[str, object]]] = {}
    for anchor in anchors:
        position = np.asarray(anchor["position"], dtype=np.float64)
        key = (str(anchor["header"]), round(float(position[1]), 3))
        rows.setdefault(key, []).append(anchor)
    if len(rows) != 2 or any(len(row) != 2 for row in rows.values()):
        return pins

    corrected_by_id: dict[str, np.ndarray] = {}
    for (header_id, row_y), row_anchors in rows.items():
        start, end = sorted(
            row_anchors,
            key=lambda anchor: float(np.asarray(anchor["position"])[0]),
        )
        start_position = np.asarray(start["position"], dtype=np.float64)
        end_position = np.asarray(end["position"], dtype=np.float64)
        span = float(end_position[0] - start_position[0])
        if abs(span) < 1e-6:
            return pins
        start_residual = np.asarray(start["observed"]) - np.asarray(start["base"])
        end_residual = np.asarray(end["observed"]) - np.asarray(end["base"])
        for profile_pin in profile.pins:
            if profile_pin.header != header_id:
                continue
            pin_position = np.asarray(profile_pin.pos_mm, dtype=np.float64)
            if abs(float(pin_position[1]) - row_y) > 0.2:
                continue
            t = float(np.clip((pin_position[0] - start_position[0]) / span, 0.0, 1.0))
            base_pin = projected_by_id.get(profile_pin.id)
            if base_pin is None:
                continue
            correction = (1.0 - t) * start_residual + t * end_residual
            corrected_by_id[profile_pin.id] = (
                np.asarray([base_pin.x, base_pin.y], dtype=np.float64) + correction
            )

    if len(corrected_by_id) != len(pins):
        return pins

    frame_w, frame_h = video_size
    return [
        PinDetection(
            pin_id=pin.pin_id,
            x=float(corrected_by_id[pin.pin_id][0]),
            y=float(corrected_by_id[pin.pin_id][1]),
            confidence=pin.confidence,
            visible=bool(
                0.0 <= corrected_by_id[pin.pin_id][0] < frame_w
                and 0.0 <= corrected_by_id[pin.pin_id][1] < frame_h
            ),
            header=pin.header,
            index=pin.index,
        )
        for pin in pins
    ]


def _blue_board_fraction(frame_bgr: np.ndarray, outline_px) -> float | None:
    """Visible board-color fraction inside the current board quad.

    The absolute number depends on components and lighting, so callers compare
    it with a slowly learned unobstructed baseline. A thin Dupont wire changes
    only a few pixels; a hand over the board removes a large fraction at once.
    """
    if frame_bgr is None or frame_bgr.size == 0 or outline_px is None:
        return None
    h, w = frame_bgr.shape[:2]
    quad = np.asarray(outline_px, dtype=np.float64).reshape(4, 2)
    if not np.all(np.isfinite(quad)):
        return None
    quad[:, 0] = np.clip(quad[:, 0], 0, max(w - 1, 0))
    quad[:, 1] = np.clip(quad[:, 1], 0, max(h - 1, 0))
    x1 = max(0, int(np.floor(np.min(quad[:, 0]))))
    y1 = max(0, int(np.floor(np.min(quad[:, 1]))))
    x2 = min(w, int(np.ceil(np.max(quad[:, 0]))) + 1)
    y2 = min(h, int(np.ceil(np.max(quad[:, 1]))) + 1)
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    local_quad = quad - np.array([x1, y1], dtype=np.float64)
    polygon = np.zeros((y2 - y1, x2 - x1), dtype=np.uint8)
    cv2.fillConvexPoly(polygon, np.rint(local_quad).astype(np.int32), 255)
    area = int(cv2.countNonZero(polygon))
    if area < 25:
        return None
    hsv = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(
        hsv,
        np.array([80, 40, 18], dtype=np.uint8),
        np.array([138, 255, 255], dtype=np.uint8),
    )
    green = cv2.inRange(
        hsv,
        np.array([25, 35, 18], dtype=np.uint8),
        np.array([95, 255, 245], dtype=np.uint8),
    )
    board_color = cv2.bitwise_or(blue, green)
    visible = cv2.countNonZero(cv2.bitwise_and(board_color, polygon))
    return float(visible) / float(area)


def solve_profile_pose(
    outline_wh_mm: tuple[float, float],
    corners_px: np.ndarray,
    camera,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Solve the physical planar pose from four semantic profile corners."""
    obj = np.ascontiguousarray(board_outline_mm(outline_wh_mm), dtype=np.float64)
    img = np.ascontiguousarray(np.asarray(corners_px, np.float64).reshape(-1, 1, 2))
    try:
        n_sol, rvecs, tvecs, _ = cv2.solvePnPGeneric(
            obj, img, camera.K, camera.dist, flags=cv2.SOLVEPNP_IPPE
        )
    except cv2.error:
        return None
    candidates: list[tuple[float, np.ndarray, np.ndarray]] = []
    if n_sol:
        for rv, tv in zip(rvecs, tvecs):
            rv = np.asarray(rv, np.float64).reshape(3)
            tv = np.asarray(tv, np.float64).reshape(3)
            if tv[2] <= 0.0:
                continue
            rotation, _ = cv2.Rodrigues(rv)
            if float((rotation @ np.array([0.0, 0.0, -1.0]))[2]) >= 0.0:
                continue
            reproj = project_points(obj, camera, rv, tv)
            error = float(np.mean(np.linalg.norm(reproj - corners_px, axis=1)))
            candidates.append((error, rv, tv))
    if not candidates:
        return None
    _, rv0, tv0 = min(candidates, key=lambda item: item[0])
    try:
        rv, tv = cv2.solvePnPRefineLM(
            obj, img, camera.K, camera.dist,
            rv0.reshape(3, 1).copy(), tv0.reshape(3, 1).copy(),
        )
        rv = np.asarray(rv, np.float64).reshape(3)
        tv = np.asarray(tv, np.float64).reshape(3)
    except cv2.error:
        rv, tv = rv0, tv0
    if tv[2] <= 0.0:
        return None
    rotation, _ = cv2.Rodrigues(rv)
    if float((rotation @ np.array([0.0, 0.0, -1.0]))[2]) >= 0.0:
        return None
    reproj = project_points(obj, camera, rv, tv)
    error = float(np.mean(np.linalg.norm(reproj - corners_px, axis=1)))
    return rv, tv, error


def solve_landmark_pose(
    profile,
    observation,
    camera,
    *,
    keypoint_threshold: float,
    ransac_reprojection_error_px: float = 5.0,
) -> tuple[np.ndarray, np.ndarray, float, int] | None:
    """Solve calibrated Pi 5 pose from four board corners plus J8 points.

    The semantic prefix is mandatory: all four board corners and at least two
    elevated J8 landmarks must be trustworthy. RANSAC rejects an occasional
    bad J8 keypoint, then Levenberg-Marquardt refines only the inlier set.
    """
    if not getattr(camera, "calibrated", False):
        return None
    landmarks = getattr(observation, "landmarks_px", None)
    if landmarks is None:
        return None
    resolved = profile.resolved_pose_landmarks()
    points = np.asarray(landmarks, dtype=np.float64)
    confidences = np.asarray(
        observation.keypoint_confidences, dtype=np.float64
    ).reshape(-1)
    if len(resolved) < 6 or points.shape != (len(resolved), 2):
        return None
    if confidences.size != len(resolved):
        return None
    visible = (
        np.isfinite(confidences)
        & (confidences >= float(keypoint_threshold))
        & np.all(np.isfinite(points), axis=1)
    )
    if not np.all(visible[:4]) or int(np.count_nonzero(visible[4:])) < 2:
        return None
    if int(np.count_nonzero(visible)) < 6:
        return None

    object_board = np.asarray([position for _id, position in resolved], np.float64)
    object_points = np.ascontiguousarray(board_to_vision(object_board[visible]))
    image_points = np.ascontiguousarray(points[visible].reshape(-1, 1, 2))
    try:
        ok, rvec, tvec, inliers = cv2.solvePnPRansac(
            object_points,
            image_points,
            camera.K,
            camera.dist,
            iterationsCount=100,
            reprojectionError=float(ransac_reprojection_error_px),
            confidence=0.995,
            flags=cv2.SOLVEPNP_EPNP,
        )
    except cv2.error:
        return None
    if not ok or inliers is None:
        return None
    inlier_indices = np.asarray(inliers, dtype=np.int32).reshape(-1)
    if inlier_indices.size < 6:
        return None
    inlier_object = np.ascontiguousarray(object_points[inlier_indices])
    inlier_image = np.ascontiguousarray(image_points[inlier_indices])
    try:
        rvec, tvec = cv2.solvePnPRefineLM(
            inlier_object,
            inlier_image,
            camera.K,
            camera.dist,
            np.asarray(rvec, np.float64).reshape(3, 1),
            np.asarray(tvec, np.float64).reshape(3, 1),
        )
    except cv2.error:
        pass
    rvec = np.asarray(rvec, np.float64).reshape(3)
    tvec = np.asarray(tvec, np.float64).reshape(3)
    if tvec[2] <= 0.0:
        return None
    rotation, _ = cv2.Rodrigues(rvec)
    if float((rotation @ np.array([0.0, 0.0, -1.0]))[2]) >= 0.0:
        return None
    projected = project_points(inlier_object, camera, rvec, tvec)
    target = inlier_image.reshape(-1, 2)
    error = float(np.mean(np.linalg.norm(projected - target, axis=1)))
    return rvec, tvec, error, int(inlier_indices.size)


class YoloProfileDetector:
    """BoardDetector using YOLO keypoints as profile corner correspondences."""

    def __init__(
        self,
        *,
        model_path: Path | str | None = None,
        reference_recovery_model_path: Path | str | None = None,
        locator: BoardPoseLocator | None = None,
        horizontal_fov_deg: float | None = None,
        camera_calibration_path: Path | str | None = None,
        use_camera_calibration: bool = True,
        keypoint_count: int = 4,
        input_size: int = 960,
        confidence_threshold: float = 0.45,
        keypoint_threshold: float = 0.35,
        nms_iou_threshold: float = 0.45,
        max_reprojection_error_px: float = 8.0,
        stability_deadband_px: float = 2.00,
        deadband_exit_confirm_frames: int = 5,
        jump_threshold_fraction: float = 0.025,
        jump_confirm_frames: int = 3,
        occlusion_hold_frames: int = 60,
        occlusion_visibility_ratio: float = 0.80,
        visibility_warmup_frames: int = 5,
        runtime_backend: str = "opencv",
        directml_device_id: int = 0,
        cuda_device_id: int = 0,
        scene_reference_search: bool = False,
    ) -> None:
        if locator is None and model_path is None:
            raise ValueError("model_path or locator is required")
        self._locator = locator or create_yolo_pose_locator(
            model_path,
            eye_variant=True,
            runtime_backend=runtime_backend,
            directml_device_id=directml_device_id,
            cuda_device_id=cuda_device_id,
            input_size=input_size,
            confidence_threshold=confidence_threshold,
            keypoint_threshold=keypoint_threshold,
            nms_iou_threshold=nms_iou_threshold,
            keypoint_count=keypoint_count,
        )
        self._use_camera_calibration = bool(use_camera_calibration)
        self._horizontal_fov_deg = horizontal_fov_deg if use_camera_calibration else None
        self._reference_recovery = None
        self._boundary_reference_recovery = None
        self._scene_reference_enabled = bool(scene_reference_search)
        self._scene_reference = None
        self._image_motion_gate = None
        self._scale_recovery_enabled = False
        self._eye_yolo_search = EyeBoardYoloSearch()
        self._reference_recovery_path = reference_recovery_model_path
        self._recovery_locator_options = dict(input_size=input_size, confidence_threshold=.55,
            keypoint_threshold=keypoint_threshold, runtime_backend=runtime_backend,
            cuda_device_id=cuda_device_id, directml_device_id=directml_device_id)
        self._reference_evidence = None
        self._camera_calibration_path = (
            Path(camera_calibration_path)
            if camera_calibration_path is not None
            else None
        )
        self._keypoint_count = int(keypoint_count)
        self._keypoint_threshold = float(keypoint_threshold)
        self._max_reproj = float(max_reprojection_error_px)
        self._deadband_px = max(0.0, float(stability_deadband_px))
        self._deadband_exit_confirm_frames = max(
            1, int(deadband_exit_confirm_frames)
        )
        self._jump_threshold_fraction = max(1e-6, float(jump_threshold_fraction))
        self._jump_confirm_frames = max(1, int(jump_confirm_frames))
        self._occlusion_hold_frames = max(1, int(occlusion_hold_frames))
        self._occlusion_visibility_ratio = float(
            np.clip(occlusion_visibility_ratio, 0.01, 1.0)
        )
        self._visibility_warmup_frames = max(1, int(visibility_warmup_frames))
        self._profile = None
        self._profile_dir: Path | None = None
        self._camera = None
        self._video_size: tuple[int, int] | None = None
        self._reference_board_bgr: np.ndarray | None = None
        self._pose_filter = PoseFilter(min_cutoff=0.3, beta=30.0, d_cutoff=1.0)
        self._pin_image_anchor = PinImageAnchor()
        self._pin_update_gate = PinUpdateGate(self._jump_confirm_frames)
        self._last_locked_result: DetectionResult | None = None
        self._stale_frames = 0
        self._visibility_baseline: float | None = None
        self._visibility_samples = 0
        self._pending_outline: np.ndarray | None = None
        self._pending_count = 0
        self._deadband_pending_outline: np.ndarray | None = None
        self._deadband_pending_count = 0
        self._skip_deadband_once = False

    @property
    def available(self) -> bool:
        return bool(self._locator.available)

    def load(self, profile, profile_dir: Path) -> None:
        if self._boundary_reference_recovery is not None:
            self._boundary_reference_recovery.close()
            self._boundary_reference_recovery = None
        self._profile = profile
        self._profile_dir = Path(profile_dir)
        self._camera = None
        self._video_size = None
        self._reference_board_bgr = _canonical_reference_board(
            profile, self._profile_dir
        )
        self._scene_reference = None
        self.set_scene_reference_search(self._scene_reference_enabled)
        if self._reference_recovery is not None:
            self._reference_recovery.close()
            self._reference_recovery = None
        if (profile.board.id == 'raspberry-pi-5' and self._reference_recovery_path is not None
                and Path(self._reference_recovery_path).is_file()):
            from app.vision.reference_recovery import ReferencePoseRecovery
            self._reference_recovery = ReferencePoseRecovery(self._reference_board_bgr,
                create_yolo_pose_locator(self._reference_recovery_path, **self._recovery_locator_options))
            self._reference_recovery.set_scale_recovery(self._scale_recovery_enabled)
            configure = getattr(self._reference_recovery.roi_locator, 'set_yolo_only', None)
            if callable(configure):
                configure(getattr(self, '_yolo_only', False))
        self._pose_filter.reset()
        self._reset_temporal()

        self._eye_yolo_search.reset()

    def _ensure_camera(self, frame_bgr: np.ndarray) -> None:
        size = (int(frame_bgr.shape[1]), int(frame_bgr.shape[0]))
        if size == self._video_size and self._camera is not None:
            return
        camera_json = (self._profile_dir / "camera.json"
                       if self._profile_dir and self._use_camera_calibration else None)
        shared = self._camera_calibration_path if self._use_camera_calibration else None
        self._camera = load_camera(
            size,
            shared if shared is not None and shared.is_file() else None,
            self._horizontal_fov_deg,
        )
        if (
            not self._camera.calibrated
            and camera_json is not None
            and camera_json.is_file()
        ):
            self._camera = load_camera(
                size, camera_json, self._horizontal_fov_deg
            )
        self._video_size = size
        self._pose_filter.reset()
        self._reset_temporal()

    def reset_for_camera(self, *, horizontal_fov_deg: float | None = None,
                         camera_calibration_path: Path | str | None = None,
                         use_camera_calibration: bool = True) -> None:
        """Clear camera and pose history without closing either ONNX locator.

        The owning vision worker must be stopped or hold its detector lock.
        """
        self._use_camera_calibration = bool(use_camera_calibration)
        self._horizontal_fov_deg = horizontal_fov_deg if use_camera_calibration else None
        self._camera_calibration_path = Path(camera_calibration_path) if camera_calibration_path is not None else None
        self._camera = None
        self._video_size = None
        self._reference_evidence = None
        self._eye_yolo_search.reset()
        if self._scene_reference is not None:
            self._scene_reference.reset()
        if self._reference_recovery is not None:
            self._reference_recovery.reset_tracking()
        if self._boundary_reference_recovery is not None:
            self._boundary_reference_recovery.reset_tracking()
        self._motion_outline = None
        self._pose_filter.reset()
        self._reset_temporal()

    def set_scale_recovery(self, enabled: bool) -> None:
        """Configure the existing Pi ROI model while its worker is stopped."""
        self._scale_recovery_enabled = bool(enabled)
        self._eye_yolo_search.reset()
        if self._reference_recovery is not None:
            self._reference_recovery.set_scale_recovery(enabled)

    def detect(self, frame_bgr: np.ndarray, frame_id: int, ts_ms: float) -> DetectionResult:
        if getattr(self, '_yolo_only', False):
            return self._detect_yolo_only(frame_bgr, frame_id, ts_ms)
        self._motion_outline = None
        self._reference_evidence = None
        self._body = None
        result = self._detect(frame_bgr, frame_id, ts_ms)
        return replace(result, motion_outline_px=self._motion_outline,
                       reference_evidence=self._reference_evidence, body=self._body)

    def set_yolo_only(self, enabled: bool) -> None:
        self._yolo_only = bool(enabled)
        if self._scene_reference is not None:
            self._scene_reference.reset()
        self.set_scale_recovery(enabled)
        locators = [self._locator]
        if self._reference_recovery is not None:
            locators.append(self._reference_recovery.roi_locator)
        for locator in locators:
            configure = getattr(locator, 'set_yolo_only', None)
            if callable(configure):
                configure(self._yolo_only)

    def _detect_yolo_only(self, frame, frame_id, ts_ms):
        """Eye MVP: current YOLO corners directly project the board's GPIO map."""
        empty = self._searching(frame_id, ts_ms, stability='yolo_direct')
        if self._profile is None or frame is None or frame.size == 0:
            return empty
        size = (frame.shape[1], frame.shape[0])
        reference_locator = (self._reference_recovery.roi_locator
                             if self._reference_recovery is not None else None)
        observation = self._eye_yolo_search.locate(
            frame, self._locator, reference_locator,
            allow_tiles=self._scale_recovery_enabled)
        if observation is None:
            return empty
        body = body_observation(observation, size, source=observation.source)
        if observation.source == 'yolo_reference_body_only':
            # This existing ROI model was trained/validated for finding a Pi
            # body. Its corner order/extent cannot authorize GPIO projection.
            return replace(empty, body=body, pose_path='yolo_body_only')
        corners = np.asarray(observation.corners_px, np.float32)
        if (corners.shape != (4, 2) or not np.isfinite(corners).all()
                or not cv2.isContourConvex(corners) or abs(cv2.contourArea(corners)) < 1.):
            self._eye_yolo_search.advance()
            return replace(empty, body=body)
        from app.vision.eye_geometry import clipped_corners
        if clipped_corners(corners, size, observation.box_xyxy):
            return replace(empty, body={**body, 'partial': True} if body else None,
                           pose_path='yolo_clipped')
        pins, outline = _project_profile_on_observed_quad(
            self._profile, corners, size, observation.confidence)
        pose_path = 'yolo'
        # Eye keeps YOLO identity/board geometry. Only the fresh contact-row
        # image shifts Pi pins across the lattice, preserving its along-row
        # spacing; ambiguous images keep the current projection unchanged.
        if self._profile.board.id == 'raspberry-pi-5':
            from app.vision.eye_j8 import correct_eye_j8_from_image
            corrected = correct_eye_j8_from_image(frame, self._profile, pins, size)
            if corrected is not pins and any(
                    current.x != previous.x or current.y != previous.y
                    for current, previous in zip(corrected, pins)):
                pose_path = 'yolo_j8_image'
            pins = corrected
        if not all(np.isfinite([pin.x, pin.y]).all() for pin in pins):
            self._eye_yolo_search.advance()
            return replace(empty, body=body)
        return replace(empty, tracking='locked', confidence=float(observation.confidence),
                       pins=pins, outline_px=outline, motion_outline_px=outline,
                       body=body, pose_path=pose_path, pose_mode='hybrid_4pt')

    def set_scene_reference_search(self, enabled: bool) -> None:
        """Opt-in offline candidate; default Webcam/Eye loads do no extra SIFT."""
        self._scene_reference_enabled = bool(enabled)
        self._scene_reference = None
        if (enabled and self._profile is not None
                and self._profile.board.id == 'raspberry-pi-5'
                and self._reference_board_bgr is not None):
            from app.vision.reference_recovery import ReferencePoseRecovery
            from app.vision.scene_reference_search import SceneReferenceSearch
            self._scene_reference = SceneReferenceSearch(ReferencePoseRecovery(self._reference_board_bgr))

    def _recover_scene_reference(self, frame, frame_id, ts_ms):
        if (not self._scene_reference_enabled or self._scene_reference is None
                or getattr(self, '_yolo_only', False)):
            return None
        recovered = self._scene_reference.locate(frame, frame_id, ts_ms)
        self._reference_evidence = dict(self._scene_reference.evidence)
        return recovered

    def _recover_boundary_reference(self, frame, observation, boundary_evidence):
        """Use the current model ROI, never its rejected corners, for SIFT.

        A colored lead can invalidate the PCB contour even when the model has
        found the correct board. The existing ROI recovery used to run only on
        missing/inconsistent model corners, leaving this failure path stranded
        unless the optional whole-scene search was enabled. Keep the strict
        contour rejection and require independent, distributed correspondences
        on this exact frame instead. No extra YOLO forward or stale pose here.
        """
        if (self._profile.board.id != 'raspberry-pi-5'
                or getattr(self, '_yolo_only', False)
                or self._reference_board_bgr is None):
            return None
        matcher = self._reference_recovery
        if matcher is None:
            if self._boundary_reference_recovery is None:
                from app.vision.reference_recovery import ReferencePoseRecovery
                self._boundary_reference_recovery = ReferencePoseRecovery(self._reference_board_bgr)
            matcher = self._boundary_reference_recovery
        recovered = matcher.locate(frame, region=observation)
        self._reference_evidence = {
            **matcher.evidence, 'scope': 'rejected_boundary_roi',
            'boundary': dict(boundary_evidence),
        }
        return recovered

    def set_motion_handoff(self, enabled: bool) -> None:
        """Webcam-only opt-in; the Eye early-return path never reads this gate."""
        from app.vision.image_motion_gate import ImageMotionGate
        self._image_motion_gate = ImageMotionGate() if enabled else None

    def _detect(self, frame_bgr: np.ndarray, frame_id: int, ts_ms: float) -> DetectionResult:
        if self._profile is None or not self.available or frame_bgr is None or frame_bgr.size == 0:
            return self._searching(frame_id, ts_ms)
        self._ensure_camera(frame_bgr)
        observation = self._locator.locate(frame_bgr)
        # Identity comes from this frame's wiring-guide YOLO model. A later
        # PCB/J8 rejection only rejects pin geometry, not the detected object.
        self._body = body_observation(observation, (frame_bgr.shape[1], frame_bgr.shape[0]))
        if (self._image_motion_gate is not None and self._scene_reference_enabled
                and self._scene_reference is not None and self._scene_reference.recent(ts_ms)):
            recovered = self._recover_scene_reference(frame_bgr, frame_id, ts_ms)
            if recovered is not None:
                observation = recovered
        if (self._reference_recovery is not None and (observation is None
                or not _pi_corner_box_consistent(observation))):
            recovered = self._reference_recovery.locate(frame_bgr)
            self._reference_evidence = dict(self._reference_recovery.evidence)
            if self._body is None:
                self._body = body_observation(
                    getattr(self._reference_recovery, 'last_observation', None),
                    (frame_bgr.shape[1], frame_bgr.shape[0]), source='pi_reference_model',
                )
            if recovered is not None:
                observation = recovered
        if observation is None or not _pi_corner_box_consistent(observation):
            recovered = self._recover_scene_reference(frame_bgr, frame_id, ts_ms)
            if recovered is not None:
                observation = recovered
        if observation is None:
            return self._hold_or_searching(frame_id, ts_ms, "occlusion_hold")
        if (self._profile.board.id == 'raspberry-pi-5'
                and observation.landmarks_px is None
                and not _pi_corner_box_consistent(observation)):
            self._pose_filter.reset()
            self._reset_temporal()
            return self._searching(frame_id, ts_ms, stability='corner_box_inconsistent')
        boundary_evidence = ({} if self._profile.board.id == 'raspberry-pi-5'
                             and observation.landmarks_px is None else None)
        reference_matched = getattr(observation, 'source', 'yolo') == 'reference_sift'
        refined_observation = None if reference_matched else refine_board_corners_from_pcb(
            frame_bgr,
            observation,
            reference_board_bgr=self._reference_board_bgr,
            boundary_evidence=boundary_evidence,
        )
        if boundary_evidence and boundary_evidence.get('rejected'):
            # A concrete bad contour is different from no available refinement.
            # Clear contaminated holds; the hybrid caller can try its existing
            # independent feature locator instead of freezing a giant Pi box.
            recovered = self._recover_boundary_reference(frame_bgr, observation, boundary_evidence)
            if recovered is None:
                recovered = self._recover_scene_reference(frame_bgr, frame_id, ts_ms)
            if recovered is None:
                self._pose_filter.reset()
                self._reset_temporal()
                return self._searching(frame_id, ts_ms, stability='pcb_boundary_unverified')
            observation = recovered
            reference_matched = True
            refined_observation = None
        raw_ordered = _ordered_quad_ok(observation.corners_px, self._video_size)
        solved = None
        refined_used = False
        pose_mode = "hybrid_4pt"
        pose_inliers = int(self._reference_evidence['inliers']) if reference_matched else 4
        confidences = np.asarray(
            observation.keypoint_confidences, dtype=np.float64
        ).reshape(-1)
        landmarks_visible = int(
            np.count_nonzero(
                np.isfinite(confidences)
                & (confidences >= self._keypoint_threshold)
            )
        )

        # The calibrated 8-point path is authoritative when available. It is
        # attempted before the historical planar solve, but fails closed to
        # that solve whenever J8 visibility or calibration evidence is short.
        landmark_observation = (
            refined_observation
            if refined_observation is not None
            else observation
        )
        landmark_solved = solve_landmark_pose(
            self._profile,
            landmark_observation,
            self._camera,
            keypoint_threshold=self._keypoint_threshold,
            ransac_reprojection_error_px=min(self._max_reproj, 5.0),
        )
        if landmark_solved is not None:
            rvec_8, tvec_8, reproj_8, inliers_8 = landmark_solved
            observation = landmark_observation
            solved = (rvec_8, tvec_8, reproj_8)
            refined_used = refined_observation is not None
            pose_mode = "pnp_8pt"
            pose_inliers = inliers_8
        if (
            solved is None
            and
            refined_observation is not None
            and _ordered_quad_ok(refined_observation.corners_px, self._video_size)
        ):
            refined_solved = solve_profile_pose(
                self._profile.board.outline_mm,
                refined_observation.corners_px,
                self._camera,
            )
            if refined_solved is not None and (
                not raw_ordered or self._profile.board.id == "raspberry-pi-5"
            ):
                # The color contour is the physical PCB edge. Prefer it even
                # when the unrefined YOLO keypoints happen to have a smaller
                # reprojection error around an incorrect inner quadrilateral.
                # Pi 5's metal USB/Ethernet edge can make the raw YOLO quad
                # look valid at longer distances while still being too large.
                observation = refined_observation
                solved = refined_solved
                refined_used = True
            elif raw_ordered and refined_solved is None:
                # A valid pose profile is already authoritative. Only use the
                # color contour as a recovery path when YOLO's four points do
                # not form a usable quadrilateral; this keeps calibrated/profile
                # scenes from being nudged by segmentation pixels.
                solved = solve_profile_pose(
                    self._profile.board.outline_mm,
                    observation.corners_px,
                    self._camera,
                )
        if solved is None and raw_ordered:
            solved = solve_profile_pose(
                self._profile.board.outline_mm, observation.corners_px, self._camera
            )
        if solved is None and not refined_used and not raw_ordered:
            return self._hold_or_searching(frame_id, ts_ms, "occlusion_hold")
        if solved is None:
            return self._hold_or_searching(frame_id, ts_ms, "occlusion_hold")
        rvec, tvec, reproj = solved
        reprojection_limit = max(self._max_reproj, 12.0) if refined_used else self._max_reproj
        if not np.isfinite(reproj) or reproj > reprojection_limit:
            return self._hold_or_searching(frame_id, ts_ms, "jump_hold")

        reproj_score = max(0.0, 1.0 - reproj / max(self._max_reproj, 1e-6))
        confidence = float(np.clip(observation.confidence * (0.5 + 0.5 * reproj_score), 0.0, 1.0))

        # Evaluate temporal movement and occlusion against the unfiltered pose.
        # Filtering first would let one contaminated measurement tug every pin.
        # A refined observed quad remains the board-plane anchor. Pi 5 adds
        # the profile's real header z-height as a differential PnP parallax;
        # UNO Q keeps its already validated calibrated 3-D path.
        use_observed_quad_projection = (
            refined_used or self._profile.board.id == "raspberry-pi-5"
        )
        if pose_mode == "pnp_8pt":
            _raw_pins, raw_outline = project_board(
                self._profile, self._camera, rvec, tvec, confidence
            )
        elif self._profile.board.id == "raspberry-pi-5" and self._camera.calibrated:
            _raw_pins, raw_outline = _project_profile_height_on_observed_quad(
                self._profile,
                observation.corners_px,
                self._video_size,
                confidence,
                self._camera,
                rvec,
                tvec,
            )
        elif use_observed_quad_projection:
            _raw_pins, raw_outline = _project_profile_on_observed_quad(
                self._profile, observation.corners_px, self._video_size, confidence
            )
        else:
            _raw_pins, raw_outline = project_board(
                self._profile, self._camera, rvec, tvec, confidence
            )
        raw_outline_arr = np.asarray(raw_outline, dtype=np.float64).reshape(4, 2)
        self._motion_outline = [tuple(point) for point in raw_outline_arr]
        visible_fraction = _blue_board_fraction(frame_bgr, raw_outline_arr)
        motion_px = self._motion_from_last(raw_outline_arr)

        motion_confirmed = False
        motion_pins = None
        if (self._image_motion_gate is not None and self._profile.board.id == 'raspberry-pi-5'
                and not self._camera.calibrated):
            # Compare FINAL J8-corrected pins, not just a moving bounding box.
            motion_pins = _correct_pi5_j8_from_image(frame_bgr, self._profile, _raw_pins, self._video_size)
            motion_confirmed = self._image_motion_gate.compare(
                frame_bgr, raw_outline_arr, motion_pins, frame_id, ts_ms)
            if motion_confirmed:
                motion_pins = [replace(pin,x=float(x),y=float(y)) for pin,(x,y) in
                               zip(motion_pins,self._image_motion_gate.ready_pins)]

        if self._is_occluded(visible_fraction) and not motion_confirmed:
            return self._hold_or_searching(
                frame_id,
                ts_ms,
                "occlusion_hold",
                motion_px=motion_px,
                visible_fraction=visible_fraction,
            )

        pi5_planar = self._profile.board.id == "raspberry-pi-5" and not self._camera.calibrated
        if (pi5_planar and self._last_locked_result is not None
                and not motion_confirmed
                and self._pin_image_anchor.stationary(frame_bgr)):
            # Fresh local image evidence says J8 did not move. Do not let
            # noisy board-corner regression drag its search ROI or 40 pins.
            self._pending_outline = None
            self._pending_count = 0
            self._deadband_pending_outline = None
            self._deadband_pending_count = 0
            self._skip_deadband_once = False
            self._pin_update_gate.reset()
            result = self._frozen_result(
                frame_id=frame_id, ts_ms=ts_ms, tracking="locked",
                confidence=confidence, stability="deadband", reproj=reproj,
                motion_px=motion_px, visible_fraction=visible_fraction,
            )
            result.pose_image_motion_px = self._pin_image_anchor.motion_px
            result.pose_image_support = self._pin_image_anchor.support
            result.pose_image_confirmed = self._pin_image_anchor.fully_supported
            self._last_locked_result = result
            self._stale_frames = 0
            self._update_visibility_baseline(visible_fraction)
            return result

        jump_confirmed = motion_confirmed or self._confirm_large_motion(raw_outline_arr, motion_px)
        if not jump_confirmed:
            return self._hold_or_searching(
                frame_id,
                ts_ms,
                "jump_hold",
                motion_px=motion_px,
                visible_fraction=visible_fraction,
            )

        rvec_f, tvec_f = self._pose_filter.apply(
            rvec, tvec, float(ts_ms) / 1000.0
        )
        if pose_mode == "pnp_8pt":
            pins, outline = project_board(
                self._profile, self._camera, rvec_f, tvec_f, confidence
            )
            wire_exclusion = project_wire_exclusion(
                self._profile, self._camera, rvec_f, tvec_f
            )
        elif self._profile.board.id == "raspberry-pi-5" and self._camera.calibrated:
            # The observed quad supplies the exact PCB-plane anchor. Filtered
            # PnP contributes only the z-height differential, so tilted J8
            # openings follow real 3-D parallax. The four observed J8 endpoint
            # landmarks then remove the remaining uncalibrated-FOV lattice
            # offset while retaining the projected perspective spacing.
            pins, outline = _project_profile_height_on_observed_quad(
                self._profile,
                observation.corners_px,
                self._video_size,
                confidence,
                self._camera,
                rvec_f,
                tvec_f,
            )
            pins = _anchor_profile_header_from_landmarks(
                self._profile,
                pins,
                observation,
                self._video_size,
                keypoint_threshold=self._keypoint_threshold,
            )
            wire_exclusion = outline
        elif self._profile.board.id == "raspberry-pi-5":
            # Without a checkerboard-accepted camera calibration, the PnP depth
            # estimate is only a FOV guess.  Applying z-height parallax from
            # that guess moves the GPIO lattice away from the physical J8
            # socket holes.  Keep Pi 5's default 4-point mode strictly planar;
            # users can regain true height parallax by completing calibration.
            #
            # The planar board quad is still only a coarse Pi 5 locator: the
            # USB/Ethernet side can pull the four-corner rectangle away from
            # the PCB body.  Finish by snapping the J8 lattice to the black
            # 2x20 socket visible in this exact frame.
            pins, outline = _project_profile_on_observed_quad(
                self._profile, observation.corners_px, self._video_size, confidence
            )
            pins = motion_pins if motion_pins is not None else _correct_pi5_j8_from_image(
                frame_bgr, self._profile, pins, self._video_size
            )
            wire_exclusion = outline
        elif use_observed_quad_projection:
            pins, outline = _project_profile_on_observed_quad(
                self._profile, observation.corners_px, self._video_size, confidence
            )
            wire_exclusion = outline
        else:
            pins, outline = project_board(
                self._profile, self._camera, rvec_f, tvec_f, confidence
            )
            wire_exclusion = project_wire_exclusion(
                self._profile, self._camera, rvec_f, tvec_f
            )
        filtered_outline = np.asarray(outline, dtype=np.float64).reshape(4, 2)
        if motion_confirmed:
            filtered_outline = self._image_motion_gate.ready_outline
            outline = [tuple(point) for point in filtered_outline]
            # All downstream board geometry must share the current-image
            # handoff, not mix the accepted outline with the noisy raw quad.
            wire_exclusion = list(outline)
        filtered_motion = self._motion_from_last(filtered_outline)
        stability = "tracking"

        if (pi5_planar and self._last_locked_result is not None
                and not motion_confirmed
                and not self._pin_update_gate.ready(pins, self._last_locked_result.pins)):
            result = self._hold_or_searching(
                frame_id, ts_ms, "jump_hold", motion_px=filtered_motion,
                visible_fraction=visible_fraction, keep_pin_pending=True,
            )
            result.pose_pin_motion_px = self._pin_update_gate.motion_px
            return result

        bypass_deadband = self._skip_deadband_once or motion_confirmed
        self._skip_deadband_once = False
        if (
            self._last_locked_result is not None
            and not bypass_deadband
            and not self._confirm_deadband_exit(filtered_outline, filtered_motion)
        ):
            result = self._frozen_result(
                frame_id=frame_id,
                ts_ms=ts_ms,
                tracking="locked",
                confidence=confidence,
                stability="deadband",
                reproj=reproj,
                motion_px=filtered_motion,
                visible_fraction=visible_fraction,
            )
            stability = "deadband"
        else:
            result = DetectionResult(
            board_id=self._profile.board.id,
            frame_id=int(frame_id),
            ts_ms=float(ts_ms),
            tracking="locked",
            confidence=confidence,
            pins=pins,
            outline_px=outline,
            wire_exclusion_px=wire_exclusion,
            rvec=[float(v) for v in rvec_f],
            tvec=[float(v) for v in tvec_f],
            pose_path="reference_sift" if reference_matched else "yolo",
            pose_inliers=pose_inliers,
            pose_reproj_px=float(reproj),
            pose_inlier_board_area_frac=self._reference_evidence['coverage'] if reference_matched else 1.0,
            pose_stability_state=stability,
            pose_motion_px=float(filtered_motion),
            pose_visible_fraction=visible_fraction,
            pose_mode=pose_mode,
            pose_landmarks_visible=landmarks_visible,
            )

        if pi5_planar:
            result.pose_pin_motion_px = self._pin_update_gate.motion_px
            result.pose_image_motion_px = self._pin_image_anchor.motion_px
            result.pose_image_support = self._pin_image_anchor.support
            if stability == "tracking":
                self._pin_image_anchor.seed(frame_bgr, result.pins, result.outline_px)
                self._pin_update_gate.reset()
        self._last_locked_result = result
        self._stale_frames = 0
        self._update_visibility_baseline(visible_fraction)
        return result

    def _reset_temporal(self) -> None:
        if self._image_motion_gate is not None:
            self._image_motion_gate.reset()
        self._pin_image_anchor.reset()
        self._pin_update_gate.reset()
        self._last_locked_result = None
        self._stale_frames = 0
        self._visibility_baseline = None
        self._visibility_samples = 0
        self._pending_outline = None
        self._pending_count = 0
        self._deadband_pending_outline = None
        self._deadband_pending_count = 0
        self._skip_deadband_once = False

    def _motion_from_last(self, outline: np.ndarray) -> float:
        last = self._last_locked_result
        if last is None or last.outline_px is None:
            return 0.0
        return _quad_motion_px(outline, np.asarray(last.outline_px, dtype=np.float64))

    def _is_occluded(self, visible_fraction: float | None) -> bool:
        baseline = self._visibility_baseline
        return bool(
            visible_fraction is not None
            and baseline is not None
            and self._visibility_samples >= self._visibility_warmup_frames
            and baseline >= 0.03
            and visible_fraction < baseline * self._occlusion_visibility_ratio
        )

    def _update_visibility_baseline(self, visible_fraction: float | None) -> None:
        if visible_fraction is None:
            return
        value = float(np.clip(visible_fraction, 0.0, 1.0))
        if self._visibility_baseline is None:
            self._visibility_baseline = value
        else:
            # Adapt quickly to a clearer view and very slowly to a darker one.
            # This follows lighting drift without teaching a passing hand to
            # become the new normal.
            alpha = 0.08 if value >= self._visibility_baseline else 0.01
            self._visibility_baseline = (
                (1.0 - alpha) * self._visibility_baseline + alpha * value
            )
        self._visibility_samples += 1

    def _confirm_large_motion(self, outline: np.ndarray, motion_px: float) -> bool:
        last = self._last_locked_result
        if last is None or last.outline_px is None:
            self._pending_outline = None
            self._pending_count = 0
            return True

        previous = np.asarray(last.outline_px, dtype=np.float64).reshape(4, 2)
        threshold = max(3.0, _quad_diagonal_px(previous) * self._jump_threshold_fraction)
        previous_area = max(_quad_area(previous), 1.0)
        area_ratio = _quad_area(outline) / previous_area
        large = motion_px > threshold or not 0.88 <= area_ratio <= 1.14
        if not large:
            self._pending_outline = None
            self._pending_count = 0
            return True

        consistency_px = max(2.5, threshold * 0.60)
        if (
            self._pending_outline is None
            or _quad_motion_px(outline, self._pending_outline) > consistency_px
        ):
            self._pending_outline = outline.copy()
            self._pending_count = 1
        else:
            self._pending_outline = 0.5 * self._pending_outline + 0.5 * outline
            self._pending_count += 1

        if self._pending_count < self._jump_confirm_frames:
            return False

        # Keep this consensus until final pins are also accepted. Clearing it
        # here made the two gates restart each other after a real relocation.
        if self._pending_count == self._jump_confirm_frames:
            self._pose_filter.reset()
        self._skip_deadband_once = True
        return True

    def _confirm_deadband_exit(self, outline: np.ndarray, motion_px: float) -> bool:
        """Release a static anchor only after a consistent new pose persists.

        One-Euro removes high-frequency noise but can still random-walk by a
        pixel as exposure/focus changes. Requiring a short consensus outside
        the deadband prevents those isolated excursions from moving GPIOs.
        """
        if self._deadband_px <= 0.0:
            return True
        if motion_px <= self._deadband_px:
            self._deadband_pending_outline = None
            self._deadband_pending_count = 0
            return False

        consistency_px = max(0.75, self._deadband_px * 0.75)
        if (
            self._deadband_pending_outline is None
            or _quad_motion_px(outline, self._deadband_pending_outline)
            > consistency_px
        ):
            self._deadband_pending_outline = outline.copy()
            self._deadband_pending_count = 1
        else:
            self._deadband_pending_outline = (
                0.5 * self._deadband_pending_outline + 0.5 * outline
            )
            self._deadband_pending_count += 1

        if self._deadband_pending_count < self._deadband_exit_confirm_frames:
            return False
        self._deadband_pending_outline = None
        self._deadband_pending_count = 0
        return True

    def _frozen_result(
        self,
        *,
        frame_id: int,
        ts_ms: float,
        tracking: str,
        confidence: float,
        stability: str,
        reproj: float | None = None,
        motion_px: float | None = None,
        visible_fraction: float | None = None,
    ) -> DetectionResult:
        last = self._last_locked_result
        assert last is not None
        return DetectionResult(
            board_id=last.board_id,
            frame_id=int(frame_id),
            ts_ms=float(ts_ms),
            tracking=tracking,
            confidence=float(confidence),
            pins=list(last.pins),
            outline_px=list(last.outline_px) if last.outline_px is not None else None,
            wire_exclusion_px=list(last.wire_exclusion_px)
            if last.wire_exclusion_px is not None else None,
            rvec=list(last.rvec) if last.rvec is not None else None,
            tvec=list(last.tvec) if last.tvec is not None else None,
            pose_path="stale" if tracking == "stale" else last.pose_path,
            pose_inliers=last.pose_inliers,
            pose_reproj_px=float(reproj) if reproj is not None else last.pose_reproj_px,
            pose_inlier_board_area_frac=last.pose_inlier_board_area_frac,
            pose_stability_state=stability,
            pose_motion_px=motion_px,
            pose_visible_fraction=visible_fraction,
            pose_mode=last.pose_mode,
            pose_landmarks_visible=last.pose_landmarks_visible,
        )

    def _hold_or_searching(
        self,
        frame_id: int,
        ts_ms: float,
        stability: str,
        *,
        motion_px: float | None = None,
        visible_fraction: float | None = None,
        keep_pin_pending: bool = False,
    ) -> DetectionResult:
        if not keep_pin_pending:
            self._pin_update_gate.reset()
        if (
            self._last_locked_result is not None
            and self._stale_frames < self._occlusion_hold_frames
        ):
            self._stale_frames += 1
            confidence = max(
                0.20,
                self._last_locked_result.confidence * (0.98 ** self._stale_frames),
            )
            return self._frozen_result(
                frame_id=frame_id,
                ts_ms=ts_ms,
                tracking="stale",
                confidence=confidence,
                stability=stability,
                motion_px=motion_px,
                visible_fraction=visible_fraction,
            )
        if self._last_locked_result is not None:
            self._pose_filter.reset()
            self._reset_temporal()
        return self._searching(frame_id, ts_ms, stability=stability)

    def _searching(
        self, frame_id: int, ts_ms: float, *, stability: str | None = None
    ) -> DetectionResult:
        board_id = self._profile.board.id if self._profile is not None else "unknown"
        return DetectionResult(
            board_id=board_id, frame_id=int(frame_id), ts_ms=float(ts_ms),
            tracking="searching", confidence=0.0, pins=[], outline_px=None,
            pose_path="yolo",
            pose_mode="hybrid_4pt",
            pose_landmarks_visible=0,
            pose_stability_state=stability,
        )

    def close(self) -> None:
        self._locator.close()
        if self._boundary_reference_recovery is not None:
            self._boundary_reference_recovery.close()
            self._boundary_reference_recovery = None
        if self._reference_recovery is not None:
            self._reference_recovery.close()
            self._reference_recovery = None
        self._camera = None
        self._reference_board_bgr = None
        self._pose_filter.reset()
        self._reset_temporal()


class HybridBoardDetector:
    """Choose the validated pose path for each supported board profile.

    Pi 5 uses its rotation-complete YOLO model and planar profile lattice.
    UNO Q keeps the existing reference-feature/3-D profile detector: its old
    YOLO model is useful as an asset but was not trained with semantic corner
    labels over a full 360 degrees. Treating a confident rotated UNO result as
    authoritative can swap physical GPIO identities, which is worse than the
    feature detector's brief two-frame acquisition.
    """

    def __init__(self, primary: YoloProfileDetector, fallback) -> None:
        self.primary = primary
        self.fallback = fallback
        self._board_id: str | None = None
        self.fresh_fallback_handoff = False

    def load(self, profile, profile_dir: Path) -> None:
        self._board_id = profile.board.id
        self.primary.load(profile, profile_dir)
        self.fallback.load(profile, profile_dir)

    def detect(self, frame_bgr: np.ndarray, frame_id: int, ts_ms: float) -> DetectionResult:
        if getattr(self.primary, '_yolo_only', False):
            return self.primary.detect(frame_bgr, frame_id, ts_ms)
        if self._board_id == "arduino-uno-q":
            return self.fallback.detect(frame_bgr, frame_id, ts_ms)
        body = None
        rejected_reference_evidence = None
        if self.primary.available:
            result = self.primary.detect(frame_bgr, frame_id, ts_ms)
            body = result.body
            if (self.fresh_fallback_handoff and self._board_id == 'raspberry-pi-5'
                    and result.tracking == 'stale'):
                # A held primary pose is not current evidence. Give the
                # independent reference tracker a chance to acquire this exact
                # frame, but never replace it with another stale pose.
                fresh = self.fallback.detect(frame_bgr, frame_id, ts_ms)
                if (fresh.tracking == 'locked' and fresh.frame_id == frame_id
                        and fresh.ts_ms == ts_ms and fresh.pins
                        and fresh.outline_px is not None):
                    fresh.pose_mode = 'feature_fallback'
                    fresh.pose_landmarks_visible = 0
                    return replace(fresh, body=body)
                return result
            if result.tracking in ("locked", "stale"):
                return result
            rejected = result.pose_stability_state in ('corner_box_inconsistent', 'pcb_boundary_unverified')
            rejected_reason = result.pose_stability_state
            rejected_reference_evidence = result.reference_evidence
        else:
            rejected = False
        result = self.fallback.detect(frame_bgr, frame_id, ts_ms)
        fresh_feature_lock = (
            result.tracking == 'locked' and result.frame_id == frame_id
            and result.ts_ms == ts_ms and bool(result.pins)
            and result.outline_px is not None
        ) if rejected else False
        if rejected and not fresh_feature_lock:
            # A real fresh feature lock may corroborate identity, but an old
            # fallback hold must not keep the rejected YOLO identity alive.
            return replace(self.primary._searching(
                frame_id, ts_ms, stability=rejected_reason), body=body,
                reference_evidence=rejected_reference_evidence)
        result.pose_mode = "feature_fallback"
        result.pose_landmarks_visible = 0
        return replace(result, body=body)

    def close(self) -> None:
        self.primary.close()
        self.fallback.close()

    def set_scale_recovery(self, enabled: bool) -> None:
        self.primary.set_scale_recovery(enabled)

    def set_yolo_only(self, enabled: bool) -> None:
        self.primary.set_yolo_only(enabled)

    def reset_for_camera(self, *, horizontal_fov_deg: float | None = None,
                         camera_calibration_path: Path | str | None = None,
                         use_camera_calibration: bool = True) -> None:
        for detector in (self.primary, self.fallback):
            detector.reset_for_camera(
                horizontal_fov_deg=horizontal_fov_deg,
                camera_calibration_path=camera_calibration_path,
                use_camera_calibration=use_camera_calibration,
            )
