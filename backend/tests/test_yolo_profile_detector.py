from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.vision.mock_detector import MockDetector
from app.vision.camera_model import (
    CameraModel,
    board_to_vision,
    board_outline_mm,
    default_camera,
    project_board,
    project_points,
)
from app.vision.synthetic import SyntheticScene
from app.vision.yolo_pose import (
    BoardPoseObservation,
    decode_yolo_pose_output,
    refine_board_corners_from_pcb,
)
from app.vision.yolo_profile_detector import (
    HybridBoardDetector,
    YoloProfileDetector,
    _anchor_profile_header_from_landmarks,
    _project_profile_height_on_observed_quad,
    _project_profile_on_observed_quad,
    solve_profile_pose,
    solve_landmark_pose,
)
from app.profiles.store import ProfileStore
from vision_fixtures.make_fixture import build_fixture


VIDEO_SIZE = (1280, 720)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return build_fixture(tmp_path_factory.mktemp("yolo-board-profile"))


class StaticLocator:
    def __init__(self, observation: BoardPoseObservation | None, *, available: bool = True):
        self.observation = observation
        self._available = available
        self.closed = False

    @property
    def available(self) -> bool:
        return self._available

    def locate(self, frame_bgr):
        return self.observation

    def close(self) -> None:
        self.closed = True


class SequenceLocator(StaticLocator):
    def __init__(self, observations):
        super().__init__(None)
        self.observations = list(observations)
        self.index = 0

    def locate(self, frame_bgr):
        if not self.observations:
            return None
        value = self.observations[min(self.index, len(self.observations) - 1)]
        self.index += 1
        return value


def _observation(corners, confidence=0.95):
    corners = np.asarray(corners, dtype=np.float64)
    return BoardPoseObservation(
        corners_px=corners,
        confidence=confidence,
        keypoint_confidences=np.full(4, confidence),
        box_xyxy=(
            float(corners[:, 0].min()),
            float(corners[:, 1].min()),
            float(corners[:, 0].max()),
            float(corners[:, 1].max()),
        ),
    )


def test_decode_raw_pose_tensor_restores_source_coordinates():
    frame_w, frame_h = VIDEO_SIZE
    input_size = 960
    scale = input_size / frame_w
    pad_x = 0.0
    pad_y = (input_size - frame_h * scale) / 2.0
    source_corners = np.array(
        [[220.0, 170.0], [900.0, 190.0], [880.0, 590.0], [200.0, 560.0]],
        dtype=np.float32,
    )
    model_corners = source_corners.copy()
    model_corners[:, 0] = model_corners[:, 0] * scale + pad_x
    model_corners[:, 1] = model_corners[:, 1] * scale + pad_y
    box_min = model_corners.min(axis=0)
    box_max = model_corners.max(axis=0)
    row = np.zeros(4 + 1 + 4 * 3, dtype=np.float32)
    row[:4] = [
        (box_min[0] + box_max[0]) / 2.0,
        (box_min[1] + box_max[1]) / 2.0,
        box_max[0] - box_min[0],
        box_max[1] - box_min[1],
    ]
    row[4] = 0.91
    keypoints = np.column_stack([model_corners, np.full(4, 0.88, dtype=np.float32)])
    row[5:] = keypoints.reshape(-1)

    observation = decode_yolo_pose_output(
        row.reshape(1, -1, 1),
        frame_size=VIDEO_SIZE,
        input_size=input_size,
        scale=scale,
        pad_x=pad_x,
        pad_y=pad_y,
    )

    assert observation is not None
    assert observation.confidence == pytest.approx(0.91)
    assert np.allclose(observation.corners_px, source_corners, atol=1e-4)
    assert np.allclose(observation.keypoint_confidences, 0.88, atol=1e-5)


