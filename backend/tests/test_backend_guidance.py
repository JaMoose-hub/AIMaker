"""Tests for the M22/M23 guided-wiring checkmark engine:

- app.vision.guidance.evaluate_guidance_step (pure classical verdict logic,
  including the M23 boundary cases: ambiguous_tie touching the target pin,
  and 2+ new endpoints in one tick)
- app.vision.guidance.GuidanceState (thread-safe holder, stale-result drop)
- the "guidance_check" WS message shape
- the /api/guidance REST endpoints via build_app's existing injection seams
- WireTraceWorker's per-tick guidance evaluation + publish

Same stub/injection pattern as test_backend_wire_trace.py; wire_tracer.trace
is monkeypatched for worker tests (real CV is exercised elsewhere).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture.bus import FrameBus
from app.component_worker import ComponentPinPosition, ComponentPoseResult, ComponentPoseState
from app.config import AppConfig, ComponentVisionConfig
from app.main import build_app
from app.vision import wire_tracer
from app.vision.guidance import (
    GuidanceResult,
    GuidanceState,
    GuidanceStep,
    GuidanceVerdictDebouncer,
    evaluate_guidance_step,
    occupied_pin_ids,
)
from app.vision.interface import DetectionResult, PinDetection
from app.vision.wire_state import WireTraceState
from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult
from app.vision_worker import DetectionState
from app.verification.state import VerificationState
from app.wire_worker import (
    WireTraceWorker,
    guidance_check_message,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VIDEO_W, VIDEO_H = 64, 48


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


class StubFrameSource:
    def __init__(self, width: int = VIDEO_W, height: int = VIDEO_H) -> None:
        self._w, self._h = width, height
        self._frame_id = 0

    def open(self) -> None:
        pass

    def read(self):
        time.sleep(0.005)
        self._frame_id += 1
        frame = np.full((self._h, self._w, 3), 32, dtype=np.uint8)
        return frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        pass


class LockedDetector:
    def __init__(self, board_id: str = "mini-board") -> None:
        self._board_id = board_id

    def load(self, profile, profile_dir: Path) -> None:
        pass

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
        pass


class FakeInsertionVlmWorker:
    def __init__(self) -> None:
        self.running = False
        self.calls = []
        self.queued_step_id = None
        self.last_outcome = None

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def submit(self, step, frame, detection, component_pose) -> bool:
        self.calls.append((step, frame, detection, component_pose))
        self.queued_step_id = step.step_id
        self.last_outcome = {"step_id": step.step_id, "status": "queued"}
        return True

    def diagnostics(self) -> dict:
        return {
            "running": self.running,
            "queued_step_id": self.queued_step_id,
            "inflight_step_id": None,
            "submitted_step_ids": sorted({call[0].step_id for call in self.calls}),
            "last_outcome": self.last_outcome,
        }


class FakeWireColorVlmWorker:
    def __init__(self) -> None:
        self.running = False
        self.calls = []
        self.queued = False
        self.inflight = False
        self.last_outcome = None

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def submit(self, step, frame, detection, component_pose, *, frame_id: int) -> bool:
        self.calls.append((step, frame, detection, component_pose, frame_id))
        self.queued = True
        self.last_outcome = {"step_id": step.step_id, "status": "queued"}
        return True

    def diagnostics(self) -> dict:
        return {
            "running": self.running,
            "queued": self.queued,
            "inflight": self.inflight,
            "image_ready": bool(self.calls),
            "last_outcome": self.last_outcome,
        }

    def preview_jpeg(self) -> bytes | None:
        return b"test-image" if self.calls else None


class FakeElectricalWorker:
    def __init__(self) -> None:
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False


def _pin_ep(pin_id: str, conf: float = 0.8) -> WireEndpoint:
    return WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id=pin_id, confidence=conf)


def _floating_ep() -> WireEndpoint:
    return WireEndpoint(kind="floating", px=(500.0, 400.0), confidence=0.0)


def _tie_ep(candidates: list[str]) -> WireEndpoint:
    return WireEndpoint(kind="ambiguous_tie", px=(20.0, 20.0), candidates=candidates)


def _wire(a: WireEndpoint, b: WireEndpoint, wire_id: int = 0) -> WireInstance:
    return WireInstance(
        wire_id=wire_id, color="red", path_px=[(1.0, 1.0), (2.0, 2.0)],
        endpoint_a=a, endpoint_b=b, confidence=0.8, ambiguous=False,
    )


def _trace(wires: list[WireInstance], tracking: str = "locked", ts_ms: float = 111.0) -> WireTraceResult:
    return WireTraceResult(frame_id=7, ts_ms=ts_ms, board_tracking=tracking, wires=wires)


STEP = GuidanceStep(step_id="step-1-d7", expected_pin_id="D7")


# --------------------------------------------- evaluate_guidance_step ----

def test_pending_when_nothing_detected():
    r = evaluate_guidance_step(STEP, _trace([]), frozenset())
    assert r.status == "pending"
    assert r.actual_pin_id is None
    assert r.as_of_ms == 111.0


def test_low_scale_trace_is_uncertain_not_pending():
    trace = WireTraceResult(
        frame_id=7, ts_ms=111.0, board_tracking="locked", wires=[],
        suppressed_reason="scale_below_minimum",
    )
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "uncertain"
    assert r.reason == "scale_unready"


def test_correct_when_expected_pin_occupied():
    trace = _trace([_wire(_pin_ep("D7", conf=0.7), _floating_ep())])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "correct"
    assert r.confidence == 0.7


def test_correct_wins_even_if_pin_was_in_baseline():
    """The target being occupied is success no matter when it got occupied -
    baseline only guards the wrong_pin branch."""
    trace = _trace([_wire(_pin_ep("D7"), _floating_ep())])
    r = evaluate_guidance_step(STEP, trace, frozenset({"D7"}))
    assert r.status == "correct"


def test_wrong_pin_names_the_actual_pin():
    trace = _trace([_wire(_pin_ep("D8", conf=0.6), _floating_ep())])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "wrong_pin"
    assert r.actual_pin_id == "D8"
    assert r.confidence == 0.6


def test_verdict_keeps_source_endpoint_provenance():
    wire = _wire(_pin_ep("D8", conf=0.6), _floating_ep(), wire_id=17)
    r = evaluate_guidance_step(STEP, _trace([wire]), frozenset())
    assert r.status == "wrong_pin"
    assert r.source_wire_id == 17
    assert r.source_endpoint == "a"


def test_unverified_wrong_pin_is_uncertain_not_an_accusation():
    wire = _wire(_pin_ep("D8"), _floating_ep())
    wire.attachment = "unknown"
    r = evaluate_guidance_step(STEP, _trace([wire]), frozenset())
    assert r.status == "uncertain"
    assert r.reason == "attachment_unverified"


def test_baseline_pin_never_counts_as_wrong_pin():
    """A wire that was already plugged into 5V before the step began must
    not be blamed as this step's wrong wire."""
    trace = _trace([_wire(_pin_ep("5V"), _floating_ep())])
    r = evaluate_guidance_step(STEP, trace, frozenset({"5V"}))
    assert r.status == "pending"


