"""Phone-owned WebRTC tracks. Never opens or replaces a desktop camera."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from fractions import Fraction
import logging
import math
import time
from dataclasses import dataclass, field

from fastapi import HTTPException
import numpy as np

try:
    import aiortc
    import av
    from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpSender, RTCRtpReceiver
    from aiortc.codecs.h264 import H264Encoder
    from aiortc.contrib.media import MediaRelay
    from aiortc.mediastreams import MediaStreamError
    from aiortc.jitterbuffer import JitterBuffer
    from aiortc.sdp import SessionDescription as SdpDescription
    from av import VideoFrame
except ImportError:  # Keep unrelated desktop capabilities available.
    RTCPeerConnection = None
    MediaStreamTrack = object
    H264Encoder = object
    JitterBuffer = object


logger = logging.getLogger(__name__)
BITRATE_PROFILES = {3000, 8000, 12000}
VIDEO_COLOR_FIELDS = ("color_range", "colorspace", "color_primaries", "color_trc")
PEER_CLOSE_TIMEOUT = 5.
PUBLISHER_JITTER_CAPACITY = 512


class MobilePublisherJitterBuffer(JitterBuffer):
    """Larger per-phone packet budget with unchanged aiortc frame assembly.

    Telemetry keeps eight timestamp/count pairs, never duplicate packet data.
    Arrival counts include duplicates/retransmissions that reach this buffer;
    they are not unique packets or the size of a complete encoded frame.
    """
    def __init__(self, capacity=PUBLISHER_JITTER_CAPACITY):
        super().__init__(capacity=capacity, prefetch=0, is_video=True)
        self.packet_arrivals = self.pli_flags = self.capacity_overflows = 0
        self.max_timestamp_packet_arrivals = 0  # lifetime high-water, with eight timestamps counted at once
        self._arrival_counts = OrderedDict()

    def add(self, packet):
        self.packet_arrivals += 1
        count = self._arrival_counts.get(packet.timestamp, 0)+1
        self._arrival_counts[packet.timestamp] = count
        self._arrival_counts.move_to_end(packet.timestamp)
        if len(self._arrival_counts) > 8:
            self._arrival_counts.popitem(last=False)
        self.max_timestamp_packet_arrivals = max(self.max_timestamp_packet_arrivals, count)
        pli, frame = super().add(packet)
        self.pli_flags += int(pli)
        return pli, frame

    def smart_remove(self, count):
        self.capacity_overflows += 1
        return super().smart_remove(count)

    def telemetry(self):
        return dict(packet_arrivals=self.packet_arrivals, pli_flags=self.pli_flags,
            capacity_overflows=self.capacity_overflows,
            max_timestamp_packet_arrivals=self.max_timestamp_packet_arrivals,
            timestamp_window=8, includes_duplicate_arrivals=True)


def configure_publisher_buffer(receiver):
    """Install only on a verified, unused aiortc 1.15 video receiver."""
    version = str(getattr(globals().get("aiortc"), "__version__", "unknown"))
    policy = dict(applied=False, requested_capacity_packets=PUBLISHER_JITTER_CAPACITY,
                  capacity_packets=None, reason=None, aiortc_version=version)
    if version.split(".")[:2] != ["1", "15"]:
        policy["reason"] = "unsupported_aiortc_version"
        return policy
    buffer = getattr(receiver, "_RTCRtpReceiver__jitter_buffer", None)
    policy["capacity_packets"] = _diagnostic_number(getattr(buffer, "_capacity", None))
    if (getattr(receiver, "_RTCRtpReceiver__kind", None) != "video"
            or getattr(receiver, "_RTCRtpReceiver__started", None) is not False
            or getattr(receiver, "_RTCRtpReceiver__decoder_thread", None) is not None):
        policy["reason"] = "receiver_active_or_unsupported_layout"
        return policy
    if isinstance(buffer, MobilePublisherJitterBuffer):
        policy.update(applied=True, reason="already_configured")
        return policy
    if (type(buffer) is not JitterBuffer or buffer._capacity != 128
            or buffer._is_video is not True or buffer._prefetch != 0
            or buffer._origin is not None or len(buffer._packets) != 128
            or any(packet is not None for packet in buffer._packets)):
        policy["reason"] = "buffer_active_or_unsupported_layout"
        return policy
    receiver._RTCRtpReceiver__jitter_buffer = MobilePublisherJitterBuffer()
    policy.update(applied=True, capacity_packets=PUBLISHER_JITTER_CAPACITY)
    return policy


def _diagnostic_number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _receiver_remb_diagnostics(pc):
    """Read the inspected aiortc layout only; never advance its rate estimator.

    RateCounter.rate(), for example, expires buckets and is NOT a readonly query.
    This reports the last estimator result, not an observed outgoing REMB packet.
    """
    version = str(getattr(globals().get("aiortc"), "__version__", "unknown"))
    result = dict(available=False, reason=None, aiortc_version=version,
                  source="receiver_estimator_last_result", receivers=[])
    if version.split(".")[:2] != ["1", "15"]:
        result["reason"] = "unsupported_aiortc_version"
        return result
    if pc is None:
        result["reason"] = "publisher_unavailable"
        return result
    try:
        for index, receiver in enumerate(pc.getReceivers()):
            if getattr(getattr(receiver, "track", None), "kind", None) != "video":
                continue
            estimator = getattr(receiver, "_RTCRtpReceiver__remote_bitrate_estimator", None)
            rate = getattr(estimator, "rate_control", None)
            initialized = getattr(rate, "current_bitrate_initialized", None)
            bitrate = _diagnostic_number(getattr(rate, "current_bitrate", None))
            if type(initialized) is not bool or bitrate is None or not hasattr(estimator, "last_update_ms"):
                result["reason"] = "unsupported_estimator_layout"
                continue
            updated = _diagnostic_number(estimator.last_update_ms)
            result["receivers"].append(dict(receiver_index=index, initialized=initialized,
                bitrate_bps=bitrate if initialized else None,
                # aiortc.clock.current_ms is milliseconds since the NTP epoch.
                last_update_ntp_ms=updated, last_update_at=(updated-2208988800000)/1000 if updated is not None else None))
        result["available"] = bool(result["receivers"])
        if not result["available"] and result["reason"] is None:
            result["reason"] = "video_receiver_unavailable"
    except Exception:
        result["reason"] = "unsupported_estimator_layout"
    return result


def _receiver_buffer_diagnostics(pc):
    """Current queue occupancy, not an eviction counter or historical maximum."""
    version = str(getattr(globals().get("aiortc"), "__version__", "unknown"))
    result = dict(available=False, reason=None, aiortc_version=version, receivers=[])
    if version.split(".")[:2] != ["1", "15"]:
        result["reason"] = "unsupported_aiortc_version"
        return result
    if pc is None:
        result["reason"] = "publisher_unavailable"
        return result
    try:
        for index, receiver in enumerate(pc.getReceivers()):
            if getattr(getattr(receiver, "track", None), "kind", None) != "video":
                continue
            buffer = getattr(receiver, "_RTCRtpReceiver__jitter_buffer", None)
            capacity, packets = getattr(buffer, "_capacity", None), getattr(buffer, "_packets", None)
            if type(capacity) is not int or not 0 < capacity <= 65536 or not isinstance(packets, (list, tuple)) or len(packets) != capacity:
                result["reason"] = "unsupported_buffer_layout"
                continue
            timestamps = {}
            for packet in packets:
                if packet is not None:
                    timestamp = packet.timestamp
                    timestamps[timestamp] = timestamps.get(timestamp, 0)+1
            queue = getattr(receiver, "_RTCRtpReceiver__decoder_queue", None)
            thread = getattr(receiver, "_RTCRtpReceiver__decoder_thread", None)
            value = dict(receiver_index=index, capacity_packets=capacity,
                pending_packets=sum(timestamps.values()), pending_timestamps=len(timestamps),
                largest_pending_timestamp_packets=max(timestamps.values(), default=0),
                decoder_queue_frames=queue.qsize() if queue is not None else None,
                decoder_thread_alive=thread.is_alive() if thread is not None else None)
            if isinstance(buffer, MobilePublisherJitterBuffer):
                value["telemetry"] = buffer.telemetry()
            result["receivers"].append(value)
        result["available"] = bool(result["receivers"])
        if not result["available"] and result["reason"] is None:
            result["reason"] = "video_receiver_unavailable"
    except Exception:
        result["reason"] = "unsupported_buffer_layout"
    return result


class MobileH264Encoder(H264Encoder):
    """One mobile viewer's encoder; aiortc packetization and RTCP stay intact.

    Configure a private PyAV context before the inherited encoder uses it. No
    aiortc module constants, factory, webcam encoder or shared context changes.
    REMB can still reduce the target to 500 kbps; the selected profile is a cap.
    """
    def __init__(self, bitrate_kbps=8000):
        super().__init__()
        self.maximum_bitrate = int(bitrate_kbps) * 1000
        self._target = self.maximum_bitrate
        self._encoding_target = None
        self._color = None
        self.measurement = (0, 0.)  # completed frames with payload, encode milliseconds

    @property
    def target_bitrate(self):
        return self._target if self._encoding_target is None else self._encoding_target

    @target_bitrate.setter
    def target_bitrate(self, value):
        self._target = max(500_000, min(int(value), self.maximum_bitrate))

    def encode(self, frame, force_keyframe=False):
        started = time.perf_counter()
        # RTCP arrives on the event loop while encoding runs in its executor.
        # Freeze this frame's target without blocking that loop on a thread lock.
        self._encoding_target = self._target
        try:
            target = self.target_bitrate
            color = tuple(getattr(frame, field) for field in VIDEO_COLOR_FIELDS)
            if (self.codec is None or self.codec.width != frame.width or self.codec.height != frame.height
                    or color != self._color
                    or abs(target - self.codec.bit_rate) / max(1, self.codec.bit_rate) > .1):
                self.buffer_data, self.buffer_pts = b"", None
                context = av.CodecContext.create("libx264", "w")
                context.width, context.height = frame.width, frame.height
                context.bit_rate, context.pix_fmt = target, "yuv420p"
                context.framerate, context.time_base = Fraction(30, 1), Fraction(1, 30)
                context.options = {"preset": "veryfast", "tune": "zerolatency", "level": "4.0"}
                context.profile = "Baseline"
                for field, value in zip(VIDEO_COLOR_FIELDS, color):
                    setattr(context, field, value)
                self.codec = context
                self._color = color
            result = super().encode(frame, force_keyframe)
            count, duration = self.measurement
            self.measurement = (count + bool(result[0]), duration + (time.perf_counter()-started)*1000)
            return result
        finally:
            self._encoding_target = None


def configure_viewer_encoder(sender, bitrate_kbps):
    """The isolated adapter for aiortc's missing per-sender bitrate API.

    These inspected releases choose an encoder lazily in this private slot.
    Unknown layouts retain aiortc defaults and visibly report the fallback.
    Never replace an encoder that is already running.
    """
    version = tuple(aiortc.__version__.split(".")[:2])
    slot = "_RTCRtpSender__encoder"
    if version not in {("1", "14"), ("1", "15")} or not hasattr(sender, slot):
        return None, "aiortc_encoder_adapter_unsupported"
    if getattr(sender, slot) is not None:
        return None, "aiortc_encoder_already_started"
    encoder = MobileH264Encoder(bitrate_kbps)
    setattr(sender, slot, encoder)
    return encoder, None


def prefer_h264(transceiver, role):
    """Set before the remote offer: aiortc fixes common codecs at that step."""
    provider = RTCRtpReceiver if role == "publisher" else RTCRtpSender
    codecs = provider.getCapabilities("video").codecs
    preferred = [c for c in codecs if c.mimeType.lower() == "video/h264"]
    transceiver.setCodecPreferences(preferred + [c for c in codecs if c not in preferred])


def negotiated_video_codec(sdp):
    """The answer's selected primary codec, not a claim based on capabilities."""
    for media in SdpDescription.parse(sdp).media:
        if media.kind == "video":
            for codec in media.rtp.codecs:
                if codec.mimeType.lower() not in {"video/rtx", "video/red", "video/ulpfec"}:
                    return codec.mimeType
    return None


