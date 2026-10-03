"""One live pipeline with synthetic pixels; never opens phones, USB or Pi."""
import asyncio
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from app.capture.phone import PhoneFrameSource, LiveSourceManager
from app.capture.bus import FrameBus
from app.capture.service import CaptureService
from app.component_worker import ComponentPoseState
from app.mobile_rtc import MobileRTC
from app.motion_worker import MotionOverlayWorker, MotionFrameState
from app.vision_worker import DetectionState
from test_camera_modes import state


def prepare(state):
    state.config.runtime_revision = 1
    def changed(_):
        state.config.runtime_revision += 1
    state.runtime_manager.camera_changed = changed
    return LiveSourceManager(state)


def feed(manager, stop, sid='paired', generation=1, size=(96, 72)):
    seq = 0
    while not stop.wait(.01):
        seq += 1
        manager.push(sid, generation, np.full((size[1], size[0], 3), 160, np.uint8), seq, time.monotonic())


def test_phone_adapter_latest_only_rejects_foreign_stale_duplicate_and_rotated_frames():
    now = [10.]
    source = PhoneFrameSource('paired', 1, (64, 48), clock=lambda: now[0])
    source.open()
    pixels = np.ones((48, 64, 3), np.uint8)
    assert not source.push('other', 1, pixels, 1, 10.)
    assert not source.push('paired', 2, pixels, 1, 10.)
    source.push('paired', 1, pixels, 1, 8.)
    assert source.read() is None
    source.push('paired', 1, pixels, 2, 10.)
    source.push('paired', 1, pixels*2, 3, 10.)
    source.push('paired', 1, pixels*9, 2, 10.)
    frame, seq, timestamp = source.read()
    assert seq == 3 and timestamp == 10000 and frame.mean() == 2
    source.push('paired', 1, pixels, 4, 10.)
    now[0] = 11.
    assert source.read() is None
    source.push('paired', 1, pixels.transpose(1, 0, 2), 5, 11.)
    assert source.read() is None and source.error == 'phone_dimensions_changed'
    source.close()
    source.push('paired', 1, pixels, 6, 11.)
    assert source.read() is None


def test_handover_reuses_workers_resets_geometry_and_restores_webcam(state):
    manager, webcam = prepare(state), state.source
    phone = PhoneFrameSource('paired', 1, (96, 72))
    workers = [state.vision_worker, *state.component_workers]
    stop = threading.Event()
    thread = threading.Thread(target=feed, args=(manager, stop), daemon=True)
    thread.start()
    try:
        result = manager.select('phone', phone=phone, timeout=1)
        assert result['ok'] and result['kind'] == 'phone' and result['ready']
        assert state.config.camera.calibration_path is None
        assert state.config.camera.source == 'phone'
        assert state.source is phone and state.config.runtime_revision == 2
        assert [state.vision_worker, *state.component_workers] == workers
        assert state.component_workers[0].stops == [{'close_models': False}]
        assert state.frame_bus.get_latest(timeout=0).frame.mean() == 160
        assert manager.select('webcam', timeout=1)['ok']
        assert state.source is webcam and state.config.camera.source == 'device'
        assert state.config.runtime_revision == 3 and state.frame_bus.get_latest(timeout=0).frame.mean() == 100
        assert not manager.push('paired', 1, np.zeros((72, 96, 3), np.uint8), 9999, time.monotonic())
    finally:
        stop.set(); thread.join(1)


def test_missing_phone_frames_roll_back_to_verified_webcam(state):
    manager, original = prepare(state), state.source
    result = manager.select('phone', phone=PhoneFrameSource('paired', 1, (96, 72)), timeout=.12)
    assert not result['ok'] and result['restored'] and result['error'] == 'camera_mode_failed'
    assert result['kind'] == 'webcam' and state.source is original
    assert manager.candidate is None and manager.webcam is None


