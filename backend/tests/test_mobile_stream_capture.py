"""Frozen phone-video photos: synthetic pixels/fake analyzers, never webcam/model."""
import asyncio
from copy import deepcopy
import hashlib
from io import BytesIO
import threading
from types import SimpleNamespace

from av import VideoFrame
from fastapi import HTTPException
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from app.mobile_rtc import CountedVideoTrack, MobileRTC, Stream
from test_mobile import setup, context, lock, upload
from test_mobile_api import app, auth
from test_mobile_https import gateway


class Source:
    def __init__(self, frame):
        self.frame, self.stopped = frame, False

    async def recv(self):
        return self.frame

    def stop(self):
        self.stopped = True


def frame_source(service, phone, clock, pixels=None):
    """Attach the real snapshot implementation to the otherwise fake transport."""
    if pixels is None:
        pixels = np.arange(30*18*3, dtype=np.uint8).reshape((30, 18, 3))
    source = Source(VideoFrame.from_ndarray(pixels, format="bgr24"))
    track = CountedVideoTrack(source, None, clock, clock.wall)
    generation = service.sessions[phone["session_id"]]["stream"]["generation"]
    rtc = MobileRTC(None, None, clock=clock, wall=clock.wall)
    rtc.streams[phone["session_id"]] = Stream(generation, track=track)
    calls = []

    def snapshot(*args, **kwargs):
        calls.append((args, kwargs))
        return rtc.capture_frame(*args, **kwargs)

    service.rtc.capture_frame = snapshot
    return source, track, calls, rtc


def request(phone, generation=1, request_id="take-one"):
    return dict(generation=generation, request_id=request_id, context_id=phone["context_id"])


def test_latest_actual_receipt_native_pixels_independent_and_ttl(setup):
    service, phone, clock = setup

    async def scenario():
        await service.start_stream(phone["session_id"])
        source, track, _, rtc = frame_source(service, phone, clock)
        await track.recv()
        clock.now += .1
        source.frame = VideoFrame.from_ndarray(np.full((30, 18, 3), (31, 82, 145), np.uint8), format="bgr24")
        await track.recv()
        pixels, identity = rtc.capture_frame(phone["session_id"], 1)
        assert pixels.shape == (30, 18, 3)
        assert np.all(pixels == (31, 82, 145))
        assert identity == dict(session_id=phone["session_id"], generation=1, frame_seq=2,
                                received_monotonic=100.1, received_at=clock.wall())
        source.frame.planes[0].update(bytes(source.frame.planes[0].buffer_size))
        assert np.all(pixels == (31, 82, 145))
        clock.now += 1.5
        rtc.capture_frame(phone["session_id"], 1)  # inclusive existing TTL
        clock.now += .001
        with pytest.raises(HTTPException, match="mobile_stream_frame_expired"):
            rtc.capture_frame(phone["session_id"], 1)
        with pytest.raises(HTTPException, match="mobile_stream_generation_changed"):
            rtc.capture_frame(phone["session_id"], 2)
        track.stop()
        assert track.latest is None and source.stopped
        with pytest.raises(HTTPException, match="mobile_stream_frame_unavailable"):
            rtc.capture_frame(phone["session_id"], 1)
    asyncio.run(scenario())


def test_close_clears_latest_before_await_and_late_input_cannot_restore_it():
    async def scenario():
        async def state(*args):
            pass
        frame = VideoFrame(18, 30, "yuv420p")
        input_entered, input_release = asyncio.Event(), asyncio.Event()

        class PendingSource(Source):
            pending = False

            async def recv(self):
                if self.pending:
                    input_entered.set()
                    await input_release.wait()
                return self.frame

        source = PendingSource(frame)
        track = CountedVideoTrack(source, None, lambda: 10.)
        await track.recv()
        source.pending = True
        pending_input = asyncio.create_task(track.recv())
        await input_entered.wait()
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed_drain():
            entered.set()
            await release.wait()

        rtc = MobileRTC(None, state)
        rtc.streams["phone"] = Stream(1, track=track, forwarders={"test": SimpleNamespace(drain=delayed_drain)})
        task = asyncio.create_task(rtc.close("phone"))
        await entered.wait()
        assert track.latest is None
        input_release.set()
        from aiortc.mediastreams import MediaStreamError
        with pytest.raises(MediaStreamError):
            await pending_input  # close cancels the pending read and emits EOF
        assert track.latest is None
        with pytest.raises(HTTPException, match="mobile_stream_generation_changed"):
            rtc.capture_frame("phone", 1)
        release.set()
        await task
        assert not rtc.streams and source.stopped
    asyncio.run(scenario())


