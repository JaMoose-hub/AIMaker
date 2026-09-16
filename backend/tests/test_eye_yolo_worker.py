"""Eye inference uses one source image, fresh YOLO results, and standard NMS."""
from base64 import b64decode
from dataclasses import replace
from types import SimpleNamespace
import threading
import time

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPinPosition, ComponentPoseResult, ComponentPoseState
from app.eye_yolo_worker import EyeYoloWorker
from app.motion_worker import MotionFrameState
from app.vision.interface import DetectionResult, PinDetection
from app.vision_worker import DetectionState


class Runtime:
    revision = 3

    def snapshot(self):
        return SimpleNamespace(board_id="raspberry-pi-5", runtime_revision=self.revision)


class Detector:
    def __init__(self):
        self.frames = []
        self.close_calls = 0

    def detect(self, image, frame_id, ts_ms):
        self.frames.append((image, frame_id, ts_ms))
        return DetectionResult("raspberry-pi-5", frame_id, ts_ms, "locked", .9,
            pins=[PinDetection("J8:1", 12., 12., .9)],
            outline_px=[(8., 8.), (40., 8.), (40., 40.), (8., 40.)],
            body={"box": [8., 8., 40., 40.], "confidence": .9, "source": "pose_model"})

    def close(self):
        self.close_calls += 1


class Component:
    def __init__(self, cid, box, confidence):
        self._profile = SimpleNamespace(component_id=cid)
        self.box, self.confidence = box, confidence
        self.slots = []
        self.missing = False
        self.fail = False

    def detect_yolo_frame(self, slot):
        self.slots.append(slot)
        if self.fail:
            raise RuntimeError("model execution failed")
        x1, y1, x2, y2 = self.box
        return ComponentPoseResult(self._profile.component_id, slot.frame_id, slot.ts_ms,
            "searching" if self.missing else "locked", 0. if self.missing else self.confidence,
            (slot.frame.shape[1], slot.frame.shape[0]),
            None if self.missing else np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]]),
            () if self.missing else (ComponentPinPosition("VCC", x1 + 1, y1 + 1, self.confidence),),
            "yolo_direct", body=None if self.missing else
                {"box": list(self.box), "confidence": self.confidence, "source": "pose_model"})

    def _run(self):
        raise AssertionError("The normal component pipeline must not run")

    def stop(self, **kwargs):
        raise AssertionError("The Eye group must not close shared models")


def setup_worker(components=None, detector=None):
    components = components if components is not None else [
        Component("hc-sr04", [70, 12, 100, 40], .49),
        Component("hw-123", [120, 12, 145, 40], .17),
        Component("mrd-tf240-8p-cs", [160, 12, 205, 55], .65)]
    detector = detector or Detector()
    worker = EyeYoloWorker(FrameBus(), DetectionState(), ComponentPoseState(),
        Runtime(), MotionFrameState(), detector, components)
    frame = np.full((90, 240, 3), (40, 80, 160), np.uint8)
    slot = FrameSlot(frame, 17, time.monotonic() * 1000, 21)
    return worker, slot, detector, components


def test_one_frame_drives_all_yolo_results_and_the_display_packet(monkeypatch):
    worker, slot, detector, components = setup_worker()
    encode = cv2.imencode
    qualities = []

    def recording_encode(extension, frame, params):
        qualities.append(params)
        return encode(extension, frame, params)

    monkeypatch.setattr("app.eye_yolo_worker.cv2.imencode", recording_encode)
    packet = worker.process(slot)
    assert packet["mode"] == "yolo_only"
    assert packet["runtime_revision"] == 3
    assert packet["seq"] == slot.seq
    assert detector.frames[0][0] is slot.frame
    assert all(component.slots == [slot] for component in components)
    for message in [packet["detection"], *packet["components"]]:
        assert (message["frame_id"], message["ts_ms"]) == (slot.frame_id, slot.ts_ms)
        assert message["body"]["frame_id"] == slot.frame_id
        assert message["body"]["source_frame_id"] == slot.frame_id
        assert message["body"]["age_ms"] == 0
        assert message["pins"]
        assert message["pose_quality"]["stability"] == "yolo_direct"
    source, result = worker.detection_state.get_synchronized()
    assert source is slot and result.frame_id == slot.frame_id
    assert worker.component_state.get_synchronized("hw-123")[0] is slot
    assert worker.state.get_capture() == (packet, slot)
    decoded = cv2.imdecode(np.frombuffer(b64decode(packet["image"].split(",", 1)[1]), np.uint8), 1)
    assert decoded.shape == slot.frame.shape
    assert qualities == [[cv2.IMWRITE_JPEG_QUALITY, 95]]
    assert worker.process(slot) is None
    assert len(detector.frames) == 1