def test_landscape_to_native_portrait_generation_clears_geometry_and_restores_original_webcam(state):
    manager, webcam = prepare(state), state.source
    webcam_config = state.config.camera.model_copy(deep=True)
    workers = [state.vision_worker, *state.component_workers]
    previous_source = None
    previous_bus_seq = state.frame_bus.latest_seq
    for generation, size in ((1, (1920, 1080)), (2, (1080, 1920))):
        source = PhoneFrameSource('paired', generation, size)
        if previous_source is not None:
            # A restarted publisher cannot silently feed the still-selected old
            # source. The desktop must reselect through the camera transaction.
            assert not manager.push('paired', generation,
                np.ones((size[1], size[0], 3), np.uint8), 1, time.monotonic())
            assert state.source is previous_source
            assert state.config.runtime_revision == generation
        stop = threading.Event()
        thread = threading.Thread(target=feed, args=(manager, stop, 'paired', generation, size), daemon=True)
        thread.start()
        try:
            assert manager.select('phone', phone=source, timeout=2)['ok']
            slot = state.frame_bus.get_latest(timeout=0)
            assert slot.frame.shape == (size[1], size[0], 3)
            assert slot.seq > previous_bus_seq
            assert state.detection_state.get_video_size() == size
            assert (state.config.camera.width, state.config.camera.height) == size
            assert state.config.runtime_revision == generation + 1
            assert state.config.camera.calibration_path is None
            assert state.source is source and manager.webcam[0] is webcam
            assert [state.vision_worker, *state.component_workers] == workers
            assert all(worker.resets == generation for worker in workers)
            if previous_source is not None:
                assert not previous_source._opened and previous_source._latest is None
                assert not manager.push('paired', generation-1, np.zeros((1080, 1920, 3), np.uint8), 99999, time.monotonic())
                assert state.frame_bus.get_latest(timeout=0).frame.shape == (1920, 1080, 3)
            previous_source, previous_bus_seq = source, slot.seq
        finally:
            stop.set()
            thread.join(1)
    assert state.component_workers[0].stops == [{'close_models': False}] * 2
    assert manager.select('webcam', timeout=1)['ok']
    assert state.source is webcam and state.config.camera == webcam_config
    assert state.config.runtime_revision == 4
    assert state.frame_bus.latest_seq > previous_bus_seq
    assert state.frame_bus.get_latest(timeout=0).frame.shape == (48, 64, 3)


def test_cannot_switch_while_capture_or_ai_is_in_flight(state):
    manager = prepare(state)
    state.debug_sessions = NS(lock=threading.RLock(), sessions={'one': {'capture_pending': True}})
    with pytest.raises(HTTPException, match='camera_capture_busy'):
        manager.select('phone', phone=PhoneFrameSource('paired', 1, (96, 72)))
    assert state.config.runtime_revision == 1


def test_full_rate_rtc_tap_is_not_limited_by_three_hz_feedback():
    async def scenario():
        clock = [10.]
        previews = []
        gate = asyncio.Event()
        async def feedback(*args):
            previews.append(args)
            await gate.wait()
        rtc = MobileRTC(feedback, Mock(), clock=lambda: clock[0])
        source = PhoneFrameSource('paired', 1, (64, 48), clock=lambda: clock[0]); source.open()
        frames = []
        rtc.live_source = NS(phone_source=lambda sid, gen: source, push=lambda *a: (frames.append(a), source.push(*a)))
        queue = asyncio.Queue()
        proxy = NS(recv=queue.get, stop=Mock())
        stream = NS(generation=1, track=NS(received_at=lambda video: clock[0]))
        rtc.streams['paired'] = stream
        task = asyncio.create_task(rtc._sample('paired', stream, proxy))
        for i in range(12):
            clock[0] += 1/30
            queue.put_nowait(NS(to_ndarray=lambda **_: np.ones((48, 64, 3), np.uint8)))
            await asyncio.sleep(0)
        assert len(frames) == 12 and len(previews) == 1
        assert source.read()[1] == 12
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert proxy.stop.call_count == 1
    asyncio.run(scenario())


def test_phone_frame_uses_existing_same_frame_tracking_and_raw_photo_capture():
    from test_debug_capture import setup
    from app.debug_capture import capture_debug_evidence
    state, clock, image = setup()
    state.config.camera.source = 'phone'
    state.source = PhoneFrameSource('paired', 1, (320, 200), clock=clock)
    images, evidence = capture_debug_evidence(state, clock=clock, sleep=clock.sleep)
    assert evidence['source'] == 'phone' and evidence['camera_id'].startswith('phone-')
    assert evidence['same_frame'] and evidence['capture_skew_ms'] == 0 and not evidence['electrical_verified']
    assert cv2.imdecode(np.frombuffer(images['overview'], np.uint8), 1).shape == image.shape
    motion = MotionOverlayWorker(FrameBus(), DetectionState(), ComponentPoseState(), state.runtime_manager, MotionFrameState())
    slot = state.frame_bus.get_latest()
    packet = motion.process(slot)
    assert packet['frame_id'] == packet['detection']['frame_id'] == slot.frame_id
    assert packet['seq'] == slot.seq and packet['runtime_revision'] == 3
    assert packet['detection']['video_size'] == [320, 200]