def test_searching_is_uncertain():
    r = evaluate_guidance_step(STEP, _trace([], tracking="searching"), frozenset())
    assert r.status == "uncertain"
    assert r.reason == "board_not_tracked"


def test_unknown_attachment_exposes_actionable_uncertainty_reason():
    wire = _wire(_pin_ep("D7"), _floating_ep())
    wire.attachment = "unknown"
    r = evaluate_guidance_step(STEP, _trace([wire]), frozenset())
    assert r.status == "uncertain"
    assert r.reason == "attachment_unverified"


def test_inserted_attachment_can_promote_correct_but_resting_cannot():
    inserted = _wire(_pin_ep("D7"), _floating_ep())
    inserted.attachment = "inserted"
    r = evaluate_guidance_step(STEP, _trace([inserted]), frozenset())
    assert r.status == "correct"

    resting = _wire(_pin_ep("D7"), _floating_ep())
    resting.attachment = "resting"
    r = evaluate_guidance_step(STEP, _trace([resting]), frozenset())
    assert r.status == "uncertain"
    assert r.reason == "attachment_unverified"


# ------------------------------------------------- M23 boundary cases ----

def test_ambiguous_tie_touching_target_is_uncertain():
    """Endpoint equidistant between D7 and D8, target D7: conflicting
    evidence, not absence of evidence - never pending, never correct."""
    trace = _trace([_wire(_tie_ep(["D7", "D8"]), _floating_ep())])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "uncertain"
    assert r.reason == "endpoint_ambiguous"