def clone_viewer_frame(frame):
    """Copy only valid planar pixels; decoder and new frames may have different pitch.

    Reading plane memory avoids the shared frame's reformatter and two ndarray
    packing copies. Each viewer still owns new AV buffers; padding is not image
    data. Unusual formats/negative pitches retain the existing conversion path.
    """
    if frame.format.name in {"yuv420p", "yuvj420p"} and all(p.line_size > 0 for p in frame.planes):
        clone = VideoFrame(frame.width, frame.height, frame.format.name)
        for source, target in zip(frame.planes, clone.planes):
            source_pixels = np.ndarray((source.height, source.width), dtype=np.uint8,
                                       buffer=source, strides=(source.line_size, 1))
            target_pixels = np.ndarray((target.height, target.width), dtype=np.uint8,
                                       buffer=target, strides=(target.line_size, 1))
            np.copyto(target_pixels, source_pixels)
    else:
        clone = VideoFrame.from_ndarray(frame.to_ndarray(format="yuv420p"), format="yuv420p")
    clone.pts, clone.time_base = frame.pts, frame.time_base
    for field in VIDEO_COLOR_FIELDS:
        setattr(clone, field, getattr(frame, field))
    return clone


class ViewerVideoTrack(MediaStreamTrack):
    """Own each encoder's pixels and drain its current encode before PC close.

    MediaRelay shares VideoFrame objects. Native encoders mutate pict_type and
    reformatters, so a viewer must never encode the shared decoder frame. Copy
    on the event loop, where analysis conversion is also serialized; dispatching
    shared-frame conversions to independent threads would recreate that race.
    """
    kind = "video"

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.closing = self.started = False
        self.pending = None
        self.drained = asyncio.Event()
        self.measurement = (0, 0.)

    async def recv(self):
        self.started = True
        if self.closing:
            self.drained.set()
            raise MediaStreamError
        self.pending = asyncio.create_task(self.source.recv())
        try:
            frame = await self.pending
        except asyncio.CancelledError:
            if self.closing:
                self.drained.set()
                raise MediaStreamError from None
            raise
        except MediaStreamError:
            self.drained.set()
            raise
        finally:
            self.pending = None
        if self.closing:
            self.drained.set()
            raise MediaStreamError
        started = time.perf_counter()
        clone = clone_viewer_frame(frame)
        count, duration = self.measurement
        self.measurement = (count+1, duration+(time.perf_counter()-started)*1000)
        return clone

    def finish(self):
        self.closing = True
        if self.pending is not None:
            self.pending.cancel()
        if not self.started:
            self.drained.set()
        self.source.stop()

    async def drain(self):
        self.finish()
        # Reaching recv again proves the previous native encode returned. A
        # timed-out encoder keeps ownership: never start a competing generation.
        try:
            await asyncio.wait_for(self.drained.wait(), 5.)
        except TimeoutError:
            raise HTTPException(503, "mobile_viewer_encoder_still_closing") from None

    def stop(self):
        self.finish()
        self.drained.set()
        super().stop()


