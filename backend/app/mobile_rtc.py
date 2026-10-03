"""Phone-owned WebRTC tracks. Never opens or replaces a desktop camera."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from fractions import Fraction
import logging
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
    from aiortc.sdp import SessionDescription as SdpDescription
    from av import VideoFrame
except ImportError:  # Keep unrelated desktop capabilities available.
    RTCPeerConnection = None
    MediaStreamTrack = object
    H264Encoder = object


logger = logging.getLogger(__name__)
BITRATE_PROFILES = {3000, 8000, 12000}
VIDEO_COLOR_FIELDS = ("color_range", "colorspace", "color_primaries", "color_trc")
PEER_CLOSE_TIMEOUT = 5.


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
            if self.callback is not None:
                try:
                    await self.callback(dict(video_fps=round(count/elapsed, 2),
                        received_frames=self.total, video_size=[frame.width, frame.height],
                        video_color={field: getattr(frame, field, None) for field in VIDEO_COLOR_FIELDS}))
                except Exception:
                    # MediaRelay catches only MediaStreamError. Diagnostics
                    # failure must not kill its reader and strand every viewer.
                    logger.exception("Mobile video metrics failed; retaining video transport")
        if not self.retain_latest:
            raise MediaStreamError
        return frame

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
            return generation

    def current(self, sid, generation):
        stream = self.streams.get(sid)
        if stream is None or stream.generation != generation or stream.closing:
            raise HTTPException(409, "mobile_stream_generation_changed")
        return stream

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
