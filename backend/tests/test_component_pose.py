from __future__ import annotations

import cv2
import json
import numpy as np
import pytest
from pathlib import Path

from app.component_worker import (
    ComponentPoseTracker,
    ComponentVisionProfile,
    component_pose_message,
    orient_component_corners_from_pin_row,
    project_component_pins,
    project_component_outline,
    refine_component_corners_from_pcb,
    refine_component_corners_from_mounting_holes,
)
from app.vision.yolo_pose import BoardPoseObservation


PROFILE = ComponentVisionProfile(
    component_id="photoresistor-module",
    pins=(("VCC", 0.8, 0.9), ("GND", 0.5, 0.9), ("AO", 0.2, 0.9)),
)


def _observation(corners: np.ndarray) -> BoardPoseObservation:
    return BoardPoseObservation(
        corners_px=corners.astype(np.float64),
        confidence=0.9,
        keypoint_confidences=np.full(4, 0.85, dtype=np.float64),
        box_xyxy=(float(corners[:, 0].min()), float(corners[:, 1].min()),
                  float(corners[:, 0].max()), float(corners[:, 1].max())),
    )


def test_profile_pins_are_projected_by_semantic_quad() -> None:
    corners = np.array([[100, 50], [200, 50], [200, 250], [100, 250]], dtype=np.float32)
    pins = project_component_pins(PROFILE, corners, 0.8, (640, 480))
    assert [pin.id for pin in pins] == ["VCC", "GND", "AO"]
    assert np.allclose([(pin.x, pin.y) for pin in pins], [(180, 230), (150, 230), (120, 230)])


HW123_PROFILE_PATH = (
    Path(__file__).resolve().parents[2]
    / "profiles/components/hw-123/vision_profile.json"
)
# Source camera crop, not a rendered fixture. The model's 0th corner was the
# physical top-right on this breadboard view; canonical VCC is at its right.
HW123_WRONG_CORNERS = np.array(
    [[157.3, 23.6], [154.6, 121.8], [19.6, 118.1], [22.4, 19.9]]
)
HW123_PAD_CENTRES = np.array(
    [[146, 33], [130, 32], [114, 32], [97, 32],
     [81, 31], [65, 31], [48, 31], [33, 30]], dtype=np.float64
)


@pytest.mark.parametrize("turn", range(4))
@pytest.mark.parametrize("semantic_shift", range(4))
def test_hw123_real_header_corrects_cyclic_order_at_every_rotation(
    turn: int, semantic_shift: int,
) -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    assert profile.pin_row_orientation
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/hw123-header-row.png"))
    corners = HW123_WRONG_CORNERS.copy()
    expected = HW123_PAD_CENTRES.copy()
    for _ in range(turn):
        width = frame.shape[1]
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        corners = np.column_stack([corners[:, 1], width - 1 - corners[:, 0]])
        expected = np.column_stack([expected[:, 1], width - 1 - expected[:, 0]])
    corners = np.roll(corners, semantic_shift, axis=0)
    original = _observation(corners)
    refined = orient_component_corners_from_pin_row(frame, original, profile)
    assert refined is not None
    pins = project_component_pins(
        profile, refined.corners_px, 0.8, (frame.shape[1], frame.shape[0])
    )
    assert [pin.id for pin in pins] == [
        "VCC", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT"
    ]
    errors = np.linalg.norm(np.array([(pin.x, pin.y) for pin in pins]) - expected, axis=1)
    assert np.max(errors) < 3.0
    assert np.array_equal(original.corners_px, corners)  # no shared-array mutation