def test_crossed_wire_touching_target_is_uncertain_not_correct():
    """A resolved endpoint is not authoritative when its path crossed a junction."""
    wire = _wire(_pin_ep("D7"), _floating_ep())
    wire.ambiguous = True
    wire.crossed_junction_count = 1
    r = evaluate_guidance_step(STEP, _trace([wire]), frozenset())
    assert r.status == "uncertain"
    assert r.reason == "wire_path_ambiguous"


def test_unrelated_baseline_crossed_wire_does_not_block_target():
    """Only ambiguous evidence relevant to this step should veto it."""
    old = _wire(_pin_ep("D8"), _floating_ep())
    old.ambiguous = True
    old.crossed_junction_count = 1
    target = _wire(_pin_ep("D7"), _floating_ep())
    r = evaluate_guidance_step(STEP, _trace([old, target]), frozenset({"D8"}))
    assert r.status == "correct"


def test_ambiguous_tie_elsewhere_does_not_block():
    """A tie between two unrelated pins doesn't poison the verdict for D7."""
    trace = _trace([
        _wire(_tie_ep(["A0", "A1"]), _floating_ep(), wire_id=0),
        _wire(_pin_ep("D7"), _floating_ep(), wire_id=1),
    ])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "correct"


def test_two_new_endpoints_same_tick_is_uncertain():
    """Two wires appeared at once - no way to know which is 'this step's
    wire'. Don't guess (M23)."""
    trace = _trace([
        _wire(_pin_ep("D8"), _floating_ep(), wire_id=0),
        _wire(_pin_ep("A2"), _floating_ep(), wire_id=1),
    ])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "uncertain"


def test_two_new_pins_on_one_wire_are_not_collapsed_into_wrong_pin():
    """The other end of one physical wire must not become an accusation."""
    trace = _trace([
        _wire(_pin_ep("D8"), _pin_ep("RESET"), wire_id=9),
    ])
    r = evaluate_guidance_step(STEP, trace, frozenset())
    assert r.status == "uncertain"
    assert r.reason == "multiple_new_endpoints"
    assert r.actual_pin_id is None


def test_ai_hint_never_read_by_evaluator():
    """The advisory channel is output-only: the evaluator's signature has no
    ai_hint parameter, and a fresh verdict always carries ai_hint=None."""
    import inspect

    params = inspect.signature(evaluate_guidance_step).parameters
    assert "ai_hint" not in params
    r = evaluate_guidance_step(STEP, _trace([]), frozenset())
    assert r.ai_hint is None


def test_guidance_debouncer_requires_two_correct_ticks():
    debouncer = GuidanceVerdictDebouncer()
    first = debouncer.update(GuidanceResult("step-1-d7", "D7", "correct", confidence=0.8))
    second = debouncer.update(GuidanceResult("step-1-d7", "D7", "correct", confidence=0.8))
    assert first.status == "uncertain"
    assert second.status == "correct"


def test_guidance_debouncer_requires_three_matching_wrong_ticks_in_four():
    debouncer = GuidanceVerdictDebouncer()
    raw = lambda pin: GuidanceResult("step-1-d7", "D7", "wrong_pin", actual_pin_id=pin, confidence=0.8)
    assert debouncer.update(raw("D8")).status == "uncertain"
    assert debouncer.update(raw("D8")).status == "uncertain"
    assert debouncer.update(raw("D9")).status == "uncertain"
    assert debouncer.update(raw("D8")).status == "wrong_pin"


def test_guidance_debouncer_does_not_promote_after_uncertain():
    debouncer = GuidanceVerdictDebouncer()
    raw = GuidanceResult("step-1-d7", "D7", "correct", confidence=0.8)
    assert debouncer.update(raw).status == "uncertain"
    assert debouncer.update(GuidanceResult("step-1-d7", "D7", "uncertain")).status == "uncertain"
    assert debouncer.update(raw).status == "uncertain"


# ------------------------------------------------------ occupied_pin_ids ----

def test_occupied_pin_ids():
    assert occupied_pin_ids(None) == frozenset()
    trace = _trace([
        _wire(_pin_ep("D7"), _pin_ep("GND_P1"), wire_id=0),
        _wire(_floating_ep(), _tie_ep(["A0", "A1"]), wire_id=1),
    ])
    assert occupied_pin_ids(trace) == frozenset({"D7", "GND_P1"})


# ---------------------------------------------------------- GuidanceState ----