def test_cross_class_nms_removes_lower_confidence_identity_and_pins():
    components = [Component("hc-sr04", [70, 12, 100, 40], .49),
                  Component("hw-123", [71, 12, 101, 40], .17)]
    worker, slot, _, _ = setup_worker(components)
    packet = worker.process(slot)
    hc, hw = packet["components"]
    assert hc["tracking"] == "locked" and hc["pins"]
    assert hw["tracking"] == "searching"
    assert hw["body"] is None and hw["outline"] is None and hw["pins"] == []
    assert hw["pose_quality"]["stability"] == "yolo_direct"
    assert hw["pose_quality"]["reason"] == "yolo_nms"
    stored = worker.component_state.get("hw-123")
    assert stored.body is None and stored.pins == ()


def test_nms_has_no_extra_confidence_floor_for_nonoverlapping_detection():
    worker, slot, _, _ = setup_worker()
    hw = next(item for item in worker.process(slot)["components"] if item["component_id"] == "hw-123")
    assert hw["body"]["confidence"] == .17
    assert hw["pins"] and hw["tracking"] == "locked"


def test_current_missing_result_never_reuses_previous_component_geometry():
    worker, slot, _, components = setup_worker()
    worker.process(slot)
    components[1].missing = True
    second = replace(slot, frame_id=18, seq=22, ts_ms=slot.ts_ms + 33)
    message = worker.process(second)["components"][1]
    assert message["frame_id"] == 18
    assert message["body"] is None and message["pins"] == []
    assert message["pose_quality"]["stability"] == "yolo_direct"
    assert worker.component_state.get_synchronized("hw-123")[0] is second
    assert 'hw-123' not in worker._display_stabilizer._samples
    assert worker._display_stabilizer.diagnostics()['hw-123']['reason'] == 'missing'


def test_one_model_error_still_publishes_other_current_models():
    worker, slot, _, components = setup_worker()
    components[1].fail = True
    packet = worker.process(slot)
    assert packet["components"][0]["pins"]
    assert packet["components"][1]["pins"] == []
    assert packet["components"][1]["pose_quality"]["stability"] == "yolo_direct"
    assert packet["components"][1]["pose_quality"]["reason"] == "yolo_error"
    assert packet["components"][2]["pins"]
    assert packet["model_errors"] == {"hw-123": "model execution failed"}


def test_camera_revision_change_discards_whole_inflight_packet():
    worker, slot, detector, _ = setup_worker()
    detect = detector.detect

    def switch_during_inference(*args):
        result = detect(*args)
        worker.runtime_manager.revision += 1
        return result

    detector.detect = switch_during_inference
    assert worker.process(slot) is None
    assert worker.detection_state.get() is None
    assert worker.component_state.all() == ()
    assert worker.state.get_capture() is None
    assert worker._display_stabilizer.diagnostics() == {}


