"""Tests for the M17 wire-trace real-time integration:

- app.vision.wire_state.WireTraceState (thread-safe latest-value holder)
- app.wire_worker.WireTraceWorker (throttled worker thread + WS publish)
- app.config.WireTraceConfig (defaults, YAML, env override)
- app.main.build_app's `wire_worker` injection seam
- the "wire_trace" WS message shape (docs/api-contract.md §2)

Same injection-seam pattern as tests/test_backend_core.py: a local stub
detector + stub frame source are injected through build_app()'s existing
seams (never touches app.vision.factory / app.vision.synthetic).
app.vision.wire_tracer.trace itself is monkeypatched for the worker/WS
tests - it does real CV work on real pixels; a canned WireTraceResult
exercises the throttling/threading/message-shape contract without needing a
frame with a real wire in it.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.capture.bus import FrameBus
from app.config import AppConfig, ComponentVisionConfig, WireTraceConfig, load_config
from app.main import build_app
from app.vision import wire_tracer
from app.vision.interface import DetectionResult, PinDetection
from app.vision.wire_state import WireTraceState
from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult
from app.vision_worker import DetectionState
from app.wire_worker import (
    DEFAULT_RUNTIME_MIN_PIN_PITCH_PX,
    DEFAULT_RUNTIME_MIN_PX_PER_MM,
    WireTraceWorker,
    wire_trace_message,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VIDEO_W, VIDEO_H = 64, 48


# ---------------------------------------------------------------- stubs ----

class StubFrameSource:
    """Implements the FrameSource protocol; emits small frames at ~200 fps."""

    def __init__(self, width: int = VIDEO_W, height: int = VIDEO_H) -> None:
        self._w, self._h = width, height
        self._frame_id = 0
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self):
        time.sleep(0.005)
        self._frame_id += 1
        frame = np.full((self._h, self._w, 3), 32, dtype=np.uint8)
        return frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        self.closed = True


class LockedDetector:
    """Implements the BoardDetector protocol; always reports tracking="locked"
    with one pin - enough for WireTraceWorker to get past its
    tracking=="searching" skip."""

    def __init__(self, board_id: str = "mini-board") -> None:
        self._board_id = board_id
        self.loaded = False
        self.closed = False

    def load(self, profile, profile_dir: Path) -> None:
        self.loaded = True

    def detect(self, frame_bgr, frame_id: int, ts_ms: float) -> DetectionResult:
        return DetectionResult(
            board_id=self._board_id,
            frame_id=frame_id,
            ts_ms=ts_ms,
            tracking="locked",
            confidence=0.9,
            pins=[PinDetection(pin_id="D3", x=10.0, y=5.0, confidence=0.97, visible=True)],
        )

    def close(self) -> None:
        self.closed = True


class SpyWireWorker:
    """Minimal start()/stop() spy - lets main.py's lifespan wiring be tested
    without any real camera/CV, mirroring why detector/source are injectable."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float = 5.0) -> None:
        self.stopped = True


def make_config(**overrides) -> AppConfig:
    values = dict(
        server={"host": "127.0.0.1", "port": 8100},
        camera={"source": "synthetic", "device_index": 0, "width": VIDEO_W, "height": VIDEO_H, "fps": 60},
        wire_trace={"enabled": True, "interval_s": 0.02, "colors": ["red"]},
        detector="mock",
        component_vision=ComponentVisionConfig(),
        board="mini-board",
        profile_dir=FIXTURES,
        frontend_dist=FIXTURES / "no-such-dist",
        default_locale="zh-TW",
        jpeg_quality=70,
        detection_hz=60,
    )
    values.update(overrides)
    return AppConfig(**values)


def _canned_result() -> WireTraceResult:
    """Exactly the example in docs/api-contract.md §2 / the task's wire_trace shape."""
    return WireTraceResult(
        frame_id=18234,
        ts_ms=1721990000123.5,
        board_tracking="locked",
        wires=[
            WireInstance(
                wire_id=0,
                color="red",
                path_px=[(520.1, 240.2), (540.5, 238.9), (601.2, 235.0)],
                endpoint_a=WireEndpoint(kind="pin", px=(520.1, 240.2), pin_id="5V", confidence=0.9),
                endpoint_b=WireEndpoint(kind="floating", px=(700.1, 190.4), confidence=0.0),
                confidence=0.87,
                ambiguous=False,
            )
        ],
    )