def test_guidance_state_roundtrip_and_clear():
    gs = GuidanceState()
    assert gs.get_step() is None
    assert gs.snapshot() == {"active": False, "step": None, "result": None}

    gs.set_step(STEP, frozenset({"5V"}))
    step, baseline = gs.get_step()
    assert step.expected_pin_id == "D7"
    assert baseline == frozenset({"5V"})

    verdict = GuidanceResult("step-1-d7", "D7", "correct", confidence=0.9, as_of_ms=1.0)
    gs.set_result(verdict)
    snap = gs.snapshot()
    assert snap["active"] is True
    assert snap["result"]["status"] == "correct"

    gs.clear()
    assert gs.get_step() is None
    assert gs.snapshot()["active"] is False


def test_guidance_state_drops_result_for_stale_step():
    """A verdict computed for step A must not survive a swap to step B."""
    gs = GuidanceState()
    gs.set_step(STEP, frozenset())
    gs.set_step(GuidanceStep(step_id="step-2-a0", expected_pin_id="A0"), frozenset())
    gs.set_result(GuidanceResult("step-1-d7", "D7", "correct"))  # stale step_id
    assert gs.get_result() is None


def test_guidance_state_result_cleared_on_new_step():
    gs = GuidanceState()
    gs.set_step(STEP, frozenset())
    gs.set_result(GuidanceResult("step-1-d7", "D7", "correct"))
    gs.set_step(GuidanceStep(step_id="step-2-a0", expected_pin_id="A0"), frozenset())
    assert gs.get_result() is None


# ------------------------------------------------ guidance_check message ----

def test_guidance_check_message_shape_wrong_pin():
    verdict = GuidanceResult("step-1-d7", "D7", "wrong_pin",
                             actual_pin_id="D8", confidence=0.61, as_of_ms=99.0)
    msg = guidance_check_message(verdict, _trace([]), "mini-board")
    assert msg == {
        "type": "guidance_check",
        "board_id": "mini-board",
        "step_id": "step-1-d7",
        "frame_id": 7,
        "ts_ms": 99.0,
        "board_tracking": "locked",
        "expected_pin_id": "D7",
        "status": "wrong_pin",
        "confidence": 0.61,
        "ai_hint": None,
        "actual_pin_id": "D8",
    }


def test_guidance_check_message_omits_actual_pin_unless_wrong():
    verdict = GuidanceResult("step-1-d7", "D7", "correct", confidence=0.9, as_of_ms=99.0)
    msg = guidance_check_message(verdict, _trace([]), "mini-board")
    assert "actual_pin_id" not in msg
    assert msg["status"] == "correct"


# ------------------------------------------------------ worker integration ----

def test_worker_evaluates_and_publishes_guidance(monkeypatch):
    """With an active step, each tick publishes wire_trace AND guidance_check
    with a verdict computed from the same fresh result."""
    canned = _trace([_wire(_pin_ep("D7", conf=0.7), _floating_ep())])
    monkeypatch.setattr(
        wire_tracer, "trace",
        lambda frame, pins, frame_id, ts_ms, tracking, colors=None, board_outline=None, include_edge_agnostic=False: canned,
    )

    bus = FrameBus()
    detection_state = DetectionState()
    detection_state.set(DetectionResult(
        board_id="mini-board", frame_id=1, ts_ms=0.0, tracking="locked",
        confidence=0.9,
        pins=[PinDetection(pin_id="D7", x=10.0, y=10.0, confidence=0.9, visible=True)],
    ))
    gs = GuidanceState()
    gs.set_step(STEP, frozenset())

    published: list[dict] = []
    done = threading.Event()

    def publish(msg: dict) -> None:
        published.append(msg)
        if msg.get("type") == "guidance_check" and msg.get("status") == "correct":
            done.set()

    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=WireTraceState(),
        board_id="mini-board", publish=publish, interval_s=0.01,
        colors=["red"], guidance_state=gs,
    )
    worker.start()
    try:
        for i in range(1, 40):
            bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 1, float(i))
            if done.wait(timeout=0.05):
                break
        assert done.is_set(), "no guidance_check published"
    finally:
        worker.stop()

    checks = [m for m in published if m["type"] == "guidance_check"]
    correct = next((m for m in checks if m["status"] == "correct"), None)
    assert correct is not None
    assert correct["expected_pin_id"] == "D7"
    # verdict also readable synchronously
    assert gs.get_result().status == "correct"
    # wire_trace messages still flow alongside
    assert any(m["type"] == "wire_trace" for m in published)


