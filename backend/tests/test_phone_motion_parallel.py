"""Phone-only concurrency, same-frame geometry and native-work ownership."""
from copy import deepcopy
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPinPosition, ComponentPoseResult, ComponentPoseState
from app import motion_worker as module
from app.motion_worker import MotionFrameState, MotionOverlayWorker
from app.vision.interface import DetectionResult, PinDetection
from app.vision_worker import DetectionState


KEYS = ('board', 'hc-sr04', 'mrd-tf240-8p-cs')


def setup_worker(phone=True):
    rng = np.random.default_rng(42)
    frame = np.full((400, 640, 3), 40, np.uint8)
    boxes = ((35, 50, 225, 210), (280, 45, 445, 165), (340, 235, 545, 355))
    for x, y, r, b in boxes:
        gray = cv2.GaussianBlur(rng.integers(15, 245, (b-y, r-x), dtype=np.uint8), (3, 3), 0)
        frame[y:b, x:r] = gray[..., None]
    now = time.monotonic()*1000
    source = FrameSlot(frame, 10, now, 10)
    detection, components = DetectionState(), ComponentPoseState()
    for key, (x, y, r, b) in zip(KEYS, boxes):
        quad = np.float32([[x, y], [r, y], [r, b], [x, b]])
        body = dict(box=[x, y, r, b], confidence=.9, source='pose_model')
        if key == 'board':
            detection.set(DetectionResult('raspberry-pi-5', 10, now, 'locked', .9,
                [PinDetection('J8:6', x+25, y+25, .9)], quad.tolist(), body=body), source)
        else:
            components.set(ComponentPoseResult(key, 10, now, 'locked', .9, (640, 400), quad,
                (ComponentPinPosition('GND', x+25, y+25, .9),), 'tracking', body=body), source)
    runtime = SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1)
    mode = SimpleNamespace(phone=phone)
    worker = MotionOverlayWorker(FrameBus(), detection, components,
        SimpleNamespace(snapshot=lambda: SimpleNamespace(**vars(runtime))), MotionFrameState(), phone_parallel=lambda: mode.phone)
    return worker, source, runtime, mode


def moved(source, step, *, covered=False):
    frame = cv2.warpAffine(source.frame, np.float32([[1, 0, step*2], [0, 1, step]]),
                           (640, 400), borderValue=(40, 40, 40))
    if covered:
        frame[220:390, 325:580] = 40
    return FrameSlot(frame, 10+step, source.ts_ms+step*33, 10+step)


def messages(packet):
    return [packet['detection'], *packet['components']]


def test_parallel_real_flow_matches_serial_movement_and_occlusion():
    serial, source, _, _ = setup_worker(False)
    parallel, _, _, _ = setup_worker(True)
    # Both workers must receive precisely the same paired source timestamps.
    parallel.detection_state = serial.detection_state
    parallel.component_state = serial.component_state
    original = deepcopy(serial.detection_state.get_synchronized()[1])
    try:
        for step in range(1, 7):
            slot = moved(source, step, covered=step == 4)
            expected, actual = serial.process(slot), parallel.process(slot)
            assert actual['tracking_execution'] == 'phone_parallel'
            assert expected['tracking_execution'] == 'serial'
            assert (actual['seq'], actual['frame_id'], actual['ts_ms']) == (slot.seq, slot.frame_id, slot.ts_ms)
            assert actual['image'] == expected['image']
            for left, right in zip(messages(expected), messages(actual)):
                assert left == right
                assert right['frame_id'] == slot.frame_id
            if step == 4:
                # Preserve the existing short display-prediction contract;
                # an occluded object is never relabelled a fresh lock.
                assert actual['components'][1]['tracking'] == 'stale'
                assert actual['components'][1]['pose_quality']['pin_evidence'] == 'prediction_not_observation'
        assert serial.detection_state.get_synchronized()[1] == original
    finally:
        serial.stop()
        parallel.stop()


