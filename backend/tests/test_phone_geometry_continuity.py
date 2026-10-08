"""Synthetic rotation/adaptive sizing. No physical phones, Pi or AI requests."""
from dataclasses import replace
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np

from app.capture.bus import FrameBus
from app.vision_worker import DetectionState, VisionWorker
from app.vision.interface import DetectionResult
from app.component_worker import ComponentPoseWorker
from app.vision.yolo_profile_detector import YoloProfileDetector, HybridBoardDetector
from app.vision.pipeline_detector import PipelineDetector
from test_phone_motion_parallel import setup_worker, moved, messages
from test_mobile import setup, preview
import asyncio


def test_epoch_catches_skipped_sizes_and_clear_without_queuing_or_resampling():
    bus = FrameBus()
    frame = np.ones((48, 64, 3), np.uint8)
    bus.put(frame, 1, 10)
    first = bus.get_latest(timeout=0)
    bus.put(frame, 2, 20)
    assert bus.get_latest(timeout=0).geometry_epoch == first.geometry_epoch
    bus.put(frame.transpose(1, 0, 2), 3, 30)
    bus.put(frame, 4, 40)
    latest = bus.get_latest(timeout=0)
    assert latest.geometry_epoch == first.geometry_epoch + 2
    assert latest.frame is frame and latest.frame_id == 4
    bus.clear();bus.put(frame, 5, 50)
    assert bus.get_latest(timeout=0).geometry_epoch > latest.geometry_epoch


def test_motion_drops_old_pins_and_body_even_after_size_returns_to_original():
    worker, source, _, _ = setup_worker()
    try:
        worker.process(moved(source, 1))
        # Same shape/image, but the bus saw another size in between. Old seeds
        # cannot become authoritative just because the dimensions match again.
        packet = worker.process(replace(moved(source, 2), geometry_epoch=2))
        for pose in messages(packet):
            assert pose['tracking'] == 'searching'
            assert pose['pins'] == [] and pose.get('body') is None
            assert not pose['pose_quality']['model_source']['paired']
    finally:
        worker.stop()


def test_vision_resets_inside_owner_and_discards_delayed_old_geometry_result():
    bus, state = FrameBus(), DetectionState()
    entered, release, published = threading.Event(), threading.Event(), threading.Event()
    resets, detected, pushes = [], [], []
    def detect(frame, frame_id, ts):
        detected.append(frame_id)
        if frame_id == 1:
            entered.set();assert release.wait(2)
        return DetectionResult('raspberry-pi-5', frame_id, ts, 'searching', 0, [])
    def publish(message):
        pushes.append(message);published.set()
    detector = NS(detect=detect, reset_stream_geometry=lambda: resets.append(threading.get_ident()))
    worker = VisionWorker(bus, detector, state, 'raspberry-pi-5', (64, 48), publish=publish)
    frame = np.ones((48, 64, 3), np.uint8)
    bus.put(frame, 1, 10);worker.start()
    try:
        assert entered.wait(1)
        bus.put(frame.transpose(1, 0, 2), 2, 20)
        bus.put(frame, 3, 30)
        release.set();assert published.wait(2)
        assert detected == [1, 3] and [m['frame_id'] for m in pushes] == [3]
        assert resets == [worker._thread.ident]
        assert state.get_synchronized()[0].frame_id == 3
    finally:
        release.set();worker.stop()


def test_component_rejects_late_old_size_result_without_touching_current_state():
    worker = object.__new__(ComponentPoseWorker)
    worker._bus, worker._state, worker._publish = FrameBus(), Mock(), Mock()
    frame = np.zeros((48, 64, 3), np.uint8)
    worker._bus.put(frame, 1, 10);old = worker._bus.get_latest(timeout=0)
    worker._bus.put(frame.transpose(1, 0, 2), 2, 20)
    worker._publish_result(NS(frame_id=1), old)
    worker._state.set.assert_not_called();worker._publish.assert_not_called()


def test_geometry_reset_retains_phone_calibration_policy_and_loaded_detectors():
    for cls in (YoloProfileDetector, PipelineDetector):
        detector = object.__new__(cls)
        detector._horizontal_fov_deg = None
        detector._camera_calibration_path = None
        detector._use_camera_calibration = False
        detector.reset_for_camera = Mock()
        detector.reset_stream_geometry()
        detector.reset_for_camera.assert_called_once_with(horizontal_fov_deg=None,
            camera_calibration_path=None, use_camera_calibration=False)
    hybrid = object.__new__(HybridBoardDetector)
    hybrid.primary, hybrid.fallback = Mock(), Mock()
    hybrid.reset_stream_geometry()
    hybrid.primary.reset_stream_geometry.assert_called_once()
    hybrid.fallback.reset_stream_geometry.assert_called_once()


def test_rotation_immediately_revokes_capture_and_late_old_analysis_cannot_relock(setup):
    service, phone, clock = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    service.on_receive(sid, generation, 1, clock(), clock.wall(), (640, 480))
    stream = service.sessions[sid]['stream']
    stream.update(can_capture=True, state='locked', recognition={'old': True})
    old_received = clock()
    for seq, size in ((2, (480, 640)), (3, (640, 480))):
        clock.now += .03
        service.on_receive(sid, generation, seq, clock(), clock.wall(), size)
        assert not stream['can_capture'] and stream['recognition'] is None
        assert stream['active'] and stream['publisher_connected']
    service.accept_preview(sid, generation, 20, old_received, preview(), (640, 480), phone['context_id'])
    assert not stream['can_capture'] and stream['recognition'] is None
    assert stream['preview_seq'] != 20
    assert not service.rtc.closed


def test_component_worker_resets_geometry_on_its_own_thread_without_stopping_model():
    worker = object.__new__(ComponentPoseWorker)
    worker._bus, worker._stop = FrameBus(), threading.Event()
    worker._yolo_only, worker._interval_s = True, .001
    worker._tracker, worker._tft_rings, worker._scale_recovery = Mock(), Mock(), Mock()
    worker._reset_eye_yolo_search, worker._state = Mock(), Mock()
    worker._profile, worker._reference_recovery = NS(component_id='hc-sr04'), None
    first, second, proceed = threading.Event(), threading.Event(), threading.Event()
    resets = []
    worker._tracker.reset_tracking.side_effect = lambda: resets.append(threading.get_ident())
    def infer(slot):
        if slot.frame_id == 1:
            first.set();assert proceed.wait(2)
        return slot
    worker.detect_yolo_frame = infer
    worker._publish_result = lambda result, slot: second.set() if slot.frame_id == 3 else None
    frame = np.zeros((48, 64, 3), np.uint8)
    worker._bus.put(frame, 1, 10)
    thread = threading.Thread(target=worker._run)
    thread.start()
    try:
        assert first.wait(1)
        worker._bus.put(frame.transpose(1, 0, 2), 2, 20)
        worker._bus.put(frame, 3, 30)
        proceed.set();assert second.wait(2)
        assert resets == [thread.ident] and thread.is_alive()
        worker._state.clear.assert_called_once_with('hc-sr04')
        worker._tft_rings.reset.assert_called_once()
    finally:
        proceed.set();worker._stop.set();thread.join(2)
        assert not thread.is_alive()
