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
import threading
import time
import uuid

import cv2
import numpy as np

from app.wiring_capture import image_quality

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
        "current": True, "visibility_verified": False, "electrical_verified": False,
        "views": [{"name": "overview", "frame_id": slot.frame_id, "seq": slot.seq,
                   "ts_ms": slot.ts_ms, "size": [slot.frame.shape[1], slot.frame.shape[0]],
                   "encoding": "jpeg", "sha256": hashlib.sha256(raw).hexdigest()}],
    }
    return {"overview": raw}, metadata


def capture_debug_evidence(state, target="overview", *, earliest_ms=None, seconds=.65,
                           clock=time.monotonic, sleep=time.sleep):
    """Select one new immutable overview; no uncertain detector crops are invented.

    Earliest time is PC monotonic milliseconds. A caller can demand a later event,
    but cannot permit pre-request images. Framing warnings remain visible metadata.
    """
    if target not in TARGETS:
        raise DebugCaptureError("unsupported_capture_target")
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
        reports.append({"frame_id": slot.frame_id, "seq": slot.seq, "quality": quality, "stability": stability})
        rank = (quality["framing_ready"], quality["score"])
        if best is None or rank >= best[0]:
            # FrameSlot is immutable but ndarray need not be: encode while selected.
            best = (rank, _encode(slot, revision, binding[1], target, quality, stability), len(reports)-1)
    _check_binding(state, revision, binding)
    if best is None:
        raise DebugCaptureError("camera_frame_not_new")
    images, metadata = best[1]
    metadata["selection"] = {"method": "debug_post_request_burst_v1", "requested_ts_ms": earliest_ms,
                             "candidate_count": len(reports), "selected_index": best[2], "candidates": reports}
    return images, metadata


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