def test_stop_waits_for_inflight_model_and_never_closes_sessions():
    worker, slot, detector, components = setup_worker()
    entered, release = threading.Event(), threading.Event()
    detect = detector.detect

    def blocking_detect(*args):
        entered.set()
        release.wait(2)
        return detect(*args)

    detector.detect = blocking_detect
    worker.bus.put(slot.frame, slot.frame_id, slot.ts_ms)
    worker.start()
    try:
        assert entered.wait(1)
        with pytest.raises(RuntimeError, match="did not stop"):
            worker.stop(timeout=.01)
    finally:
        release.set()
        worker.stop(timeout=2)
    assert detector.close_calls == 0
    assert all(len(component.slots) == 1 for component in components)
    assert worker._executor is None
    assert worker.state.get_capture() is None


def test_reset_allows_new_camera_frame_counter_without_retaining_old_result():
    worker, slot, detector, _ = setup_worker()
    worker.process(slot)
    worker.reset_tracking()
    assert worker._display_stabilizer.diagnostics() == {}
    assert worker.detection_state.get() is None
    assert worker.component_state.all() == ()
    assert worker.state.get_capture() is None
    assert worker.process(replace(slot, frame_id=1, seq=1))["frame_id"] == 1
    assert detector.close_calls == 0


def test_live_diagnostics_include_roi_and_immediately_show_a_cuda_fallback():
    worker, _, detector, components = setup_worker()
    class Locator:
        failed = False
        def diagnostics(self):
            return dict(actual_backend='opencv' if self.failed else 'cuda',
                        available=True, preprocessing_backend='opencv' if self.failed else 'cuda',
                        fallback_reason='GPU execution failed' if self.failed else None)
    detector._locator = Locator()
    detector._reference_recovery = SimpleNamespace(roi_locator=Locator())
    for component in components:
        component._locator = Locator()
    before = worker.snapshot()['models']
    assert len(before) == 5
    assert any(model['id'] == 'raspberry-pi-5-roi' for model in before)
    assert all(model['actual_backend'] == 'cuda' for model in before)
    components[1]._locator.failed = True
    after = worker.snapshot()['models']
    failed = next(model for model in after if model['id'] == components[1]._profile.component_id)
    assert failed['actual_backend'] == 'opencv'
    assert failed['fallback_reason'] == 'GPU execution failed'
    assert sum(model['actual_backend'] == 'cuda' for model in after) == 4


def test_independent_models_run_together_on_one_frame_and_join_before_publish():
    worker, slot, detector, components = setup_worker()
    barrier = threading.Barrier(1+len(components), timeout=2)
    detect = detector.detect
    def board(*args):
        barrier.wait()
        return detect(*args)
    detector.detect = board
    for component in components:
        original = component.detect_yolo_frame
        def component_detect(current, original=original):
            barrier.wait()
            return original(current)
        component.detect_yolo_frame = component_detect
    try:
        packet = worker.process(slot)
        assert packet['inference_execution'] == 'parallel'
        assert all(message['frame_id'] == slot.frame_id for message in
                   [packet['detection'], *packet['components']])
        assert worker.state.get_capture()[1] is slot
    finally:
        worker.stop()


def test_live_rate_expires_when_the_camera_stops_delivering(monkeypatch):
    worker, _, _, _ = setup_worker()
    worker._rates.extend([(10., 1), (11., 31)])
    worker._processed = 31
    worker._processing_ms = 20.
    monkeypatch.setattr('app.eye_yolo_worker.time.monotonic', lambda: 11.1)
    assert worker.snapshot()['processing_fps'] == 30.
    monkeypatch.setattr('app.eye_yolo_worker.time.monotonic', lambda: 11.7)
    stopped = worker.snapshot()
    assert stopped['processing_fps'] == stopped['processing_ms'] == 0.
    assert stopped['processed_frames'] == 31