def test_three_objects_overlap_source_gray_is_prepared_once_on_owner(monkeypatch):
    worker, source, _, mode = setup_worker()
    owner = threading.get_ident()
    barrier = threading.Barrier(3)
    calls, gray_threads = [], []
    original_update, original_gray = module.MotionTrack.update, module.tracking_gray

    def track(self, *args, **kwargs):
        calls.append((id(self), threading.get_ident()))
        if mode.phone:
            barrier.wait(timeout=3)
        return original_update(self, *args, **kwargs)

    def gray(frame):
        gray_threads.append((id(frame), threading.get_ident()))
        return original_gray(frame)

    monkeypatch.setattr(module.MotionTrack, 'update', track)
    monkeypatch.setattr(module, 'tracking_gray', gray)
    try:
        packet = worker.process(moved(source, 1))
        assert len({thread for _, thread in calls}) == 3
        assert len({track for track, _ in calls}) == 3
        assert all(thread != owner for _, thread in calls)
        assert len(gray_threads) == 2  # current + one shared seed, not per object
        assert all(thread == owner for _, thread in gray_threads)
        assert set(packet['timing_ms']['objects']) == set(KEYS)
        pool = worker._executor
        mode.phone = False
        calls.clear()
        assert worker.process(moved(source, 2))['tracking_execution'] == 'serial'
        assert {thread for _, thread in calls} == {owner}
        assert worker._executor is None
        assert all(not thread.is_alive() for thread in pool._threads)
    finally:
        worker.stop()


def test_recovery_budget_keeps_rotating_priority_under_simultaneous_claims(monkeypatch):
    worker, source, _, _ = setup_worker()
    barrier = threading.Barrier(3)
    winners = []

    def update(self, gray, frame_id, ts_ms, *, search_budget):
        barrier.wait(timeout=3)
        granted = search_budget()
        if granted:
            winners.append(self.message.get('component_id', 'board'))
        self.flow.search_deferred = not granted
        return None

    monkeypatch.setattr(module.MotionTrack, 'update', update)
    try:
        for step in range(1, 7):
            packet = worker.process(moved(source, step))
            assert packet['recovery_searches'] == 1
            assert len(packet['recovery_deferred']) == 2
        assert winners == list(KEYS)*2
    finally:
        worker.stop()


def test_error_drains_other_objects_before_clearing_tracks(monkeypatch):
    worker, source, _, _ = setup_worker()
    barrier, release, failed = threading.Barrier(3), threading.Event(), threading.Event()
    result = []

    def update(self, *args, **kwargs):
        barrier.wait(timeout=3)
        if self.message.get('component_id') is None:
            failed.set()
            raise ValueError('object failed')
        assert release.wait(3)
        assert len(worker.tracks) == 3
        return None

    monkeypatch.setattr(module.MotionTrack, 'update', update)
    def process():
        try:
            worker.process(moved(source, 1))
        except Exception as exc:
            result.append(exc)
    thread = threading.Thread(target=process)
    thread.start()
    try:
        assert failed.wait(3)
        assert thread.is_alive() and len(worker.tracks) == 3
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        assert len(result) == 1 and isinstance(result[0], ValueError)
        assert worker.tracks == worker.body_tracks == {}
    finally:
        release.set()
        thread.join(3)
        worker.stop()


def test_stop_during_jobs_drains_pool_and_never_publishes_old_packet(monkeypatch):
    worker, source, runtime, _ = setup_worker()
    barrier, entered, release = threading.Barrier(3), threading.Event(), threading.Event()
    original = module.MotionTrack.update
    def update(self, *args, **kwargs):
        barrier.wait(timeout=3)
        entered.set()
        assert release.wait(3)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(module.MotionTrack, 'update', update)
    monkeypatch.setattr(module, 'warm_motion_runtime', lambda: None)
    worker.state.get(timeout=0)
    slot = moved(source, 1)
    worker.bus.put(slot.frame, slot.frame_id, slot.ts_ms)
    worker.start()
    stopper = threading.Thread(target=worker.stop)
    try:
        assert entered.wait(3)
        pool = worker._executor
        stopper.start()
        assert worker._stop.wait(1)
        with pytest.raises(RuntimeError, match='stop motion'):
            worker.reset_tracking()
        release.set()
        stopper.join(3)
        assert not stopper.is_alive()
        assert worker.state._packet is None
        assert worker._executor is None and worker._thread is None
        assert all(not thread.is_alive() for thread in pool._threads)
        worker.reset_tracking()
        assert worker.tracks == worker.body_tracks == {}
        assert worker.context is None
        runtime.runtime_revision = 2
        worker._stop.clear()
        packet = worker.process(moved(source, 2))
        assert packet['runtime_revision'] == 2
    finally:
        release.set()
        if stopper.ident is not None:
            stopper.join(3)
        worker.stop()