def _locked_detection_state(pin_id: str = "5V", x: float = 10.0, y: float = 10.0) -> DetectionState:
    state = DetectionState()
    state.set(
        DetectionResult(
            board_id="mini-board",
            frame_id=1,
            ts_ms=0.0,
            tracking="locked",
            confidence=0.9,
            pins=[PinDetection(pin_id=pin_id, x=x, y=y, confidence=0.9, visible=True)],
        )
    )
    return state


# ------------------------------------------------------------ WireTraceState ----

def test_wire_trace_state_get_set():
    state = WireTraceState()
    assert state.get() is None
    result = _canned_result()
    state.set(result)
    assert state.get() is result


def test_wire_trace_state_thread_safety():
    state = WireTraceState()
    errors: list[Exception] = []

    def writer(i: int) -> None:
        try:
            for _ in range(200):
                state.set(WireTraceResult(frame_id=i, ts_ms=float(i), board_tracking="locked", wires=[]))
        except Exception as exc:  # pragma: no cover - would fail the test anyway
            errors.append(exc)

    def reader() -> None:
        try:
            for _ in range(200):
                state.get()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    threads += [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    assert not errors
    assert state.get() is not None


# ------------------------------------------------------------ message shape ----

def test_wire_trace_message_shape_matches_api_contract():
    msg = wire_trace_message(_canned_result(), board_id="arduino-uno-q")
    assert msg == {
        "type": "wire_trace",
        "board_id": "arduino-uno-q",
        "frame_id": 18234,
        "ts_ms": 1721990000123.5,
        "board_tracking": "locked",
        "wires": [
            {
                "wire_id": 0,
                "color": "red",
                "confidence": 0.87,
                "ambiguous": False,
                "detection_methods": ["color"],
                "path": [[520.1, 240.2], [540.5, 238.9], [601.2, 235.0]],
                "endpoint_a": {"kind": "pin", "pin_id": "5V", "confidence": 0.9},
                "endpoint_b": {"kind": "floating", "px": [700.1, 190.4], "confidence": 0.0},
            }
        ],
    }


def test_wire_trace_message_ambiguous_tie_shape():
    result = WireTraceResult(
        frame_id=1,
        ts_ms=100.0,
        board_tracking="locked",
        wires=[
            WireInstance(
                wire_id=0,
                color="green",
                path_px=[(1.0, 2.0)],
                endpoint_a=WireEndpoint(kind="ambiguous_tie", px=(1.0, 2.0), candidates=["D7", "D8"]),
                endpoint_b=WireEndpoint(kind="pin", px=(3.0, 4.0), pin_id="D9", confidence=0.5),
                confidence=0.3,
                ambiguous=True,
            )
        ],
    )
    msg = wire_trace_message(result, board_id="arduino-uno-q")
    wire = msg["wires"][0]
    assert wire["endpoint_a"] == {
        "kind": "ambiguous_tie", "px": [1.0, 2.0], "candidates": ["D7", "D8"], "confidence": 0.0,
    }
    assert wire["endpoint_b"] == {"kind": "pin", "pin_id": "D9", "confidence": 0.5}
    assert wire["ambiguous"] is True


def test_live_wire_message_exposes_normalized_coordinates_and_geometry_candidate():
    result = WireTraceResult(
        frame_id=2,
        ts_ms=200.0,
        board_tracking="locked",
        video_size=(1000, 500),
        wires=[WireInstance(
            wire_id=0,
            color="red",
            path_px=[(100.0, 50.0), (900.0, 250.0)],
            endpoint_a=WireEndpoint(
                kind="pin", px=(100.0, 50.0), pin_id="D7", confidence=0.8,
                distance_px=3.0, margin_px=7.0,
            ),
            endpoint_b=WireEndpoint(
                kind="pin", px=(900.0, 250.0), pin_id="D8", confidence=0.7,
                distance_px=4.0, margin_px=5.0,
            ),
            confidence=0.75,
            ambiguous=False,
        )],
    )
    wire = wire_trace_message(result, board_id="arduino-uno-q")["wires"][0]
    assert wire["path_normalized"] == [[0.1, 0.1], [0.9, 0.5]]
    assert wire["endpoint_a"]["normalized_px"] == [0.1, 0.1]
    assert wire["endpoint_a"]["margin_px"] == 7.0
    assert wire["connection"] == {
        "status": "candidate",
        "pin_ids": ["D7", "D8"],
        "endpoint_kinds": ["pin", "pin"],
        "confidence": 0.75,
        "endpoints": [
            {"object_id": "arduino-uno-q", "pin": "D7", "kind": "pin", "position": [0.1, 0.1]},
            {"object_id": "arduino-uno-q", "pin": "D8", "kind": "pin", "position": [0.9, 0.5]},
        ],
    }


def test_live_pin_position_uses_projected_pin_not_raw_wire_terminal():
    """Resolved connection coordinates must be canonical pin coordinates.

    The raw skeleton terminal can stop several pixels short of a ferrule/pin
    center.  It remains useful internally for attachment motion, but a
    normalized API connection position must point to the live projected pin.
    """
    result = WireTraceResult(
        frame_id=5,
        ts_ms=500.0,
        board_tracking="locked",
        video_size=(1000, 500),
        pin_positions={"D7": (120.0, 80.0), "D8": (880.0, 240.0)},
        wires=[WireInstance(
            wire_id=0,
            color="red",
            path_px=[(100.0, 50.0), (900.0, 250.0)],
            endpoint_a=WireEndpoint(
                kind="pin", px=(100.0, 50.0), pin_id="D7", confidence=0.8,
                distance_px=3.0,
            ),
            endpoint_b=WireEndpoint(
                kind="pin", px=(900.0, 250.0), pin_id="D8", confidence=0.7,
                distance_px=4.0,
            ),
            confidence=0.75,
            ambiguous=False,
        )],
    )

    wire = wire_trace_message(result, board_id="arduino-uno-q")["wires"][0]

    assert wire["endpoint_a"]["normalized_px"] == [0.12, 0.16]
    assert wire["endpoint_b"]["normalized_px"] == [0.88, 0.48]
    assert wire["connection"]["endpoints"] == [
        {"object_id": "arduino-uno-q", "pin": "D7", "kind": "pin", "position": [0.12, 0.16]},
        {"object_id": "arduino-uno-q", "pin": "D8", "kind": "pin", "position": [0.88, 0.48]},
    ]


def test_live_unknown_attachment_is_not_reported_as_connection_candidate():
    result = WireTraceResult(
        frame_id=4, ts_ms=400.0, board_tracking="locked", video_size=(1000, 500),
        wires=[WireInstance(
            wire_id=0, color="red", path_px=[(100.0, 50.0), (900.0, 250.0)],
            endpoint_a=WireEndpoint(kind="pin", px=(100.0, 50.0), pin_id="D7", confidence=0.8),
            endpoint_b=WireEndpoint(kind="pin", px=(900.0, 250.0), pin_id="D8", confidence=0.7),
            confidence=0.75, ambiguous=False, attachment="unknown",
        )],
    )
    wire = wire_trace_message(result, board_id="arduino-uno-q")["wires"][0]
    assert wire["connection"]["status"] == "uncertain"
    assert wire["attachment"] == "unknown"


def test_live_wire_message_exposes_scale_sanity_geometry():
    result = WireTraceResult(
        frame_id=3, ts_ms=300.0, board_tracking="locked",
        geometry={
            "pitch_px": 10.3,
            "px_per_mm": 4.0551,
            "snap_radius_px": 15.965,
            "snap_radius_over_pitch": 1.55,
        },
    )
    msg = wire_trace_message(result, board_id="arduino-uno-q")
    assert msg["geometry"] == {
        "pitch_px": 10.3,
        "px_per_mm": 4.0551,
        "snap_radius_px": 15.965,
        "snap_radius_over_pitch": 1.55,
    }


def test_wire_trace_message_exposes_scale_suppression_reason():
    result = WireTraceResult(
        frame_id=3, ts_ms=300.0, board_tracking="locked", wires=[],
        suppressed_reason="scale_below_minimum",
    )
    msg = wire_trace_message(result, board_id="arduino-uno-q")
    assert msg["suppressed_reason"] == "scale_below_minimum"


def test_runtime_physical_scale_gate_suppresses_low_pitch_trace(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(wire_tracer, "trace", lambda *a, **k: calls.append(1))

    bus = FrameBus()
    detection_state = _locked_detection_state()
    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=WireTraceState(),
        board_id="mini-board", publish=None, interval_s=0.01, colors=["red"],
        min_pin_pitch_px=DEFAULT_RUNTIME_MIN_PIN_PITCH_PX,
    )
    frame = np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
    worker.start()
    try:
        bus.put(frame, 1, 1.0)
        deadline = time.monotonic() + 1.0
        while worker._state.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        result = worker._state.get()
    finally:
        worker.stop()

    # The one-pin fixture has no measurable lattice pitch. In physical mode
    # that is deliberately blocked rather than treated as an empty scene.
    assert result is not None
    assert result.suppressed_reason == "scale_below_minimum"
    assert result.wires == []
    assert result.geometry is not None
    assert result.geometry["min_pitch_px"] == DEFAULT_RUNTIME_MIN_PIN_PITCH_PX
    assert calls == []


def test_runtime_scale_gate_also_rejects_low_pixel_density(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(wire_tracer, "trace", lambda *a, **k: calls.append(1))

    bus = FrameBus()
    detection_state = DetectionState()
    detection_state.set(DetectionResult(
        board_id="mini-board", frame_id=1, ts_ms=0.0,
        tracking="locked", confidence=0.9,
        pins=[
            PinDetection("D3", 10.0, 5.0, 0.9, header="J", index=0),
            PinDetection("D4", 29.0, 5.0, 0.9, header="J", index=1),
        ],
    ))
    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=WireTraceState(),
        board_id="mini-board", publish=None, interval_s=0.01, colors=["red"],
        min_pin_pitch_px=18.0, min_px_per_mm=8.0,
    )
    worker.start()
    try:
        bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 1, 1.0)
        deadline = time.monotonic() + 1.0
        while worker._state.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        result = worker._state.get()
    finally:
        worker.stop()

    # 19 px / 2.54 mm is ~7.48 px/mm: it clears the 18px pitch floor but
    # remains below the independent physical density requirement.
    assert result is not None
    assert result.suppressed_reason == "scale_below_minimum"
    assert calls == []