def test_worker_passes_selected_component_to_guided_roi(monkeypatch):
    poses = ComponentPoseState(primary_component_id="mrd-tf240-8p-cs")
    for component_id in ["hc-sr04", "mrd-tf240-8p-cs"]:
        poses.set(ComponentPoseResult(
            component_id=component_id, frame_id=1, ts_ms=1.0,
            tracking="locked", confidence=0.9, video_size=(VIDEO_W, VIDEO_H),
            outline_px=None, pins=(ComponentPinPosition("GND", 40.0, 20.0, 0.9),),
            stability="tracking",
        ))
    guidance_state = GuidanceState()
    guidance_state.set_step(GuidanceStep(
        step_id="hc-ground", expected_pin_id="D7", expected_role="GND", component_id="hc-sr04",
    ), frozenset())
    worker = WireTraceWorker(
        bus=FrameBus(), detection_state=DetectionState(), state=WireTraceState(),
        board_id="mini-board", guidance_state=guidance_state, component_pose_state=poses,
    )
    received = []
    monkeypatch.setattr(worker._guided_roi, "update", lambda step, frame, detection, pose: received.append(pose))
    worker._publish_guidance(_trace([]), frame_bgr=np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8))
    assert received == [poses.get("hc-sr04")]


def test_worker_without_step_publishes_no_guidance(monkeypatch):
    canned = _trace([])
    monkeypatch.setattr(
        wire_tracer, "trace",
        lambda frame, pins, frame_id, ts_ms, tracking, colors=None, board_outline=None, include_edge_agnostic=False: canned,
    )
    bus = FrameBus()
    detection_state = DetectionState()
    detection_state.set(DetectionResult(
        board_id="mini-board", frame_id=1, ts_ms=0.0, tracking="locked",
        confidence=0.9,
        pins=[PinDetection(pin_id="D7", x=10.0, y=10.0, confidence=0.9, visible=True)],
    ))
    published: list[dict] = []
    got_trace = threading.Event()

    def publish(msg: dict) -> None:
        published.append(msg)
        if msg.get("type") == "wire_trace":
            got_trace.set()

    worker = WireTraceWorker(
        bus=bus, detection_state=detection_state, state=WireTraceState(),
        board_id="mini-board", publish=publish, interval_s=0.01,
        colors=["red"], guidance_state=GuidanceState(),  # no active step
    )
    worker.start()
    try:
        for i in range(1, 40):
            bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), i, float(i))
            if got_trace.wait(timeout=0.05):
                break
        assert got_trace.is_set()
        time.sleep(0.05)  # a couple more ticks
    finally:
        worker.stop()
    assert all(m["type"] != "guidance_check" for m in published)


def test_worker_guidance_uses_faster_cadence_only_while_step_is_active():
    guidance_state = GuidanceState()
    worker = WireTraceWorker(
        bus=FrameBus(),
        detection_state=DetectionState(),
        state=WireTraceState(),
        board_id="mini-board",
        interval_s=0.5,
        guidance_interval_s=0.3,
        guidance_state=guidance_state,
    )

    assert worker._effective_interval_s() == 0.5
    guidance_state.set_step(STEP, frozenset())
    assert worker._effective_interval_s() == 0.3
    guidance_state.clear()
    assert worker._effective_interval_s() == 0.5


def test_worker_manual_geometry_uses_fast_burst_cadence():
    guidance_state = GuidanceState()
    verification_state = VerificationState()
    worker = WireTraceWorker(
        bus=FrameBus(),
        detection_state=DetectionState(),
        state=WireTraceState(),
        board_id="mini-board",
        interval_s=0.5,
        guidance_interval_s=0.3,
        guidance_state=guidance_state,
        verification_state=verification_state,
    )
    guidance_state.set_step(STEP, frozenset())
    verification_state.set_step(STEP.step_id, STEP.expected_pin_id)

    assert worker._effective_interval_s() == 0.3
    assert verification_state.request_geometry(STEP.step_id) is True
    assert worker._effective_interval_s() == pytest.approx(0.05)


def test_worker_guidance_never_slows_a_faster_idle_cadence():
    guidance_state = GuidanceState()
    worker = WireTraceWorker(
        bus=FrameBus(),
        detection_state=DetectionState(),
        state=WireTraceState(),
        board_id="mini-board",
        interval_s=0.1,
        guidance_interval_s=0.3,
        guidance_state=guidance_state,
    )
    guidance_state.set_step(STEP, frozenset())

    assert worker._effective_interval_s() == 0.1


# ------------------------------------------------------------ REST API ----