def test_submit_failure_drains_work_queued_without_returned_future(monkeypatch):
    worker, source, _, _ = setup_worker()
    original = module.ThreadPoolExecutor
    pools = []
    class FailingPool:
        def __init__(self, **kwargs):
            self.pool = original(**kwargs)
            self.calls = 0
            pools.append(self.pool)
        def submit(self, *args):
            future = self.pool.submit(*args)
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError('thread start failed after queue')
            return future
        def shutdown(self, **kwargs):
            return self.pool.shutdown(**kwargs)
    monkeypatch.setattr(module, 'ThreadPoolExecutor', FailingPool)
    with pytest.raises(RuntimeError, match='thread start'):
        worker.process(moved(source, 1))
    assert worker._executor is None
    assert worker.tracks == worker.body_tracks == {}
    assert all(not thread.is_alive() for pool in pools for thread in pool._threads)
    worker.stop()


@pytest.mark.parametrize('change', ['stop', 'revision', 'source'])
def test_change_during_jpeg_never_publishes_phone_packet(monkeypatch, change):
    worker, source, runtime, mode = setup_worker()
    entered, release = threading.Event(), threading.Event()
    original = module.cv2.imencode
    def encode(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(module.cv2, 'imencode', encode)
    monkeypatch.setattr(module, 'warm_motion_runtime', lambda: None)
    worker.state.get(timeout=0)
    slot = moved(source, 1)
    worker.bus.put(slot.frame, slot.frame_id, slot.ts_ms)
    worker.start()
    try:
        assert entered.wait(3)
        if change == 'stop':
            worker._stop.set()
        elif change == 'revision':
            runtime.runtime_revision += 1
        else:
            mode.phone = False
        release.set()
        # Wait for this frame's processing, without racing an assertion against JPEG.
        with worker._process_lock:
            pass
        worker.stop()
        assert worker.state._packet is None
    finally:
        release.set()
        worker.stop()


@pytest.mark.parametrize('phone', [True, False])
def test_phone_uses_precise_deadline_serial_keeps_event_wait(monkeypatch, phone):
    worker, source, _, _ = setup_worker(phone)
    slots = [moved(source, 1), moved(source, 2)]
    cursors, precise, coarse, processed = [], [], [], []
    clock = [50.0]
    monkeypatch.setattr(module, 'warm_motion_runtime', lambda: None)
    monkeypatch.setattr(module.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(worker.state, 'requested', lambda: True)
    monkeypatch.setattr(worker._stop, 'wait', lambda delay: coarse.append(delay) or False)

    def next_frame(timeout, newer_than):
        cursors.append(newer_than)
        if not slots:
            worker._stop.set()
            return None
        return slots.pop(0)

    def process(slot):
        processed.append(slot.seq)
        clock[0] += .020
        # Cadence applies even when a source switch discards a packet. There
        # is never an extra queued frame or a deadline based on finish time.
        return None

    def deadline(stop, due):
        precise.append((stop, due, clock[0]))
        clock[0] = max(clock[0], due)
        return stop.is_set()

    monkeypatch.setattr(worker.bus, 'get_latest', next_frame)
    monkeypatch.setattr(worker, 'process', process)
    monkeypatch.setattr(module, 'wait_eye_deadline', deadline)
    worker._run()
    assert processed == [11, 12]
    assert cursors == [-1, 11, 12]
    if phone:
        assert coarse == [] and len(precise) == 2
        assert all(stop is worker._stop for stop, _, _ in precise)
        assert precise[0][1] == pytest.approx(50 + 1/30)
        assert precise[1][1] == pytest.approx(50 + 2/30)
        assert all(due-now == pytest.approx(1/30-.020) for _, due, now in precise)
    else:
        assert precise == []
        assert coarse == pytest.approx([1/30-.020]*2)
    worker.stop()


def test_stop_at_phone_deadline_does_not_request_another_frame(monkeypatch):
    worker, source, _, _ = setup_worker()
    calls = []
    monkeypatch.setattr(module, 'warm_motion_runtime', lambda: None)
    monkeypatch.setattr(worker.state, 'requested', lambda: True)
    monkeypatch.setattr(worker.bus, 'get_latest', lambda **kw: calls.append(kw) or moved(source, 1))
    monkeypatch.setattr(worker, 'process', lambda slot: None)
    def deadline(stop, due):
        stop.set()
        return True
    monkeypatch.setattr(module, 'wait_eye_deadline', deadline)
    worker._run()
    assert len(calls) == 1
    worker.stop()