class CountedVideoTrack(MediaStreamTrack):
    """Count the continuously drained RTC track, before the 3 Hz analysis tap."""
    kind = "video"

    def __init__(self, source, callback, clock, wall=time.time, on_receive=None):
        super().__init__()
        self.source, self.callback, self.clock = source, callback, clock
        self.wall = wall
        self.on_receive = on_receive
        self.started, self.window_count, self.total = None, 0, 0
        self.receipts = OrderedDict()
        self.latest = None
        self.retain_latest = True
        self.pending = None
        self.metrics_task = None

    async def recv(self):
        if not self.retain_latest:
            raise MediaStreamError
        self.pending = asyncio.create_task(self.source.recv())
        try:
            frame = await self.pending
        except asyncio.CancelledError:
            if not self.retain_latest:
                raise MediaStreamError from None
            raise
        except MediaStreamError:
            self.clear_latest()
            raise
        except Exception:
            self.clear_latest()
            logger.exception("Mobile video source failed")
            raise MediaStreamError from None
        finally:
            self.pending = None
        if not self.retain_latest:
            raise MediaStreamError
        now = self.clock()
        self.receipts[id(frame)] = now
        if len(self.receipts) > 128:
            self.receipts.popitem(last=False)
        self.total += 1
        received_wall = self.wall()
        self.latest = (frame, self.total, now, received_wall)
        if self.on_receive is not None:
            try:
                self.on_receive(self.total, now, received_wall, (frame.width, frame.height))
            except Exception:
                logger.exception("Mobile receive notification failed; retaining video transport")
        if self.started is None:
            self.started, self.window_count = now, self.total
        elif now-self.started >= 1.:
            elapsed, count = now-self.started, self.total-self.window_count
            self.started, self.window_count = now, self.total
            if self.callback is not None and (self.metrics_task is None or self.metrics_task.done()):
                # Status/AI consumers must never backpressure MediaRelay. Keep
                # only one optional report in flight; skip intervening reports
                # instead of building a queue of obsolete FPS/session snapshots.
                self.metrics_task = asyncio.create_task(self._report_metrics(dict(
                    video_fps=round(count/elapsed, 2), received_frames=self.total,
                    video_size=[frame.width, frame.height],
                    video_color={field: getattr(frame, field, None) for field in VIDEO_COLOR_FIELDS})))
        if not self.retain_latest:
            raise MediaStreamError
        return frame

    async def _report_metrics(self, values):
        try:
            if self.retain_latest:
                await self.callback(values)
        except Exception:
            # Reporting failure cannot kill native reception or its viewers.
            logger.exception("Mobile video metrics failed; retaining video transport")

    def received_at(self, frame):
        # An unbuffered relay can retain its final frame after input stops.
        # Its original receipt time, not its later analysis time, governs TTL.
        return self.receipts.get(id(frame))

    def clear_latest(self):
        # A pending recv may return after close starts; it must not restore it.
        self.retain_latest = False
        self.latest = None
        if self.pending is not None:
            self.pending.cancel()
        if self.metrics_task is not None:
            self.metrics_task.cancel()

    def stop(self):
        self.clear_latest()
        self.source.stop()
        super().stop()