# ------------------------------------------------------------ worker behavior ----

def test_wire_trace_worker_skips_when_searching(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(wire_tracer, "trace", lambda *a, **k: calls.append(1))

    bus = FrameBus()
    detection_state = DetectionState()  # None -> nothing to snap against yet
    wire_state = WireTraceState()
    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=wire_state,
        board_id="mini-board", publish=None, interval_s=0.02, colors=["red"],
    )
    worker.start()
    try:
        frame = np.zeros((VIDEO_H, VIDEO_W, 3), np.uint8)
        bus.put(frame, 1, 1.0)
        time.sleep(0.15)
        assert calls == []  # detection_state.get() is None -> never called

        detection_state.set(
            DetectionResult(board_id="mini-board", frame_id=1, ts_ms=0.0, tracking="searching", confidence=0.0, pins=[])
        )
        bus.put(frame, 2, 2.0)
        time.sleep(0.15)
        assert calls == []  # tracking=="searching" -> still skipped
    finally:
        worker.stop()


def test_wire_trace_rejects_pose_from_a_different_frame():
    bus = FrameBus()
    frame = np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
    bus.put(frame, 2, 2.0)
    slot = bus.get_latest(timeout=0.0)
    assert slot is not None

    worker = WireTraceWorker(
        bus=bus,
        detection_state=_locked_detection_state(),  # detection is frame 1
        state=WireTraceState(),
        board_id="mini-board",
        interval_s=0.01,
    )
    matched_slot, detection = worker._synchronize_detection(slot)
    assert matched_slot is None and detection is None
    worker.stop()