def test_unlocked_snapshot_lossless_same_image_identity_and_idempotent_after_stop(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    original_analyze = service.state.mobile_photo.analyze

    def analyze(*args):
        return {**original_analyze(*args), "frame_id": 777777, "seq": 777777}

    service.state.mobile_photo.analyze = analyze

    async def scenario():
        await service.start_stream(sid)
        source, track, calls, _ = frame_source(service, phone, clock)
        await track.recv()
        original = source.frame.to_ndarray(format="bgr24").copy()
        assert not service.snapshot(sid)["stream"]["can_capture"]
        first, second = await asyncio.gather(service.capture_stream(sid, request(phone)), service.capture_stream(sid, request(phone)))
        assert first == second and len(calls) == 1 and len(service.state.mobile_photo.calls) == 1
        assert first["capture_source"] == "desktop_stream" and first["session_id"] == sid
        assert first["frame_id"] == 777777 and first["stream_identity"]["frame_seq"] == 1
        assert first["video_size"] == first["original_size"] == [18, 30]
        assert first["analysis_limited"] is False
        path = service.assets.path(first["asset_id"])
        assert path.suffix == ".png"
        with Image.open(path) as image:
            assert np.array_equal(np.asarray(image)[:, :, ::-1], original)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == first["image_sha256"]
        assert service.assets.describe(first["asset_id"])["stream_identity"] == first["stream_identity"]
        assert service.view(sid)["capture_id"] == first["capture_id"]
        await service.stop_stream(sid)
        clock.now += 10
        assert await service.capture_stream(sid, request(phone)) == first
        for changed in (dict(generation=2), dict(context_id="other")):
            with pytest.raises(HTTPException, match="mobile_capture_request_conflict"):
                await service.capture_stream(sid, {**request(phone), **changed})
        assert len(calls) == len(service.state.mobile_photo.calls) == 1
        assert len(list(service.assets.root.glob("*/asset.json"))) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["missing", "expired", "generation", "stopped", "context", "desktop-context"])
def test_invalid_sources_rejected_before_asset_or_analysis(setup, reason):
    service, phone, clock = setup
    sid = phone["session_id"]

    async def scenario():
        await service.start_stream(sid)
        _, track, _, _ = frame_source(service, phone, clock)
        body = request(phone)
        if reason != "missing":
            await track.recv()
        if reason == "expired":
            clock.now += 1.501
        elif reason == "generation":
            body["generation"] = 2
        elif reason == "stopped":
            await service.stop_stream(sid)
        elif reason == "context":
            body["context_id"] = "old-context"
        elif reason == "desktop-context":
            service.publish_context(context(title="Different desktop state"))
        with pytest.raises(HTTPException) as failed:
            await service.capture_stream(sid, body)
        assert failed.value.status_code == 409
        assert not service.capture_requests and not service.state.mobile_photo.calls
        assert not list(service.assets.root.glob("*/asset.json"))
    asyncio.run(scenario())


def test_request_cancel_does_not_cancel_frozen_analysis_or_retry_capture_new_frame(setup):
    service, phone, clock = setup
    entered, release = threading.Event(), threading.Event()
    original = service.state.mobile_photo.analyze

    def analyze(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    service.state.mobile_photo.analyze = analyze

    async def scenario():
        await service.start_stream(phone["session_id"])
        _, track, calls, _ = frame_source(service, phone, clock)
        await track.recv()
        task = asyncio.create_task(service.capture_stream(phone["session_id"], request(phone)))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await track.recv()
        finally:
            release.set()
        packet = await service.capture_stream(phone["session_id"], request(phone))
        assert packet["stream_identity"]["frame_seq"] == 1
        assert len(calls) == len(service.state.mobile_photo.calls) == 1
    asyncio.run(scenario())


def test_analysis_failure_is_not_implicitly_reexecuted_on_same_request(setup):
    service, phone, clock = setup
    calls = []

    def analyze(*args):
        calls.append(args)
        raise HTTPException(503, "synthetic_analysis_failure")

    service.state.mobile_photo.analyze = analyze

    async def scenario():
        await service.start_stream(phone["session_id"])
        _, track, snapshots, _ = frame_source(service, phone, clock)
        await track.recv()
        for _ in range(2):
            with pytest.raises(HTTPException, match="synthetic_analysis_failure"):
                await service.capture_stream(phone["session_id"], request(phone))
            await track.recv()
        assert len(calls) == len(snapshots) == 1
        assert len(list(service.assets.root.glob("*/asset.json"))) == 1
        assert not service.captures
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["context", "restart", "manual-view", "disconnect"])
def test_late_analysis_saved_without_overwriting_new_context_or_selection(setup, change):
    service, phone, clock = setup
    entered, release = threading.Event(), threading.Event()
    original = service.state.mobile_photo.analyze
    bound = []
    service.state.assistant.bind_photo_reference = lambda *args: bound.append(args)

    def analyze(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    service.state.mobile_photo.analyze = analyze

    async def scenario():
        sid = phone["session_id"]
        await service.start_stream(sid)
        _, track, _, _ = frame_source(service, phone, clock)
        await track.recv()
        task = asyncio.create_task(service.capture_stream(sid, request(phone)))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            if change == "context":
                service.publish_context(context(title="Changed while analyzing"))
            elif change == "restart":
                await service.start_stream(sid)
            elif change == "disconnect":
                await service.disconnect(sid)
            else:
                service.view(sid, dict(capture_id=None, wire_id=None))
            expected = deepcopy(service.sessions.get(sid, {}).get("view"))
        finally:
            release.set()
        packet = await task
        assert service.get_capture(packet["capture_id"]) == packet
        assert service.sessions.get(sid, {}).get("view") == expected
        assert not bound
    asyncio.run(scenario())


@pytest.mark.parametrize("older_source,newer_source", [
    ("desktop_stream", "desktop_stream"), ("desktop_stream", "phone_frame"), ("phone_frame", "desktop_stream")])
def test_latest_submission_wins_when_two_capture_paths_complete_out_of_order(setup, tmp_path, older_source, newer_source):
    service, phone, clock = setup
    sid = phone["session_id"]
    lock(service, phone, clock)
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = service.state.mobile_photo.analyze
    bound = []
    service.state.assistant.bind_photo_reference = lambda cid, packet, context: bound.append(packet["capture_id"])

    def analyze(asset, context, session):
        if session["_capture_order"] == 1:
            entered.set()
            assert release.wait(3)
        return {**original(asset, context, session), "capture_id": "capture-"+str(session["_capture_order"])}

    service.state.mobile_photo.analyze = analyze

    async def scenario():
        _, track, _, _ = frame_source(service, phone, clock)
        await track.recv()
        first_task = asyncio.create_task(service.finalize_capture(sid, dict(ticket_id=ticket["ticket_id"],
            asset_id=asset["id"], request_id="old-phone", capture_source="phone_frame")) if older_source == "phone_frame"
            else service.capture_stream(sid, request(phone)))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            if newer_source == "phone_frame":
                newer = await service.finalize_capture(sid, dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"],
                    request_id="new-phone", capture_source="phone_frame"))
            else:
                await track.recv()
                newer = await service.capture_stream(sid, request(phone, request_id="new-desktop"))
            assert service.view(sid)["capture_id"] == newer["capture_id"] == "capture-2"
        finally:
            release.set()
        older = await first_task
        assert service.get_capture(older["capture_id"]) == older
        assert service.view(sid)["capture_id"] == newer["capture_id"]
        assert bound == [newer["capture_id"]]
        assert len(service.state.mobile_photo.calls) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("capture_source", [None, "camera_photo", "phone_frame"])