def _client(config: AppConfig | None = None, **build_overrides) -> TestClient:
    app = build_app(
        config or make_config(),
        detector=LockedDetector(),
        source=StubFrameSource(),
        scene=object(),
        **build_overrides,
    )
    return TestClient(app)


def test_api_set_step_and_read_state():
    with _client() as client:
        res = client.post("/api/guidance/step", json={"expected_pin_id": "D3"})
        body = res.json()
        assert res.status_code == 200 and body["ok"] is True
        assert body["step_id"].endswith("-d3")
        assert body["advance_mode"] == "confirm"
        assert body["baseline_pin_ids"] == []

        state = client.get("/api/guidance/state").json()
        assert state["active"] is True
        assert state["step"]["expected_pin_id"] == "D3"
        assert state["step"]["advance_mode"] == "confirm"

        res = client.delete("/api/guidance/step")
        assert res.json() == {"ok": True}
        assert client.get("/api/guidance/state").json()["active"] is False


def test_api_unknown_pin_is_ok_false():
    with _client() as client:
        res = client.post("/api/guidance/step", json={"expected_pin_id": "D99"})
        body = res.json()
        assert res.status_code == 200
        assert body["ok"] is False
        assert body["error"] == "unknown_pin"
        # nothing activated
        assert client.get("/api/guidance/state").json()["active"] is False


def test_api_auto_step_is_rejected_until_physical_gate_is_ready():
    with _client() as client:
        res = client.post(
            "/api/guidance/step",
            json={"expected_pin_id": "D3", "advance_mode": "auto"},
        )
        body = res.json()
        assert res.status_code == 200
        assert body["ok"] is False
        assert body["error"] == "physical_gate_unready"
        assert body["warnings"]
        assert client.get("/api/guidance/state").json()["active"] is False


def test_api_auto_step_records_mode_when_physical_gate_is_ready(monkeypatch):
    from app.vision import profile_quality

    monkeypatch.setattr(
        profile_quality,
        "inspect_profile_quality",
        lambda _profile, _profile_dir, **_thresholds: {
            "physical_gate_ready": True,
            "warnings": [],
        },
    )
    with _client() as client:
        res = client.post(
            "/api/guidance/step",
            json={"expected_pin_id": "D3", "advance_mode": "auto"},
        )
        body = res.json()
        assert body["ok"] is True
        assert body["advance_mode"] == "auto"
        assert client.get("/api/guidance/state").json()["step"]["advance_mode"] == "auto"


def test_api_step_baseline_snapshots_current_occupancy():
    with _client() as client:
        # Seed the wire state as if a wire were already plugged into D3.
        app = client.app
        app.state.wire_state.set(_trace([_wire(_pin_ep("D3"), _floating_ep())]))
        res = client.post("/api/guidance/step", json={"expected_pin_id": "A4"})
        assert res.json()["baseline_pin_ids"] == ["D3"]


def test_api_caller_supplied_step_id_kept():
    with _client() as client:
        res = client.post("/api/guidance/step",
                          json={"expected_pin_id": "D3", "step_id": "plan-x-step-2"})
        assert res.json()["step_id"] == "plan-x-step-2"


def test_api_vlm_is_called_once_only_after_manual_button_request():
    worker = FakeInsertionVlmWorker()
    with _client(insertion_vlm_worker=worker) as client:
        client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "D3",
                "expected_role": "VCC",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-vcc",
            },
        )
        client.app.state.component_pose_state.set(
            ComponentPoseResult(
                component_id="photoresistor-module",
                frame_id=1,
                ts_ms=1.0,
                tracking="locked",
                confidence=0.8,
                video_size=(VIDEO_W, VIDEO_H),
                outline_px=None,
                pins=(ComponentPinPosition("VCC", 40.0, 20.0, 0.9),),
                stability="tracking",
            )
        )
        # Camera and detector threads are asynchronous; seed an exact ready
        # snapshot so this test exercises the API boundary, not scheduling.
        client.app.state.frame_bus.put(
            np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 99, 99.0
        )
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=99,
                ts_ms=99.0,
                tracking="locked",
                confidence=0.9,
                pins=[PinDetection("D3", 10.0, 5.0, 0.97, True)],
            )
        )

        time.sleep(0.06)
        assert worker.calls == []  # no camera-loop auto trigger
        response = client.post("/api/guidance/visual-check").json()
        assert response == {
            "ok": True,
            "status": "queued",
            "step_id": "photoresistor-vcc",
        }
        assert len(worker.calls) == 1
        assert client.get("/api/guidance/visual-check").json()["status"] == "queued"