@pytest.mark.parametrize("brightness", [0.5, 0.75, 1.2])
def test_hw123_header_orientation_tolerates_lighting(brightness: float) -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/hw123-header-row.png"))
    frame = np.clip(frame.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    refined = orient_component_corners_from_pin_row(
        frame, _observation(HW123_WRONG_CORNERS), profile
    )
    assert refined is not None
    assert np.allclose(refined.corners_px, np.roll(HW123_WRONG_CORNERS, -1, axis=0))


@pytest.mark.parametrize('offset', [(3, 0), (-3, 0), (0, 3), (0, -3)])
def test_hw123_row_search_tolerates_small_model_boundary_offset(offset) -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    frame = cv2.imread(str(Path(__file__).parent / 'fixtures/hw123-header-row.png'))
    corners = HW123_WRONG_CORNERS + offset
    original = _observation(corners)
    refined = orient_component_corners_from_pin_row(frame, original, profile)
    assert refined is not None
    # Search resolves order only; it cannot silently rewrite pin/profile geometry.
    assert np.allclose(refined.corners_px, np.roll(corners, -1, axis=0))
    assert np.array_equal(original.corners_px, corners)


def test_hw123_row_search_does_not_use_out_of_frame_warp_padding() -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    frame = cv2.imread(str(Path(__file__).parent / 'fixtures/hw123-header-row.png'))
    assert orient_component_corners_from_pin_row(
        frame, _observation(HW123_WRONG_CORNERS + [0, 22]), profile,
    ) is None


def test_tft_worker_corroborates_outer_outline_not_mounting_holes(monkeypatch) -> None:
    from types import SimpleNamespace
    from app.capture.bus import FrameSlot
    from app.component_worker import ComponentPoseWorker, ComponentPoseState, ComponentPoseResult
    profile_path = Path(__file__).resolve().parents[2] / 'profiles/components/mrd-tf240-8p-cs/vision_profile.json'
    profile = ComponentVisionProfile.load(profile_path)
    frame = np.full((400, 640, 3), 50, np.uint8)
    source = FrameSlot(frame, 12, 1200, 12)
    fresh = np.float32([[110, 85], [310, 85], [310, 335], [110, 335]])
    held = fresh + [-10, 0]
    result = ComponentPoseResult(profile.component_id, 12, 1200, 'stale', .7, (640, 400), held, (), 'jump_hold')
    state = ComponentPoseState()
    worker = ComponentPoseWorker(
        bus=SimpleNamespace(get_latest=lambda **kwargs: source), state=state,
        model_path='unused', profile_path=profile_path,
        locator=SimpleNamespace(locate=lambda _: _observation(fresh)),
        publish=lambda _: worker._stop.set(),
    )
    monkeypatch.setattr('app.component_worker.refine_component_corners_from_mounting_holes', lambda _, obs: obs)
    monkeypatch.setattr(worker._tracker, 'update', lambda *args, **kwargs: result)
    worker._run()
    _, published = state.get_synchronized(profile.component_id)
    assert np.allclose(published.motion_outline_px, project_component_outline(profile, fresh))
    assert np.allclose(published.outline_px, project_component_outline(profile, held))
    assert not np.allclose(published.motion_outline_px, fresh)
    assert np.array_equal(result.outline_px, held)


def test_hw123_unverified_row_goes_stale_then_hides_instead_of_rotating_pins() -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    frame = cv2.imread(str(Path(__file__).parent / "fixtures/hw123-header-row.png"))
    original = _observation(HW123_WRONG_CORNERS)
    refined = orient_component_corners_from_pin_row(frame, original, profile)
    tracker = ComponentPoseTracker(profile, occlusion_hold_s=2.0)
    locked = tracker.update(frame, refined, frame_id=1, ts_ms=1000.0)
    assert locked.tracking == "locked"
    covered = frame.copy()
    covered[20:43, 20:158] = (65, 65, 65)
    unverified = orient_component_corners_from_pin_row(covered, original, profile)
    assert unverified is None
    held = tracker.update(covered, unverified, frame_id=2, ts_ms=1300.0)
    assert held.tracking == "stale"
    assert held.pins == locked.pins
    expired = tracker.update(covered, unverified, frame_id=3, ts_ms=3200.0)
    assert expired.tracking == "searching"
    assert expired.pins == ()


def test_hw123_row_rejects_uniform_background_and_ambiguous_edges() -> None:
    profile = ComponentVisionProfile.load(HW123_PROFILE_PATH)
    corners = np.array([[20, 20], [275, 20], [275, 275], [20, 275]], np.float64)
    observation = _observation(corners)
    blank = np.full((300, 300, 3), 180, np.uint8)
    assert orient_component_corners_from_pin_row(blank, observation, profile) is None
    ambiguous = np.full_like(blank, (75, 30, 10))
    for shift in [0, 2]:
        for pin in project_component_pins(profile, np.roll(corners, shift, axis=0), .9, (300, 300)):
            cv2.circle(ambiguous, (round(pin.x), round(pin.y)), 7, (220, 220, 220), -1)
    assert orient_component_corners_from_pin_row(ambiguous, observation, profile) is None


def test_pin_row_orientation_is_opt_in_and_validates_profile_geometry(tmp_path) -> None:
    assert not PROFILE.pin_row_orientation
    data = json.loads(HW123_PROFILE_PATH.read_text(encoding="utf-8"))
    data["pins"][1]["y_norm"] = 0.5
    path = tmp_path / "vision_profile.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="horizontal pin row"):
        ComponentVisionProfile.load(path)


def test_mounting_hole_profile_can_disable_blue_pcb_corner_refinement(tmp_path) -> None:
    profile_path = tmp_path / "vision_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "id": "mrd-tf240-8p-cs",
                "keypoint_count": 4,
                "corner_refinement": "none",
                "pins": [
                    {"id": "GND", "x_norm": 0.287, "y_norm": 0.015},
                    {"id": "VCC", "x_norm": 0.350, "y_norm": 0.015},
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = ComponentVisionProfile.load(profile_path)
    assert profile.corner_refinement == "none"


def test_unknown_component_corner_refinement_is_rejected(tmp_path) -> None:
    profile_path = tmp_path / "vision_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "id": "invalid",
                "corner_refinement": "mounting-hole",
                "pins": [{"id": "P1", "x_norm": 0.5, "y_norm": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    try:
        ComponentVisionProfile.load(profile_path)
    except ValueError as exc:
        assert "corner_refinement" in str(exc)
    else:
        raise AssertionError("invalid corner refinement must be rejected")


def test_mrd_profile_projects_all_header_pins_in_canonical_order() -> None:
    profile_path = (
        Path(__file__).resolve().parents[2]
        / "profiles"
        / "components"
        / "mrd-tf240-8p-cs"
        / "vision_profile.json"
    )
    profile = ComponentVisionProfile.load(profile_path)
    mounting_holes = np.array(
        [[100, 100], [700, 100], [700, 900], [100, 900]], dtype=np.float32
    )
    pins = project_component_pins(profile, mounting_holes, 0.9, (800, 1000))
    outline = project_component_outline(profile, mounting_holes)

    assert profile.corner_refinement == "mounting_holes"
    assert [pin.id for pin in pins] == [
        "GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BLK"
    ]
    assert np.allclose(
        [(pin.x, pin.y) for pin in pins],
        [(272, 68), (310, 68), (347, 68), (385, 68),
         (423, 68), (460, 68), (498, 68), (536, 68)],
        atol=0.4,
    )
    assert np.allclose(
        outline,
        [[40, 64], [754, 64], [754, 937.6], [40, 937.6]],
        atol=0.6,
    )


def test_mounting_hole_refinement_snaps_all_four_semantic_centres() -> None:
    frame = np.full((420, 640, 3), 105, dtype=np.uint8)
    actual = np.array(
        [[490, 95], [500, 330], [145, 325], [150, 90]], dtype=np.float64
    )
    for x, y in actual.astype(np.int32):
        cv2.circle(frame, (x, y), 13, (245, 245, 245), -1)
        cv2.circle(frame, (x, y), 7, (55, 55, 55), -1)
    predicted = actual + np.array(
        [[22, -18], [18, 34], [-20, 15], [-24, -28]], dtype=np.float64
    )
    observation = BoardPoseObservation(
        corners_px=predicted,
        confidence=0.8,
        keypoint_confidences=np.full(4, 0.8, dtype=np.float64),
        box_xyxy=(110.0, 50.0, 535.0, 370.0),
    )
    refined = refine_component_corners_from_mounting_holes(frame, observation)
    assert refined is not None
    assert np.max(np.linalg.norm(refined.corners_px - actual, axis=1)) <= 3.0


def test_eight_point_profile_uses_direct_pin_landmarks(tmp_path) -> None:
    profile_path = tmp_path / "vision_profile.json"
    profile_path.write_text(
        json.dumps(
            {
                "id": "hc-sr04",
                "keypoint_count": 8,
                "orientation_keypoint_indices": [4, 7],
                "pins": [
                    {"id": "VCC", "x_norm": 0.4, "y_norm": 1.0, "keypoint_index": 4},
                    {"id": "TRIG", "x_norm": 0.47, "y_norm": 1.0, "keypoint_index": 5},
                    {"id": "ECHO", "x_norm": 0.53, "y_norm": 1.0, "keypoint_index": 6},
                    {"id": "GND", "x_norm": 0.6, "y_norm": 1.0, "keypoint_index": 7},
                ],
            }
        ),
        encoding="utf-8",
    )
    profile = ComponentVisionProfile.load(profile_path)
    assert profile.keypoint_count == 8
    assert profile.pin_keypoint_indices == (4, 5, 6, 7)
    assert profile.orientation_keypoint_indices == (4, 7)

    corners = np.array([[100, 50], [200, 50], [200, 250], [100, 250]], dtype=np.float32)
    landmarks = np.vstack(
        [corners, np.array([[141, 244], [147, 243], [153, 242], [159, 241]])]
    )
    confidences = np.array([0.9, 0.9, 0.9, 0.9, 0.81, 0.82, 0.83, 0.84])
    pins = project_component_pins(
        profile,
        corners,
        0.88,
        (640, 480),
        landmarks_px=landmarks,
        keypoint_confidences=confidences,
    )
    assert [pin.id for pin in pins] == ["VCC", "TRIG", "ECHO", "GND"]
    assert np.allclose(
        [(pin.x, pin.y) for pin in pins],
        [(141, 244), (147, 243), (153, 242), (159, 241)],
    )
    assert [pin.confidence for pin in pins] == [0.81, 0.82, 0.83, 0.84]


def test_occlusion_freezes_last_trusted_pin_coordinates() -> None:
    tracker = ComponentPoseTracker(
        PROFILE,
        visibility_warmup_frames=1,
        occlusion_visibility_ratio=0.6,
        occlusion_hold_s=2.0,
    )
    corners = np.array([[100, 50], [200, 50], [200, 250], [100, 250]], dtype=np.float64)
    clear = np.zeros((300, 320, 3), dtype=np.uint8)
    clear[50:251, 100:201] = (255, 0, 0)
    locked = tracker.update(clear, _observation(corners), frame_id=1, ts_ms=1000.0)
    assert locked.tracking == "locked"

    covered = np.zeros_like(clear)
    shifted = corners + np.array([40.0, 0.0])
    held = tracker.update(covered, _observation(shifted), frame_id=2, ts_ms=1300.0)
    assert held.tracking == "stale"
    assert held.stability == "occlusion_hold"
    assert np.array_equal(held.outline_px, locked.outline_px)
    assert [(pin.x, pin.y) for pin in held.pins] == [(pin.x, pin.y) for pin in locked.pins]


def test_deadband_holds_exact_coordinates_and_message_shape() -> None:
    tracker = ComponentPoseTracker(PROFILE, visibility_warmup_frames=5, deadband_px=2.0)
    corners = np.array([[100, 50], [200, 50], [200, 250], [100, 250]], dtype=np.float64)
    frame = np.zeros((300, 320, 3), dtype=np.uint8)
    frame[50:251, 100:201] = (255, 0, 0)
    first = tracker.update(frame, _observation(corners), frame_id=1, ts_ms=1000.0)
    second = tracker.update(frame, _observation(corners + 0.8), frame_id=2, ts_ms=1100.0)
    assert second.stability == "deadband"
    assert np.array_equal(second.outline_px, first.outline_px)
    message = component_pose_message(second)
    assert message["type"] == "component_pose"
    assert message["component_id"] == "photoresistor-module"
    assert [pin["id"] for pin in message["pins"]] == ["VCC", "GND", "AO"]


def test_blue_pcb_contour_repairs_a_skewed_yolo_corner() -> None:
    frame = np.zeros((300, 360, 3), dtype=np.uint8)
    actual = np.array([[250, 235], [150, 235], [150, 55], [250, 55]], dtype=np.int32)
    cv2.fillConvexPoly(frame, actual, (255, 0, 0))
    predicted = actual.astype(np.float64)
    predicted[2] += np.array([30.0, -25.0])
    observation = BoardPoseObservation(
        corners_px=predicted,
        confidence=0.8,
        keypoint_confidences=np.full(4, 0.8, dtype=np.float64),
        box_xyxy=(125.0, 30.0, 275.0, 260.0),
    )
    refined = refine_component_corners_from_pcb(frame, observation)
    assert refined is not None
    assert np.max(np.linalg.norm(refined.corners_px - actual, axis=1)) <= 2.0


def test_blue_pcb_refinement_preserves_direct_pin_landmarks() -> None:
    frame = np.zeros((300, 360, 3), dtype=np.uint8)
    actual = np.array([[250, 235], [150, 235], [150, 55], [250, 55]], dtype=np.int32)
    cv2.fillConvexPoly(frame, actual, (255, 0, 0))
    predicted = actual.astype(np.float64)
    predicted[2] += np.array([30.0, -25.0])
    pin_landmarks = np.array(
        [[230.0, 70.0], [210.0, 70.0], [190.0, 70.0], [170.0, 70.0]]
    )
    observation = BoardPoseObservation(
        corners_px=predicted,
        confidence=0.8,
        keypoint_confidences=np.full(8, 0.8, dtype=np.float64),
        box_xyxy=(125.0, 30.0, 275.0, 260.0),
        landmarks_px=np.vstack([predicted, pin_landmarks]),
    )
    refined = refine_component_corners_from_pcb(frame, observation)
    assert refined is not None
    assert refined.landmarks_px is not None
    assert np.allclose(refined.landmarks_px[:4], refined.corners_px)
    assert np.array_equal(refined.landmarks_px[4:], pin_landmarks)


def test_pin_landmark_direction_recovers_collapsed_component_corners() -> None:
    frame = np.zeros((260, 360, 3), dtype=np.uint8)
    actual = np.array(
        [[70, 50], [290, 50], [290, 190], [70, 190]], dtype=np.float64
    )
    cv2.fillConvexPoly(frame, actual.astype(np.int32), (255, 0, 0))
    collapsed = np.array(
        [[145, 105], [210, 145], [155, 110], [225, 130]], dtype=np.float64
    )
    pin_landmarks = np.array(
        [[130, 190], [160, 190], [195, 190], [230, 190]], dtype=np.float64
    )
    observation = BoardPoseObservation(
        corners_px=collapsed,
        confidence=0.8,
        keypoint_confidences=np.full(8, 0.8, dtype=np.float64),
        box_xyxy=(50.0, 30.0, 310.0, 215.0),
        landmarks_px=np.vstack([collapsed, pin_landmarks]),
    )
    refined = refine_component_corners_from_pcb(
        frame,
        observation,
        orientation_keypoint_indices=(4, 7),
    )
    assert refined is not None
    assert np.max(np.linalg.norm(refined.corners_px - actual, axis=1)) <= 2.0


def test_invalid_eight_point_quad_publishes_diagnostics_without_trusted_pins() -> None:
    profile = ComponentVisionProfile(
        component_id="hc-sr04",
        pins=(
            ("VCC", 0.42, 1.0),
            ("TRIG", 0.47, 1.0),
            ("ECHO", 0.53, 1.0),
            ("GND", 0.59, 1.0),
        ),
        keypoint_count=8,
        pin_keypoint_indices=(4, 5, 6, 7),
    )
    tracker = ComponentPoseTracker(profile)
    crossed = np.array(
        [[100, 50], [200, 250], [200, 50], [100, 250]], dtype=np.float64
    )
    direct_pins = np.array(
        [[140, 240], [150, 240], [160, 240], [170, 240]], dtype=np.float64
    )
    observation = BoardPoseObservation(
        corners_px=crossed,
        confidence=0.74,
        keypoint_confidences=np.full(8, 0.8, dtype=np.float64),
        box_xyxy=(90.0, 40.0, 210.0, 260.0),
        landmarks_px=np.vstack([crossed, direct_pins]),
    )
    result = tracker.update(
        np.zeros((300, 320, 3), dtype=np.uint8),
        observation,
        frame_id=7,
        ts_ms=1000.0,
    )
    assert result.tracking == "searching"
    assert result.pins == ()
    assert result.diagnostic_reason == "invalid_quad"
    assert [(pin.id, pin.x, pin.y) for pin in result.diagnostic_pins] == [
        ("VCC", 140.0, 240.0),
        ("TRIG", 150.0, 240.0),
        ("ECHO", 160.0, 240.0),
        ("GND", 170.0, 240.0),
    ]
    message = component_pose_message(result)
    assert message["pins"] == []
    assert message["diagnostic"]["reason"] == "invalid_quad"
    assert [pin["id"] for pin in message["diagnostic"]["pins"]] == [
        "VCC", "TRIG", "ECHO", "GND"
    ]


def test_small_motion_requires_stable_deadband_exit_consensus() -> None:
    tracker = ComponentPoseTracker(
        PROFILE,
        deadband_px=2.0,
        deadband_exit_confirm_frames=3,
        visibility_warmup_frames=30,
    )
    corners = np.array([[100, 50], [200, 50], [200, 250], [100, 250]], dtype=np.float64)
    frame = np.zeros((300, 320, 3), dtype=np.uint8)
    frame[40:261, 90:211] = (255, 0, 0)
    first = tracker.update(frame, _observation(corners), frame_id=1, ts_ms=1000.0)
    shifted = corners + np.array([2.5, 0.0])
    pending1 = tracker.update(frame, _observation(shifted), frame_id=2, ts_ms=1100.0)
    pending2 = tracker.update(frame, _observation(shifted), frame_id=3, ts_ms=1200.0)
    accepted = tracker.update(frame, _observation(shifted), frame_id=4, ts_ms=1300.0)
    assert np.array_equal(pending1.outline_px, first.outline_px)
    assert np.array_equal(pending2.outline_px, first.outline_px)
    assert np.allclose(accepted.outline_px, shifted)


def test_clear_relocated_sensor_reacquires_after_consensus() -> None:
    tracker = ComponentPoseTracker(
        PROFILE,
        visibility_warmup_frames=1,
        reacquire_confirm_frames=3,
        reacquire_min_visible_fraction=0.45,
    )
    original = np.array([[80, 40], [160, 40], [160, 220], [80, 220]], dtype=np.float64)
    original_frame = np.zeros((300, 360, 3), dtype=np.uint8)
    cv2.fillConvexPoly(original_frame, original.astype(np.int32), (255, 0, 0))
    first = tracker.update(
        original_frame, _observation(original), frame_id=1, ts_ms=1000.0
    )
    assert first.tracking == "locked"

    relocated = original + np.array([120.0, 10.0])
    relocated_frame = np.zeros_like(original_frame)
    cv2.fillConvexPoly(relocated_frame, relocated.astype(np.int32), (255, 0, 0))
    pending1 = tracker.update(
        relocated_frame, _observation(relocated), frame_id=2, ts_ms=1100.0
    )
    pending2 = tracker.update(
        relocated_frame, _observation(relocated), frame_id=3, ts_ms=1200.0
    )
    accepted = tracker.update(
        relocated_frame, _observation(relocated), frame_id=4, ts_ms=1300.0
    )
    assert pending1.stability == "reacquire_hold"
    assert pending2.stability == "reacquire_hold"
    assert accepted.tracking == "locked"
    assert accepted.stability == "reacquired"
    assert np.allclose(accepted.outline_px, relocated)