def test_existing_ticket_sources_keep_same_frame_contract_and_stream_running(setup, tmp_path, capture_source):
    service, phone, clock = setup
    lock(service, phone, clock)
    sid = phone["session_id"]
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    body = dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="phone-capture")
    if capture_source is not None:
        body["capture_source"] = capture_source
    packet = asyncio.run(service.finalize_capture(sid, body))
    assert packet["capture_source"] == (capture_source or "camera_photo")
    assert packet["image_sha256"] == asset["sha256"] and "stream_identity" not in packet
    assert service.snapshot(sid)["stream"]["active"] and not service.rtc.closed


def test_http_desktop_and_phone_capture_require_correct_identity_and_generation(app, setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    _, track, _, _ = frame_source(service, phone, clock)
    asyncio.run(track.recv())
    with TestClient(app, client=("192.168.1.99", 1000)) as remote:
        body = {**request(phone), "session_id": sid}
        assert remote.post("/api/mobile/stream-capture", json=body).status_code == 403
        assert remote.post("/api/mobile/stream-capture", json={**body, "session_id": "other"}, headers=auth(phone)).status_code == 403
        assert remote.post("/api/mobile/stream-capture", json={**body, "generation": True}, headers=auth(phone)).status_code == 422
        response = remote.post("/api/mobile/stream-capture", json=request(phone), headers=auth(phone))
        assert response.status_code == 200
        packet = response.json()
        image = remote.get(packet["image_url"], headers=auth(phone))
        assert image.headers["content-type"] == "image/png"
        with Image.open(BytesIO(image.content)) as decoded:
            assert list(decoded.size) == packet["video_size"]
    with TestClient(app, client=("127.0.0.1", 1000)) as desktop:
        assert desktop.post("/api/mobile/stream-capture", json=request(phone)).status_code == 401
        assert desktop.post("/api/mobile/stream-capture", json=body).json() == packet
    assert len(service.state.mobile_photo.calls) == 1


def test_gateway_forwards_capture_body_and_bearer_with_real_phone_identity(gateway):
    proxy, calls = gateway
    with TestClient(proxy, client=("192.168.1.99", 1000)) as client:
        payload = b'{"generation":1,"request_id":"photo","context_id":"context"}'
        response = client.post("/api/mobile/stream-capture", content=payload,
                               headers={"Authorization": "Bearer test-paired", "X-Forwarded-For": "127.0.0.1"})
        assert response.status_code == 201
        assert client.get("/api/mobile/stream-capture").status_code == 404
    upstream, content = calls[0]
    assert content == payload and upstream.headers["authorization"] == "Bearer test-paired"
    assert upstream.headers["x-forwarded-for"] == "192.168.1.99"