def test_api_vlm_accepts_a_manual_snapshot_when_pose_is_not_locked():
    worker = FakeInsertionVlmWorker()
    with _client(insertion_vlm_worker=worker) as client:
        client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "D3",
                "expected_role": "VCC",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-vcc",
            },
        )
        # The board tracker is explicitly searching. VLM must receive the
        # user's raw-frame snapshot rather than rejecting the button.
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=101,
                ts_ms=101.0,
                tracking="searching",
                confidence=0.0,
                pins=[],
            )
        )
        client.app.state.frame_bus.put(
            np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 101, 101.0
        )

        response = client.post("/api/guidance/visual-check").json()
        assert response == {
            "ok": True,
            "status": "queued",
            "step_id": "photoresistor-vcc",
        }
        assert len(worker.calls) == 1


def test_api_wire_color_vlm_is_called_only_after_its_manual_button_request():
    worker = FakeWireColorVlmWorker()
    with _client(wire_color_vlm_worker=worker) as client:
        client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "D3",
                "expected_role": "VCC",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-vcc",
            },
        )
        client.app.state.component_pose_state.set(
            ComponentPoseResult(
                component_id="photoresistor-module",
                frame_id=1,
                ts_ms=1.0,
                tracking="locked",
                confidence=0.8,
                video_size=(VIDEO_W, VIDEO_H),
                outline_px=None,
                pins=(ComponentPinPosition("VCC", 40.0, 20.0, 0.9),),
                stability="tracking",
            )
        )
        client.app.state.frame_bus.put(
            np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 99, 99.0
        )
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=99,
                ts_ms=99.0,
                tracking="locked",
                confidence=0.9,
                pins=[PinDetection("D3", 10.0, 5.0, 0.97, True)],
            )
        )

        time.sleep(0.06)
        assert worker.calls == []
        uno_colour = client.post("/api/guidance/color-check/board").json()
        assert uno_colour["ok"] is True
        assert uno_colour["endpoint"] == "board"
        assert uno_colour["sample"]["pin_id"] == "D3"
        uno_preview = client.get("/api/guidance/color-check/image/board")
        assert uno_preview.status_code == 200
        assert uno_preview.headers["content-type"].startswith("image/jpeg")

        sensor_colour = client.post("/api/guidance/color-check/component").json()
        assert sensor_colour["ok"] is True
        assert sensor_colour["endpoint"] == "component"
        assert sensor_colour["sample"]["pin_id"] == "VCC"
        sensor_preview = client.get("/api/guidance/color-check/image/component")
        assert sensor_preview.status_code == 200
        assert sensor_preview.headers["content-type"].startswith("image/jpeg")
        response = client.post("/api/guidance/color-vlm-check").json()
        assert response == {
            "ok": True,
            "status": "queued",
            "step_id": "photoresistor-vcc",
        }
        assert len(worker.calls) == 1
        assert client.get("/api/guidance/color-vlm-check").json()["status"] == "queued"
        assert client.get("/api/guidance/color-vlm-check/image").content == b"test-image"


def test_api_color_samples_require_only_the_endpoint_being_captured():
    with _client() as client:
        client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "D3",
                "expected_role": "VCC",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-vcc",
            },
        )
        client.app.state.frame_bus.put(
            np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 99, 99.0
        )
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=99,
                ts_ms=99.0,
                tracking="locked",
                confidence=0.9,
                pins=[PinDetection("D3", 10.0, 5.0, 0.97, True)],
            )
        )

        # There is no Sensor pose yet. The UNO Q snapshot must still be usable.
        uno = client.post("/api/guidance/color-check/board").json()
        assert uno["ok"] is True
        assert uno["endpoint"] == "board"

        client.app.state.component_pose_state.set(
            ComponentPoseResult(
                component_id="photoresistor-module",
                frame_id=100,
                ts_ms=100.0,
                tracking="locked",
                confidence=0.8,
                video_size=(VIDEO_W, VIDEO_H),
                outline_px=None,
                pins=(ComponentPinPosition("VCC", 40.0, 20.0, 0.9),),
                stability="tracking",
            )
        )
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=100,
                ts_ms=100.0,
                tracking="searching",
                confidence=0.0,
                pins=[],
            )
        )

        # After moving to a close-up of the Sensor, the earlier UNO Q lock is
        # irrelevant; only the Sensor pose is required for this capture.
        sensor = client.post("/api/guidance/color-check/component").json()
        assert sensor["ok"] is True
        assert sensor["endpoint"] == "component"