def test_wire_trace_uses_detection_states_exact_source_frame_when_bus_is_ahead():
    bus = FrameBus()
    frame_1 = np.full((VIDEO_H, VIDEO_W, 3), 11, dtype=np.uint8)
    frame_2 = np.full((VIDEO_H, VIDEO_W, 3), 22, dtype=np.uint8)
    bus.put(frame_1, 1, 1.0)
    slot_1 = bus.get_latest(timeout=0.0)
    assert slot_1 is not None
    detection_state = DetectionState()
    detection = DetectionResult(
        board_id="mini-board",
        frame_id=1,
        ts_ms=1.0,
        tracking="locked",
        confidence=0.9,
        pins=[PinDetection("D3", 10.0, 5.0, 0.9, True)],
    )
    detection_state.set(detection, slot_1)
    bus.put(frame_2, 2, 2.0)
    latest = bus.get_latest(timeout=0.0)
    assert latest is not None and latest.frame_id == 2

    worker = WireTraceWorker(
        bus=bus,
        detection_state=detection_state,
        state=WireTraceState(),
        board_id="mini-board",
        interval_s=0.01,
    )
    matched_slot, matched_detection = worker._synchronize_detection(
        latest, newer_than=-1
    )

    assert matched_slot is slot_1
    assert matched_detection is detection
    assert int(matched_slot.frame[0, 0, 0]) == 11
    worker.stop()


