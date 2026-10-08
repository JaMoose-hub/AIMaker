"""Preview status projection must not stall native RTC receipt or scheduling."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from test_mobile import preview as ready_preview, setup


@pytest.mark.parametrize('expired', [False, True])
def test_slow_preview_notification_leaves_rtc_loop_and_receipt_free(setup, monkeypatch, expired):
    assert_preview_isolation(setup, monkeypatch, expired)


@pytest.mark.parametrize('expired', [False, True])
def test_selected_phone_preview_notification_leaves_rtc_loop_free(setup, monkeypatch, expired):
    assert_preview_isolation(setup, monkeypatch, expired, selected=True)


def assert_preview_isolation(setup, monkeypatch, expired, selected=False):
    service, phone, clock = setup
    sid = phone['session_id']
    generation = asyncio.run(service.start_stream(sid))['generation']
    service.on_receive(sid, generation, 1, clock.now, clock.wall(), (100, 100))
    # Geometry predates this analysis; test TTL expiry, not rotation rejection.
    service.sessions[sid]['stream']['geometry_received'] = clock.now - 3
    if selected:
        from app.capture.phone import PhoneFrameSource
        service.state.source = PhoneFrameSource(sid, generation, (100, 100))
        service.state.config = SimpleNamespace(runtime_revision=1)
        slot = SimpleNamespace(frame=np.zeros((100, 100, 3), np.uint8),
                               ts_ms=(clock.now - (2 if expired else 0)) * 1000)
        service.state.motion_frame_state = SimpleNamespace(
            get_capture=lambda: ({'runtime_revision': 1}, slot))
        service.state.mobile_photo.preview_packet = lambda *args: ready_preview()
    entered, release, received = threading.Event(), threading.Event(), threading.Event()
    loops = []
    notify = service.notify

    def slow_notify(session):
        if not entered.is_set():
            entered.set()
            assert release.wait(3), 'test did not release preview notification'
        notify(session)

    monkeypatch.setattr(service, 'notify', slow_notify)

    async def preview():
        loops.append(asyncio.get_running_loop())
        await service.on_frame(sid, generation, np.zeros((100, 100, 3), np.uint8),
                               2, clock.now - (2 if expired else 0))

    def receive():
        service.on_receive(sid, generation, 3, clock.now, clock.wall(), (100, 100))
        received.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(lambda: asyncio.run(preview()))
        try:
            assert entered.wait(2), 'preview notification was not reached'
            loops[0].call_soon_threadsafe(receive)
            assert received.wait(.5), 'preview status blocked the native RTC event loop or media lock'
        finally:
            release.set()
            work.result(timeout=2)
    stream = service.snapshot(sid)['stream']
    assert stream['received_frames'] == 3
    assert stream['generation'] == generation and stream['active']
    assert not service.rtc.closed
    if expired:
        assert not stream['can_capture']
        assert stream['reason'] == 'context_changed_or_preview_expired'
    else:
        assert stream['preview_seq'] == 2
