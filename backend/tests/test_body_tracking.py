from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from app.vision.body_tracking import BodyFallback, BodyTrack, body_observation
from app.vision.interface import DetectionResult
from app.body_worker import BodyVisionWorker
from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPoseState
from app.vision_worker import DetectionState
from app.motion_worker import MotionOverlayWorker, MotionFrameState
from app.vision_worker import detection_message
from app.motion_worker import absent


def observation(box=(60, 50, 230, 180), confidence=.9):
    return SimpleNamespace(box_xyxy=box, confidence=confidence)


def message(frame=1, ts=1000):
    return dict(frame_id=frame, ts_ms=ts, tracking='searching', pins=[], outline=None,
                body=body_observation(observation(), (320, 240)))


def texture():
    return np.random.default_rng(13).integers(0, 256, (240, 320), dtype=np.uint8)


def test_body_box_is_independent_of_corners_and_pins():
    result = body_observation(observation(), (320, 240))
    assert result['box'] == [60, 50, 230, 180]
    assert 'pins' not in result and 'corners' not in result


@pytest.mark.parametrize('box', [(0, 0, 999, 999), (20, 20, 10, 10),
                                 (500, 400, 600, 500), (0, 0, np.nan, 50)])
def test_invalid_body_boxes_are_not_published(box):
    assert body_observation(observation(box), (320, 240)) is None


def test_fallback_is_throttled_and_skipped_frames_do_not_inherit_boxes():
    locator = Mock()
    locator.locate.return_value = observation()
    fallback = BodyFallback(locator)
    image = np.zeros((240, 320, 3), np.uint8)
    assert fallback.detect(image, 1000)
    assert fallback.detect(image, 1200) is None
    assert fallback.detect(image, 1350)
    locator.locate.return_value = None
    assert fallback.detect(image, 1700) is None
    assert locator.locate.call_count == 3
    # Camera timestamp restart must not permanently silence the fallback.
    fallback.detect(image, 100)
    assert locator.locate.call_count == 4


def test_body_tracks_actual_image_translation_without_any_pin_seed():
    gray = texture()
    source = message()
    track = BodyTrack()
    track.observe(source, gray, 1.)
    shifted = cv2.warpAffine(gray, np.float32([[1, 0, 8], [0, 1, 5]]), (320, 240))
    current = track.update(shifted, 2, 1040)
    assert current is not None
    np.testing.assert_allclose(current['outline'], [[68, 55], [238, 55], [238, 185], [68, 185]], atol=1)
    assert current['frame_id'] == 2 and current['source_frame_id'] == 1
    assert source['tracking'] == 'searching' and source['pins'] == []
    assert source['outline'] is None
    assert track.update(shifted, 3, 1651) is None


def test_blank_image_removal_and_future_source_never_show_a_held_box():
    track = BodyTrack()
    track.observe(message(), texture(), 1.)
    assert track.update(np.zeros((240, 320), np.uint8), 2, 1040) is None
    assert track.update(texture(), 3, 1080) is None
    track.observe(message(4, 2000), texture(), 1.)
    assert track.update(texture(), 3, 1900) is None


def test_duplicate_source_does_not_refresh_expiration():
    track = BodyTrack()
    track.observe(message(), texture(), 1.)
    track.observe(message(1, 1600), texture(), 1.)
    assert track.update(texture(), 2, 1651) is None


def test_body_worker_pairs_actual_image_and_never_upgrades_pin_result():
    runtime = Mock()
    runtime.snapshot.return_value = SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=8)
    locator = Mock()
    locator.locate.return_value = observation()
    worker = BodyVisionWorker(None, runtime, None, locator)
    slot = SimpleNamespace(frame=np.zeros((240, 320, 3), np.uint8), frame_id=10, ts_ms=1000)
    worker.process(slot)
    source, payload = worker.get_synchronized()
    assert source is slot and payload['frame_id'] == 10 and payload['runtime_revision'] == 8
    assert payload['body'] and 'pins' not in payload
    result = DetectionResult('raspberry-pi-5', 1, 1000, 'searching', 0)
    assert result.tracking == 'searching' and result.pins == [] and result.outline_px is None
    result.body = payload['body']
    wire = detection_message(result, (320, 240))
    assert wire['body'] == result.body
    assert absent(wire, 2, 1100).get('body') is None
    runtime.snapshot.return_value = SimpleNamespace(board_id='arduino-uno-q', runtime_revision=9)
    worker.process(slot)
    assert worker.get_synchronized()[1]['body'] is None
    assert locator.locate.call_count == 1
    worker.stop()
    assert worker.get_synchronized() is None
    locator.close.assert_called_once()


def test_independent_body_source_survives_missing_pin_worker_and_rejects_runtime_switch():
    runtime = SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1)
    manager = SimpleNamespace(snapshot=lambda: runtime)
    image = cv2.cvtColor(texture(), cv2.COLOR_GRAY2BGR)
    source = FrameSlot(image, 1, 1000, 1)
    body = message()
    body.update(board_id=runtime.board_id, runtime_revision=1)
    state = Mock()
    state.get_synchronized.return_value = (source, body)
    worker = MotionOverlayWorker(FrameBus(), DetectionState(), ComponentPoseState(),
                                 manager, MotionFrameState(), body_state=state)
    packet = worker.process(FrameSlot(image, 2, 1040, 2))
    assert packet['detection']['body']['source_frame_id'] == 1
    assert packet['detection']['body']['frame_id'] == 2
    assert packet['detection']['tracking'] == 'searching'
    assert packet['detection']['outline'] is None and packet['detection']['pins'] == []
    assert packet['detection']['pose_quality']['model_source'] == {'paired': False}
    # No new body identity -> expire instead of copying into a newer image.
    assert worker.process(FrameSlot(image, 3, 1651, 3))['detection']['body'] is None
    runtime.runtime_revision = 2
    assert worker.process(FrameSlot(image, 4, 1700, 4))['detection']['body'] is None


def test_body_worker_does_not_double_throttle_camera_quantized_timestamps():
    runtime = Mock()
    runtime.snapshot.return_value = SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1)
    locator = Mock()
    locator.locate.return_value = observation()
    worker = BodyVisionWorker(None, runtime, None, locator)
    # Worker wake-ups are 350ms apart; selected camera frames can be 333ms apart.
    for i, ts in enumerate([1000, 1333, 1700]):
        worker.process(FrameSlot(np.zeros((240, 320, 3), np.uint8), i, ts, i))
        assert worker.get_synchronized()[1]['body'] is not None
    assert locator.locate.call_count == 3