def test_decode_8pt_pose_accepts_four_corners_plus_two_visible_j8_points():
    input_size = 960
    points = np.array([
        [180, 150], [800, 170], [790, 650], [160, 630],
        [680, 560], [680, 585], [360, 585], [360, 560],
    ], dtype=np.float32)
    row = np.zeros(4 + 1 + 8 * 3, dtype=np.float32)
    minimum = points.min(axis=0)
    maximum = points.max(axis=0)
    row[:4] = [*((minimum + maximum) / 2.0), *(maximum - minimum)]
    row[4] = 0.92
    visibility = np.array([0.9, 0.9, 0.9, 0.9, 0.85, 0.82, 0.1, 0.1])
    row[5:] = np.column_stack([points, visibility]).reshape(-1)

    observation = decode_yolo_pose_output(
        row.reshape(1, -1, 1),
        frame_size=(960, 960),
        input_size=input_size,
        scale=1.0,
        pad_x=0.0,
        pad_y=0.0,
        keypoint_count=8,
    )

    assert observation is not None
    assert observation.landmarks_px is not None
    assert observation.landmarks_px.shape == (8, 2)
    assert np.allclose(observation.corners_px, points[:4])

    visibility[5] = 0.1
    row[5:] = np.column_stack([points, visibility]).reshape(-1)
    assert decode_yolo_pose_output(
        row.reshape(1, -1, 1),
        frame_size=(960, 960),
        input_size=input_size,
        scale=1.0,
        pad_x=0.0,
        pad_y=0.0,
        keypoint_count=8,
    ) is None