def test_api_geometry_check_starts_five_frame_manual_collection():
    with _client() as client:
        client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "D3",
                "expected_role": "VCC",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-vcc",
            },
        )
        client.app.state.component_pose_state.set(
            ComponentPoseResult(
                component_id="photoresistor-module",
                frame_id=1,
                ts_ms=1.0,
                tracking="locked",
                confidence=0.8,
                video_size=(VIDEO_W, VIDEO_H),
                outline_px=None,
                pins=(ComponentPinPosition("VCC", 40.0, 20.0, 0.9),),
                stability="tracking",
            )
        )
        client.app.state.detection_state.set(
            DetectionResult(
                board_id="mini-board",
                frame_id=99,
                ts_ms=99.0,
                tracking="locked",
                confidence=0.9,
                pins=[PinDetection("D3", 10.0, 5.0, 0.97, True)],
            )
        )

        response = client.post("/api/guidance/geometry-check").json()
        assert response["ok"] is True
        assert response["status"] == "collecting"
        assert response["sample_target"] == 5
        assert response["required_agreement"] == 3
        snapshot = client.get("/api/guidance/state").json()["verification"]
        assert snapshot["target"]["geometry_requested"] is True
        assert snapshot["target"]["geometry_generation"] == 1
        assert snapshot["evidence"]["geometry"]["reason"] == "collecting_geometry_samples"


@pytest.mark.parametrize("endpoint", ["geometry-check", "color-check/component", "visual-check"])
@pytest.mark.parametrize("target_present", [True, False])
def test_guidance_uses_selected_component_not_primary(endpoint, target_present):
    worker = FakeInsertionVlmWorker()
    with _client(insertion_vlm_worker=worker) as client:
        client.post("/api/guidance/step", json={
            "expected_pin_id": "D3", "expected_role": "VCC",
            "component_id": "photoresistor-module", "step_id": "selected-component",
        })
        poses = ComponentPoseState(primary_component_id="mrd-tf240-8p-cs")
        for component_id in (["photoresistor-module"] if target_present else []) + ["mrd-tf240-8p-cs"]:
            poses.set(ComponentPoseResult(
                component_id=component_id, frame_id=1, ts_ms=1.0,
                tracking="locked", confidence=0.9, video_size=(VIDEO_W, VIDEO_H),
                outline_px=None, pins=(ComponentPinPosition("VCC", 40.0, 20.0, 0.9),),
                stability="tracking",
            ))
        client.app.state.component_pose_state = poses
        client.app.state.frame_bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 99, 99.0)
        client.app.state.detection_state.set(DetectionResult(
            board_id="mini-board", frame_id=99, ts_ms=99.0, tracking="locked",
            confidence=0.9, pins=[PinDetection("D3", 10.0, 5.0, 0.97, True)],
        ))
        assert poses.get().component_id == "mrd-tf240-8p-cs"
        response = client.post(f"/api/guidance/{endpoint}").json()
        if endpoint == "visual-check":
            # Snapshot-only VLM is allowed without a pose, but never receives
            # another module's identically named VCC as the selected target.
            assert response["ok"] is True
            assert worker.calls[0][3] is poses.get("photoresistor-module")
        elif target_present:
            assert response["ok"] is True
        else:
            assert response["ok"] is False
            assert response["error"] == "component_not_ready"


def test_api_electrical_check_only_starts_on_final_a0_request():
    worker = FakeElectricalWorker()
    config = make_config(
        board="arduino-uno-q",
        profile_dir=Path(__file__).resolve().parents[2] / "profiles",
        electrical_verification={"enabled": True, "port": "COM-test"}
    )
    with _client(config, electrical_worker=worker) as client:
        response = client.post(
            "/api/guidance/step",
            json={
                "expected_pin_id": "A0",
                "expected_role": "AO",
                "component_id": "photoresistor-module",
                "step_id": "photoresistor-ao",
            },
        )
        assert response.json()["ok"] is True
        before = client.get("/api/guidance/state").json()["verification"]
        assert before["target"]["electrical_requested"] is False
        assert before["evidence"]["electrical"]["reason"] == "awaiting_electrical_start"

        started = client.post("/api/guidance/electrical-check").json()
        assert started["ok"] is True
        assert started["generation"] == 1
        after = client.get("/api/guidance/state").json()["verification"]
        assert after["target"]["electrical_requested"] is True