def test_display_stabilization_keeps_current_image_result_and_pin_identities():
    worker, slot, detector, components = setup_worker()
    slot = replace(slot, ts_ms=slot.ts_ms - 100.)
    original_detect = detector.detect
    shift = [0.]

    def detect(*args):
        current = original_detect(*args)
        dx = shift[0]
        return replace(current,
            pins=[replace(pin, x=pin.x + dx) for pin in current.pins],
            outline_px=[(x + dx, y) for x, y in current.outline_px],
            body={**current.body, 'box': [8. + dx, 8., 40. + dx, 40.]})

    detector.detect = detect
    first = worker.process(slot)
    shift[0] = 2.
    for component in components:
        x1, y1, x2, y2 = component.box
        component.box = [x1 + 2., y1, x2 + 2., y2]
    second = replace(slot, frame_id=18, seq=22, ts_ms=slot.ts_ms + 33.)
    packet = worker.process(second)
    assert packet['image'] == first['image']  # Same unmodified source pixels.
    assert packet['runtime_revision'] == 3 and packet['seq'] == second.seq
    assert packet['display_stabilization']['raspberry-pi-5']['reason'] == 'smoothed'
    assert packet['timing_ms']['display_stabilization'] >= 0
    assert 8. < packet['detection']['outline'][0][0] < 10.
    for message in [packet['detection'], *packet['components']]:
        assert message['frame_id'] == second.frame_id and message['ts_ms'] == second.ts_ms
        assert message['body']['frame_id'] == second.frame_id
        assert message['body']['source_frame_id'] == second.frame_id
        assert message['pose_quality']['stability'] == 'yolo_direct'
    assert packet['detection']['pins'][0]['id'] == 'J8:1'
    assert all(message['pins'][0]['id'] == 'VCC' for message in packet['components'])
    assert worker.detection_state.get_synchronized()[0] is second
    assert all(worker.component_state.get_synchronized(component._profile.component_id)[0] is second
               for component in components)
    assert worker.state.get_capture() == (packet, second)
    worker.stop()
    assert worker._display_stabilizer.diagnostics() == {}


def test_nms_after_previous_detection_clears_display_history_instead_of_reviving_pins():
    worker, slot, _, components = setup_worker()
    worker.process(slot)
    assert 'hw-123' in worker._display_stabilizer._samples
    components[1].box = [71., 12., 101., 40.]
    second = replace(slot, frame_id=18, seq=22, ts_ms=slot.ts_ms + 33.)
    packet = worker.process(second)
    hw = packet['components'][1]
    assert hw['pins'] == [] and hw['body'] is None and hw['outline'] is None
    assert hw['pose_quality']['reason'] == 'yolo_nms'
    assert 'hw-123' not in worker._display_stabilizer._samples
    worker.stop()


def test_body_only_roi_after_valid_board_never_inherits_previous_gpio():
    worker, slot, detector, _ = setup_worker()
    worker.process(slot)
    original = detector.detect

    def roi_body_only(*args):
        current = original(*args)
        return replace(current, tracking='searching', pins=[], outline_px=None,
            motion_outline_px=None, pose_path='yolo_roi_body_only',
            body={**current.body, 'source': 'pi_reference_model'})

    detector.detect = roi_body_only
    for step in (1, 2):
        current = replace(slot, frame_id=slot.frame_id + step, seq=slot.seq + step,
                          ts_ms=slot.ts_ms + 33. * step)
        packet = worker.process(current)
        board = packet['detection']
        assert board['frame_id'] == current.frame_id and board['pins'] == []
        assert board['outline'] is None and board['tracking'] == 'searching'
        assert board['body']['source'] == 'pi_reference_model'
        assert worker.detection_state.get().pins == []
    worker.stop()


def test_packet_error_discards_display_history_before_next_fresh_frame(monkeypatch):
    worker, slot, _, _ = setup_worker()
    worker.process(slot)
    with monkeypatch.context() as patch:
        patch.setattr('app.eye_yolo_worker.cv2.imencode', lambda *args: (False, None))
        with pytest.raises(RuntimeError, match='Could not encode'):
            worker.process(replace(slot, frame_id=18, seq=22, ts_ms=slot.ts_ms + 33.))
    assert worker._display_stabilizer.diagnostics() == {}
    packet = worker.process(replace(slot, frame_id=19, seq=23, ts_ms=slot.ts_ms + 66.))
    assert all(item['reason'] == 'fresh_seed' for item in packet['display_stabilization'].values())
    worker.stop()
