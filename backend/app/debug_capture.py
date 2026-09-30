"""Bounded raw webcam evidence. Display overlays and pin guesses are never pixels.

Quality/stability are framing heuristics, not visibility or hardware verdicts.
The session service owns persistence and run binding; this module returns bytes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import time
import uuid
from types import SimpleNamespace

import cv2
import numpy as np

from app.wiring_capture import image_quality, _quality_sources

TARGETS = {"overview", "tft_screen", "hc_target", "pi_header", "module_header"}
MAX_BYTES = 64 * 1024 * 1024


class DebugCaptureError(ValueError):
    pass


def _source_binding(state):
    source = getattr(state, "source", None)
    if source is None:
        raise DebugCaptureError("camera_source_unavailable")
    camera = state.config.camera
    # Retain the source itself in the binding so its process-local identity cannot
    # be reused. Mode is separate: configure_mode can mutate the same source.
    signature = [id(source), type(source).__module__, type(source).__qualname__,
                 getattr(source, "current_index", None), getattr(source, "device_name", None),
                 getattr(source, "capture_mode", None),
                 [getattr(camera, key, None) for key in ("width", "height", "fps")]]
    camera_id = "webcam-" + hashlib.sha256(json.dumps(signature, sort_keys=True,
        separators=(",", ":"), default=str).encode("utf-8")).hexdigest()[:24]
    return source, camera_id


def current_debug_camera(state) -> str:
    """Opaque camera/mode identity, stable for this live source's lifetime.

    Device names and process addresses are hashed, never exposed in metadata.
    This does not open the source or bypass the physical-webcam runtime gate.
    """
    return _source_binding(state)[1]


def _check_binding(state, revision, binding):
    if (getattr(state, "source", None) is not binding[0]
            or current_debug_camera(state) != binding[1]
            or _runtime(state) != revision):
        raise DebugCaptureError("camera_changed")


def _runtime(state):
    if state.config.camera.source != "device":
        raise DebugCaptureError("webcam_required")
    glasses = getattr(state, "glasses_stream", None)
    if glasses is not None:
        status = glasses.snapshot()
        if status.get("active") or status.get("state") in {"starting", "switching", "restoring", "stopping"}:
            raise DebugCaptureError("webcam_restore_required")
    runtime = state.runtime_manager.snapshot()
    if runtime.board_id != "raspberry-pi-5":
        raise DebugCaptureError("pi5_required")
    return runtime.runtime_revision


def _slot(state, revision, binding, earliest_ms, clock):
    _check_binding(state, revision, binding)
    slot = state.frame_bus.get_latest(timeout=0)
    _check_binding(state, revision, binding)
    if slot is None or not math.isfinite(slot.ts_ms) or not 0 <= clock()*1000-slot.ts_ms <= 1000:
        raise DebugCaptureError("camera_frame_unavailable")
    if slot.ts_ms < earliest_ms:
        raise DebugCaptureError("camera_frame_not_new")
    frame = slot.frame
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
            or frame.shape[2] != 3 or min(frame.shape[:2]) < 16 or frame.nbytes > MAX_BYTES):
        raise DebugCaptureError("camera_frame_invalid")
    return slot


def _thumbnail(frame):
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (96, 64), interpolation=cv2.INTER_AREA)


def _encode(slot, revision, camera_id, target, quality, stability):
    # Always encode the actual decoded source; never trust an unrelated JPEG cache.
    ok, image = cv2.imencode(".jpg", slot.frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
    if not ok:
        raise DebugCaptureError("camera_encode_failed")
    raw = image.tobytes()
    if len(raw) > MAX_BYTES:
        raise DebugCaptureError("camera_frame_too_large")
    metadata = {
        "capture_id": uuid.uuid4().hex, "target": target, "source": "device",
        "camera_id": camera_id,
        "runtime_revision": revision, "frame_id": slot.frame_id, "seq": slot.seq,
        "ts_ms": slot.ts_ms, "capture_ts_ms": slot.ts_ms,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "size": [slot.frame.shape[1], slot.frame.shape[0]],
        "sha256": hashlib.sha256(raw).hexdigest(), "quality": deepcopy(quality),
        "stability": deepcopy(stability), "mode": "overview", "crop": None,
        "same_frame": True, "capture_skew_ms": 0,
        "current": True, "visibility_verified": False, "electrical_verified": False,
        "views": [{"name": "overview", "frame_id": slot.frame_id, "seq": slot.seq,
                   "ts_ms": slot.ts_ms, "size": [slot.frame.shape[1], slot.frame.shape[0]],
                   "encoding": "jpeg", "mime_type": "image/jpeg", "sha256": hashlib.sha256(raw).hexdigest()}],
    }
    return {"overview": raw}, metadata


def _wiring_body(wiring_target):
    from app.cloud_wiring import resolve_wire
    from fastapi import HTTPException
    required = {"project_id", "project_revision", "catalog_version", "profile_versions", "component_id",
                "wire_id", "board_pin", "component_pin", "connection_kind"}
    if not isinstance(wiring_target, dict) or not required.issubset(wiring_target):
        raise DebugCaptureError("invalid_wiring_target")
    body = SimpleNamespace(**deepcopy({key: wiring_target[key] for key in required}))
    try:
        resolve_wire(body)
    except (HTTPException, ValueError, KeyError, TypeError) as error:
        raise DebugCaptureError("invalid_wiring_target") from error
    return body


def _located_candidate(state, body, earliest_ms, clock):
    """Reuse pin localization with atomic raw frames, never display JPEG pixels."""
    from app.cloud_wiring import locate_capture
    motion = getattr(state, "motion_frame_state", None)
    reader = getattr(motion, "get_capture", None)
    pair = reader() if getattr(state.config, "realtime_tracking", False) and callable(reader) else None
    if pair is not None:
        packet, slot = pair
        if (packet.get("frame_id") != slot.frame_id or packet.get("ts_ms") != slot.ts_ms
                or packet.get("seq", slot.seq) != slot.seq):
            raise ValueError("camera_pose_source_mismatch")
    # Old providers only expose an encoded display packet. They may supply an
    # overview, but cannot provide authoritative raw pixels for pin crops.
    proxy = SimpleNamespace(
        config=SimpleNamespace(camera=state.config.camera, realtime_tracking=pair is not None),
        runtime_manager=state.runtime_manager,
        motion_frame_state=SimpleNamespace(get_capture=lambda: pair),
        detection_state=getattr(state, "detection_state", SimpleNamespace(get_synchronized=lambda: None)),
        component_pose_state=getattr(state, "component_pose_state", SimpleNamespace(get_synchronized=lambda _: None)))
    located = locate_capture(proxy, body)
    sources = located[0]
    for frame, message, frame_id, ts_ms in sources:
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
                or frame.shape[2] != 3 or min(frame.shape[:2]) < 16 or frame.nbytes > MAX_BYTES):
            raise ValueError("camera_frame_invalid")
        if not math.isfinite(ts_ms) or not earliest_ms <= ts_ms <= clock()*1000 or clock()*1000-ts_ms > 1000:
            raise ValueError("camera_frame_not_new")
        if message.get("ts_ms", ts_ms) != ts_ms:
            raise ValueError("camera_pose_source_mismatch")
    return located


def _finish_views(images, metadata):
    for view in metadata["views"]:
        data = images[view["name"]]
        png = data.startswith(b"\x89PNG\r\n\x1a\n")
        view.update(encoding="png" if png else "jpeg", mime_type="image/png" if png else "image/jpeg",
                    sha256=hashlib.sha256(data).hexdigest())
    if sum(len(data) for data in images.values()) > MAX_BYTES:
        raise DebugCaptureError("camera_frame_too_large")
    return images, metadata


def _encode_located(state, body, located, revision, camera_id, target, stability, response_mode):
    from app.cloud_wiring import _capture_located_images, inspection_views
    from app.cloud_connector_inspection import contact_views
    images, metadata = _capture_located_images(state, body, located)
    if response_mode == "thorough":
        images, metadata = inspection_views(images, metadata, body.component_id)
        images, metadata = contact_views(images, metadata)
    # Keep the established debug overview key/API while preserving endpoint
    # names required by the independent thorough inspection helpers.
    images = {("overview" if name == "pi_overview" else name): data for name, data in images.items()}
    for view in metadata["views"]:
        if view["name"] == "pi_overview":
            view["name"] = "overview"
        if view.get("source_view") == "pi_overview":
            view["source_view"] = "overview"
    frame, message, frame_id, ts_ms = located[0][0]
    quality = image_quality(frame)
    quality["framing_ready"] = stability["stable"] and not quality["warnings"]
    metadata.update(capture_id=uuid.uuid4().hex, target=target, source="device", camera_id=camera_id,
                    runtime_revision=revision, frame_id=frame_id, seq=message.get("seq", frame_id), ts_ms=ts_ms,
                    size=[frame.shape[1], frame.shape[0]], sha256=hashlib.sha256(images["overview"]).hexdigest(),
                    quality=quality, stability=deepcopy(stability), current=True, visibility_verified=False,
                    electrical_verified=False, wiring_target=deepcopy(vars(body)))
    return _finish_views(images, metadata)


def capture_debug_evidence(state, target="overview", *, wiring_target=None, response_mode="fast", earliest_ms=None, seconds=.65,
                           clock=time.monotonic, sleep=time.sleep):
    """Select new immutable source views, with validated current pin crops when available.

    Earliest time is PC monotonic milliseconds. A caller can demand a later event,
    but cannot permit pre-request images. Framing warnings remain visible metadata.
    """
    if target not in TARGETS:
        raise DebugCaptureError("unsupported_capture_target")
    if response_mode not in {"fast", "thorough"}:
        raise DebugCaptureError("invalid_response_mode")
    body = _wiring_body(wiring_target) if wiring_target is not None else None
    started = clock()
    earliest_ms = max(started*1000, earliest_ms if earliest_ms is not None else 0)
    revision = _runtime(state)
    binding = _source_binding(state)
    duration = min(1., max(0., float(seconds)))
    best = None
    previous = None
    seen = set()
    reports = []
    for index in range(9):
        sleep(max(0., started + duration*index/8-clock()))
        try:
            slot = _slot(state, revision, binding, earliest_ms, clock)
        except DebugCaptureError as error:
            if str(error) in {"camera_frame_unavailable", "camera_frame_not_new"}:
                continue
            raise
        if slot.seq in seen:
            continue
        seen.add(slot.seq)
        thumb = _thumbnail(slot.frame)
        difference = float(cv2.absdiff(previous, thumb).mean()) if previous is not None else None
        previous = thumb
        stability = {"mean_difference": round(difference, 3) if difference is not None else None,
                     "stable": difference is not None and difference <= 8., "heuristic": True}
        quality = image_quality(slot.frame)
        quality["framing_ready"] = stability["stable"] and not quality["warnings"]
        located = None
        if body is not None:
            try:
                located = _located_candidate(state, body, earliest_ms, clock)
            except (ValueError, KeyError, TypeError, AttributeError):
                pass
            _check_binding(state, revision, binding)
        endpoint_quality = _quality_sources(located[0], (body.board_pin, body.component_pin)) if located else []
        reports.append({"frame_id": slot.frame_id, "seq": slot.seq, "quality": quality, "stability": stability,
                        "mode": "pin_crops" if located else "overview", "endpoint_quality": endpoint_quality})
        rank = (located is not None, quality["framing_ready"],
                min(item["score"] for item in endpoint_quality) if endpoint_quality else quality["score"])
        if best is None or rank >= best[0]:
            # FrameSlot is immutable but ndarray need not be: encode while selected.
            encoded = _encode_located(state, body, located, revision, binding[1], target, stability, response_mode) if located else _encode(slot, revision, binding[1], target, quality, stability)
            best = (rank, encoded, len(reports)-1)
    _check_binding(state, revision, binding)
    if best is None:
        raise DebugCaptureError("camera_frame_not_new")
    images, metadata = best[1]
    if body is not None:
        metadata["wiring_target"] = deepcopy(vars(body))
    metadata["selection"] = {"method": "debug_post_request_burst_v1", "requested_ts_ms": earliest_ms,
                             "candidate_count": len(reports), "selected_index": best[2], "candidates": reports,
                             "elapsed_ms": round((clock() - started) * 1000, 1)}
    return images, metadata


def inspect_debug_wiring(wiring_target, images, metadata, *, generate, model, effort,
                         locale="zh-TW", timeout_s=210, progress=lambda *_: None):
    """Reuse independent endpoints/optional localization through a budgeted caller.

    `generate(prompt, schema, **kwargs)` MUST be the session's budget/accounting
    hook. This helper never obtains a bridge or bypasses the session's call cap.
    Newly localized source crops are returned for the same evidence attachment.
    """
    from app.cloud_connector_inspection import run_inspection
    body = _wiring_body(wiring_target)
    if metadata.get("wiring_target") != vars(body):
        raise DebugCaptureError("capture_wiring_target_changed")
    body.model, body.effort, body.locale = model, effort, locale
    capture = deepcopy(metadata)
    prepared = dict(images)
    if "overview" not in prepared or metadata.get("source") != "device":
        raise DebugCaptureError("physical_webcam_frame_required")
    # Existing endpoint inspection uses pi_overview, debug cards use overview.
    prepared["pi_overview"] = prepared.pop("overview")
    for view in capture["views"]:
        if view["name"] == "overview":
            view["name"] = "pi_overview"
        if view.get("source_view") == "overview":
            view["source_view"] = "pi_overview"
    with tempfile.TemporaryDirectory(prefix="boardvision-debug-wiring-") as directory:
        paths = {}
        for name, data in prepared.items():
            # View names originate only from our capture helpers, not the model.
            if not name.replace("_", "").isalnum():
                raise DebugCaptureError("invalid_capture_view")
            extension = ".png" if data.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg"
            path = Path(directory) / (name + extension)
            path.write_bytes(data)
            paths[name] = path
        result, issues, stages = run_inspection(SimpleNamespace(generate=generate), body, paths,
            capture=capture, timeout_s=timeout_s, progress=progress)
        prepared = {name: path.read_bytes() for name, path in paths.items()}
    prepared["overview"] = prepared.pop("pi_overview")
    for view in capture["views"]:
        if view["name"] == "pi_overview":
            view["name"] = "overview"
        if view.get("source_view") == "pi_overview":
            view["source_view"] = "overview"
    prepared, capture = _finish_views(prepared, capture)
    return dict(opinion=result.model_dump(), consistency_issues=issues, stages=stages,
                images=prepared, metadata=capture)


class TFTPhaseSampler:
    """Concurrent camera sampler; observed phases are candidates until marker match.

    Polls only in-memory ComponentTests snapshots, never SSH. A phase event is not
    proof of what the camera saw; the observer must read its secret visual marker.
    """
    def __init__(self, state, tests, run_id, *, max_seconds=45., interval_s=.2,
                 max_frames=24, max_bytes=MAX_BYTES, clock=time.monotonic):
        self.state, self.tests, self.run_id = state, tests, run_id
        self.clock = clock
        self.revision = _runtime(state)
        self.binding = _source_binding(state)
        self.started = clock()
        self.max_seconds = min(45., max(0., max_seconds))
        self.interval_s = max(.2, interval_s)
        self.max_frames = min(24, max(1, max_frames))
        self.max_bytes = min(MAX_BYTES, max(1, max_bytes))
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.thread = None
        self.records = []
        self.last_seq = -1
        self.previous = None
        self.error = None

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name="debug-tft-camera", daemon=True)
            self.thread.start()
        return self

    def tick(self):
        if self.done.is_set() or self.clock()-self.started > self.max_seconds:
            self.done.set()
            return
        try:
            _check_binding(self.state, self.revision, self.binding)
        except DebugCaptureError as error:
            self.error = str(error)
            self.done.set()
            return
        snapshot = self.tests.snapshot()
        run = next((r for r in snapshot["results"] if r["id"] == self.run_id), None)
        if run is None or not run.get("reserved") or run.get("invalidated"):
            self.done.set()
            return
        if run.get("phase") == "awaiting_visual":
            self.done.set()
            return
        stage = run.get("camera_phase")
        if not stage or stage.get("run_id") != self.run_id or run.get("outcome") != "running":
            return
        # Wait for a new source exposure after observing a committed stage.
        earliest = max(self.started*1000, stage["received_monotonic_ms"] + 150)
        try:
            slot = _slot(self.state, self.revision, self.binding, earliest, self.clock)
        except DebugCaptureError as error:
            if str(error) not in {"camera_frame_unavailable", "camera_frame_not_new"}:
                self.error = str(error)
                self.done.set()
            return
        if slot.seq <= self.last_seq:
            return
        self.last_seq = slot.seq
        thumb = _thumbnail(slot.frame)
        difference = float(cv2.absdiff(thumb, self.previous).mean()) if self.previous is not None else None
        self.previous = thumb
        quality = image_quality(slot.frame)
        stability = {"stable": difference is not None and difference <= 8., "mean_difference": difference, "heuristic": True}
        images, metadata = _encode(slot, self.revision, self.binding[1], "tft_screen", quality, stability)
        try:
            _check_binding(self.state, self.revision, self.binding)
        except DebugCaptureError as error:
            self.error = str(error)
            self.done.set()
            return
        metadata.update(run_id=self.run_id, phase_seq=stage["seq"], phase=stage["phase"],
                        phase_evidence=deepcopy(stage), phase_association="candidate_requires_marker",
                        verification_source="camera_advisory", human_confirmation_required=True)
        with self.lock:
            if self.done.is_set():
                return
            self.records.append((images, metadata))
            # Keep up to three sharp distinct frames per phase, all bounded globally.
            same = [r for r in self.records if r[1]["phase_seq"] == stage["seq"]]
            if len(same) > 3:
                worst = min(same, key=lambda r: (r[1]["stability"]["stable"], r[1]["quality"]["score"]))
                self.records.remove(worst)
            while (len(self.records) > self.max_frames or
                   sum(len(b) for imgs, _ in self.records for b in imgs.values()) > self.max_bytes):
                self.records.pop(0)

    def _loop(self):
        try:
            while not self.done.is_set():
                self.tick()
                self.done.wait(self.interval_s)
        except Exception as error:
            self.error = str(error)
            self.done.set()

    def stop(self):
        self.done.set()
        if self.thread is not None:
            self.thread.join(2)
        with self.lock:
            return deepcopy(self.records)

    def snapshot(self):
        with self.lock:
            return deepcopy(self.records)
