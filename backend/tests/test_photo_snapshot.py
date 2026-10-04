"""One-shot photo isolation with fake models; no camera, cloud, Pi or GPIO I/O."""
import copy
import hashlib
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace as NS

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.photo_wiring import router
from app.capture.bus import FrameSlot
from app.component_worker import ComponentPoseWorker, ComponentVisionProfile
from app.photo_wiring import session_transition
from app.vision.model_lock import serialized_model_call
from app.vision.yolo_pose import BoardPoseObservation
from test_photo_wiring import setup, body


def live_setup():
    service, state, clock, detector = setup()
    for worker in state.component_workers:
        def photo_context(owner=worker):
            context = copy.copy(owner)
            context.running, context._thread = False, None
            return context
        worker.photo_context = photo_context
    return service, state, clock, detector


def assert_live_untouched(service, state):
    assert not service.active
    assert not state.camera_control_lock.locked()
    for worker, _ in service._workers():
        assert worker.running
        assert worker.stops == worker.starts == 0
    assert all(worker.reset_calls == 0 for worker in state.component_workers)
    for name in ('detection_state', 'component_pose_state', 'motion_frame_state', 'wire_state'):
        getattr(state, name).clear.assert_not_called()


def test_snapshot_keeps_live_workers_and_one_frozen_original_frame():
    service, state, _, detector = live_setup()
    packet = service.snapshot(body())
    assert packet['continuous_inference'] is True
    assert packet['camera_id'].startswith('webcam-')
    assert packet['runtime_revision'] == 7
    assert state.frame_bus.calls == [{'timeout': 2, 'newer_than': 0}]
    for observation in [packet['detection'], *packet['components']]:
        assert observation['frame_id'] == packet['frame_id']
        assert observation['ts_ms'] == packet['capture_ts_ms']
        assert observation['video_size'] == packet['video_size'] == [160, 100]
    frozen = service.image(packet['capture_id'])
    assert hashlib.sha256(frozen).hexdigest() == packet['image_sha256']
    state.frame_bus.frame[:] = 255
    assert np.mean(detector.calls[0][2]) < 50
    assert service.image(packet['capture_id']) == frozen
    assert_live_untouched(service, state)


def test_component_photo_context_has_own_cursor_and_uses_serialized_model_owner():
    class Locator:
        active = maximum = 0

        @serialized_model_call
        def locate(self, frame):
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            time.sleep(.01)
            self.active -= 1
            return BoardPoseObservation(np.float32([[20, 20], [80, 20], [80, 60], [20, 60]]),
                .9, np.ones(4), (18, 18, 82, 62))

    worker = ComponentPoseWorker.__new__(ComponentPoseWorker)
    worker._profile = ComponentVisionProfile('hc-sr04', (('VCC', .2, .9),))
    worker._locator, worker._reference_recovery = Locator(), NS(evidence={'live': True})
    worker._scale_recovery_enabled, worker._yolo_only = False, False
    worker._eye_yolo_region, worker._eye_yolo_shape = 4, (900, 1200)
    worker._tracker = NS(reset_tracking=lambda: pytest.fail('live tracker reset'))
    worker._state = NS(clear=lambda: pytest.fail('live state cleared'))
    contexts = [worker.photo_context(), worker.photo_context()]
    slot = FrameSlot(np.zeros((100, 160, 3), np.uint8), 42, 1000, 7)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda context: context.detect_yolo_frame(slot), contexts))
    assert all(result.frame_id == 42 and result.ts_ms == 1000 for result in results)
    assert worker._locator.maximum == 1
    assert worker._eye_yolo_region == 4 and worker._eye_yolo_shape == (900, 1200)
    assert worker._reference_recovery.evidence == {'live': True}
    assert all(not hasattr(context, '_tracker') and not hasattr(context, '_thread') for context in contexts)


def test_snapshot_rejects_source_or_result_mismatch_without_changing_live_state():
    service, state, _, detector = live_setup()
    original = detector.detect
    def changed(*args):
        result = original(*args)
        state.source = NS(device_name='another-source')
        return result
    detector.detect = changed
    with pytest.raises(HTTPException, match='photo_context_changed'):
        service.snapshot(body())
    assert not service.captures
    assert_live_untouched(service, state)

    service, state, _, _ = live_setup()
    state.component_workers[0].mismatch = True
    with pytest.raises(HTTPException, match='photo_component_frame_mismatch'):
        service.snapshot(body())
    assert not service.captures
    assert_live_untouched(service, state)


def test_snapshot_route_preserves_the_legacy_pause_session_contract():
    service, state, _, _ = live_setup()
    app = FastAPI()
    app.state.photo_wiring_service = service
    app.include_router(router)
    client = TestClient(app)
    response = client.post('/api/photo-wiring/snapshot', json=body().model_dump())
    assert response.status_code == 200 and response.json()['continuous_inference'] is True
    assert session_transition('POST', '/api/photo-wiring/snapshot')
    assert_live_untouched(service, state)
    started = client.post('/api/photo-wiring/sessions').json()
    assert started['continuous_inference'] is False
    assert all(not worker.running for worker, _ in service._workers())
    legacy = client.post(f"/api/photo-wiring/sessions/{started['session_id']}/captures", json=body().model_dump())
    assert legacy.status_code == 200 and legacy.json()['continuous_inference'] is False
    assert all(worker.reset_calls == 1 for worker in state.component_workers)
    assert client.delete(f"/api/photo-wiring/sessions/{started['session_id']}").json()['resumed']


def test_snapshot_failures_release_camera_guard_and_do_not_pause_workers():
    service, state, _, detector = live_setup()
    state.frame_bus.get_latest = lambda **_: None
    with pytest.raises(HTTPException, match='photo_new_frame_unavailable'):
        service.snapshot(body())
    assert not detector.calls
    assert_live_untouched(service, state)
    token = service.start()['session_id']
    with pytest.raises(HTTPException, match='photo_session_busy'):
        service.snapshot(body())
    service.finish(token)
