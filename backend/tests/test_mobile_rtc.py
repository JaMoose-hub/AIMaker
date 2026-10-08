"""RTC negotiation/ownership test doubles never bind ports or start a camera."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.mobile_rtc as rtc


class DiagnosticPC:
    connectionState = "connected"
    iceConnectionState = "completed"
    iceGatheringState = "complete"
    signalingState = "stable"

    def __init__(self):
        self.calls = 0
        self.receivers = []
        self.report = {
            "video": SimpleNamespace(type="inbound-rtp", kind="video", ssrc=123,
                packetsReceived=2100, packetsLost=12, jitter=900),
            "audio": SimpleNamespace(type="inbound-rtp", kind="audio", ssrc=456,
                packetsReceived=999, packetsLost=1, jitter=48),
            "transport": SimpleNamespace(type="transport", id="dtls-one", packetsReceived=2200,
                packetsSent=500, bytesReceived=1700000, bytesSent=85000, iceRole="controlled", dtlsState="connected"),
        }

    async def getStats(self):
        self.calls += 1
        return self.report

    def getReceivers(self):
        return self.receivers


def diagnostic_service():
    now = [100.]

    async def unexpected(*_):
        raise AssertionError("diagnostics must not publish or process frames")

    service = rtc.MobileRTC(unexpected, unexpected, clock=lambda: now[0], wall=lambda: 1700000000+now[0])
    pc = DiagnosticPC()
    frame = SimpleNamespace(width=1080, height=1920)
    stream = rtc.Stream(3, publisher=pc, track=SimpleNamespace(total=30, latest=(frame, 30, 99.5, 1700000099.5)))
    stream.codecs[pc] = "video/H264"
    service.streams["phone"] = stream
    return service, stream, pc, now


def test_diagnostics_reads_rtp_during_decoded_stall_without_updating_stream():
    service, stream, pc, now = diagnostic_service()
    before = vars(stream).copy(), vars(stream.track).copy(), deepcopy(pc.report)

    async def scenario():
        first = await service.diagnostics("phone", 3)
        assert first["decoded"] == dict(seq=30, received_at=1700000099.5, age_ms=500., fresh=True, video_size=[1080, 1920])
        assert first["connection_state"] == "connected" and first["ice_connection_state"] == "completed"
        assert first["stats_available"] is True
        assert first["inbound_rtp"] == [dict(ssrc=123, packets_received=2100, packets_lost=12,
            jitter_raw=900, jitter_raw_unit="rtp_timestamp_units", clock_rate_hz=90000, jitter_ms=10.)]
        assert first["transports"][0]["bytes_received"] == 1700000
        now[0] += 8
        pc.report["video"].packetsReceived += 100
        # Duplicate/reordered packets can make the cumulative lost counter negative.
        pc.report["video"].packetsLost = -2
        second = await service.diagnostics("phone", 3)
        assert second["decoded"]["seq"] == 30 and second["decoded"]["age_ms"] == 8500
        assert second["decoded"]["fresh"] is False
        assert second["inbound_rtp"][0]["packets_received"] == 2200
        assert second["inbound_rtp"][0]["packets_lost"] == -2
        assert pc.calls == 2
        assert vars(stream) == before[0] and vars(stream.track) == before[1]
        assert pc.report["transport"] == before[2]["transport"]
        assert service.generations == {} and service.lifecycle_locks == {}
    asyncio.run(scenario())


def test_diagnostics_no_publisher_or_no_retained_frame_does_not_imply_live():
    service, stream, pc, _ = diagnostic_service()
    stream.track.latest = None
    stream.publisher = None
    result = asyncio.run(service.diagnostics("phone", 3))
    assert result["stats_available"] is False and result["inbound_rtp"] == []
    assert result["decoded"] == dict(seq=30, received_at=None, age_ms=None, fresh=False, video_size=None)
    assert result["connection_state"] is None and pc.calls == 0


def test_event_loop_delay_is_distinct_from_network_jitter_and_diagnostics_are_readonly():
    service, stream, pc, _ = diagnostic_service()
    assert service.loop_health['available'] is False
    service._record_loop_lag(.004)
    service._record_loop_lag(.24)
    before = deepcopy(service.loop_health)
    result = asyncio.run(service.diagnostics('phone', 3))
    assert result['event_loop'] == before == service.loop_health
    assert result['event_loop']['max_lag_ms'] == 240.
    assert result['event_loop']['stalls'] == 1
    assert result['inbound_rtp'][0]['jitter_ms'] == 10.
    assert stream.track.total == 30 and service.generations == {}


@pytest.mark.parametrize("replace", ["generation", "publisher", "closing"])
def test_diagnostics_rejects_late_stats_from_retired_owner(replace):
    service, stream, pc, _ = diagnostic_service()

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed():
            entered.set()
            await release.wait()
            return pc.report

        pc.getStats = delayed
        task = asyncio.create_task(service.diagnostics("phone", 3))
        await entered.wait()
        if replace == "generation":
            service.streams["phone"] = rtc.Stream(4)
        elif replace == "publisher":
            stream.publisher = DiagnosticPC()
        else:
            stream.closing = True
        release.set()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 409
    asyncio.run(scenario())


def test_diagnostics_wrong_generation_is_rejected_before_reading_stats():
    service, _, pc, _ = diagnostic_service()
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.diagnostics("phone", 2))
    assert error.value.status_code == 409 and pc.calls == 0


def test_diagnostics_stats_failure_retains_age_and_unknown_clock_is_not_guessed():
    service, stream, pc, _ = diagnostic_service()
    stream.codecs[pc] = "video/unknown"
    result = asyncio.run(service.diagnostics("phone", 3))
    assert result["inbound_rtp"][0]["jitter_raw"] == 900
    assert result["inbound_rtp"][0]["jitter_ms"] is None
    assert result["inbound_rtp"][0]["clock_rate_hz"] is None

    async def failed():
        raise RuntimeError("private details must not appear in response")

    pc.getStats = failed
    result = asyncio.run(service.diagnostics("phone", 3))
    assert result["stats_available"] is False and result["stats_error"] == "RuntimeError"
    assert result["decoded"]["seq"] == 30 and result["decoded"]["age_ms"] == 500


def test_remb_diagnostics_reads_real_estimator_fields_without_advancing_it(monkeypatch):
    from aiortc.rate import RemoteBitrateEstimator

    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    estimator = RemoteBitrateEstimator()
    receiver = SimpleNamespace(track=SimpleNamespace(kind="video"), _RTCRtpReceiver__remote_bitrate_estimator=estimator)
    pc = DiagnosticPC()
    pc.receivers = [receiver]
    before = deepcopy(vars(estimator.rate_control))
    initial = rtc._receiver_remb_diagnostics(pc)
    assert initial["available"] is True
    assert initial["receivers"][0]["initialized"] is False
    # The constructor's 30 Mbps value is NOT an initialized estimate.
    assert initial["receivers"][0]["bitrate_bps"] is None
    assert vars(estimator.rate_control) == before

    def cannot_call(*_):
        raise AssertionError("diagnostics must not advance the estimator")

    estimator.add = estimator.incoming_bitrate.rate = estimator.rate_control.update = cannot_call
    estimator.rate_control.current_bitrate_initialized = True
    estimator.rate_control.current_bitrate = 7800000
    estimator.last_update_ms = 2208988800000 + 1700000000123
    before = deepcopy(vars(estimator.rate_control))
    value = rtc._receiver_remb_diagnostics(pc)
    assert value["receivers"][0] == dict(receiver_index=0, initialized=True, bitrate_bps=7800000,
        last_update_ntp_ms=3908988800123, last_update_at=1700000000.123)
    assert vars(estimator.rate_control) == before and estimator.last_update_ms == 3908988800123


def test_remb_diagnostics_unsupported_version_and_layout_are_explicit(monkeypatch):
    pc = DiagnosticPC()
    monkeypatch.setattr(rtc.aiortc, "__version__", "2.0.0")
    result = rtc._receiver_remb_diagnostics(pc)
    assert result["available"] is False and result["reason"] == "unsupported_aiortc_version"
    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    pc.receivers = [SimpleNamespace(track=SimpleNamespace(kind="video"))]
    result = rtc._receiver_remb_diagnostics(pc)
    assert result["available"] is False and result["reason"] == "unsupported_estimator_layout"


def test_diagnostics_jitter_buffer_occupancy_is_readonly_and_explicitly_current(monkeypatch):
    from aiortc.jitterbuffer import JitterBuffer
    from queue import Queue

    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    buffer = JitterBuffer(capacity=128, is_video=True)
    for seq in range(120, 126):
        buffer.add(SimpleNamespace(sequence_number=seq, timestamp=90000))
    queue = Queue()
    queue.put("already queued encoded frame")
    pc = DiagnosticPC()
    receiver = SimpleNamespace(track=SimpleNamespace(kind="video"),
        _RTCRtpReceiver__jitter_buffer=buffer, _RTCRtpReceiver__decoder_queue=queue,
        _RTCRtpReceiver__decoder_thread=SimpleNamespace(is_alive=lambda: True))
    pc.receivers = [receiver]
    before = buffer._origin, tuple(buffer._packets)
    value = rtc._receiver_buffer_diagnostics(pc)
    assert value["available"] is True
    assert value["receivers"] == [dict(receiver_index=0, capacity_packets=128, pending_packets=6,
        pending_timestamps=1, largest_pending_timestamp_packets=6, decoder_queue_frames=1, decoder_thread_alive=True)]
    assert (buffer._origin, tuple(buffer._packets)) == before and queue.qsize() == 1
    monkeypatch.setattr(rtc.aiortc, "__version__", "2.0.0")
    value = rtc._receiver_buffer_diagnostics(pc)
    assert value["available"] is False and value["reason"] == "unsupported_aiortc_version"
    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    receiver._RTCRtpReceiver__jitter_buffer = object()
    value = rtc._receiver_buffer_diagnostics(pc)
    assert value["available"] is False and value["reason"] == "unsupported_buffer_layout"


def fu_a_packets(start=100, count=200, timestamp=90000):
    from aiortc.rtp import RtpPacket
    from aiortc.codecs.h264 import h264_depayload

    packets = []
    for index in range(count):
        packet = RtpPacket(payload_type=96, sequence_number=(start+index) % 65536, timestamp=timestamp, ssrc=7)
        packet.marker = int(index == count-1)
        packet.payload = bytes([0x7c, 0x05 | (0x80 if index == 0 else 0) | (0x40 if index == count-1 else 0)]) + bytes([index % 251+1])*1198
        packet._data = h264_depayload(packet.payload)
        packets.append(packet)
    return packets


@pytest.mark.parametrize("start", [100, 65500])
def test_phone_512_reconstructs_large_fu_a_nal_where_stock_128_evicts_start(start):
    from aiortc.jitterbuffer import JitterBuffer

    packets = fu_a_packets(start)
    expected = b"".join(packet._data for packet in packets)
    following = fu_a_packets(start+200, 1, 93000)[0]
    outputs = []
    for buffer in (JitterBuffer(128, is_video=True), rtc.MobilePublisherJitterBuffer()):
        flags, frames = 0, []
        for packet in packets+[following]:
            pli, frame = buffer.add(packet)
            flags += pli
            if frame is not None:
                frames.append(frame.data)
        outputs.append((flags, frames))
    assert len(expected) == 239605 and expected.startswith(b"\x00\x00\x00\x01\x65")
    assert outputs[0][0] == 1 and outputs[0][1] != [expected]
    assert not outputs[0][1][0].startswith(b"\x00\x00\x00\x01\x65")
    assert outputs[1] == (0, [expected])
    assert buffer.telemetry()["max_timestamp_packet_arrivals"] == 200
    assert buffer.telemetry()["capacity_overflows"] == 0


def test_phone_buffer_missing_packet_waits_for_retransmission_not_invented_image():
    buffer = rtc.MobilePublisherJitterBuffer()
    packets = fu_a_packets()
    for packet in packets[:50]+packets[51:]+fu_a_packets(300, 1, 93000):
        _, frame = buffer.add(packet)
        assert frame is None
    # Larger capacity cannot synthesize the missing slice; this explicit late
    # packet (as with successful RTX) is what allows complete reconstruction.
    _, frame = buffer.add(packets[50])
    assert frame.data == b"".join(packet._data for packet in packets)


def test_buffer_telemetry_is_bounded_and_does_not_change_stock_overflow_behavior():
    from aiortc.jitterbuffer import JitterBuffer

    stock, observed = JitterBuffer(128, is_video=True), rtc.MobilePublisherJitterBuffer(128)
    packets = fu_a_packets()+fu_a_packets(300, 1, 93000)
    packets += fu_a_packets(301, 1, 93000)  # another arrival for that timestamp
    for index in range(20):
        packets += fu_a_packets(302+index, 1, 96000+index*3000)
    for packet in packets:
        pli1, frame1 = stock.add(packet)
        pli2, frame2 = observed.add(packet)
        assert pli1 == pli2
        assert (None if frame1 is None else (frame1.timestamp, frame1.data)) == (None if frame2 is None else (frame2.timestamp, frame2.data))
    telemetry = observed.telemetry()
    assert telemetry["packet_arrivals"] == len(packets)
    assert telemetry["capacity_overflows"] == telemetry["pli_flags"] == 1
    assert telemetry["max_timestamp_packet_arrivals"] == 200
    assert len(observed._arrival_counts) == 8
    assert all(type(count) is int for count in observed._arrival_counts.values())


def unused_video_receiver():
    from aiortc.jitterbuffer import JitterBuffer

    return SimpleNamespace(_RTCRtpReceiver__kind="video", _RTCRtpReceiver__started=False,
        _RTCRtpReceiver__decoder_thread=None,
        _RTCRtpReceiver__jitter_buffer=JitterBuffer(128, is_video=True))


@pytest.mark.parametrize("condition", ["version", "started", "thread", "packet", "origin", "audio", "capacity"])
def test_publisher_buffer_guard_never_overwrites_active_or_unknown_receiver(monkeypatch, condition):
    from aiortc.jitterbuffer import JitterBuffer

    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    receiver = unused_video_receiver()
    if condition == "version":
        monkeypatch.setattr(rtc.aiortc, "__version__", "1.16.0")
    elif condition == "started":
        receiver._RTCRtpReceiver__started = True
    elif condition == "thread":
        receiver._RTCRtpReceiver__decoder_thread = object()
    elif condition == "packet":
        receiver._RTCRtpReceiver__jitter_buffer._packets[0] = object()
    elif condition == "origin":
        receiver._RTCRtpReceiver__jitter_buffer._origin = 0
    elif condition == "audio":
        receiver._RTCRtpReceiver__kind = "audio"
    elif condition == "capacity":
        receiver._RTCRtpReceiver__jitter_buffer = JitterBuffer(256, is_video=True)
    original = receiver._RTCRtpReceiver__jitter_buffer
    policy = rtc.configure_publisher_buffer(receiver)
    assert policy["applied"] is False and policy["reason"]
    assert receiver._RTCRtpReceiver__jitter_buffer is original


def test_only_publisher_buffer_is_installed_before_remote_description(fake_rtc, monkeypatch):
    service, _, _ = fake_rtc
    monkeypatch.setattr(rtc.aiortc, "__version__", "1.15.0")
    original_add, original_remote = PC.addTransceiver, PC.setRemoteDescription
    negotiation = []

    def add(self, kind, direction):
        transceiver = original_add(self, kind, direction)
        transceiver.receiver = unused_video_receiver()
        return transceiver

    async def remote(self, description):
        transceiver = self.transceivers[0]
        negotiation.append((transceiver.direction, transceiver.receiver._RTCRtpReceiver__jitter_buffer.capacity))
        await original_remote(self, description)

    monkeypatch.setattr(PC, "addTransceiver", add)
    monkeypatch.setattr(PC, "setRemoteDescription", remote)

    async def scenario():
        generation = await service.start("phone")
        await service.offer("phone", "sdp", "offer", "publisher", generation)
        await service.offer("phone", "sdp", "offer", "viewer", generation)
        assert negotiation == [("recvonly", 512), ("sendonly", 128)]
        stream = service.streams["phone"]
        assert stream.publisher_buffer_policy["applied"] is True
        receiver = stream.publisher.transceivers[0].receiver
        receiver.track = SimpleNamespace(kind="video")
        stream.publisher.getReceivers = lambda: [receiver]
        telemetry = rtc._receiver_buffer_diagnostics(stream.publisher)["receivers"][0]["telemetry"]
        assert telemetry["pli_flags"] == telemetry["packet_arrivals"] == 0
        buffer = receiver._RTCRtpReceiver__jitter_buffer
        assert rtc.configure_publisher_buffer(receiver)["reason"] == "already_configured"
        assert receiver._RTCRtpReceiver__jitter_buffer is buffer
        await service.close_all()
    asyncio.run(scenario())


class Track:
    kind = "video"

    def __init__(self):
        self.handlers, self.stopped = {}, False

    def on(self, name):
        def register(callback):
            self.handlers[name] = callback
            return callback
        return register

    async def recv(self):
        await asyncio.Event().wait()

    def stop(self):
        self.stopped = True


class Relay:
    def __init__(self):
        self.calls = []

    def subscribe(self, track, buffered):
        self.calls.append((track, buffered))
        return Track()


class PC:
    instances = []

    def __init__(self, configuration):
        self.handlers, self.tracks = {}, []
        self.transceivers = []
        self.configuration = configuration
        self.connectionState = "new"
        self.closed = False
        self.inbound = Track()
        self.__class__.instances.append(self)

    def on(self, name):
        def register(callback):
            self.handlers[name] = callback
            return callback
        return register

    async def setRemoteDescription(self, description):
        assert self.transceivers and self.transceivers[0].preferences
        self.remote = description
        if "track" in self.handlers:
            self.handlers["track"](self.inbound)

    def addTrack(self, track):
        self.tracks.append(track)

    def addTransceiver(self, kind, direction):
        transceiver = SimpleNamespace(kind=kind, direction=direction, preferences=[])
        transceiver.setCodecPreferences = lambda codecs: setattr(transceiver, "preferences", codecs)
        self.transceivers.append(transceiver)
        return transceiver

    async def createAnswer(self):
        return SimpleNamespace(sdp="fake-answer", type="answer")

    async def setLocalDescription(self, description):
        self.localDescription = description

    async def close(self):
        self.closed, self.connectionState = True, "closed"
        if "connectionstatechange" in self.handlers:
            await self.handlers["connectionstatechange"]()


@pytest.fixture
def fake_rtc(monkeypatch):
    monkeypatch.setattr(rtc, "RTCPeerConnection", PC)
    monkeypatch.setattr(rtc, "RTCConfiguration", lambda **kwargs: kwargs)
    monkeypatch.setattr(rtc, "RTCSessionDescription", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(rtc, "MediaRelay", Relay)
    PC.instances = []
    frames, states = [], []

    async def frame(*args):
        frames.append(args)

    async def state(*args):
        states.append(args)

    return rtc.MobileRTC(frame, state), frames, states


def test_publisher_viewer_relay_generation_and_close(fake_rtc):
    service, frames, states = fake_rtc

    async def scenario():
        generation = await service.start("phone")
        with pytest.raises(HTTPException):
            await service.offer("phone", "sdp", "offer", "viewer", generation)
        answer = await service.offer("phone", "sdp", "offer", "publisher", generation)
        assert answer == dict(sdp="fake-answer", type="answer", generation=1, codec=None, codec_source="negotiated_sdp")
        with pytest.raises(HTTPException):
            await service.offer("phone", "sdp", "offer", "publisher", generation)
        await service.offer("phone", "sdp", "offer", "viewer", generation)
        stream = service.streams["phone"]
        assert all(buffered is False for _, buffered in stream.relay.calls)
        assert len(stream.relay.calls) == 2
        assert PC.instances[0].configuration == {"iceServers": []}
        assert len(PC.instances[1].tracks) == 1
        next_generation = await service.start("phone")
        assert next_generation == 2 and all(pc.closed for pc in PC.instances)
        assert PC.instances[0].inbound.stopped
        with pytest.raises(HTTPException) as error:
            await service.offer("phone", "sdp", "offer", "viewer", 1)
        assert error.value.status_code == 409
        await service.close_all()
        assert not service.streams and not frames and service.loop_monitor is None
    asyncio.run(scenario())


def test_publisher_disconnect_revokes_state(fake_rtc):
    service, _, states = fake_rtc

    async def scenario():
        generation = await service.start("phone")
        await service.offer("phone", "sdp", "offer", "publisher", generation)
        publisher = PC.instances[0]
        publisher.connectionState = "failed"
        await publisher.handlers["connectionstatechange"]()
        assert states[-1] == ("phone", 1, "disconnected")
        await service.close_all()
    asyncio.run(scenario())


def test_counted_track_reports_receive_fps_not_analysis_sample_fps():
    now, metrics = [0.], []

    class Source(Track):
        async def recv(self):
            return SimpleNamespace(width=640, height=480)

    async def measured(value):
        metrics.append(value)

    async def scenario():
        source = Source()
        track = rtc.CountedVideoTrack(source, measured, lambda: now[0])
        for i in range(31):
            now[0] = i/30
            final = await track.recv()
        await track.metrics_task
        assert metrics == [dict(video_fps=30., received_frames=31, video_size=[640, 480],
                                video_color={field: None for field in rtc.VIDEO_COLOR_FIELDS})]
        now[0] = 5.
        assert track.received_at(final) == 1.  # Analysis later cannot refresh the source timestamp.
        track.stop()
        assert source.stopped
    asyncio.run(scenario())


def test_metrics_failure_does_not_kill_actual_relay_or_receive_notifications(caplog):
    from aiortc.contrib.media import MediaRelay
    from av import VideoFrame
    now, receipts = [0.], []

    class QueueSource(Track):
        def __init__(self):
            super().__init__()
            self.queue = asyncio.Queue()

        async def recv(self):
            value = await self.queue.get()
            if value is None:
                raise rtc.MediaStreamError
            return value

    async def broken_metrics(value):
        raise RuntimeError("synthetic diagnostic failure")

    async def scenario():
        source = QueueSource()
        counted = rtc.CountedVideoTrack(source, broken_metrics, lambda: now[0], lambda: 1000+now[0],
            lambda *args: receipts.append(args))
        proxy = MediaRelay().subscribe(counted, buffered=False)
        try:
            for seq in range(3):
                now[0] = float(seq)
                frame = VideoFrame(32, 48, "yuv420p")
                await source.queue.put(frame)
                assert await asyncio.wait_for(proxy.recv(), 1) is frame
            assert len(receipts) == 3 and counted.total == 3
            assert receipts[-1] == (3, 2., 1002., (32, 48))
            await source.queue.put(None)
            with pytest.raises(rtc.MediaStreamError):
                await asyncio.wait_for(proxy.recv(), 1)
            assert counted.latest is None
        finally:
            counted.stop()
            proxy.stop()
    asyncio.run(scenario())
    assert "Mobile video metrics failed; retaining video transport" in caplog.text


def test_slow_metrics_do_not_delay_receipt_or_accumulate_reporting_tasks():
    async def scenario():
        now, calls = [0.], []
        entered, release = asyncio.Event(), asyncio.Event()

        class Source(Track):
            async def recv(self):
                return SimpleNamespace(width=1920, height=1080)

        async def slow_metrics(value):
            calls.append(value)
            entered.set()
            await release.wait()

        track = rtc.CountedVideoTrack(Source(), slow_metrics, lambda: now[0])
        try:
            await track.recv()
            now[0] = 1.
            # Statistics are optional; native pixels must not wait for them.
            await asyncio.wait_for(track.recv(), .3)
            await asyncio.wait_for(entered.wait(), .3)
            reporting = track.metrics_task
            for index in range(2, 12):
                now[0] = float(index)
                await asyncio.wait_for(track.recv(), .3)
            assert track.total == 12 and len(calls) == 1
            assert track.metrics_task is reporting and not reporting.done()
            release.set()
            await reporting
            now[0] = 12.
            await track.recv()
            await track.metrics_task
            assert len(calls) == 2 and calls[-1]["received_frames"] == 13
        finally:
            release.set()
            track.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("late_frame", [False, True])
def test_counted_close_owns_pending_recv_and_never_publishes_late_frame(late_frame):
    async def scenario():
        entered, cancelled = asyncio.Event(), asyncio.Event()
        receipts = []

        class Source(Track):
            async def recv(self):
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    if late_frame:
                        return SimpleNamespace(width=32, height=48)
                    raise

        source = Source()
        track = rtc.CountedVideoTrack(source, None, lambda: 10., on_receive=lambda *args: receipts.append(args))
        task = asyncio.create_task(track.recv())
        await entered.wait()
        track.clear_latest()
        with pytest.raises(rtc.MediaStreamError):
            await asyncio.wait_for(task, 1)
        assert cancelled.is_set() and track.pending is None
        assert track.latest is None and track.total == 0 and not receipts
        track.stop()
        assert source.stopped
    asyncio.run(scenario())


def test_close_cancels_pending_metrics_and_does_not_return_a_frame_after_close():
    async def scenario():
        now = [0.]
        entered, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Source(Track):
            async def recv(self):
                return SimpleNamespace(width=32, height=48)

        async def metrics(value):
            entered.set()
            try:
                await release.wait()
            finally:
                cancelled.set()

        track = rtc.CountedVideoTrack(Source(), metrics, lambda: now[0])
        await track.recv()
        now[0] = 1.
        frame = await asyncio.wait_for(track.recv(), .3)
        await asyncio.wait_for(entered.wait(), .3)
        assert frame.width == 32  # Delivered before close despite pending metrics.
        track.clear_latest()
        await asyncio.gather(track.metrics_task, return_exceptions=True)
        with pytest.raises(rtc.MediaStreamError):
            await track.recv()
        assert cancelled.is_set() and track.latest is None
        track.stop()
    asyncio.run(scenario())


@pytest.mark.parametrize("vp8_only", [False, True], ids=["prefer-h264", "vp8-only-peer-fallback"])
def test_actual_local_aiortc_synthetic_publisher_viewer_and_sampler(vp8_only):
    """Two local peers, synthetic pixels only; no camera/STUN/cloud/model calls."""
    from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, VideoStreamTrack, RTCRtpSender
    from av import VideoFrame
    import numpy as np

    class SyntheticVideo(VideoStreamTrack):
        async def recv(self):
            pts, time_base = await self.next_timestamp()
            frame = VideoFrame.from_ndarray(np.full((240, 320, 3), (20, 80, 140), dtype=np.uint8), format="bgr24")
            frame.pts, frame.time_base = pts, time_base
            return frame

    async def scenario():
        frames, metrics = [], []

        async def sample(sid, generation, frame, seq, received):
            frames.append((frame.shape, seq))

        async def state(*args):
            pass

        async def measured(sid, generation, value):
            metrics.append(value)

        service = rtc.MobileRTC(sample, state, on_video_metrics=measured)
        publisher = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        viewer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        source = SyntheticVideo()
        received_track = asyncio.get_running_loop().create_future()

        @viewer.on("track")
        def track(value):
            if not received_track.done():
                received_track.set_result(value)

        try:
            generation = await service.start("local-synthetic")
            publisher.addTrack(source)
            if vp8_only:
                publisher.getTransceivers()[0].setCodecPreferences([c for c in RTCRtpSender.getCapabilities("video").codecs if c.mimeType.lower() in {"video/vp8", "video/rtx"}])
            await publisher.setLocalDescription(await publisher.createOffer())
            answer = await service.offer("local-synthetic", publisher.localDescription.sdp, "offer", "publisher", generation)
            expected_codec = "video/VP8" if vp8_only else "video/H264"
            assert answer["codec"] == expected_codec
            await publisher.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
            viewer_transceiver = viewer.addTransceiver("video", direction="recvonly")
            if vp8_only:
                viewer_transceiver.setCodecPreferences([c for c in RTCRtpSender.getCapabilities("video").codecs if c.mimeType.lower() in {"video/vp8", "video/rtx"}])
            await viewer.setLocalDescription(await viewer.createOffer())
            answer = await service.offer("local-synthetic", viewer.localDescription.sdp, "offer", "viewer", generation)
            assert answer["codec"] == expected_codec
            await viewer.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
            remote = await asyncio.wait_for(received_track, 5)
            frame = await asyncio.wait_for(remote.recv(), 5)
            assert (frame.width, frame.height) == (320, 240)
            deadline = asyncio.get_running_loop().time()+3
            while not metrics and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(.05)
            assert metrics and metrics[-1]["video_fps"] > 15
            assert metrics[-1]["publisher_codec"] == expected_codec
            assert metrics[-1]["viewer_codecs"] == [expected_codec]
            transports = metrics[-1]["server_metrics"]["viewer_transports"]
            assert len(transports) == 1
            assert transports[0]["encoder_policy"] == ("aiortc_default" if vp8_only else "mobile_h264")
            assert transports[0]["send_fps"] is None  # Encoding is not proof of network delivery.
            if not vp8_only:
                assert 500 <= transports[0]["target_bitrate_kbps"] <= 8000
            assert frames and all(shape == (240, 320, 3) for shape, _ in frames)
            assert metrics[-1]["received_frames"] > len(frames)*3
            assert all(seq == index+1 for index, (_, seq) in enumerate(frames))
        finally:
            await service.close_all()
            await asyncio.gather(publisher.close(), viewer.close())
            source.stop()

    asyncio.run(asyncio.wait_for(scenario(), 15))


def test_h264_preferences_keep_fallback_and_repair_codecs(monkeypatch):
    codecs = [SimpleNamespace(mimeType=name) for name in ["video/VP8", "video/rtx", "video/H264", "video/H264"]]
    provider = SimpleNamespace(getCapabilities=lambda kind: SimpleNamespace(codecs=codecs))
    monkeypatch.setattr(rtc, "RTCRtpSender", provider)
    monkeypatch.setattr(rtc, "RTCRtpReceiver", provider)
    for role in ["publisher", "viewer"]:
        result = []
        rtc.prefer_h264(SimpleNamespace(setCodecPreferences=result.extend), role)
        assert result == codecs[2:] + codecs[:2]


def test_viewers_own_pixels_and_metadata_without_mutating_shared_frame():
    from av import VideoFrame
    from fractions import Fraction
    import numpy as np

    shared = VideoFrame.from_ndarray(np.full((48, 64, 3), 100, dtype=np.uint8), format="bgr24")
    shared.pts, shared.time_base = 123, Fraction(1, 90000)
    shared.color_range, shared.colorspace = 2, 1
    shared.color_primaries, shared.color_trc = 1, 1

    class Source(Track):
        async def recv(self):
            return shared

    async def scenario():
        first, second = rtc.ViewerVideoTrack(Source()), rtc.ViewerVideoTrack(Source())
        a, b = await asyncio.gather(first.recv(), second.recv())
        before = b.to_ndarray().copy()
        assert a is not b and a is not shared
        assert a.format.name == b.format.name == "yuv420p"
        assert (a.color_range, a.colorspace, a.color_primaries, a.color_trc) == (2, 1, 1, 1)
        assert (b.color_range, b.colorspace, b.color_primaries, b.color_trc) == (2, 1, 1, 1)
        assert (a.width, a.height, a.pts, a.time_base) == (64, 48, 123, Fraction(1, 90000))
        assert all(x.buffer_ptr != y.buffer_ptr for x, y in zip(a.planes, b.planes))
        a.planes[0].update(bytes([0]) * a.planes[0].buffer_size)
        assert np.array_equal(b.to_ndarray(), before)
        assert np.all(shared.to_ndarray(format="bgr24") == 100)
        first.stop()
        second.stop()
    asyncio.run(scenario())


def test_drain_waits_for_current_encode_and_blocks_further_frames():
    from av import VideoFrame
    from fractions import Fraction

    class Source(Track):
        async def recv(self):
            frame = VideoFrame(64, 48, "yuv420p")
            frame.pts, frame.time_base = 0, Fraction(1, 90000)
            return frame

    async def scenario():
        track = rtc.ViewerVideoTrack(Source())
        encoding, release = asyncio.Event(), asyncio.Event()

        async def sender():
            await track.recv()
            encoding.set()
            await release.wait()  # Models native encode: cancellation must not skip it.
            with pytest.raises(rtc.MediaStreamError):
                await track.recv()

        sending = asyncio.create_task(sender())
        await encoding.wait()
        draining = asyncio.create_task(track.drain())
        await asyncio.sleep(0)
        assert not draining.done()
        release.set()
        await asyncio.gather(sending, draining)
        assert track.source.stopped and track.drained.is_set()
    asyncio.run(scenario())


def test_drain_unblocks_source_wait_without_late_frame():
    async def scenario():
        track = rtc.ViewerVideoTrack(Track())
        receiving = asyncio.create_task(track.recv())
        await asyncio.sleep(0)
        await track.drain()
        with pytest.raises(rtc.MediaStreamError):
            await receiving
        assert track.source.stopped
    asyncio.run(scenario())


def test_restart_waits_for_offer_and_closes_owned_failed_viewer(fake_rtc, monkeypatch):
    service, _, _ = fake_rtc

    async def scenario():
        generation = await service.start("phone")
        await service.offer("phone", "sdp", "offer", "publisher", generation)
        entered, release = asyncio.Event(), asyncio.Event()
        original = PC.setLocalDescription

        async def paused(self, description):
            entered.set()
            await release.wait()
            await original(self, description)

        monkeypatch.setattr(PC, "setLocalDescription", paused)
        offering = asyncio.create_task(service.offer("phone", "sdp", "offer", "viewer", generation))
        await entered.wait()
        restarting = asyncio.create_task(service.start("phone"))
        await asyncio.sleep(0)
        assert not restarting.done()
        release.set()
        await offering
        assert await restarting == 2
        assert all(pc.closed for pc in PC.instances)
        monkeypatch.setattr(PC, "setLocalDescription", original)
        await service.offer("phone", "sdp", "offer", "publisher", 2)
        await service.offer("phone", "sdp", "offer", "viewer", 2)
        failed = PC.instances[-1]
        failed.connectionState = "failed"
        await failed.handlers["connectionstatechange"]()
        assert failed.closed and failed not in service.streams["phone"].viewers
        assert failed not in service.streams["phone"].forwarders
        await service.close_all()
    asyncio.run(scenario())


def test_failed_encoder_drain_retains_ownership_and_prevents_new_generation(fake_rtc):
    service, _, _ = fake_rtc

    async def scenario():
        await service.start("phone")
        stream = service.streams["phone"]

        async def undrained():
            raise HTTPException(503, "mobile_viewer_encoder_still_closing")

        stream.forwarders[object()] = SimpleNamespace(drain=undrained)
        with pytest.raises(HTTPException) as error:
            await service.start("phone")
        assert error.value.status_code == 503
        assert service.streams["phone"] is stream and stream.closing
        assert service.generations["phone"] == 1
        with pytest.raises(HTTPException):
            service.current("phone", 1)
        stream.forwarders.clear()
        assert await service.start("phone") == 2
        await service.close_all()
    asyncio.run(scenario())


def test_mobile_encoder_caps_remb_per_instance_and_preserves_stock_defaults():
    from aiortc.codecs import h264

    standard = h264.H264Encoder()
    low, normal, high = (rtc.MobileH264Encoder(value) for value in (3000, 8000, 12000))
    assert (low.target_bitrate, normal.target_bitrate, high.target_bitrate) == (3_000_000, 8_000_000, 12_000_000)
    for encoder, cap in [(low, 3_000_000), (normal, 8_000_000), (high, 12_000_000)]:
        encoder.target_bitrate = 25_000_000
        assert encoder.target_bitrate == cap
        encoder.target_bitrate = 700_000
        assert encoder.target_bitrate == 700_000
        encoder.target_bitrate = 100_000
        assert encoder.target_bitrate == 500_000
    assert h264.DEFAULT_BITRATE == standard.target_bitrate == 1_000_000
    standard.target_bitrate = 12_000_000
    assert standard.target_bitrate == h264.MAX_BITRATE == 3_000_000


def test_mobile_encoder_context_keeps_policy_across_bitrate_and_size_changes():
    from av import VideoFrame
    from fractions import Fraction
    from aiortc.codecs.h264 import H264Decoder, h264_depayload
    from aiortc.jitterbuffer import JitterFrame

    encoder = rtc.MobileH264Encoder(12000)
    contexts = []
    for index, (width, height, bitrate) in enumerate([(64, 48, 8_000_000), (64, 48, 900_000), (48, 64, 12_000_000)]):
        encoder.target_bitrate = bitrate
        frame = VideoFrame(width, height, "yuv420p")
        for plane in frame.planes:
            plane.update(bytes([128]) * plane.buffer_size)
        frame.pts, frame.time_base = index*3000, Fraction(1, 90000)
        frame.color_range, frame.colorspace = 2, 1
        frame.color_primaries, frame.color_trc = 1, 1
        payloads, timestamp = encoder.encode(frame, True)
        assert payloads and encoder.codec.bit_rate == bitrate
        decoded = H264Decoder().decode(JitterFrame(b"".join(h264_depayload(p) for p in payloads), timestamp))
        assert decoded and (decoded[0].width, decoded[0].height) == (width, height)
        assert (decoded[0].color_range, decoded[0].colorspace, decoded[0].color_primaries, decoded[0].color_trc) == (2, 1, 1, 1)
        contexts.append(encoder.codec)
    assert contexts[0] is not contexts[1] and contexts[1] is not contexts[2]
    assert encoder.measurement[0] == 3 and encoder.measurement[1] > 0


def test_encoder_adapter_only_changes_selected_sender_and_reports_unknown_layout(monkeypatch):
    from aiortc import RTCPeerConnection, RTCConfiguration

    async def scenario():
        first = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        other = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        try:
            selected = first.addTransceiver("video", direction="sendonly").sender
            untouched = other.addTransceiver("video", direction="sendonly").sender
            encoder, error = rtc.configure_viewer_encoder(selected, 12000)
            assert isinstance(encoder, rtc.MobileH264Encoder) and error is None
            assert getattr(selected, "_RTCRtpSender__encoder") is encoder
            assert getattr(untouched, "_RTCRtpSender__encoder") is None
            assert rtc.configure_viewer_encoder(selected, 8000) == (None, "aiortc_encoder_already_started")
            monkeypatch.setattr(rtc.aiortc, "__version__", "9.0.0")
            assert rtc.configure_viewer_encoder(untouched, 8000) == (None, "aiortc_encoder_adapter_unsupported")
            assert getattr(untouched, "_RTCRtpSender__encoder") is None
        finally:
            await asyncio.gather(first.close(), other.close())
    asyncio.run(scenario())


def test_server_metrics_report_actual_bytes_and_distinct_encode_clone_cost():
    now = [10.]
    counter = [1000]

    class Sender:
        async def getStats(self):
            return {"video": SimpleNamespace(type="outbound-rtp", kind="video", bytesSent=counter[0])}

    async def scenario():
        service = rtc.MobileRTC(None, None, clock=lambda: now[0])
        peer = object()
        encoder = rtc.MobileH264Encoder()
        forwarder = SimpleNamespace(measurement=(10, 10.))
        encoder.measurement = (10, 80.)
        stream = rtc.Stream(1, viewers={peer}, codecs={peer: "video/H264"}, forwarders={peer: forwarder},
                            sender_metrics={peer: dict(sender=Sender(), encoder=encoder, fallback=None, previous=None)})
        first = (await service._server_metrics(stream))["viewer_transports"][0]
        assert first["send_bitrate_kbps"] is first["encode_ms"] is None
        now[0] += 2
        counter[0] += 2_000_000
        encoder.measurement = (70, 680.)
        forwarder.measurement = (70, 70.)
        result = await service._server_metrics(stream)
        row = result["viewer_transports"][0]
        assert row["send_bitrate_kbps"] == 8000
        assert row["encode_fps"] == 30 and row["send_fps"] is None
        assert row["encode_ms"] == 10 and row["clone_ms"] == 1
        assert result["latency_scope"] == "server_processing_not_end_to_end"
        stream.viewers.clear()
        assert (await service._server_metrics(stream))["viewer_transports"] == []
    asyncio.run(scenario())


def test_cancelled_close_preserves_peer_task_until_restart_can_finish(fake_rtc, monkeypatch):
    service, _, _ = fake_rtc

    async def scenario():
        await service.start("phone")
        await service.offer("phone", "sdp", "offer", "publisher", 1)
        stream = service.streams["phone"]
        pc = stream.publisher
        entered, release = asyncio.Event(), asyncio.Event()
        original = pc.close
        calls = []

        async def blocked_close():
            calls.append(1)
            entered.set()
            await release.wait()
            await original()

        monkeypatch.setattr(pc, "close", blocked_close)
        request = asyncio.create_task(service.close("phone"))
        await entered.wait()
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request
        cleanup = stream.close_tasks[pc]
        assert not cleanup.done() and not cleanup.cancelled()
        assert service.streams["phone"] is stream and stream.closing
        restarting = asyncio.create_task(service.start("phone"))
        await asyncio.sleep(0)
        assert not restarting.done()
        release.set()
        assert await restarting == 2
        assert cleanup.done() and pc.closed and calls == [1]
        await service.close_all()
    asyncio.run(scenario())


def test_peer_close_timeout_is_bounded_and_retry_joins_same_cleanup(fake_rtc, monkeypatch):
    service, _, _ = fake_rtc
    monkeypatch.setattr(rtc, "PEER_CLOSE_TIMEOUT", .01)

    async def scenario():
        await service.start("phone")
        await service.offer("phone", "sdp", "offer", "publisher", 1)
        await service.offer("phone", "sdp", "offer", "viewer", 1)
        stream = service.streams["phone"]
        viewer = next(iter(stream.viewers))
        release = asyncio.Event()
        original = viewer.close
        calls = []

        async def blocked_close():
            calls.append(1)
            await release.wait()
            await original()

        monkeypatch.setattr(viewer, "close", blocked_close)
        for operation in [service.close, service.start]:
            with pytest.raises(HTTPException) as error:
                await operation("phone")
            assert error.value.status_code == 503 and error.value.detail == "mobile_peer_still_closing"
        cleanup = stream.close_tasks[viewer]
        assert not cleanup.done() and calls == [1]
        assert stream.closing and service.generations["phone"] == 1
        release.set()
        assert await service.start("phone") == 2
        assert cleanup.done() and viewer.closed and calls == [1]
        await service.close_all()
    asyncio.run(scenario())


@pytest.mark.parametrize("format", ["yuv420p", "yuvj420p"])
@pytest.mark.parametrize("size", [(130, 98), (131, 99), (1080, 1920)])
def test_direct_clone_copies_valid_planar_pixels_with_padding_and_odd_chroma(format, size):
    from av import VideoFrame
    from fractions import Fraction
    import numpy as np

    def pixels(plane):
        return np.ndarray((plane.height, plane.width), dtype=np.uint8, buffer=plane, strides=(plane.line_size, 1))

    frame = VideoFrame(*size, format)
    frame.pts, frame.time_base = 777, Fraction(1, 90000)
    frame.color_range, frame.colorspace = 2, 1
    frame.color_primaries, frame.color_trc = 1, 1
    for i, plane in enumerate(frame.planes):
        plane.update(bytes([255]) * plane.buffer_size)  # Padding must not shift into valid pixels.
        y, x = np.indices((plane.height, plane.width))
        pixels(plane)[:] = (3*x+7*y+41*i) % 200

    class WithoutConverter:
        def __getattr__(self, name):
            if name == "to_ndarray":
                raise AssertionError("planar clone must not enter the shared reformatter")
            return getattr(frame, name)

    first, second = rtc.clone_viewer_frame(WithoutConverter()), rtc.clone_viewer_frame(WithoutConverter())
    assert first.format.name == format and (first.width, first.height) == size
    assert (first.pts, first.time_base) == (frame.pts, frame.time_base)
    assert tuple(getattr(first, field) for field in rtc.VIDEO_COLOR_FIELDS) == (2, 1, 1, 1)
    for source, a, b in zip(frame.planes, first.planes, second.planes):
        assert np.array_equal(pixels(source), pixels(a)) and np.array_equal(pixels(a), pixels(b))
        assert len({source.buffer_ptr, a.buffer_ptr, b.buffer_ptr}) == 3
        original = pixels(source).copy()
        pixels(a)[:] = 255
        assert np.array_equal(pixels(source), original) and np.array_equal(pixels(b), original)


def test_direct_clone_matches_native_decoded_planes_with_different_stride():
    from av import VideoFrame
    from fractions import Fraction
    from aiortc.codecs.h264 import H264Decoder, h264_depayload
    from aiortc.jitterbuffer import JitterFrame
    import numpy as np

    frame = VideoFrame(130, 98, "yuv420p")
    frame.pts, frame.time_base = 0, Fraction(1, 90000)
    for index, plane in enumerate(frame.planes):
        view = np.ndarray((plane.height, plane.width), dtype=np.uint8, buffer=plane, strides=(plane.line_size, 1))
        y, x = np.indices(view.shape)
        view[:] = (x*5+y*3+index*31) % 256
    payloads, timestamp = rtc.MobileH264Encoder().encode(frame, True)
    decoded = H264Decoder().decode(JitterFrame(b"".join(h264_depayload(p) for p in payloads), timestamp))[0]
    actual = rtc.clone_viewer_frame(decoded)
    assert any(a.line_size != b.line_size for a, b in zip(decoded.planes, actual.planes))
    for source, target in zip(decoded.planes, actual.planes):
        def valid(plane):
            return np.ndarray((plane.height, plane.width), dtype=np.uint8, buffer=plane, strides=(plane.line_size, 1))
        assert np.array_equal(valid(source), valid(target))
    assert np.array_equal(decoded.to_ndarray(), actual.to_ndarray())