@dataclass
class Stream:
    generation: int
    publisher: object | None = None
    viewers: set = field(default_factory=set)
    track: object | None = None
    relay: object | None = None
    sampler: asyncio.Task | None = None
    subscriptions: list = field(default_factory=list)
    forwarders: dict = field(default_factory=dict)
    codecs: dict = field(default_factory=dict)
    closing: bool = False
    bitrate_kbps: int = 8000
    sender_metrics: dict = field(default_factory=dict)
    close_tasks: dict = field(default_factory=dict)
    publisher_buffer_policy: dict = field(default_factory=lambda: dict(applied=False, reason="publisher_not_negotiated"))


class MobileRTC:
    def __init__(self, on_frame, on_state, *, on_video_metrics=None, on_receive=None, clock=time.monotonic, wall=time.time, fps=3.):
        self.on_frame, self.on_state = on_frame, on_state
        self.on_video_metrics = on_video_metrics
        self.on_receive = on_receive
        self.clock, self.interval = clock, 1 / max(1., fps)
        self.wall = wall
        self.streams: dict[str, Stream] = {}
        self.generations: dict[str, int] = {}
        self.lifecycle_locks: dict[str, asyncio.Lock] = {}
        self.loop_monitor = None
        self.loop_health = dict(available=False, latest_lag_ms=None, max_lag_ms=0., stalls=0, sampled_at=None)
        self._last_loop_warning = float('-inf')

    def _record_loop_lag(self, delay):
        lag = round(max(0., delay) * 1000, 2)
        self.loop_health.update(available=True, latest_lag_ms=lag,
            max_lag_ms=max(lag, self.loop_health['max_lag_ms']), sampled_at=self.wall())
        if lag >= 100:
            self.loop_health['stalls'] += 1
            if self.clock() - self._last_loop_warning >= 5:
                self._last_loop_warning = self.clock()
                logger.warning('Mobile RTC event loop delayed %.1f ms; media and API scheduling share this loop', lag)

    async def _watch_loop(self):
        # Timing only, no images, model calls, bandwidth overrides or buffers.
        # Measure local scheduling separately from actual RTP jitter / loss so
        # a future slowdown can be attributed without assuming a network fault.
        loop = asyncio.get_running_loop()
        while self.streams:
            expected = loop.time() + .1
            await asyncio.sleep(.1)
            self._record_loop_lag(loop.time() - expected)

    @property
    def available(self):
        return RTCPeerConnection is not None

    async def start(self, sid, bitrate_kbps=8000):
        if not self.available:
            raise HTTPException(503, "mobile_rtc_dependency_unavailable")
        if bitrate_kbps not in BITRATE_PROFILES:
            raise HTTPException(422, "mobile_invalid_bitrate_profile")
        async with self.lifecycle_locks.setdefault(sid, asyncio.Lock()):
            await self._close(sid)
            generation = self.generations.get(sid, 0) + 1
            self.generations[sid] = generation
            self.streams[sid] = Stream(generation, relay=MediaRelay(), bitrate_kbps=bitrate_kbps)
            if self.loop_monitor is None or self.loop_monitor.done():
                self.loop_health = dict(available=False, latest_lag_ms=None, max_lag_ms=0., stalls=0, sampled_at=None)
                self.loop_monitor = asyncio.create_task(self._watch_loop())
            return generation

    def current(self, sid, generation):
        stream = self.streams.get(sid)
        if stream is None or stream.generation != generation or stream.closing:
            raise HTTPException(409, "mobile_stream_generation_changed")
        return stream

    async def diagnostics(self, sid, generation, max_age=1.5):
        """On-demand transport counters, independent of decoded-frame callbacks.

        This does not sample pixels, publish a session snapshot, refresh a lease,
        or change the estimator / encoder. All counts are cumulative; callers
        must compare matching generations and SSRCs to calculate interval rates.
        """
        stream = self.current(sid, generation)
        pc = stream.publisher
        report, error = {}, None
        if pc is not None:
            try:
                report = await asyncio.wait_for(pc.getStats(), timeout=1.)
            except Exception as exc:
                # Keep last decoded age and connection diagnostics available even
                # if this optional stats API is unsupported or temporarily fails.
                error = type(exc).__name__
        if self.current(sid, generation) is not stream or stream.publisher is not pc:
            raise HTTPException(409, "mobile_stream_generation_changed")
        codec = stream.codecs.get(pc)
        clock_rate = 90000 if codec in {"video/H264", "video/VP8"} else None
        inbound, transports = [], []
        for stat in report.values():
            if getattr(stat, "type", None) == "inbound-rtp" and getattr(stat, "kind", None) == "video":
                jitter = _diagnostic_number(getattr(stat, "jitter", None))
                inbound.append(dict(ssrc=getattr(stat, "ssrc", None),
                    packets_received=_diagnostic_number(getattr(stat, "packetsReceived", None)),
                    packets_lost=_diagnostic_number(getattr(stat, "packetsLost", None)),
                    jitter_raw=jitter, jitter_raw_unit="rtp_timestamp_units", clock_rate_hz=clock_rate,
                    jitter_ms=jitter*1000/clock_rate if jitter is not None and clock_rate else None))
            elif getattr(stat, "type", None) == "transport":
                transports.append(dict(id=getattr(stat, "id", None),
                    packets_received=_diagnostic_number(getattr(stat, "packetsReceived", None)),
                    packets_sent=_diagnostic_number(getattr(stat, "packetsSent", None)),
                    bytes_received=_diagnostic_number(getattr(stat, "bytesReceived", None)),
                    bytes_sent=_diagnostic_number(getattr(stat, "bytesSent", None)),
                    ice_role=getattr(stat, "iceRole", None), dtls_state=getattr(stat, "dtlsState", None)))
        track = stream.track
        latest = track.latest if track is not None else None
        now = self.clock()
        age = (now-latest[2])*1000 if latest is not None else None
        return dict(generation=generation, sampled_at=self.wall(), codec=codec,
            stats_available=pc is not None and error is None, stats_error=error,
            connection_state=getattr(pc, "connectionState", None),
            ice_connection_state=getattr(pc, "iceConnectionState", None),
            ice_gathering_state=getattr(pc, "iceGatheringState", None),
            signaling_state=getattr(pc, "signalingState", None),
            inbound_rtp=inbound, transports=transports,
            decoded=dict(seq=track.total if track is not None else 0,
                received_at=latest[3] if latest is not None else None,
                age_ms=age, fresh=age is not None and 0 <= age <= max_age*1000,
                video_size=[latest[0].width, latest[0].height] if latest is not None else None),
            remb_estimator=_receiver_remb_diagnostics(pc), receiver_buffers=_receiver_buffer_diagnostics(pc),
            publisher_buffer_policy=dict(stream.publisher_buffer_policy),
            event_loop=dict(self.loop_health))

    def capture_frame(self, sid, generation, max_age=1.5):
        """Freeze actual incoming pixels on the same loop as relay conversions.

        Only independent BGR leaves this method; shared AVFrame reformatters
        never run in an analysis/upload worker. This is not the 3 Hz preview.
        """
        stream = self.current(sid, generation)
        latest = stream.track.latest if stream.track is not None else None
        if latest is None:
            raise HTTPException(409, "mobile_stream_frame_unavailable")
        frame, seq, received, wall = latest
        if not 0 <= self.clock()-received <= max_age:
            raise HTTPException(409, "mobile_stream_frame_expired")
        pixels = frame.to_ndarray(format="bgr24").copy(order="C")
        return pixels, dict(session_id=sid, generation=generation, frame_seq=seq,
                            received_monotonic=received, received_at=wall)

    async def offer(self, sid, sdp, type, role, generation):
        # Negotiation owns peers too; close/restart must not miss an unfinished
        # offer or let it publish an answer for an already retired generation.
        async with self.lifecycle_locks.setdefault(sid, asyncio.Lock()):
            return await self._offer(sid, sdp, type, role, generation)

    async def _offer(self, sid, sdp, type, role, generation):
        stream = self.current(sid, generation)
        if type != "offer" or role not in {"publisher", "viewer"}:
            raise HTTPException(422, "mobile_invalid_offer")
        if role == "publisher" and stream.publisher is not None:
            raise HTTPException(409, "mobile_publisher_already_connected")
        if role == "viewer" and stream.track is None:
            raise HTTPException(409, "mobile_publisher_not_ready")
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        if role == "publisher":
            stream.publisher = pc
        else:
            stream.viewers.add(pc)

        @pc.on("connectionstatechange")
        async def changed():
            if self.streams.get(sid) is not stream or stream.closing:
                return
            if pc.connectionState in {"failed", "closed"}:
                if role == "publisher":
                    if stream.track is not None:
                        stream.track.clear_latest()
                    await self.on_state(sid, generation, "disconnected")
                elif pc.connectionState == "failed":
                    async with self.lifecycle_locks.setdefault(sid, asyncio.Lock()):
                        if self.streams.get(sid) is stream and not stream.closing:
                            await self._close_viewer(stream, pc)
                else:
                    stream.viewers.discard(pc)
                    stream.forwarders.pop(pc, None)
                    stream.codecs.pop(pc, None)
                    stream.sender_metrics.pop(pc, None)

        if role == "publisher":
            @pc.on("track")
            def track_received(track):
                if track.kind != "video" or self.streams.get(sid) is not stream or stream.track is not None:
                    track.stop()
                    return
                async def metrics(values):
                    if self.on_video_metrics is not None and self.streams.get(sid) is stream and not stream.closing:
                        values.update(publisher_codec=stream.codecs.get(stream.publisher),
                                      viewer_codecs=sorted({stream.codecs[v] for v in stream.viewers if v in stream.codecs}),
                                      codec_source="negotiated_sdp", server_metrics=await self._server_metrics(stream))
                        await self.on_video_metrics(sid, generation, values)
                def received(seq, stamp, wall, size):
                    if self.on_receive is not None and self.streams.get(sid) is stream and not stream.closing:
                        self.on_receive(sid, generation, seq, stamp, wall, size)
                stream.track = CountedVideoTrack(track, metrics, self.clock, self.wall, received)
                proxy = stream.relay.subscribe(stream.track, buffered=False)
                stream.subscriptions.append(proxy)
                stream.sampler = asyncio.create_task(self._sample(sid, stream, proxy))

                @track.on("ended")
                async def ended():
                    if self.streams.get(sid) is stream:
                        stream.track.clear_latest()
                        await self.on_state(sid, generation, "disconnected")
        try:
            transceiver = pc.addTransceiver("video", direction="recvonly" if role == "publisher" else "sendonly")
            prefer_h264(transceiver, role)
            if role == "publisher":
                stream.publisher_buffer_policy = configure_publisher_buffer(getattr(transceiver, "receiver", None))
                if not stream.publisher_buffer_policy["applied"]:
                    logger.warning("Mobile publisher jitter buffer fallback generation=%d reason=%s",
                                   generation, stream.publisher_buffer_policy["reason"])
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=type))
            if role == "viewer":
                proxy = stream.relay.subscribe(stream.track, buffered=False)
                stream.subscriptions.append(proxy)
                forwarder = ViewerVideoTrack(proxy)
                stream.forwarders[pc] = forwarder
                sender = pc.addTrack(forwarder)
            answer = await pc.createAnswer()
            codec = negotiated_video_codec(answer.sdp)
            if role == "viewer":
                encoder, fallback = configure_viewer_encoder(sender, stream.bitrate_kbps) if codec == "video/H264" else (None, None)
                stream.sender_metrics[pc] = dict(sender=sender, encoder=encoder, fallback=fallback, previous=None)
                if fallback:
                    logger.warning("Mobile viewer encoder fallback generation=%d reason=%s", generation, fallback)
            await pc.setLocalDescription(answer)
            if self.streams.get(sid) is not stream:
                raise HTTPException(409, "mobile_stream_generation_changed")
            codec = negotiated_video_codec(pc.localDescription.sdp)
            if codec:
                stream.codecs[pc] = codec
            logger.info("Mobile RTC negotiated role=%s generation=%d codec=%s", role, generation, codec)
            return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "generation": generation,
                    "codec": codec, "codec_source": "negotiated_sdp"}
        except BaseException:
            await self._close_viewer(stream, pc)
            if role == "publisher" and stream.publisher is pc:
                stream.publisher = None
            raise

    async def _sample(self, sid, stream, proxy):
        last = float("-inf")
        seq = 0
        live_seq = 0
        preview_task = None
        try:
            while self.streams.get(sid) is stream:
                video = await proxy.recv()
                now = self.clock()
                live = getattr(self, 'live_source', None)
                selected = live is not None and live.phone_source(sid, stream.generation) is not None
                frame = video.to_ndarray(format="bgr24") if selected else None
                received = stream.track.received_at(video)
                if selected and received is not None:
                    live_seq += 1
                    live.push(sid, stream.generation, frame, live_seq, received)
                if now - last < self.interval:
                    continue
                last, seq = now, seq + 1
                # Relay is unbuffered: analysis never accumulates old video frames.
                if frame is None:
                    frame = video.to_ndarray(format="bgr24")
                if received is not None:
                    if selected:
                        # Feedback may inspect shared results at 3 Hz; never
                        # block the full-rate source tap on inference/quality.
                        if preview_task is None or preview_task.done():
                            preview_task = asyncio.create_task(self.on_frame(sid, stream.generation, frame, seq, received))
                    else:
                        await self.on_frame(sid, stream.generation, frame, seq, received)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Mobile video sampling failed")
            if self.streams.get(sid) is stream:
                await self.on_state(sid, stream.generation, "disconnected")
        finally:
            if preview_task is not None:
                preview_task.cancel()
                await asyncio.gather(preview_task, return_exceptions=True)
            proxy.stop()

    async def _server_metrics(self, stream):
        transports = []
        for pc, item in list(stream.sender_metrics.items()):
            if pc not in stream.viewers:
                continue
            sender, encoder = item["sender"], item["encoder"]
            try:
                stats = await sender.getStats()
                sent_bytes = sum(s.bytesSent for s in stats.values() if s.type == "outbound-rtp" and s.kind == "video")
            except (AttributeError, ConnectionError):
                continue
            now = self.clock()
            encoded = encoder.measurement if encoder is not None else (0, 0.)
            cloned = stream.forwarders[pc].measurement if pc in stream.forwarders else (0, 0.)
            previous = item["previous"]
            row = dict(codec=stream.codecs.get(pc), target_bitrate_kbps=round(encoder.target_bitrate/1000) if encoder else None,
                       send_bitrate_kbps=None, encode_ms=None, clone_ms=None, send_fps=None, encode_fps=None,
                       encoder_policy="mobile_h264" if encoder else "aiortc_default", encoder_fallback_reason=item["fallback"])
            if previous is not None and now > previous[0]:
                elapsed = now-previous[0]
                row["send_bitrate_kbps"] = round(max(0, sent_bytes-previous[1])*8/elapsed/1000, 2)
                encode_count = encoded[0]-previous[2][0]
                clone_count = cloned[0]-previous[3][0]
                if encoder is not None:
                    row["encode_fps"] = round(max(0, encode_count)/elapsed, 2)
                if encode_count > 0:
                    row["encode_ms"] = round(max(0., encoded[1]-previous[2][1])/encode_count, 3)
                if clone_count > 0:
                    row["clone_ms"] = round(max(0., cloned[1]-previous[3][1])/clone_count, 3)
            item["previous"] = (now, sent_bytes, encoded, cloned)
            transports.append(row)
        return dict(updated_at=time.time(), latency_scope="server_processing_not_end_to_end", viewer_transports=transports)

    async def close(self, sid):
        async with self.lifecycle_locks.setdefault(sid, asyncio.Lock()):
            await self._close(sid)

    async def _close(self, sid):
        stream = self.streams.get(sid)
        if stream is None:
            return
        stream.closing = True
        if stream.track is not None:
            stream.track.clear_latest()
            reporting = stream.track.metrics_task
            if reporting is not None:
                await asyncio.gather(reporting, return_exceptions=True)
        if stream.sampler is not None:
            stream.sampler.cancel()
            await asyncio.gather(stream.sampler, return_exceptions=True)
        # Let each native viewer encode return before aiortc cancels RTP tasks.
        # Failed peers remain owned until close succeeds; a timeout blocks restart.
        await asyncio.gather(*(track.drain() for track in stream.forwarders.values()))
        await asyncio.gather(*(self._close_viewer(stream, pc) for pc in list(stream.viewers)))
        if stream.publisher is not None:
            await self._close_peer(stream, stream.publisher)
        # Include failed negotiations whose caller was cancelled during close.
        await asyncio.gather(*(self._close_peer(stream, pc) for pc in list(stream.close_tasks)))
        for proxy in stream.subscriptions:
            proxy.stop()
        if stream.track is not None:
            stream.track.stop()
        self.streams.pop(sid, None)
        if not self.streams and self.loop_monitor is not None:
            self.loop_monitor.cancel()
            await asyncio.gather(self.loop_monitor, return_exceptions=True)
            self.loop_monitor = None
        await self.on_state(sid, stream.generation, "stopped")

    async def _close_viewer(self, stream, pc):
        track = stream.forwarders.get(pc)
        if track is not None:
            await track.drain()
        await self._close_peer(stream, pc)
        stream.viewers.discard(pc)
        stream.forwarders.pop(pc, None)
        stream.codecs.pop(pc, None)
        stream.sender_metrics.pop(pc, None)

    async def _close_peer(self, stream, pc):
        # aiortc.close owns an internal completion Future. Cancelling it mid-ICE
        # close can strand every later call. Keep one task and let HTTP timeout
        # or cancellation stop only the wait; retries join the same cleanup.
        task = stream.close_tasks.get(pc)
        if task is None:
            task = asyncio.create_task(pc.close())
            stream.close_tasks[pc] = task
        try:
            await asyncio.wait_for(asyncio.shield(task), PEER_CLOSE_TIMEOUT)
        except TimeoutError:
            if task.done() and not task.cancelled():
                return task.result()
            raise HTTPException(503, "mobile_peer_still_closing") from None

    async def close_all(self):
        for sid in list(self.streams):
            await self.close(sid)