@pytest.mark.parametrize('size', [(1920, 1080), (1080, 1920)])
def test_phone_shared_preview_does_not_rerun_models(monkeypatch, size):
    from test_mobile_recognition import analyzer
    service, models, _, _ = analyzer(monkeypatch)
    width, height = size
    pixels = np.zeros((height, width, 3), np.uint8)
    outline = [[20, height-200], [200, height-200], [200, height-20], [20, height-20]]
    pins = [dict(pin=1, x=40, y=height-100)]
    packet = dict(detection=dict(outline=outline, pins=pins, tracking='locked', confidence=.9,
        video_size=list(size), frame_id=17, runtime_revision=9), components=[])
    result = service.preview_packet(pixels, {'context_id': 'context', 'context': {}},
        dict(session_id='paired', generation=2, sample_seq=21), packet)
    assert result['recognition']['frame_seq'] == 21
    assert result['recognition']['detection']['runtime_revision'] == 2
    assert result['recognition']['video_size'] == result['recognition']['detection']['video_size'] == list(size)
    assert result['recognition']['detection']['outline'] == outline
    assert result['recognition']['detection']['pins'] == pins
    assert packet['detection']['runtime_revision'] == 9  # no mutation of shared display
    assert all(model._locator.locate.call_count == 0 for model in models.values())
    assert result['board_present'] and not result['sharp']


def test_source_api_is_desktop_only_and_requires_the_current_paired_generation(state):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.cameras import router
    app = FastAPI(); app.include_router(router)
    state.live_source = prepare(state)
    state.mobile_service = NS(lock=threading.RLock(), latest={'conversation_id': 'current'},
        require=lambda sid: dict(conversation_id='current', stream=dict(active=True, generation=2)),
        rtc=NS(capture_frame=Mock()))
    for name, value in vars(state).items():
        setattr(app.state, name, value)
    with TestClient(app, client=('192.168.1.4', 5000)) as remote:
        assert remote.post('/api/camera/live-source', json={'kind': 'webcam'}).status_code == 403
    with TestClient(app, client=('127.0.0.1', 5000)) as desktop:
        result = desktop.post('/api/camera/live-source', json={'kind': 'phone', 'session_id': 'paired', 'generation': 1})
        assert result.status_code == 409 and result.json()['detail'] == 'mobile_stream_generation_changed'
        assert state.mobile_service.rtc.capture_frame.call_count == 0
        state.camera_control_lock.acquire()
        try:
            assert desktop.post('/api/camera/live-source', json={'kind': 'webcam'}).status_code == 409
        finally:
            state.camera_control_lock.release()


def test_source_api_commits_only_after_fresh_phone_frames_arrive(state):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.cameras import router
    app = FastAPI(); app.include_router(router)
    state.live_source = prepare(state)
    state.mobile_service = NS(lock=threading.RLock(), latest={'conversation_id': 'current'},
        require=lambda sid: dict(conversation_id='current', stream=dict(active=True, generation=1)),
        rtc=NS(capture_frame=lambda *a: (np.ones((72,96,3), np.uint8), {})))
    for name, value in vars(state).items():
        setattr(app.state, name, value)
    stop = threading.Event()
    thread = threading.Thread(target=feed, args=(state.live_source, stop), daemon=True); thread.start()
    try:
        with TestClient(app, client=('127.0.0.1', 5000)) as client:
            response = client.post('/api/camera/live-source', json={'kind': 'phone', 'session_id': 'paired', 'generation': 1})
            assert response.status_code == 200
            assert response.json()['kind'] == 'phone' and response.json()['ready']
            assert client.get('/api/camera/live-source').json()['generation'] == 1
    finally:
        stop.set(); thread.join(1)
