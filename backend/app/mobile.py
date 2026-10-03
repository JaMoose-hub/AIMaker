"""LAN companion state and immutable media, independent of the webcam runtime."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from app.designs import GenerateRequest
from app.mobile_rtc import BITRATE_PROFILES, MobileRTC
from app.mobile_stability import DROPOUT_SECONDS, accept_candidate, clear_candidate, valid_points

ROOT = Path(__file__).resolve().parents[1] / "runs" / "mobile"
MAX_UPLOAD = 200 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
PREVIEW_TTL = 1.5
register_heif_opener(thumbnails=False)


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    pending.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    pending.replace(path)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value):
        raise HTTPException(422, "mobile_invalid_id")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k.lower() not in {"password", "token", "secret", "api_key"}}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def _program(name):
    found = shutil.which(name)
    bundled = Path("C:/Program Files/FFMPEG/bin") / (name + ".exe")
    if not found and bundled.is_file():
        found = str(bundled)
    if not found:
        raise HTTPException(503, "mobile_" + name + "_unavailable")
    return found


class MobileAssets:
    """Each public asset names immutable normalized pixels, never a client path."""
    def __init__(self, root):
        self.root = Path(root)
        self.lock = threading.RLock()

    def _record(self, aid):
        try:
            return json.loads((self.root / _id(aid) / "asset.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise HTTPException(404, "mobile_asset_not_found")

    def describe(self, aid):
        record = self._record(aid)
        return {key: record.get(key) for key in ("id", "type", "mime", "url", "thumbnail_url", "width", "height", "original_width", "original_height", "analysis_limited", "duration", "size", "filename", "sha256", "created_at", "capture_source", "stream_identity")}

    def authorize(self, aid, conversation_id):
        if self._record(aid)["conversation_id"] != conversation_id:
            raise HTTPException(403, "mobile_asset_conversation_mismatch")

    def analysis_asset(self, aid):
        record = self._record(aid)
        return {**self.describe(aid), "analysis_path": self.root / aid / record["analysis_file"],
                "conversation_id": record["conversation_id"], "session_id": record["session_id"]}

    def path(self, aid, thumbnail=False):
        record = self._record(aid)
        return self.root / aid / ("thumbnail.jpg" if thumbnail else record["analysis_file"])

    def resolve_images(self, ids):
        if len(ids) > 4 or len(set(ids)) != len(ids):
            raise HTTPException(422, "mobile_max_four_photos_or_one_video")
        records = [self._record(aid) for aid in ids]
        if any(r["type"] == "video" for r in records) and len(records) != 1:
            raise HTTPException(422, "mobile_max_four_photos_or_one_video")
        paths, metadata = [], []
        for record in records:
            aid = record["id"]
            frames = record.get("frames") or [{"file": record["analysis_file"], "timestamp_s": None}]
            for frame in frames:
                paths.append(self.root / aid / frame["file"])
                metadata.append({"asset_id": aid, "type": record["type"], "timestamp_s": frame["timestamp_s"],
                                 "duration": record["duration"], "audio_analysed": False,
                                 "width": record["width"], "height": record["height"]})
        return paths, metadata

    @staticmethod
    def _normalize(source, destination):
        with Image.open(source) as original:
            if original.width * original.height > 100_000_000:
                raise HTTPException(413, "mobile_image_too_large")
            image = ImageOps.exif_transpose(original).convert("RGB")
            original_size = image.size
            if image.width * image.height > MAX_IMAGE_PIXELS:
                scale = math.sqrt(MAX_IMAGE_PIXELS / (image.width * image.height))
                image = image.resize((max(1, int(image.width*scale)), max(1, int(image.height*scale))), Image.Resampling.LANCZOS)
            image.save(destination, "JPEG", quality=95, optimize=True)
            thumb = image.copy()
            thumb.thumbnail((480, 480))
            thumb.save(destination.parent / "thumbnail.jpg", "JPEG", quality=85)
            return image.size, original_size

    def ingest(self, source, *, conversation_id, session_id, upload_id, filename, content_type):
        source = Path(source)
        size = source.stat().st_size
        if size <= 0 or size > MAX_UPLOAD:
            raise HTTPException(413, "mobile_upload_size_limit")
        with source.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        key = _digest([conversation_id, session_id, _id(upload_id)])
        receipt = self.root / "uploads" / (key + ".json")
        with self.lock:
            if receipt.exists():
                previous = json.loads(receipt.read_text(encoding="utf-8"))
                if previous["sha256"] != sha:
                    raise HTTPException(409, "mobile_upload_id_conflict")
                return self.describe(previous["asset_id"])
            aid = uuid4().hex
            directory = self.root / aid
            directory.mkdir(parents=True)
            original = directory / "original.bin"
            shutil.copyfile(source, original)
            try:
                try:
                    (width, height), (original_width, original_height) = self._normalize(original, directory / "photo.jpg")
                    kind, mime, analysis, duration, frames = "image", "image/jpeg", "photo.jpg", None, []
                except Image.DecompressionBombError:
                    raise HTTPException(413, "mobile_image_pixel_limit")
                except (UnidentifiedImageError, OSError, ValueError):
                    if not (content_type or "").startswith("video/"):
                        raise HTTPException(422, "mobile_unsupported_image")
                    width, height, duration, frames = self._video(original, directory)
                    original_width, original_height = None, None
                    kind, mime, analysis = "video", "video/mp4", "video.mp4"
                    # The container can be MOV as well; use its uploaded MIME.
                    mime = content_type if content_type in {"video/mp4", "video/quicktime", "video/x-m4v"} else "application/octet-stream"
                    shutil.copyfile(original, directory / analysis)
                record = dict(id=aid, type=kind, mime=mime, analysis_file=analysis,
                    url=f"/api/mobile/assets/{aid}/file", thumbnail_url=f"/api/mobile/assets/{aid}/thumbnail",
                    width=width, height=height, duration=duration, size=size,
                    original_width=original_width, original_height=original_height,
                    analysis_limited=kind == "image" and (width, height) != (original_width, original_height),
                    filename=Path(filename or "upload").name[:200], original_sha256=sha,
                    sha256=hashlib.sha256((directory / analysis).read_bytes()).hexdigest(),
                    created_at=time.time(), conversation_id=conversation_id, session_id=session_id, frames=frames)
                _write_json(directory / "asset.json", record)
                _write_json(receipt, {"sha256": sha, "asset_id": aid})
                return self.describe(aid)
            except BaseException:
                # Only remove the newly generated UUID directory inside this store.
                if directory.resolve().parent == self.root.resolve():
                    shutil.rmtree(directory)
                raise

    def ingest_frame(self, pixels, *, conversation_id, session_id, stream_identity):
        """Persist independent native BGR without a lossy second compression."""
        if (not isinstance(pixels, np.ndarray) or pixels.dtype != np.uint8 or pixels.ndim != 3
                or pixels.shape[2] != 3 or not pixels.size or pixels.nbytes > 64*1024*1024):
            raise HTTPException(422, "mobile_invalid_stream_frame")
        with self.lock:
            aid = uuid4().hex
            directory = self.root / aid
            directory.mkdir(parents=True)
            try:
                image = Image.fromarray(pixels[:, :, ::-1])
                path = directory / "photo.png"
                image.save(path, "PNG")
                thumb = image.copy()
                thumb.thumbnail((480, 480))
                thumb.save(directory / "thumbnail.jpg", "JPEG", quality=85)
                sha = hashlib.sha256(path.read_bytes()).hexdigest()
                record = dict(id=aid, type="image", mime="image/png", analysis_file=path.name,
                    url=f"/api/mobile/assets/{aid}/file", thumbnail_url=f"/api/mobile/assets/{aid}/thumbnail",
                    width=image.width, height=image.height, original_width=image.width, original_height=image.height,
                    analysis_limited=False, duration=None, size=path.stat().st_size,
                    filename=f"phone-stream-{stream_identity['generation']}-{stream_identity['frame_seq']}.png",
                    sha256=sha, original_sha256=sha, created_at=time.time(), conversation_id=conversation_id,
                    session_id=session_id, frames=[], capture_source="desktop_stream", stream_identity=deepcopy(stream_identity))
                _write_json(directory / "asset.json", record)
                return self.analysis_asset(aid)
            except BaseException:
                if directory.resolve().parent == self.root.resolve():
                    shutil.rmtree(directory)
                raise

    def _video(self, original, directory):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            probe = subprocess.run([_program("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(original)],
                                   capture_output=True, check=True, timeout=20, creationflags=flags)
            info = json.loads(probe.stdout)
            stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
            duration = float(stream.get("duration") or info.get("format", {}).get("duration") or 0)
            if not math.isfinite(duration) or not 0 < duration <= 60:
                raise HTTPException(422, "mobile_video_max_60_seconds")
            if not 0 < int(stream["width"]) * int(stream["height"]) <= 100_000_000:
                raise HTTPException(422, "mobile_invalid_video_dimensions")
            count = min(8, max(1, math.ceil(duration)))
            timestamps = [duration * (i + .5) / count for i in range(count)]
            frames = []
            for i, stamp in enumerate(timestamps):
                target = directory / f"frame-{i:02d}.jpg"
                subprocess.run([_program("ffmpeg"), "-v", "error", "-nostdin", "-ss", str(stamp), "-i", str(original),
                    "-frames:v", "1", "-vf", "scale='min(1920,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease", "-q:v", "2", "-y", str(target)],
                    capture_output=True, check=True, timeout=25, creationflags=flags)
                frames.append({"file": target.name, "timestamp_s": round(stamp, 3)})
            with Image.open(directory / frames[0]["file"]) as frame:
                width, height = frame.size
                thumb = frame.copy()
                thumb.thumbnail((480, 480))
                thumb.save(directory / "thumbnail.jpg", "JPEG", quality=85)
            return width, height, duration, frames
        except HTTPException:
            raise
        except (subprocess.SubprocessError, ValueError, KeyError, StopIteration, OSError) as error:
            raise HTTPException(422, "mobile_video_decode_failed") from error


class MobileService:
    def __init__(self, state, root=None, *, clock=time.monotonic, wall=time.time, rtc_factory=MobileRTC):
        self.state, self.root = state, Path(root) if root else ROOT
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.assets = MobileAssets(self.root / "assets")
        self.contexts, self.latest, self.pairings, self.sessions, self.tokens = {}, None, {}, {}, {}
        self.captures, self.tickets, self.capture_requests = {}, {}, {}
        self.capture_order = {}
        self.listeners = []
        self.monitor = None
        self.rtc = rtc_factory(self.on_frame, self.on_rtc_state, on_video_metrics=self.on_video_metrics,
                               on_receive=self.on_receive, clock=self.clock, wall=self.wall)

    async def start(self):
        if self.monitor is None:
            self.monitor = asyncio.create_task(self._watch())

    async def close(self):
        if self.monitor is not None:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
            self.monitor = None
        await self.rtc.close_all()
        pending = [item["future"] for item in self.capture_requests.values() if not item["future"].done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        analyzer = getattr(self.state, "mobile_photo", None)
        if analyzer is not None:
            await asyncio.to_thread(analyzer.close)

    async def _watch(self):
        while True:
            await asyncio.sleep(.25)
            expired = []
            with self.lock:
                for session in self.sessions.values():
                    stream = session["stream"]
                    if session["expires"] < self.clock():
                        if stream["active"]:
                            expired.append(session["session_id"])
                        continue
                    if self._expire_stream(session) or stream.get("_expiry_pending"):
                        self.notify(session)
            for sid in expired:
                await self.rtc.close(sid)
                await asyncio.to_thread(self.state.mobile_photo.release, sid)

    def publish_context(self, payload):
        payload = _clean(deepcopy(payload))
        # Desktop debug controllers may restore a new runtime case ID without
        # changing this workspace. Do not bind phone messages/photos to that
        # webcam case, or persist it under an otherwise stable context hash.
        if isinstance(payload.get("context"), dict):
            payload["context"].pop("debug_session_id", None)
        if len(json.dumps(payload, ensure_ascii=False)) > 500_000:
            raise HTTPException(413, "mobile_context_too_large")
        cid = _id(payload["conversation_id"])
        payload["design"] = GenerateRequest.model_validate(payload["design"]).model_dump()
        payload["context_epoch"] = self.state.assistant.read(cid).get("context_epoch", 0)
        identifier = _digest(payload)[:32]
        with self.lock:
            record = {**payload, "context_id": identifier, "published_at": self.wall()}
            self.contexts[identifier] = record
            _write_json(self.root / "contexts" / (identifier + ".json"), record)
            self.latest = record
            for session in self.sessions.values():
                if session["context_id"] != identifier:
                    self._invalidate(session, "desktop_context_changed")
                self.notify(session)
            return deepcopy(record)

    def context(self, identifier):
        if identifier not in self.contexts:
            try:
                self.contexts[identifier] = json.loads((self.root / "contexts" / (_id(identifier)+".json")).read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise HTTPException(404, "mobile_context_not_found")
        return deepcopy(self.contexts[identifier])

    @staticmethod
    def base_urls(default_url):
        parsed = urlsplit(default_url)
        # Only advertise the certified HTTPS origin, not other adapters which
        # may not be covered by the development certificate's IP SAN.
        if parsed.scheme == "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return [default_url.rstrip("/")]
        port = parsed.port or 8100
        values = []
        try:
            for entry in socket.getaddrinfo(socket.gethostname(), port, type=socket.SOCK_STREAM):
                host = entry[4][0]
                address = ipaddress.ip_address(host)
                if address.version == 4 and not address.is_loopback and not address.is_link_local:
                    values.append(f"http://{host}:{port}")
        except OSError:
            pass
        if parsed.hostname and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            values.insert(0, default_url.rstrip("/"))
        return list(dict.fromkeys(values)) or [default_url.rstrip("/")]

    def create_pairing(self, cid, base_url):
        with self.lock:
            if self.latest is None or self.latest["conversation_id"] != cid:
                raise HTTPException(409, "mobile_publish_current_context_first")
            parsed = urlsplit(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
                raise HTTPException(422, "mobile_invalid_base_url")
            try:
                parsed.port
            except ValueError:
                raise HTTPException(422, "mobile_invalid_base_url")
            self.pairings = {code: item for code, item in self.pairings.items() if item["expires"] >= self.clock()}
            urls = self.base_urls(base_url)
            chosen = base_url.rstrip("/") if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} else urls[0]
            code = f"{secrets.randbelow(1_000_000):06d}"
            while code in self.pairings:
                code = f"{secrets.randbelow(1_000_000):06d}"
            item = {"code": code, "context_id": self.latest["context_id"], "base_url": chosen,
                    "expires": self.clock()+300, "expires_at": self.wall()+300}
            self.pairings[code] = item
            return {"code": code, "expires_at": item["expires_at"], "base_urls": urls,
                    "base_url": chosen, "web_url": chosen + "/mobile?code=" + code if parsed.scheme == "https" else None,
                    "qr_payload": json.dumps({"type": "tinkro-mobile", "base_url": chosen, "code": code})}

    @staticmethod
    def _empty_stream(generation=0):
        return dict(active=False, generation=generation, publisher_connected=False, state="finding", can_capture=False,
                    reason="stream_stopped", preview_seq=0, objects=[], quality={}, model_runtime={}, updated_at=None, recognition=None,
                    video_fps=None, recognition_fps=None, recognition_ms=None, received_frames=0, recognition_started=None, recognition_count=0,
                    last_video_received=None, video_received_at=None, video_receive_seq=0,
                    bitrate_kbps=8000, publisher_stats=None, server_metrics=None,
                    expires_at=None, valid_for_ms=0, last_received=None, stable_since=None, stable_count=0, previous=None, anchor=None, lock_id=None,
                    stable_times=[], qualified_received=None, invalid_count=0)

    def pair(self, code, device_name):
        with self.lock:
            pairing = self.pairings.pop(code, None)
            if not pairing or pairing["expires"] < self.clock():
                raise HTTPException(401, "mobile_pairing_expired_or_invalid")
            context = self.context(pairing["context_id"])
            sid, token = uuid4().hex, secrets.token_urlsafe(32)
            session = dict(session_id=sid, conversation_id=context["conversation_id"], context_id=context["context_id"],
                           device_name=device_name, base_url=pairing["base_url"], created_at=self.wall(),
                           expires=self.clock()+12*3600, stream=self._empty_stream(),
                           view=dict(capture_id=None, wire_id=None, revision=0))
            self.sessions[sid] = session
            self.tokens[hashlib.sha256(token.encode()).hexdigest()] = sid
            self.notify(session)
            return {**self.snapshot(sid), "token": token}

    def authorize(self, token):
        with self.lock:
            sid = self.tokens.get(hashlib.sha256((token or "").encode()).hexdigest())
            session = self.sessions.get(sid)
            if session is None or session["expires"] < self.clock():
                raise HTTPException(401, "mobile_session_expired_or_invalid")
            return sid

    def require(self, sid):
        session = self.sessions.get(sid)
        if not session or session["expires"] < self.clock():
            raise HTTPException(404, "mobile_session_not_found")
        return session

    def _invalidate(self, session, reason, *, preserve_recognition=False, preserve_candidate=False):
        session["stream"].update(state="finding", can_capture=False, reason=reason,
            lock_id=None, expires_at=None, valid_for_ms=0)
        if not preserve_candidate:
            clear_candidate(session["stream"])
        if not preserve_recognition:
            session["stream"]["recognition"] = None

    def _expire_stream(self, session):
        """Receipt liveness is independent of inference and sender statistics."""
        stream = session["stream"]
        if not stream["active"]:
            return False
        if stream["invalid_count"] and stream["qualified_received"] is not None and self.clock()-stream["qualified_received"] > DROPOUT_SECONDS:
            clear_candidate(stream)
        received = stream["last_video_received"]
        stale_video = stream["active"] and received is not None and self.clock()-received > PREVIEW_TTL
        stale_preview = stream["last_received"] is not None and self.clock()-stream["last_received"] > PREVIEW_TTL
        if not (stale_video or stale_preview):
            return False
        reason = "video_receive_stalled" if stale_video else "preview_expired"
        changed = (stream["reason"] != reason or stream["can_capture"] or stream["recognition"] is not None
                   or stream["recognition_fps"] != 0 or (stale_video and stream["publisher_connected"]))
        self._invalidate(session, reason)
        stream.update(recognition_fps=0., recognition_ms=None, recognition_started=None, recognition_count=0)
        if stale_video:
            stream.update(publisher_connected=False, video_fps=0.)
        if changed:
            stream["_expiry_pending"] = True
        return changed

    def snapshot(self, sid):
        with self.lock:
            session = self.require(sid)
            stream = session["stream"]
            self._expire_stream(session)
            context = self.context(session["context_id"])
            result = {k: deepcopy(v) for k, v in session.items() if k != "expires"}
            result["stream"] = {k: deepcopy(v) for k, v in stream.items() if k not in {"_expiry_pending", "last_received", "last_video_received", "stable_since", "stable_count", "previous", "anchor", "lock_id", "recognition_started", "recognition_count", "stable_times", "qualified_received", "invalid_count"}}
            age = self.clock()-stream["last_video_received"] if stream["last_video_received"] is not None else None
            fresh = bool(stream["active"] and age is not None and 0 <= age <= PREVIEW_TTL)
            result["stream"].update(video_receive_age_ms=max(0, round(age*1000)) if age is not None else None,
                                    video_receive_fresh=fresh, publisher_connected=fresh)
            if not fresh:
                result["stream"].update(video_fps=0., recognition_fps=0., recognition_ms=None)
            if result["stream"]["expires_at"] is not None:
                result["stream"]["valid_for_ms"] = max(0, int((result["stream"]["expires_at"]-self.wall())*1000))
            recognition = result["stream"].get("recognition")
            if recognition is not None:
                recognition["valid_for_ms"] = max(0, int((PREVIEW_TTL-(self.clock()-stream["last_received"]))*1000))
            result.update(context=context, title=context.get("title", "Tinkro"),
                available_context=({k: self.latest.get(k) for k in ("context_id", "conversation_id", "title", "stage", "published_at")} if self.latest else None))
            return result

    def desktop_snapshot(self, cid):
        with self.lock:
            matches = [s for s in self.sessions.values() if s["conversation_id"] == cid and s["expires"] >= self.clock()]
            latest = max(matches, key=lambda s: s["created_at"]) if matches else None
            return {"session": self.snapshot(latest["session_id"]) if latest else None,
                    "context": deepcopy(self.latest) if self.latest and self.latest["conversation_id"] == cid else None}

    async def disconnect(self, sid):
        """Revoke this pairing and live resources; retain its saved project media."""
        with self.lock:
            session = self.require(sid)
            cid = session["conversation_id"]
            session["stream"].update(active=False, publisher_connected=False)
            self._invalidate(session, "phone_disconnected")
            for ticket in self.tickets.values():
                if ticket["session_id"] == sid:
                    ticket["invalid"] = True
            self.sessions.pop(sid)
            for token_hash, paired_sid in list(self.tokens.items()):
                if paired_sid == sid:
                    self.tokens.pop(token_hash)
            desktop_packet = {"type": "state", "session": self.desktop_snapshot(cid)["session"]}
            for listener in list(self.listeners):
                if listener[0] == sid:
                    self._queue_event(listener, {"type": "disconnected", "session": None, "reason": "phone_disconnected"})
                elif listener[1] == cid:
                    self._queue_event(listener, desktop_packet)
        try:
            await self.rtc.close(sid)
        finally:
            await asyncio.to_thread(self.state.mobile_photo.release, sid)

    async def join(self, sid):
        await self.rtc.close(sid)
        await asyncio.to_thread(self.state.mobile_photo.release, sid)
        with self.lock:
            session = self.require(sid)
            if self.latest is None:
                raise HTTPException(409, "mobile_no_desktop_context")
            session.update(conversation_id=self.latest["conversation_id"], context_id=self.latest["context_id"])
            session["view"] = dict(capture_id=None, wire_id=None, revision=session["view"]["revision"]+1)
            for ticket in self.tickets.values():
                if ticket["session_id"] == sid:
                    ticket["invalid"] = True
            self._invalidate(session, "joined_context")
            self.notify(session)
            return self.snapshot(sid)

    def send(self, sid, body):
        from app.assistant import SendRequest
        with self.lock:
            session = self.require(sid)
            if body["context_id"] != session["context_id"]:
                raise HTTPException(409, "mobile_context_changed")
            context = self.context(body["context_id"])
            ids = body.get("asset_ids", [])
            for aid in ids:
                self.assets.authorize(aid, session["conversation_id"])
            self.assets.resolve_images(ids)
            capture = self.capture(body["capture_id"], sid) if body.get("capture_id") else None
            if capture and capture["context_id"] != body["context_id"]:
                raise HTTPException(409, "mobile_capture_context_changed")
            payload = {"request_id": body["request_id"], "text": body.get("text", ""),
                       "stage": context["stage"], "target": context["target"], "design": context["design"],
                       "context": {**context["context"], "mobile_context_id": context["context_id"]},
                       "round": context["round"], "asset_ids": ids, "inherit_media": body.get("inherit_media", True), "source": "mobile"}
            for key in ("capture_id", "check_scope", "wire_id"):
                if body.get(key) is not None:
                    payload[key] = body[key]
            cid = session["conversation_id"]
        return self.state.assistant.send(cid, SendRequest.model_validate(payload))

    async def start_stream(self, sid, bitrate_kbps=8000):
        self.require(sid)
        if bitrate_kbps not in BITRATE_PROFILES:
            raise HTTPException(422, "mobile_invalid_bitrate_profile")
        generation = await self.rtc.start(sid, bitrate_kbps=bitrate_kbps)
        with self.lock:
            session = self.require(sid)
            session["stream"] = self._empty_stream(generation)
            session["stream"].update(active=True, reason="finding_board", bitrate_kbps=bitrate_kbps)
            self.notify(session)
            return self.snapshot(sid)["stream"]

    def publisher_metrics(self, sid, values):
        """Untrusted client diagnostics cannot establish receipt or capture lock."""
        with self.lock:
            session = self.require(sid)
            stream = session["stream"]
            if not stream["active"] or values.get("generation") != stream["generation"]:
                raise HTTPException(409, "mobile_stream_generation_changed")
            result = {"generation": stream["generation"], "reported_at": self.wall()}
            limits = dict(capture_fps=240, send_fps=240, send_bitrate_kbps=100000,
                          width=16384, height=16384, rtt_ms=600000)
            for key, maximum in limits.items():
                value = values.get(key)
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                          or not math.isfinite(value) or not 0 <= value <= maximum
                                          or (key in {"width", "height"} and (value < 1 or int(value) != value))):
                    raise HTTPException(422, "mobile_invalid_publisher_metrics")
                result[key] = value
            reason = values.get("quality_limitation_reason")
            if reason is not None and (not isinstance(reason, str) or len(reason) > 64):
                raise HTTPException(422, "mobile_invalid_publisher_metrics")
            result["quality_limitation_reason"] = reason
            stream["publisher_stats"] = result
            self.notify(session)
            return deepcopy(result)

    async def stop_stream(self, sid):
        await self.rtc.close(sid)
        with self.lock:
            session = self.require(sid)
            session["stream"].update(active=False, publisher_connected=False, video_fps=0., recognition_fps=0., recognition_ms=None)
            self._invalidate(session, "stream_stopped")
            self.notify(session)
            return self.snapshot(sid)["stream"]

    async def on_rtc_state(self, sid, generation, reason):
        with self.lock:
            session = self.sessions.get(sid)
            if session is None or session["stream"]["generation"] != generation:
                return
            session["stream"].update(publisher_connected=False, active=False, video_fps=0., recognition_fps=0., recognition_ms=None)
            self._invalidate(session, "stream_"+reason)
            if session["expires"] >= self.clock():
                self.notify(session)

    async def on_frame(self, sid, generation, frame, seq, received):
        with self.lock:
            session = self.sessions.get(sid)
            if not session or not session["stream"]["active"] or session["stream"]["generation"] != generation:
                return
            context = (deepcopy(self.latest) if self.latest and self.latest["conversation_id"] == session["conversation_id"]
                       else self.context(session["context_id"]))
        identity = dict(session_id=sid, generation=generation, seq=seq, sample_seq=seq, frame_id=seq,
                        received_monotonic=received, ts_ms=self.wall()*1000)
        started = self.clock()
        try:
            from app.capture.phone import PhoneFrameSource
            source = getattr(self.state, 'source', None)
            if isinstance(source, PhoneFrameSource) and (source.session_id, source.generation) == (sid, generation):
                revision = self.state.config.runtime_revision
                synchronized = self.state.motion_frame_state.get_capture()
                if synchronized is None or synchronized[0]['runtime_revision'] != revision:
                    result = dict(reason='finding_board')
                else:
                    packet, slot = synchronized
                    frame, received = slot.frame, slot.ts_ms / 1000
                    result = await asyncio.to_thread(self.state.mobile_photo.preview_packet, frame, context, identity, packet)
                    if self.state.source is not source or self.state.config.runtime_revision != revision:
                        return
            else:
                result = await asyncio.to_thread(self.state.mobile_photo.preview, frame, context, identity)
        except Exception:
            result = dict(board_present=False, target_present=False, sharp=False, framed=False, objects=[], quality={}, reason="preview_analysis_failed")
        result["recognition_ms"] = (self.clock()-started)*1000
        self.accept_preview(sid, generation, seq, received, result, (frame.shape[1], frame.shape[0]), context["context_id"])

    def on_receive(self, sid, generation, seq, received, received_at, size):
        """Called at native receipt, before the sampled inference/metrics awaits."""
        with self.lock:
            session = self.sessions.get(sid)
            if not session or session["expires"] < self.clock():
                return
            stream = session["stream"]
            if not stream["active"] or stream["generation"] != generation or seq <= stream["video_receive_seq"]:
                return
            if not 0 <= self.clock()-received <= PREVIEW_TTL:
                return
            previous = stream["last_video_received"]
            resumed = previous is None or received-previous > PREVIEW_TTL or not stream["publisher_connected"]
            if resumed:
                self._invalidate(session, "receiving_video")
                stream.update(video_fps=None, recognition_fps=0., recognition_ms=None,
                              recognition_started=None, recognition_count=0)
            stream.update(last_video_received=received, video_received_at=received_at, video_receive_seq=seq,
                          received_frames=seq, publisher_connected=True, video_size=list(size))
            if resumed:
                self.notify(session)

    async def on_video_metrics(self, sid, generation, values):
        with self.lock:
            session = self.sessions.get(sid)
            if session and session["stream"]["active"] and session["stream"]["generation"] == generation:
                session["stream"].update({key: value for key, value in values.items() if key in {
                    "video_fps", "video_size", "video_color", "publisher_codec", "viewer_codecs", "codec_source", "server_metrics"}})
                self.notify(session)

    def accept_preview(self, sid, generation, seq, received, result, size, context_id):
        with self.lock:
            session = self.sessions.get(sid)
            if session is None or session["expires"] < self.clock():
                return
            stream = session["stream"]
            if not stream["active"] or generation != stream["generation"] or seq <= stream["preview_seq"]:
                return
            if (not self.latest or context_id != self.latest["context_id"] or self.latest["conversation_id"] != session["conversation_id"]
                    or not 0 <= self.clock()-received <= PREVIEW_TTL):
                self._invalidate(session, "context_changed_or_preview_expired")
                self.notify(session)
                return
            if stream["last_received"] is not None and received <= stream["last_received"]:
                return
            if stream["last_received"] is not None and received-stream["last_received"] > PREVIEW_TTL:
                self._invalidate(session, "preview_expired")
            remaining = max(0., PREVIEW_TTL-(self.clock()-received))
            stream.update(preview_seq=seq, last_received=received, updated_at=self.wall(),
                          objects=deepcopy(result.get("objects", [])), quality=deepcopy(result.get("quality", {})),
                          model_runtime=deepcopy(result.get("model_runtime", {})),
                          video_size=list(size), expires_at=self.wall()+remaining, valid_for_ms=int(remaining*1000))
            recognition = result.get("recognition")
            # A packet belongs to one phone generation, workspace and analyzed
            # image. It is never a copy of /ws/detections from the webcam.
            if (recognition and recognition.get("source") == "phone"
                    and recognition.get("session_id") == sid and recognition.get("generation") == generation
                    and recognition.get("context_id") == context_id and recognition.get("frame_seq") == seq
                    and recognition.get("video_size") == list(size)):
                stream["recognition"] = {**deepcopy(recognition), "valid_for_ms": int(remaining*1000)}
            else:
                stream["recognition"] = None
            now = self.clock()
            if stream["recognition_started"] is None:
                stream["recognition_started"], stream["recognition_count"] = now, 0
            else:
                stream["recognition_count"] += 1
                elapsed = now-stream["recognition_started"]
                if elapsed >= 1.:
                    stream["recognition_fps"] = round(stream["recognition_count"]/elapsed, 2)
                    stream["recognition_started"], stream["recognition_count"] = now, 0
            stream["recognition_ms"] = result.get("recognition_ms")
            if context_id != session["context_id"]:
                # Live geometry follows the desktop lesson without restarting
                # the camera or adopting the phone's frozen photo/chat context.
                self._invalidate(session, "desktop_context_changed", preserve_recognition=True)
                self.notify(session)
                return
            ready = all(result.get(key) is True for key in ("board_present", "target_present", "sharp", "framed"))
            points = {}
            required = {"raspberry-pi-5"}
            if result.get("target_id"):
                required.add(result["target_id"])
            try:
                for item in result.get("objects", []):
                    if item.get("id") not in required:
                        continue
                    values = np.asarray(item.get("outline_px"), dtype=float)
                    if values.shape == (4, 2) and np.isfinite(values).all():
                        points[item["id"]] = values.tolist()
            except (TypeError, ValueError, KeyError):
                ready = False
            if not ready or set(points) != required or not valid_points(points):
                # Capture readiness is stricter than live recognition: blur or
                # an absent target must not suppress other current detections.
                stream["invalid_count"] += 1
                last_good = stream["qualified_received"]
                retain = (stream["invalid_count"] == 1 and last_good is not None
                          and 0 <= received-last_good <= DROPOUT_SECONDS+1e-9)
                self._invalidate(session, result.get("reason") or "finding_board", preserve_recognition=True, preserve_candidate=retain)
            else:
                locked = accept_candidate(stream, points, received)
                stream.update(state="locked" if locked else "hold_still", can_capture=locked,
                              reason="ready_to_capture" if locked else "hold_still")
                if locked and not stream["lock_id"]:
                    stream["lock_id"] = uuid4().hex
            self.notify(session)

    def capture_ticket(self, sid):
        with self.lock:
            self.snapshot(sid)
            session = self.require(sid)
            stream = session["stream"]
            if not stream["can_capture"] or not self.latest or self.latest["context_id"] != session["context_id"]:
                raise HTTPException(409, "mobile_capture_not_locked")
            tid = uuid4().hex
            record = dict(ticket_id=tid, session_id=sid, context_id=session["context_id"],
                          generation=stream["generation"], preview_seq=stream["preview_seq"], created_at=self.wall(),
                          expires=self.clock()+120, expires_at=self.wall()+120, invalid=False)
            self.tickets[tid] = record
            self._invalidate(session, "capturing_photo")
            self.notify(session)
            return {k: record[k] for k in ("ticket_id", "expires_at", "context_id", "generation", "preview_seq")}

    async def finalize_capture(self, sid, body):
        body = {**body, "capture_source": body.get("capture_source", "camera_photo")}
        if body["capture_source"] not in {"camera_photo", "phone_frame"}:
            raise HTTPException(422, "mobile_invalid_capture_source")
        key = (sid, body["request_id"])
        with self.lock:
            session = self.require(sid)
            existing = self.capture_requests.get(key)
            if existing:
                if existing["fingerprint"] != _digest(body):
                    raise HTTPException(409, "mobile_capture_request_conflict")
                future = existing["future"]
            else:
                ticket = self.tickets.get(body["ticket_id"])
                if (not ticket or ticket["session_id"] != sid or ticket["invalid"] or ticket["expires"] < self.clock()
                        or ticket["context_id"] != session["context_id"] or not self.latest
                        or self.latest["context_id"] != ticket["context_id"]):
                    raise HTTPException(409, "mobile_capture_ticket_expired")
                if ticket.get("request_id"):
                    raise HTTPException(409, "mobile_capture_ticket_consumed")
                asset = self.assets.analysis_asset(body["asset_id"])
                self.assets.authorize(asset["id"], session["conversation_id"])
                if asset["type"] != "image" or asset["session_id"] != sid or asset["created_at"] < ticket["created_at"]:
                    raise HTTPException(409, "mobile_fresh_camera_photo_required")
                ticket["request_id"] = body["request_id"]
                context = self.context(ticket["context_id"])
                self.capture_order[sid] = self.capture_order.get(sid, 0)+1
                bound = {**deepcopy(session), "generation": ticket["generation"], "preview_seq": ticket["preview_seq"],
                         "capture_source": body["capture_source"], "_capture_order": self.capture_order[sid]}
                future = asyncio.create_task(self._analyze_capture(sid, asset, context, bound))
                self.capture_requests[key] = {"fingerprint": _digest(body), "future": future}
        return await asyncio.shield(future)

    async def capture_stream(self, sid, body):
        body = {key: body[key] for key in ("request_id", "context_id", "generation")}
        body["capture_source"] = "desktop_stream"
        key = (sid, body["request_id"])
        with self.lock:
            session = self.require(sid)
            existing = self.capture_requests.get(key)
            if existing:
                if existing["fingerprint"] != _digest(body):
                    raise HTTPException(409, "mobile_capture_request_conflict")
                future = existing["future"]
            else:
                stream = session["stream"]
                if not stream["active"] or stream["generation"] != body["generation"]:
                    raise HTTPException(409, "mobile_stream_generation_changed")
                if (session["context_id"] != body["context_id"] or not self.latest
                        or self.latest["context_id"] != body["context_id"]):
                    raise HTTPException(409, "mobile_context_changed")
                # No await between checking ownership and freezing the current
                # incoming frame. Retry joins this task, never another frame.
                pixels, identity = self.rtc.capture_frame(sid, body["generation"], max_age=PREVIEW_TTL)
                context = self.context(body["context_id"])
                self.capture_order[sid] = self.capture_order.get(sid, 0)+1
                bound = {**deepcopy(session), "generation": body["generation"], "capture_source": "desktop_stream",
                         "stream_identity": identity, "_capture_order": self.capture_order[sid]}
                future = asyncio.create_task(self._save_stream_capture(sid, pixels, context, bound))
                self.capture_requests[key] = {"fingerprint": _digest(body), "future": future}
        return await asyncio.shield(future)

    async def _save_stream_capture(self, sid, pixels, context, session):
        asset = await asyncio.to_thread(self.assets.ingest_frame, pixels, conversation_id=session["conversation_id"],
                                       session_id=sid, stream_identity=session["stream_identity"])
        return await self._analyze_capture(sid, asset, context, session)

    async def _analyze_capture(self, sid, asset, context, session):
        packet = await asyncio.to_thread(self.state.mobile_photo.analyze, asset, context, session)
        if (packet.get("image_sha256") != asset["sha256"] or
                packet.get("video_size") != [asset["width"], asset["height"]]):
            raise HTTPException(409, "mobile_capture_image_identity_mismatch")
        packet.update(asset_id=asset["id"], context_id=context["context_id"], session_id=sid,
                      conversation_id=session["conversation_id"], capture_source=session.get("capture_source", "camera_photo"),
                      image_url=asset["url"], image_sha256=asset["sha256"],
                      original_size=[asset.get("original_width") or asset["width"], asset.get("original_height") or asset["height"]],
                      analysis_limited=bool(asset.get("analysis_limited")))
        if "stream_identity" in session:
            packet["stream_identity"] = deepcopy(session["stream_identity"])
        cid = _id(packet["capture_id"])
        bind_reference = False
        with self.lock:
            _write_json(self.root / "captures" / (cid+".json"), {"packet": packet, "conversation_id": session["conversation_id"]})
            self.captures[cid] = {"packet": deepcopy(packet), "conversation_id": session["conversation_id"]}
            current = self.sessions.get(sid)
            if (current and current["expires"] >= self.clock() and current["context_id"] == context["context_id"]
                    and self.latest and self.latest["context_id"] == context["context_id"]
                    and current["stream"]["generation"] == session["generation"]
                    and self.capture_order.get(sid) == session.get("_capture_order")
                    and current["view"]["revision"] == session["view"]["revision"]):
                current["view"] = dict(capture_id=cid, wire_id=None, revision=current["view"]["revision"]+1)
                bind_reference = bool(self.latest and self.latest["context_id"] == context["context_id"])
                self.notify(current)
        # Model and chat locks must not be acquired while holding the session lock.
        if bind_reference:
            bind = getattr(self.state.assistant, "bind_photo_reference", None)
            if callable(bind):
                bind(session["conversation_id"], packet, context)
        return deepcopy(packet)

    def capture(self, cid, sid=None):
        with self.lock:
            if cid not in self.captures:
                try:
                    self.captures[cid] = json.loads((self.root / "captures" / (_id(cid)+".json")).read_text(encoding="utf-8"))
                except FileNotFoundError:
                    raise HTTPException(404, "mobile_capture_not_found")
            record = self.captures[cid]
            if sid and self.require(sid)["conversation_id"] != record["conversation_id"]:
                raise HTTPException(403, "mobile_capture_conversation_mismatch")
            return deepcopy(record["packet"])

    def get_capture(self, capture_id):
        return self.capture(capture_id)

    def view(self, sid, body=None):
        with self.lock:
            session = self.require(sid)
            if body is not None:
                cid, wire = body.get("capture_id"), body.get("wire_id")
                if cid:
                    capture = self.capture(cid, sid)
                    if wire is not None and wire not in {w["wire_id"] for w in capture["wires"]}:
                        raise HTTPException(422, "mobile_unknown_capture_wire")
                elif wire is not None:
                    raise HTTPException(422, "mobile_capture_required")
                session["view"] = dict(capture_id=cid, wire_id=wire, revision=session["view"]["revision"]+1)
                self.notify(session)
            return deepcopy(session["view"])

    def subscribe(self, sid=None, cid=None):
        queue = asyncio.Queue(maxsize=1)
        listener = (sid, cid, asyncio.get_running_loop(), queue)
        with self.lock:
            self.listeners.append(listener)
        return listener

    def unsubscribe(self, listener):
        with self.lock:
            if listener in self.listeners:
                self.listeners.remove(listener)

    def notify(self, session):
        if session["expires"] < self.clock():
            return
        packet = {"type": "state", "session": self.snapshot(session["session_id"])}
        session["stream"].pop("_expiry_pending", None)
        for listener in list(self.listeners):
            sid, cid, _, _ = listener
            if sid != session["session_id"] and cid != session["conversation_id"]:
                continue
            self._queue_event(listener, packet)

    @staticmethod
    def _queue_event(listener, packet):
        _, _, loop, queue = listener
        def put(q=queue, value=deepcopy(packet)):
            if q.full():
                q.get_nowait()
            q.put_nowait(value)
        if not loop.is_closed():
            loop.call_soon_threadsafe(put)