def test_calibrated_8pt_pnp_projects_all_pi5_gpio_at_steep_tilt():
    profile_root = Path(__file__).resolve().parents[2] / "profiles"
    profile = ProfileStore(profile_root).profile("raspberry-pi-5")
    width, height = VIDEO_SIZE
    fallback = default_camera(VIDEO_SIZE, horizontal_fov_deg=70.42)
    camera = CameraModel(
        K=fallback.K,
        dist=fallback.dist,
        size=fallback.size,
        calibrated=True,
        calibration_path="synthetic-test",
    )
    tilt = np.deg2rad(38.0)
    yaw = np.deg2rad(27.0)
    rx = np.array([
        [1.0, 0.0, 0.0],
        [0.0, np.cos(tilt), -np.sin(tilt)],
        [0.0, np.sin(tilt), np.cos(tilt)],
    ])
    rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0.0],
        [np.sin(yaw), np.cos(yaw), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rotation = rx @ rz
    rvec, _ = cv2.Rodrigues(rotation)
    board_w, board_h = profile.board.outline_mm
    center = np.array([board_w / 2.0, board_h / 2.0, 0.0])
    tvec = np.array([0.0, 0.0, 330.0]) - rotation @ center
    object_board = np.asarray(
        [position for _name, position in profile.resolved_pose_landmarks()],
        dtype=np.float64,
    )
    image_points = project_points(
        board_to_vision(object_board), camera, rvec.reshape(3), tvec
    )
    observation = BoardPoseObservation(
        corners_px=image_points[:4],
        confidence=0.96,
        keypoint_confidences=np.full(8, 0.95),
        box_xyxy=(0.0, 0.0, float(width), float(height)),
        landmarks_px=image_points,
    )

    solved = solve_landmark_pose(
        profile, observation, camera, keypoint_threshold=0.35
    )

    assert solved is not None
    solved_rvec, solved_tvec, reproj, inliers = solved
    assert inliers >= 6
    assert reproj < 0.1
    predicted, _ = project_board(profile, camera, solved_rvec, solved_tvec)
    expected, _ = project_board(profile, camera, rvec.reshape(3), tvec)
    error = np.linalg.norm(
        np.asarray([(pin.x, pin.y) for pin in predicted])
        - np.asarray([(pin.x, pin.y) for pin in expected]),
        axis=1,
    )
    assert len(predicted) == 40
    assert float(np.percentile(error, 95)) < 0.25


def test_blue_pcb_boundary_refines_noisy_semantic_corners():
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    expected = np.array(
        [[270.0, 180.0], [970.0, 180.0], [970.0, 570.0], [270.0, 570.0]],
        dtype=np.float64,
    )
    cv2.fillConvexPoly(frame, expected.astype(np.int32), (180, 80, 20))
    noisy = expected + np.array(
        [[-22.0, 17.0], [19.0, -13.0], [24.0, 21.0], [-18.0, -16.0]]
    )
    observation = BoardPoseObservation(
        corners_px=noisy,
        confidence=0.94,
        keypoint_confidences=np.full(4, 0.9),
        box_xyxy=(245.0, 155.0, 995.0, 595.0),
    )

    refined = refine_board_corners_from_pcb(frame, observation)

    assert refined is not None
    assert np.mean(np.linalg.norm(refined.corners_px - expected, axis=1)) < 2.0
    assert refined.confidence == observation.confidence


def test_pcb_refinement_fails_closed_without_blue_boundary():
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    corners = np.array(
        [[100.0, 100.0], [500.0, 100.0], [500.0, 380.0], [100.0, 380.0]]
    )
    observation = BoardPoseObservation(
        corners_px=corners,
        confidence=0.9,
        keypoint_confidences=np.full(4, 0.9),
        box_xyxy=(90.0, 90.0, 510.0, 390.0),
    )

    assert refine_board_corners_from_pcb(frame, observation) is None


def test_pcb_refinement_recovers_a_far_board_from_oversized_yolo_pose():
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    expected = np.array(
        [[690.0, 490.0], [1075.0, 450.0], [1110.0, 745.0], [730.0, 790.0]],
        dtype=np.float64,
    )
    cv2.fillConvexPoly(frame, expected.astype(np.int32), (180, 80, 20))
    oversized = np.array(
        [[750.0, 400.0], [1245.0, 685.0], [1070.0, 1050.0], [560.0, 810.0]],
        dtype=np.float64,
    )
    observation = BoardPoseObservation(
        corners_px=oversized,
        confidence=0.86,
        keypoint_confidences=np.full(4, 0.97),
        box_xyxy=(495.0, 380.0, 1315.0, 1080.0),
    )

    refined = refine_board_corners_from_pcb(frame, observation)

    assert refined is not None
    assert np.mean(np.linalg.norm(refined.corners_px - expected, axis=1)) < 3.0


def test_reference_appearance_recovers_semantics_after_180_degree_rotation():
    reference = np.full((300, 400, 3), (180, 80, 20), dtype=np.uint8)
    cv2.circle(reference, (55, 55), 28, (245, 245, 245), -1)
    cv2.rectangle(reference, (245, 45), (365, 115), (20, 20, 20), -1)
    cv2.rectangle(reference, (70, 205), (180, 275), (220, 220, 220), -1)
    frame = np.full((600, 800, 3), 100, dtype=np.uint8)
    frame[150:450, 200:600] = cv2.rotate(reference, cv2.ROTATE_180)
    # This diamond mirrors the real failure mode: the model knows cyclic
    # semantic order, but regresses edge midpoints at an unseen rotation.
    diamond = np.array(
        [[570.0, 300.0], [400.0, 390.0], [230.0, 300.0], [400.0, 210.0]]
    )
    observation = BoardPoseObservation(
        corners_px=diamond,
        confidence=0.9,
        keypoint_confidences=np.full(4, 0.95),
        box_xyxy=(150.0, 100.0, 650.0, 500.0),
    )
    expected = np.array(
        [[599.0, 449.0], [200.0, 449.0], [200.0, 150.0], [599.0, 150.0]]
    )

    refined = refine_board_corners_from_pcb(
        frame, observation, reference_board_bgr=reference
    )

    assert refined is not None
    assert np.mean(np.linalg.norm(refined.corners_px - expected, axis=1)) < 3.0


@pytest.mark.parametrize(
    ("name", "rotate_code"),
    [
        ("0", None),
        ("cw", cv2.ROTATE_90_CLOCKWISE),
        ("180", cv2.ROTATE_180),
        ("ccw", cv2.ROTATE_90_COUNTERCLOCKWISE),
    ],
)
def test_reference_appearance_preserves_semantic_corners_at_every_right_angle(
    name, rotate_code
):
    reference = np.full((300, 400, 3), (180, 80, 20), dtype=np.uint8)
    cv2.circle(reference, (55, 55), 28, (245, 245, 245), -1)
    cv2.rectangle(reference, (245, 45), (365, 115), (20, 20, 20), -1)
    cv2.rectangle(reference, (70, 205), (180, 275), (220, 220, 220), -1)
    image = reference.copy() if rotate_code is None else cv2.rotate(reference, rotate_code)
    image_h, image_w = image.shape[:2]
    offset_x = (900 - image_w) // 2
    offset_y = (700 - image_h) // 2
    frame = np.full((700, 900, 3), 100, dtype=np.uint8)
    frame[offset_y:offset_y + image_h, offset_x:offset_x + image_w] = image
    base = np.array([[0.0, 0.0], [399.0, 0.0], [399.0, 299.0], [0.0, 299.0]])
    if name == "0":
        rotated = base
    elif name == "cw":
        rotated = np.column_stack([299.0 - base[:, 1], base[:, 0]])
    elif name == "180":
        rotated = np.column_stack([399.0 - base[:, 0], 299.0 - base[:, 1]])
    else:
        rotated = np.column_stack([base[:, 1], 399.0 - base[:, 0]])
    expected = rotated + np.array([offset_x, offset_y])
    # Deliberately roll the model semantics. Appearance matching must restore
    # the physical pin identity instead of accepting the nearest cyclic order.
    predicted = np.roll(expected, 1, axis=0)
    observation = BoardPoseObservation(
        corners_px=predicted,
        confidence=0.9,
        keypoint_confidences=np.full(4, 0.95),
        box_xyxy=(
            offset_x - 30.0,
            offset_y - 30.0,
            offset_x + image_w + 30.0,
            offset_y + image_h + 30.0,
        ),
    )

    refined = refine_board_corners_from_pcb(
        frame, observation, reference_board_bgr=reference
    )

    assert refined is not None
    assert np.mean(np.linalg.norm(refined.corners_px - expected, axis=1)) < 1.0


def test_profile_geometry_projects_gpio_from_yolo_corners(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    ts_ms = 4200.0
    truth = scene.truth_at(ts_ms / 1000.0, frame_id=7)
    corners = np.asarray(truth.outline_px, dtype=np.float64)
    locator = StaticLocator(
        BoardPoseObservation(
            corners_px=corners,
            confidence=0.95,
            keypoint_confidences=np.full(4, 0.95),
            box_xyxy=(
                float(corners[:, 0].min()), float(corners[:, 1].min()),
                float(corners[:, 0].max()), float(corners[:, 1].max()),
            ),
        )
    )
    detector = YoloProfileDetector(locator=locator)
    detector.load(profile, profile_dir)
    result = detector.detect(scene.frame_at(ts_ms / 1000.0), 7, ts_ms)

    assert result.tracking == "locked"
    assert result.pose_path == "yolo"
    assert result.pose_inliers == 4
    assert result.pose_reproj_px is not None and result.pose_reproj_px < 0.1
    assert [pin.pin_id for pin in result.pins] == [pin.pin_id for pin in truth.pins]
    predicted = np.array([(pin.x, pin.y) for pin in result.pins])
    expected = np.array([(pin.x, pin.y) for pin in truth.pins])
    assert np.median(np.linalg.norm(predicted - expected, axis=1)) < 0.2
    detector.close()
    assert locator.closed


def test_height_aware_projection_tracks_gpio_parallax_at_steep_tilt(fixture):
    profile, _profile_dir = fixture
    camera = default_camera(VIDEO_SIZE, horizontal_fov_deg=70.42)
    tilt = np.deg2rad(48.0)
    yaw = np.deg2rad(24.0)
    rx = np.array([
        [1.0, 0.0, 0.0],
        [0.0, np.cos(tilt), -np.sin(tilt)],
        [0.0, np.sin(tilt), np.cos(tilt)],
    ])
    rz = np.array([
        [np.cos(yaw), -np.sin(yaw), 0.0],
        [np.sin(yaw), np.cos(yaw), 0.0],
        [0.0, 0.0, 1.0],
    ])
    rotation = rx @ rz
    rvec, _ = cv2.Rodrigues(rotation)
    rvec = rvec.reshape(3)
    board_w, board_h = profile.board.outline_mm
    centre_board = np.array([board_w / 2.0, board_h / 2.0, 0.0])
    tvec = np.array([0.0, 0.0, 250.0]) - rotation @ centre_board
    corners = project_points(
        board_outline_mm(profile.board.outline_mm), camera, rvec, tvec
    )
    solved = solve_profile_pose(profile.board.outline_mm, corners, camera)
    assert solved is not None
    solved_rvec, solved_tvec, reproj = solved
    assert reproj < 0.1

    height_aware, outline = _project_profile_height_on_observed_quad(
        profile,
        corners,
        VIDEO_SIZE,
        0.95,
        camera,
        solved_rvec,
        solved_tvec,
    )
    planar, _ = _project_profile_on_observed_quad(
        profile, corners, VIDEO_SIZE, 0.95
    )
    truth, _ = project_board(profile, camera, rvec, tvec, 0.95)
    height_points = np.asarray([(pin.x, pin.y) for pin in height_aware])
    planar_points = np.asarray([(pin.x, pin.y) for pin in planar])
    truth_points = np.asarray([(pin.x, pin.y) for pin in truth])

    assert np.allclose(outline, corners, atol=1e-4)
    assert np.median(np.linalg.norm(height_points - truth_points, axis=1)) < 0.5
    assert np.median(np.linalg.norm(planar_points - truth_points, axis=1)) > 2.0


def test_pi5_header_landmarks_remove_uncalibrated_lattice_offset():
    profile_root = Path(__file__).resolve().parents[2] / "profiles"
    profile = ProfileStore(profile_root).profile("raspberry-pi-5")
    camera = default_camera(VIDEO_SIZE, horizontal_fov_deg=70.42)
    rvec = np.array([0.18, -0.12, 0.27], dtype=np.float64)
    tvec = np.array([-42.0, -28.0, 330.0], dtype=np.float64)
    base, _outline = project_board(profile, camera, rvec, tvec, 0.91)
    base_by_id = {pin.pin_id: np.array([pin.x, pin.y]) for pin in base}

    resolved = profile.resolved_pose_landmarks()
    landmark_points = project_points(
        board_to_vision(np.asarray([position for _name, position in resolved])),
        camera,
        rvec,
        tvec,
    )
    endpoint_offsets = {
        "3V3_P1": np.array([24.0, 7.0]),
        "5V_P2": np.array([28.0, 10.0]),
        "GPIO21": np.array([10.0, 16.0]),
        "GND_P39": np.array([20.0, 13.0]),
    }
    expected_anchors: dict[str, np.ndarray] = {}
    for index, landmark in enumerate(profile.pose_landmarks):
        if landmark.pin_id in endpoint_offsets:
            landmark_points[index] = (
                base_by_id[landmark.pin_id] + endpoint_offsets[landmark.pin_id]
            )
            expected_anchors[landmark.pin_id] = landmark_points[index].copy()
    observation = BoardPoseObservation(
        corners_px=landmark_points[:4],
        confidence=0.91,
        keypoint_confidences=np.full(8, 0.95),
        box_xyxy=(0.0, 0.0, float(VIDEO_SIZE[0]), float(VIDEO_SIZE[1])),
        landmarks_px=landmark_points,
    )

    corrected = _anchor_profile_header_from_landmarks(
        profile,
        base,
        observation,
        VIDEO_SIZE,
        keypoint_threshold=0.35,
    )
    corrected_by_id = {
        pin.pin_id: np.array([pin.x, pin.y]) for pin in corrected
    }

    assert len(corrected) == 40
    for pin_id, expected in expected_anchors.items():
        assert np.allclose(corrected_by_id[pin_id], expected, atol=1e-6)
    # An interior pin receives the row-wise interpolation, not one global
    # translation copied from either end.
    gpio17 = profile.pin_by_id("GPIO17")
    start = profile.pin_by_id("3V3_P1")
    end = profile.pin_by_id("GND_P39")
    assert gpio17 is not None and start is not None and end is not None
    t = (gpio17.pos_mm[0] - start.pos_mm[0]) / (end.pos_mm[0] - start.pos_mm[0])
    expected_offset = (
        (1.0 - t) * endpoint_offsets[start.id] + t * endpoint_offsets[end.id]
    )
    assert np.allclose(
        corrected_by_id[gpio17.id] - base_by_id[gpio17.id],
        expected_offset,
        atol=1e-6,
    )


def test_pi5_header_landmark_correction_rejects_a_crossed_endpoint():
    profile_root = Path(__file__).resolve().parents[2] / "profiles"
    profile = ProfileStore(profile_root).profile("raspberry-pi-5")
    camera = default_camera(VIDEO_SIZE, horizontal_fov_deg=70.42)
    rvec = np.array([0.08, -0.05, 0.12], dtype=np.float64)
    tvec = np.array([-42.0, -28.0, 340.0], dtype=np.float64)
    pins, _outline = project_board(profile, camera, rvec, tvec, 0.9)
    resolved = profile.resolved_pose_landmarks()
    landmarks = project_points(
        board_to_vision(np.asarray([position for _name, position in resolved])),
        camera,
        rvec,
        tvec,
    )
    landmarks[[4, 5]] = landmarks[[5, 4]]
    observation = BoardPoseObservation(
        corners_px=landmarks[:4],
        confidence=0.9,
        keypoint_confidences=np.full(8, 0.95),
        box_xyxy=(0.0, 0.0, float(VIDEO_SIZE[0]), float(VIDEO_SIZE[1])),
        landmarks_px=landmarks,
    )

    rejected = _anchor_profile_header_from_landmarks(
        profile,
        pins,
        observation,
        VIDEO_SIZE,
        keypoint_threshold=0.35,
    )

    assert [(pin.x, pin.y) for pin in rejected] == [(pin.x, pin.y) for pin in pins]


def test_hybrid_uses_existing_pipeline_when_yolo_model_is_unavailable(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    primary = YoloProfileDetector(locator=StaticLocator(None, available=False))
    fallback = MockDetector(scene=scene)
    detector = HybridBoardDetector(primary, fallback)
    detector.load(profile, Path(profile_dir))

    result = detector.detect(scene.frame_at(1.0), 3, 1000.0)

    assert result.tracking == "locked"
    assert result.pose_path != "yolo"
    assert len(result.pins) == len(profile.pins)
    detector.close()


def test_hybrid_keeps_arduino_on_validated_profile_detector(fixture):
    profile, profile_dir = fixture
    arduino_profile = profile.model_copy(deep=True)
    arduino_profile.board.id = "arduino-uno-q"
    scene = SyntheticScene(arduino_profile, profile_dir, VIDEO_SIZE)
    truth = scene.truth_at(1.0, frame_id=3)
    primary = YoloProfileDetector(
        locator=StaticLocator(_observation(truth.outline_px))
    )
    detector = HybridBoardDetector(primary, MockDetector(scene=scene))
    detector.load(arduino_profile, Path(profile_dir))

    result = detector.detect(scene.frame_at(1.0), 3, 1000.0)

    assert result.tracking == "locked"
    assert result.pose_path != "yolo"
    assert len(result.pins) == len(arduino_profile.pins)
    detector.close()


def test_yolo_deadband_keeps_static_pin_coordinates_exact(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    corners = np.asarray(scene.truth_at(2.0, frame_id=0).outline_px)
    rng = np.random.default_rng(2026)
    observations = [
        _observation(corners + rng.normal(0.0, 0.12, corners.shape))
        for _ in range(40)
    ]
    detector = YoloProfileDetector(
        locator=SequenceLocator(observations), stability_deadband_px=0.85
    )
    detector.load(profile, profile_dir)
    # No blue contour: this exercises the YOLO/PnP temporal guard itself,
    # rather than letting PCB-boundary refinement erase the injected noise.
    frame = np.full((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), 110, dtype=np.uint8)

    tracks = []
    states = []
    for frame_id in range(len(observations)):
        result = detector.detect(frame, frame_id, frame_id * (1000.0 / 30.0))
        assert result.tracking == "locked"
        tracks.append([(pin.x, pin.y) for pin in result.pins])
        states.append(result.pose_stability_state)

    tracks = np.asarray(tracks)
    assert float(np.max(np.std(tracks[5:], axis=0))) < 0.05
    assert "deadband" in states[1:]


def test_yolo_hand_occlusion_holds_last_good_geometry(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    t = 2.0
    truth = scene.truth_at(t, frame_id=0)
    corners = np.asarray(truth.outline_px, dtype=np.float64)
    observations = [_observation(corners)] * 12
    detector = YoloProfileDetector(
        locator=SequenceLocator(observations),
        visibility_warmup_frames=4,
        occlusion_visibility_ratio=0.70,
    )
    detector.load(profile, profile_dir)
    clear = scene.frame_at(t)

    locked = None
    for frame_id in range(6):
        locked = detector.detect(clear, frame_id, frame_id * (1000.0 / 30.0))
        assert locked.tracking == "locked"
    assert locked is not None
    frozen = np.asarray([(pin.x, pin.y) for pin in locked.pins])

    # Neutral rectangle emulates a hand covering most of the blue PCB while
    # YOLO still returns a superficially confident four-corner observation.
    occluded = clear.copy()
    center = corners.mean(axis=0)
    covered = center + 0.78 * (corners - center)
    cv2.fillConvexPoly(occluded, covered.astype(np.int32), (145, 145, 145))
    held = detector.detect(occluded, 6, 200.0)

    assert held.tracking == "stale"
    assert held.pose_stability_state == "occlusion_hold"
    assert np.array_equal(
        np.asarray([(pin.x, pin.y) for pin in held.pins]), frozen
    )
    assert held.pose_visible_fraction is not None

    recovered = detector.detect(clear, 7, 233.3)
    assert recovered.tracking == "locked"
    assert recovered.pose_stability_state in {"deadband", "tracking"}


def test_default_gate_freezes_on_early_hand_visibility_drop(monkeypatch, fixture):
    """A roughly 28% PCB visibility drop must freeze before pose contamination.

    This reproduces the first stage of the physical webcam hand test.  The old
    0.65 ratio accepted this frame; the 0.80 gate rejects it immediately.
    """
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    corners = np.asarray(scene.truth_at(2.0, frame_id=0).outline_px)
    shifted = corners + np.array([6.0, -4.0])
    observations = [_observation(corners)] * 6 + [_observation(shifted)]
    detector = YoloProfileDetector(
        locator=SequenceLocator(observations),
        visibility_warmup_frames=4,
        stability_deadband_px=0.0,
    )
    detector.load(profile, profile_dir)
    frame = np.full((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), 110, dtype=np.uint8)
    fractions = iter([0.40] * 6 + [0.29])
    monkeypatch.setattr(
        "app.vision.yolo_profile_detector._blue_board_fraction",
        lambda *_args, **_kwargs: next(fractions),
    )

    locked = None
    for frame_id in range(6):
        locked = detector.detect(frame, frame_id, frame_id * (1000.0 / 30.0))
        assert locked.tracking == "locked"
    assert locked is not None
    frozen = np.asarray([(pin.x, pin.y) for pin in locked.pins])

    held = detector.detect(frame, 6, 200.0)

    assert held.tracking == "stale"
    assert held.pose_stability_state == "occlusion_hold"
    assert np.array_equal(np.asarray([(pin.x, pin.y) for pin in held.pins]), frozen)


def test_yolo_large_jump_requires_multiframe_confirmation(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    corners = np.asarray(scene.truth_at(2.0, frame_id=0).outline_px)
    shifted = corners + np.array([35.0, -18.0])
    observations = [_observation(corners)] + [_observation(shifted)] * 3
    detector = YoloProfileDetector(
        locator=SequenceLocator(observations), jump_confirm_frames=3
    )
    detector.load(profile, profile_dir)
    frame = np.full((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), 110, dtype=np.uint8)

    first = detector.detect(frame, 0, 0.0)
    frozen = np.asarray([(pin.x, pin.y) for pin in first.pins])
    jump1 = detector.detect(frame, 1, 33.3)
    jump2 = detector.detect(frame, 2, 66.6)
    accepted = detector.detect(frame, 3, 99.9)

    assert jump1.tracking == jump2.tracking == "stale"
    assert jump1.pose_stability_state == jump2.pose_stability_state == "jump_hold"
    assert np.array_equal(np.asarray([(p.x, p.y) for p in jump2.pins]), frozen)
    assert accepted.tracking == "locked"
    assert np.median(
        np.linalg.norm(
            np.asarray([(p.x, p.y) for p in accepted.pins]) - frozen, axis=1
        )
    ) > 10.0


def test_yolo_deadband_releases_after_sustained_real_motion(fixture):
    profile, profile_dir = fixture
    scene = SyntheticScene(profile, profile_dir, VIDEO_SIZE)
    corners = np.asarray(scene.truth_at(2.0, frame_id=0).outline_px)
    shifted = corners + np.array([5.0, 0.0])
    observations = [_observation(corners)] + [_observation(shifted)] * 20
    detector = YoloProfileDetector(
        locator=SequenceLocator(observations),
        stability_deadband_px=2.0,
        deadband_exit_confirm_frames=5,
    )
    detector.load(profile, profile_dir)
    frame = np.full((VIDEO_SIZE[1], VIDEO_SIZE[0], 3), 110, dtype=np.uint8)

    first = detector.detect(frame, 0, 0.0)
    origin = np.asarray([(pin.x, pin.y) for pin in first.pins])
    released = None
    for frame_id in range(1, len(observations)):
        result = detector.detect(frame, frame_id, frame_id * (1000.0 / 30.0))
        points = np.asarray([(pin.x, pin.y) for pin in result.pins])
        if np.median(np.linalg.norm(points - origin, axis=1)) > 2.0:
            released = result
            break

    assert released is not None, "sustained board motion remained permanently frozen"
    assert released.tracking == "locked"
    assert released.pose_stability_state == "tracking"