def test_trace_can_retain_board_disconnected_fragment_for_private_geometry(monkeypatch):
    branch = wire_tracer.SkeletonBranch(
        color="yellow",
        points=[(40 + index, 30) for index in range(30)],
    )
    monkeypatch.setattr(
        wire_tracer,
        "trace_wires",
        lambda *args, **kwargs: {"yellow": [branch]},
    )
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    pins = [PinDetection("D3", 5.0, 5.0, 0.9, True)]

    public = wire_tracer.trace(frame, pins, 1, 1.0, "locked", colors=["yellow"])
    private = wire_tracer.trace(
        frame,
        pins,
        1,
        1.0,
        "locked",
        colors=["yellow"],
        include_floating=True,
    )

    assert public.wires == []
    assert len(private.wires) == 1
    assert private.wires[0].endpoint_a.kind == "floating"
    assert private.wires[0].endpoint_b.kind == "floating"


def test_wire_trace_worker_respects_interval_not_per_frame(monkeypatch):
    call_times: list[float] = []

    def fake_trace(frame_bgr, pins, frame_id, ts_ms, board_tracking, colors=None, board_outline=None, include_edge_agnostic=False):
        call_times.append(time.monotonic())
        return WireTraceResult(frame_id=frame_id, ts_ms=ts_ms, board_tracking=board_tracking, wires=[])

    monkeypatch.setattr(wire_tracer, "trace", fake_trace)

    bus = FrameBus()
    detection_state = _locked_detection_state()
    wire_state = WireTraceState()
    interval_s = 0.1
    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=wire_state,
        board_id="mini-board", publish=None, interval_s=interval_s, colors=["red"],
    )

    stop_pushing = threading.Event()

    def push_frames() -> None:
        i = 0
        frame = np.zeros((VIDEO_H, VIDEO_W, 3), np.uint8)
        while not stop_pushing.is_set():
            i += 1
            # This test exercises cadence, not pose/frame registration. Keep
            # the fixture's detection frame_id aligned with the repeated
            # frame while FrameBus.seq still advances on every put().
            bus.put(frame, 1, time.monotonic() * 1000.0)
            time.sleep(0.002)  # ~500 fps - much faster than interval_s

    pusher = threading.Thread(target=push_frames, daemon=True)
    pusher.start()
    worker.start()
    try:
        time.sleep(0.55)
    finally:
        worker.stop()
        stop_pushing.set()
        pusher.join(timeout=2.0)

    # ~duration/interval_s ticks expected (~5-6); nowhere near "one call per
    # frame push" (which would be >100 calls over 0.55s at ~500 fps).
    assert 2 <= len(call_times) <= 8, call_times
    if len(call_times) >= 2:
        gaps = [b - a for a, b in zip(call_times, call_times[1:])]
        assert all(gap >= interval_s * 0.5 for gap in gaps), gaps


def test_wire_trace_worker_survives_trace_exception(monkeypatch):
    call_count = {"n": 0}

    def flaky_trace(frame_bgr, pins, frame_id, ts_ms, board_tracking, colors=None, board_outline=None, include_edge_agnostic=False):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        return WireTraceResult(frame_id=frame_id, ts_ms=ts_ms, board_tracking=board_tracking, wires=[])

    monkeypatch.setattr(wire_tracer, "trace", flaky_trace)

    bus = FrameBus()
    detection_state = _locked_detection_state()
    wire_state = WireTraceState()
    published: list[dict] = []
    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=wire_state,
        board_id="mini-board", publish=published.append, interval_s=0.02, colors=["red"],
    )

    stop_pushing = threading.Event()

    def push_frames() -> None:
        i = 0
        frame = np.zeros((VIDEO_H, VIDEO_W, 3), np.uint8)
        while not stop_pushing.is_set():
            i += 1
            bus.put(frame, 1, time.monotonic() * 1000.0)
            time.sleep(0.005)

    pusher = threading.Thread(target=push_frames, daemon=True)
    pusher.start()
    worker.start()
    try:
        deadline = time.monotonic() + 3.0
        while wire_state.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)

        assert wire_state.get() is not None, "worker died instead of surviving the exception"
        assert call_count["n"] >= 2, "worker never retried after the exception"
        assert published and published[-1]["type"] == "wire_trace"
    finally:
        worker.stop()
        stop_pushing.set()
        pusher.join(timeout=2.0)


