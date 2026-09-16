"""Eye spends one model call per frame without changing normal-camera search."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPoseState, ComponentPoseWorker, project_component_pins
from app.vision.yolo_pose import BoardPoseObservation


ROOT = Path(__file__).resolve().parents[2]


def observation():
    corners = np.array([[10., 10.], [50., 10.], [50., 35.], [10., 35.]])
    return BoardPoseObservation(corners, .8, np.full(5, .9), (8., 8., 52., 38.),
                                landmarks_px=np.vstack((corners, [30., 25.])))


class Locator:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def locate(self, frame):
        self.calls.append((frame.shape[:2], tuple(frame[0, 0].tolist())))
        result = next(self.outputs)
        if isinstance(result, Exception):
            raise result
        return result


def make_worker(component, outputs):
    def forbidden(*args, **kwargs):
        raise AssertionError("Eye inference must not publish or use other pose judges")

    locator = Locator(outputs)
    worker = ComponentPoseWorker(bus=FrameBus(), state=ComponentPoseState(),
        model_path='unused', profile_path=ROOT / f'profiles/components/{component}/vision_profile.json',
        publish=forbidden, locator=locator)
    worker._tracker.update = forbidden
    if worker._reference_recovery is not None:
        worker._reference_recovery.locate = forbidden
    worker.set_yolo_only(True)
    return worker, locator


def slot(frame_id, *, width=200, height=100):
    y, x = np.indices((height, width))
    frame = np.stack((x % 256, y % 256, np.full_like(x, frame_id)), axis=2).astype(np.uint8)
    return FrameSlot(frame, frame_id, 1000. + frame_id * 33.3, frame_id)


@pytest.mark.parametrize('component', ['hc-sr04', 'hw-123', 'mrd-tf240-8p-cs'])
def test_clipped_component_corners_do_not_project_a_complete_pin_row(component):
    worker, _ = make_worker(component, [])
    cut = replace(observation(), corners_px=np.array([[0., 10.], [50., 10.], [50., 35.], [0., 35.]]))
    result = worker._direct_yolo_result(slot(1), cut)
    assert result.pins == () and result.outline_px is None and result.body['partial']
    assert result.tracking_reason == 'yolo_clipped'
    recovered = worker._direct_yolo_result(slot(2), observation())
    assert recovered.frame_id == 2 and recovered.pins


@pytest.mark.parametrize('component,regions', [
    ('hc-sr04', [((100, 200), (0, 0)), ((50, 100), (0, 0)),
                ((50, 100), (100, 0)), ((50, 100), (0, 50)),
                ((50, 100), (100, 50)), ((100, 200), (0, 0))]),
    ('mrd-tf240-8p-cs', [((100, 200), (0, 0)), ((100, 100), (50, 0)),
                         ((100, 100), (0, 0)), ((100, 100), (100, 0)),
                         ((100, 200), (0, 0))]),
    ('hw-123', [((100, 200), (0, 0))] * 6),
])
def test_missing_components_get_one_forward_per_frame_and_cycle_existing_regions(component, regions):
    worker, locator = make_worker(component, [None] * len(regions))
    for frame_id, (shape, origin) in enumerate(regions, 1):
        result = worker.detect_yolo_frame(slot(frame_id))
        assert len(locator.calls) == frame_id
        assert locator.calls[-1] == (shape, (*origin, frame_id))
        assert result.frame_id == frame_id and result.tracking == 'searching'
        assert result.pins == () and result.outline_px is None and result.body is None
    assert worker._state.get() is None


def test_winning_tile_uses_current_pixels_and_maps_all_geometry_without_reusing_a_miss():
    candidate = observation()
    worker, locator = make_worker('hc-sr04', [None, None, candidate, candidate, None, candidate])
    for frame_id in (1, 2):
        assert worker.detect_yolo_frame(slot(frame_id)).pins == ()
    for frame_id in (3, 4):
        current = slot(frame_id)
        result = worker.detect_yolo_frame(current)
        expected = worker._direct_yolo_result(current, replace(candidate,
            corners_px=candidate.corners_px + [100, 0],
            landmarks_px=candidate.landmarks_px + [100, 0],
            box_xyxy=(108., 8., 152., 38.), source='yolo_tile'))
        assert len(locator.calls) == frame_id
        assert locator.calls[-1] == ((50, 100), (100, 0, frame_id))
        assert result.frame_id == frame_id and result.video_size == (200, 100)
        np.testing.assert_allclose(result.outline_px, expected.outline_px)
        assert result.pins == expected.pins and result.body == expected.body
        assert result.confidence == .8 and result.tracking == 'locked'
    missing = worker.detect_yolo_frame(slot(5))
    assert missing.frame_id == 5 and missing.pins == ()
    assert missing.body is None and missing.outline_px is None
    following = worker.detect_yolo_frame(slot(6))
    assert len(locator.calls) == 6
    assert locator.calls[-1] == ((50, 100), (0, 50, 6))
    np.testing.assert_allclose(following.outline_px, candidate.corners_px + [0, 50])


def test_tft_small_quad_keeps_current_direct_output_but_searches_next_region_next_frame():
    small = replace(observation(), corners_px=observation().corners_px * .2 + 4,
                    landmarks_px=None, box_xyxy=(4., 4., 90., 90.))
    worker, locator = make_worker('mrd-tf240-8p-cs', [small, None, small])
    first = worker.detect_yolo_frame(slot(1))
    assert len(locator.calls) == 1
    assert first.tracking == 'locked' and len(first.pins) == 8
    assert first.confidence == small.confidence
    missing = worker.detect_yolo_frame(slot(2))
    assert len(locator.calls) == 2 and locator.calls[-1][0] == (100, 100)
    assert missing.pins == () and missing.body is None
    third = worker.detect_yolo_frame(slot(3))
    assert len(locator.calls) == 3 and locator.calls[-1][1] == (0, 0, 3)
    assert third.tracking == 'locked' and len(third.pins) == 8


def test_tft_clipped_strip_rejection_does_not_trigger_another_forward():
    clipped = replace(observation(), box_xyxy=(-1., 8., 52., 38.))
    worker, locator = make_worker('mrd-tf240-8p-cs', [None, clipped, observation()])
    worker.detect_yolo_frame(slot(1))
    second = worker.detect_yolo_frame(slot(2))
    assert len(locator.calls) == 2
    assert second.pins == () and second.body is None
    third = worker.detect_yolo_frame(slot(3))
    assert len(locator.calls) == 3 and third.tracking == 'locked'
    assert locator.calls[-1][1] == (0, 0, 3)


@pytest.mark.parametrize('reset', ['camera', 'shape', 'exit'])
def test_eye_cursor_resets_without_touching_or_reloading_model(reset):
    worker, locator = make_worker('hc-sr04', [None, None, observation()])
    worker.detect_yolo_frame(slot(1))
    worker.detect_yolo_frame(slot(2))
    if reset == 'camera':
        worker.reset_tracking()
    elif reset == 'exit':
        worker.set_yolo_only(False)
        worker.set_yolo_only(True)
    current = slot(3, width=400, height=200) if reset == 'shape' else slot(3)
    result = worker.detect_yolo_frame(current)
    assert worker._locator is locator and len(locator.calls) == 3
    assert locator.calls[-1] == (current.frame.shape[:2], (0, 0, 3))
    np.testing.assert_allclose(result.outline_px, observation().corners_px)


def test_model_exception_uses_one_forward_and_schedules_next_frame_without_output():
    worker, locator = make_worker('hc-sr04', [RuntimeError('test model failure'), None])
    with pytest.raises(RuntimeError, match='test model failure'):
        worker.detect_yolo_frame(slot(1))
    result = worker.detect_yolo_frame(slot(2))
    assert len(locator.calls) == 2 and locator.calls[-1] == ((50, 100), (0, 0, 2))
    assert result.pins == () and result.body is None


def test_normal_locate_keeps_full_then_tile_behavior_and_independent_cursor():
    candidate = observation()
    worker, locator = make_worker('hc-sr04', [None, None, candidate, None])
    worker.detect_yolo_frame(slot(1))  # schedule Eye's first tile
    current = slot(2)
    recovered = worker._locate(current.frame)
    assert len(locator.calls) == 3
    assert locator.calls[1:] == [((100, 200), (0, 0, 2)), ((50, 100), (0, 0, 2))]
    np.testing.assert_array_equal(recovered.corners_px, candidate.corners_px)
    worker.set_yolo_only(False)
    assert worker._locate(slot(3).frame) is None
    assert len(locator.calls) == 4 and locator.calls[-1] == ((100, 200), (0, 0, 3))


def test_odd_native_shape_tile_keeps_pixels_and_pin_coordinates_at_source_scale():
    candidate = observation()
    worker, locator = make_worker('hc-sr04', [None, None, None, None, candidate])
    for frame_id in range(1, 6):
        current = slot(frame_id, width=1921, height=1081)
        result = worker.detect_yolo_frame(current)
    assert len(locator.calls) == 5 and locator.calls[-1][0] == (541, 961)
    translated = candidate.corners_px + [960, 540]
    np.testing.assert_allclose(result.outline_px, translated)
    expected = project_component_pins(worker._profile, translated, .8, (1921, 1081),
        landmarks_px=candidate.landmarks_px + [960, 540], keypoint_confidences=candidate.keypoint_confidences)
    assert result.video_size == (1921, 1081) and result.pins == expected


def test_eye_mode_propagates_to_optional_locator_and_restores_normal_decode_on_exit():
    worker, locator = make_worker('hc-sr04', [])
    configured = []
    locator.set_yolo_only = configured.append
    worker.set_yolo_only(True)
    worker.set_yolo_only(False)
    assert configured == [True, False]
