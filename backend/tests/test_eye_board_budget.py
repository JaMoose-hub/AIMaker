"""Eye board search budgets one inference without reusing pose observations."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from app.profiles.store import ProfileStore
from app.vision.eye_board_search import EyeBoardYoloSearch
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import BoardPoseObservation
from app.vision.yolo_profile_detector import YoloProfileDetector


ROOT = Path(__file__).resolve().parents[2]


def observation(offset=0):
    corners = np.array([[10., 10.], [80., 10.], [80., 60.], [10., 60.]]) + offset
    return BoardPoseObservation(corners, .85, np.full(4, .9),
                                tuple(np.r_[corners.min(0), corners.max(0)]))


class Locator:
    available = True

    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.frames = []
        self.closed = False

    def locate(self, frame):
        self.frames.append(frame)
        return next(self.outputs)

    def close(self):
        self.closed = True


def test_each_miss_searches_one_strategy_and_each_success_is_fresh():
    scheduler = EyeBoardYoloSearch()
    primary = Locator([None, None])
    first, second = observation(), observation(2)
    reference = Locator([None, first, second, None])
    frames = [np.full((100, 200, 3), index, np.uint8) for index in range(6)]
    results = []
    for index, frame in enumerate(frames):
        before = len(primary.frames) + len(reference.frames)
        results.append(scheduler.locate(frame, primary, reference))
        assert len(primary.frames) + len(reference.frames) == before + 1
    assert results[:2] == [None, None]
    np.testing.assert_array_equal(results[2].corners_px, first.corners_px + [50, 0])
    np.testing.assert_array_equal(results[3].corners_px, second.corners_px + [50, 0])
    assert results[4:] == [None, None]
    assert [frame.shape[:2] for frame in reference.frames] == [(100, 200)] + [(100, 100)] * 3
    assert [int(frame[0, 0, 0]) for frame in reference.frames] == [1, 2, 3, 4]


def test_reference_full_winner_is_body_only_and_retries_primary():
    scheduler = EyeBoardYoloSearch()
    primary = Locator([None, observation(10)])
    first, second = observation(), observation(3)
    reference = Locator([first, second, second])
    frame = np.zeros((100, 200, 3), np.uint8)
    assert scheduler.locate(frame, primary, reference) is None
    for expected in (first, second, second):
        actual = scheduler.locate(frame, primary, reference)
        np.testing.assert_array_equal(actual.corners_px, expected.corners_px)
        assert actual.source == 'yolo_reference_body_only'
    assert scheduler.locate(frame, primary, reference).source == 'yolo'
    assert len(primary.frames) == 2 and len(reference.frames) == 3


@pytest.mark.parametrize('reset_kind', ['explicit', 'shape'])
def test_search_resets_to_primary_without_replacing_locators(reset_kind):
    scheduler = EyeBoardYoloSearch()
    expected = observation()
    primary, reference = Locator([None, expected]), Locator([])
    frame = np.zeros((100, 200, 3), np.uint8)
    assert scheduler.locate(frame, primary, reference) is None
    if reset_kind == 'explicit':
        scheduler.reset()
    else:
        frame = np.zeros((200, 400, 3), np.uint8)
    assert scheduler.locate(frame, primary, reference) is expected
    assert not primary.closed and not reference.closed


def test_without_tiles_full_strategies_still_have_one_forward_budget():
    scheduler = EyeBoardYoloSearch()
    primary, reference = Locator([None, None]), Locator([None])
    frame = np.zeros((100, 200, 3), np.uint8)
    for _ in range(3):
        assert scheduler.locate(frame, primary, reference, allow_tiles=False) is None
    assert len(primary.frames) == 2 and len(reference.frames) == 1
    assert all(item.shape == frame.shape for item in primary.frames + reference.frames)


def test_unavailable_primary_can_use_reference_without_wasting_a_frame():
    scheduler = EyeBoardYoloSearch()
    primary, reference = Locator([]), Locator([observation()])
    primary.available = False
    assert scheduler.locate(np.zeros((100, 200, 3), np.uint8), primary, reference) is not None
    assert len(primary.frames) == 0 and len(reference.frames) == 1


def detector_fixture(primary, reference):
    detector = YoloProfileDetector(locator=primary)
    profile = ProfileStore(ROOT / 'profiles').profile('raspberry-pi-5')
    detector.load(profile, ROOT / 'profiles/boards/raspberry-pi-5')
    detector._reference_recovery = ReferencePoseRecovery(None, reference)
    detector.set_yolo_only(True)
    return detector


@pytest.mark.parametrize('reset_kind', ['camera', 'disable', 'shape'])
def test_detector_reset_restarts_search_and_preserves_loaded_sessions(reset_kind):
    primary, reference = Locator([None, observation()]), Locator([])
    detector = detector_fixture(primary, reference)
    frame = np.zeros((100, 200, 3), np.uint8)
    first = detector.detect(frame, 1, 100.)
    assert first.pins == [] and first.body is None
    if reset_kind == 'camera':
        detector.reset_for_camera(use_camera_calibration=False)
    elif reset_kind == 'disable':
        detector.set_yolo_only(False)
        detector.set_yolo_only(True)
    else:
        frame = np.zeros((200, 400, 3), np.uint8)
    result = detector.detect(frame, 2, 200.)
    assert result.frame_id == 2 and len(result.pins) == 40
    assert detector._locator is primary
    assert detector._reference_recovery.roi_locator is reference
    assert not primary.closed and not reference.closed


def test_invalid_current_quad_keeps_only_current_body_then_searches_next_model():
    invalid = replace(observation(), corners_px=np.zeros((4, 2)))
    primary, reference = Locator([invalid]), Locator([observation()])
    detector = detector_fixture(primary, reference)
    frame = np.zeros((100, 200, 3), np.uint8)
    first = detector.detect(frame, 10, 1000.)
    assert first.pins == [] and first.body is not None
    result = detector.detect(frame, 11, 1100.)
    assert result.frame_id == 11 and result.pins == []
    assert result.body is not None and result.outline_px is None
    assert result.pose_path == 'yolo_body_only'
    assert len(primary.frames) == len(reference.frames) == 1


def test_webcam_path_does_not_use_eye_scheduler(monkeypatch):
    detector = detector_fixture(Locator([]), Locator([]))
    detector.set_yolo_only(False)
    expected = detector._searching(7, 700.)
    monkeypatch.setattr(detector, '_detect', lambda *args: expected)

    def forbidden(*args, **kwargs):
        raise AssertionError('webcam must not enter Eye search scheduling')

    monkeypatch.setattr(detector._eye_yolo_search, 'locate', forbidden)
    actual = detector.detect(np.zeros((100, 200, 3), np.uint8), 7, 700.)
    assert actual.frame_id == expected.frame_id and actual.pins == []


def test_clipped_pi_corner_keeps_body_without_warping_gpio_and_recovers_fresh():
    cut = replace(observation(), corners_px=np.array([[10., 10.], [199., 20.], [180., 80.], [10., 70.]]))
    primary, reference = Locator([cut, observation()]), Locator([])
    detector = detector_fixture(primary, reference)
    frame = np.zeros((100, 200, 3), np.uint8)
    result = detector.detect(frame, 1, 100.)
    assert result.pins == [] and result.outline_px is None and result.body['partial']
    assert result.pose_path == 'yolo_clipped'
    recovered = detector.detect(frame, 2, 133.)
    assert recovered.frame_id == 2 and len(recovered.pins) == 40
    assert len(primary.frames) == 2 and not reference.frames


def test_cut_body_stays_without_gpio_when_keypoints_jitter_inward():
    cut = replace(observation(), box_xyxy=(10., 10., 210., 80.))
    primary, reference = Locator([cut, cut, observation()]), Locator([])
    detector = detector_fixture(primary, reference)
    frame = np.zeros((100, 200, 3), np.uint8)
    for frame_id in (1, 2):
        result = detector.detect(frame, frame_id, 100. + frame_id * 33.)
        assert result.pins == [] and result.pose_path == 'yolo_clipped'
    assert len(detector.detect(frame, 3, 199.).pins) == 40


def test_eye_j8_correction_uses_current_frame_without_changing_yolo_identity(monkeypatch):
    import app.vision.yolo_profile_detector as module

    candidate = observation()
    primary, reference = Locator([candidate, candidate, None]), Locator([])
    detector = detector_fixture(primary, reference)
    frames = [np.full((100, 200, 3), value, np.uint8) for value in (1, 2, 3)]
    seen = []

    def correct(frame, profile, pins, size):
        seen.append((frame, profile, size))
        # New image evidence exists only on frame1. A fallback must retain
        # frame2's raw projection, never the previously corrected pins.
        return [replace(pin, y=pin.y + 4.) for pin in pins] if frame[0, 0, 0] == 1 else pins

    def forbidden(*args, **kwargs):
        raise AssertionError('Eye image correction must not need camera/PnP/SIFT setup')

    monkeypatch.setattr('app.vision.eye_j8.correct_eye_j8_from_image', correct)
    monkeypatch.setattr(detector, '_ensure_camera', forbidden)
    monkeypatch.setattr(module, 'refine_board_corners_from_pcb', forbidden)
    baseline, _ = module._project_profile_on_observed_quad(
        detector._profile, candidate.corners_px, (200, 100), candidate.confidence)
    first = detector.detect(frames[0], 20, 2000.)
    second = detector.detect(frames[1], 21, 2033.)
    missing = detector.detect(frames[2], 22, 2066.)
    assert [item[0] is frame for item, frame in zip(seen, frames)] == [True, True]
    assert all(item[1] is detector._profile and item[2] == (200, 100) for item in seen)
    assert (first.frame_id, first.ts_ms, first.confidence) == (20, 2000., candidate.confidence)
    assert (second.frame_id, second.ts_ms) == (21, 2033.)
    assert first.body == second.body
    assert first.pose_path == 'yolo_j8_image' and second.pose_path == 'yolo'
    assert first.pose_stability_state == second.pose_stability_state == 'yolo_direct'
    np.testing.assert_array_equal(first.outline_px, candidate.corners_px)
    np.testing.assert_array_equal(first.motion_outline_px, candidate.corners_px)
    assert [pin.pin_id for pin in first.pins] == [pin.pin_id for pin in baseline]
    np.testing.assert_allclose([pin.y for pin in first.pins], [pin.y + 4. for pin in baseline])
    assert second.pins == baseline
    assert missing.frame_id == 22 and missing.pins == [] and missing.body is None
    assert len(primary.frames) == 3 and not reference.frames


@pytest.mark.parametrize('kind', ['clipped', 'invalid', 'body_only', 'missing'])
def test_eye_j8_image_correction_cannot_authorize_an_invalid_pose(kind, monkeypatch):
    import app.vision.yolo_profile_detector as module

    candidate = observation()
    if kind == 'clipped':
        candidate = replace(candidate, box_xyxy=(-5., 10., 80., 60.))
    elif kind == 'invalid':
        candidate = replace(candidate, corners_px=np.zeros((4, 2)))
    elif kind == 'body_only':
        candidate = replace(candidate, source='yolo_reference_body_only')
    else:
        candidate = None
    detector = detector_fixture(Locator([]), Locator([]))
    monkeypatch.setattr(detector._eye_yolo_search, 'locate', lambda *args, **kwargs: candidate)

    def forbidden(*args, **kwargs):
        raise AssertionError('Image correction must not invent pins from missing/invalid YOLO geometry')

    monkeypatch.setattr('app.vision.eye_j8.correct_eye_j8_from_image', forbidden)
    result = detector.detect(np.zeros((100, 200, 3), np.uint8), 5, 500.)
    assert result.frame_id == 5 and result.pins == [] and result.outline_px is None


def test_existing_j8_helper_falls_back_without_image_support():
    import app.vision.yolo_profile_detector as module

    detector = detector_fixture(Locator([]), Locator([]))
    # Native scale is large enough to exercise the image search, unlike the
    # tiny budget fixtures. White pixels contain no dark J8 body evidence.
    corners = np.array([[100., 100.], [950., 100.], [950., 660.], [100., 660.]])
    pins, _ = module._project_profile_on_observed_quad(detector._profile, corners, (1080, 800), .85)
    frame = np.full((800, 1080, 3), 255, np.uint8)
    corrected = module._correct_pi5_j8_from_image(frame, detector._profile, pins, (1080, 800))
    assert corrected is pins
