"""Synthetic slow debug/photo operations must leave native media receipt free."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest
from fastapi.testclient import TestClient

from app import mobile as mobile_module
from app.api import mobile as mobile_api
from test_mobile import context, setup, upload
from test_mobile_api import app, auth, jpeg
from test_shared_test_help import fixture, imported, invitation


@pytest.mark.parametrize('action', ['offer', 'start', 'later'])
def test_slow_test_help_does_not_block_native_receipt(tmp_path, monkeypatch, action):
    _, state, service, phone, _, meta = fixture(tmp_path)
    message = imported(state, meta) if action != 'offer' else None
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    entered, release = threading.Event(), threading.Event()
    target = state.debug_sessions if action == 'start' else state.assistant
    name = 'create' if action == 'start' else '_save'
    original = getattr(target, name)

    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(imported, state, meta) if action == 'offer' else pool.submit(
            service.wiring_review_invitation, sid, invitation(service, message, action))
        try:
            if not entered.wait(2):
                work.result(timeout=1)
                pytest.fail('slow operation was not reached')
            receipt = pool.submit(service.on_receive, sid, generation, 20, service.clock(), service.wall(), (960, 540))
            receipt.result(timeout=.5)
        finally:
            release.set()
        work.result(timeout=2)
    stream = service.snapshot(sid)['stream']
    assert stream['received_frames'] == 20 and stream['active'] and stream['generation'] == generation
    assert not service.rtc.closed and not state.design_service.bridge.calls and not state.pi_execution.jobs


@pytest.mark.parametrize('phase', ['save', 'bind'])
def test_capture_completion_keeps_event_loop_and_media_receipt_available(setup, tmp_path, monkeypatch, phase):
    service, phone, clock = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    asset = upload(service, phone, tmp_path)
    session = deepcopy(service.sessions[sid])
    session.update(generation=generation, _capture_order=1)
    service.capture_order[sid] = 1
    entered, release, received = threading.Event(), threading.Event(), threading.Event()
    loops = []
    original = mobile_module._write_json

    def slow(*args):
        entered.set()
        assert release.wait(3)
        if phase == 'save':
            return original(*args)

    if phase == 'save':
        monkeypatch.setattr(mobile_module, '_write_json', slow)
    else:
        monkeypatch.setattr(service.state.assistant, 'bind_photo_reference', slow, raising=False)

    async def analyze():
        loops.append(asyncio.get_running_loop())
        return await service._analyze_capture(sid, asset, service.latest, session)

    def receive():
        service.on_receive(sid, generation, 30, clock.now, clock.wall(), (960, 540))
        received.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(lambda: asyncio.run(analyze()))
        try:
            assert entered.wait(2)
            loops[0].call_soon_threadsafe(receive)
            assert received.wait(.5), 'photo completion blocked the native RTC event loop'
        finally:
            release.set()
        packet = work.result(timeout=2)
    assert service.snapshot(sid)['stream']['received_frames'] == 30
    assert service.capture(packet['capture_id'], sid) == packet
    assert not service.rtc.closed


def test_upload_spooling_is_not_on_native_rtc_event_loop(app, setup, monkeypatch):
    service, phone, _ = setup
    original = mobile_api.tempfile.NamedTemporaryFile
    calls = []

    def checked(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            calls.append('worker')
        else:
            raise AssertionError('upload file I/O runs on the native RTC event loop')
        return original(*args, **kwargs)

    monkeypatch.setattr(mobile_api.tempfile, 'NamedTemporaryFile', checked)
    with TestClient(app, client=('192.168.1.10', 5000)) as client:
        response = client.post('/api/mobile/assets', headers=auth(phone), data={'upload_id': 'isolated-upload'},
            files={'file': ('photo.jpg', jpeg(), 'image/jpeg')})
    assert response.status_code == 200 and calls
    assert not list(service.root.glob('*.upload'))


@pytest.mark.parametrize('change', ['selection', 'publisher', 'context'])
def test_delayed_chat_binding_cannot_restore_stale_capture(setup, tmp_path, monkeypatch, change):
    service, phone, _ = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    asset = upload(service, phone, tmp_path)
    frozen = deepcopy(service.latest)
    session = deepcopy(service.sessions[sid])
    session.update(generation=generation, _capture_order=1)
    service.capture_order[sid] = 1
    assistant = service.state.assistant
    assistant.lock = threading.RLock()
    bound = []
    assistant.bind_photo_reference = lambda *args: bound.append(args)
    entered = threading.Event()
    original = service._bind_capture_reference

    def waiting(*args):
        entered.set()
        return original(*args)

    monkeypatch.setattr(service, '_bind_capture_reference', waiting)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with assistant.lock:
            work = pool.submit(lambda: asyncio.run(service._analyze_capture(sid, asset, frozen, session)))
            assert entered.wait(2)
            if change == 'selection':
                service.view(sid, {'capture_id': None, 'wire_id': None})
            elif change == 'publisher':
                asyncio.run(service.start_stream(sid))
            else:
                service.publish_context(context(title='New context'))
        packet = work.result(timeout=2)
    assert not bound
    assert service.capture(packet['capture_id'], sid) == packet


def test_failed_capture_persistence_does_not_publish_or_bind(setup, tmp_path, monkeypatch):
    service, phone, _ = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    asset = upload(service, phone, tmp_path)
    session = deepcopy(service.sessions[sid])
    session.update(generation=generation, _capture_order=1)
    service.capture_order[sid] = 1
    before = deepcopy(session['view'])
    bound = []
    service.state.assistant.bind_photo_reference = lambda *args: bound.append(args)

    def fail(*args):
        raise OSError('synthetic disk failure')

    monkeypatch.setattr(mobile_module, '_write_json', fail)
    with pytest.raises(OSError, match='synthetic disk failure'):
        asyncio.run(service._analyze_capture(sid, asset, service.latest, session))
    assert not service.captures and not bound
    assert service.view(sid) == before
    assert service.snapshot(sid)['stream']['active'] and not service.rtc.closed


def test_oversized_upload_cleans_up_without_stopping_stream(app, setup, monkeypatch):
    service, phone, _ = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    monkeypatch.setattr(mobile_api, 'MAX_UPLOAD', 10)
    with TestClient(app, client=('192.168.1.10', 5000)) as client:
        response = client.post('/api/mobile/assets', headers=auth(phone), data={'upload_id': 'oversized'},
            files={'file': ('photo.jpg', jpeg(), 'image/jpeg')})
    assert response.status_code == 413
    assert not list(service.root.glob('*.upload'))
    assert service.snapshot(sid)['stream']['generation'] == generation and not service.rtc.closed


def test_slow_metrics_notification_keeps_receipt_and_rtc_event_loop_free(setup, monkeypatch):
    service, phone, clock = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    service.on_receive(sid, generation, 1, clock(), clock.wall(), (1920, 1080))
    entered, release, received = threading.Event(), threading.Event(), threading.Event()
    loops = []

    def slow_notification(session):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(service, 'notify', slow_notification)

    async def metrics():
        loops.append(asyncio.get_running_loop())
        await service.on_video_metrics(sid, generation, {'video_fps': 30.})

    def receive():
        service.on_receive(sid, generation, 2, clock(), clock.wall(), (1920, 1080))
        received.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(lambda: asyncio.run(metrics()))
        try:
            assert entered.wait(2)
            loops[0].call_soon_threadsafe(receive)
            unblocked = received.wait(.3)
        finally:
            release.set()
        work.result(timeout=2)
    assert unblocked, 'status notification blocked the RTC loop or receive lock'
    assert service.snapshot(sid)['stream']['received_frames'] == 2


@pytest.mark.parametrize('change', ['rotation', 'generation', 'expired'])
def test_delayed_video_metrics_do_not_restore_old_stream_state(setup, change):
    service, phone, clock = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    service.on_receive(sid, generation, 1, clock(), clock.wall(), (1920, 1080))
    measured = clock()
    values = {'video_fps': 30., 'video_size': [1920, 1080], 'video_color': {'colorspace': 1}}
    if change == 'rotation':
        service.on_receive(sid, generation, 2, clock(), clock.wall(), (1080, 1920))
    elif change == 'generation':
        asyncio.run(service.start_stream(sid))
    else:
        clock.now += mobile_module.PREVIEW_TTL + .01
    before = deepcopy(service.sessions[sid]['stream'])
    service._apply_video_metrics(sid, generation, values, measured)
    after = service.sessions[sid]['stream']
    if change == 'rotation':
        assert after['video_size'] == [1080, 1920] and after['video_receive_seq'] == 2
        assert after.get('video_color') == before.get('video_color')
    else:
        assert after == before