# ------------------------------------------------------------------ config ----

def test_wire_trace_config_defaults():
    cfg = WireTraceConfig()
    assert cfg.enabled is True
    assert cfg.interval_s == 0.5
    assert cfg.guidance_interval_s == 0.3
    assert cfg.colors == ["red", "yellow", "green", "brown", "blue"]
    assert cfg.min_pin_pitch_px is None
    assert cfg.min_px_per_mm is None


def test_wire_trace_config_loads_from_yaml():
    cfg = load_config()
    assert cfg.wire_trace.enabled is True
    assert cfg.wire_trace.interval_s == 0.5
    assert cfg.wire_trace.guidance_interval_s == 0.3
    assert cfg.wire_trace.colors == ["red", "yellow", "green", "brown", "blue"]


def test_wire_trace_config_env_override(monkeypatch):
    monkeypatch.setenv("BOARDVISION_WIRE_TRACE__INTERVAL_S", "1.0")
    cfg = load_config()
    assert cfg.wire_trace.interval_s == 1.0
    # untouched fields still come from the YAML
    assert cfg.wire_trace.enabled is True
    assert cfg.wire_trace.colors == ["red", "yellow", "green", "brown", "blue"]


# ------------------------------------------------------------ build_app wiring ----

def test_build_app_wire_worker_injection_start_stop_symmetry():
    spy = SpyWireWorker()
    app = build_app(
        make_config(),
        detector=LockedDetector(),
        source=StubFrameSource(),
        wire_worker=spy,
    )
    assert app.state.wire_worker is spy
    with TestClient(app):
        assert spy.started is True
        assert spy.stopped is False
    assert spy.stopped is True


def test_build_app_enables_scale_gate_for_real_pipeline_source():
    config = make_config(
        detector="pipeline",
        camera={
            "source": "device", "device_index": 1,
            "width": VIDEO_W, "height": VIDEO_H, "fps": 30,
        },
    )
    app = build_app(
        config,
        detector=LockedDetector(),
        source=StubFrameSource(),
    )
    with TestClient(app):
        worker = app.state.wire_worker
        assert worker is not None
        assert worker._min_pin_pitch_px == DEFAULT_RUNTIME_MIN_PIN_PITCH_PX
        assert worker._min_px_per_mm == DEFAULT_RUNTIME_MIN_PX_PER_MM


def test_build_app_disabled_wire_trace_builds_no_worker():
    app = build_app(
        make_config(wire_trace={"enabled": False, "interval_s": 0.5, "colors": ["red"]}),
        detector=LockedDetector(),
        source=StubFrameSource(),
    )
    with TestClient(app):
        assert app.state.wire_worker is None


# ------------------------------------------------------------------ WS round trip ----

def test_wire_trace_ws_message_round_trip(monkeypatch):
    def fake_trace(frame_bgr, pins, frame_id, ts_ms, board_tracking, colors=None, board_outline=None, include_edge_agnostic=False):
        return _canned_result()

    monkeypatch.setattr(wire_tracer, "trace", fake_trace)

    app = build_app(
        make_config(),
        detector=LockedDetector(board_id="mini-board"),
        source=StubFrameSource(),
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws/detections") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"

            wire_msg = None
            for _ in range(200):
                msg = ws.receive_json()
                if msg.get("type") == "wire_trace" and msg.get("wires"):
                    wire_msg = msg
                    break

            assert wire_msg is not None, "no wire_trace message received"
            assert wire_msg == {
                "type": "wire_trace",
                "board_id": "mini-board",
                "frame_id": 18234,
                "ts_ms": 1721990000123.5,
                "board_tracking": "locked",
                "wires": [
                    {
                        "wire_id": 0,
                        "color": "red",
                        "confidence": 0.87,
                        "ambiguous": False,
                        "detection_methods": ["color"],
                        "path": [[520.1, 240.2], [540.5, 238.9], [601.2, 235.0]],
                        "endpoint_a": {"kind": "pin", "pin_id": "5V", "confidence": 0.9},
                        "endpoint_b": {"kind": "floating", "px": [700.1, 190.4], "confidence": 0.0},
                    }
                ],
            }
