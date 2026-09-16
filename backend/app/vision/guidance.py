"""Guided-wiring checkmark engine — M22/M23.

Design doc: docs/color-agnostic-wire-and-guidance-design.md §2.2. A guidance
step names one target pin ("plug a wire into D7"); this module decides, from
the latest WireTraceResult, whether that happened. The decision is 100%
classical — string and set comparisons over data snap_endpoint() already
produced. No model, no image understanding, no guessing:

- The comparison is `pin_id == expected_pin_id` on typed, already-resolved
  endpoints. Perception ended at Stage D; this is bookkeeping.
- Four statuses, deliberately not a boolean (same "never fake certainty"
  idiom as WireEndpoint's floating/ambiguous_tie):
    pending    — no new endpoint seen yet; not wrong, just not done
    correct    — an endpoint resolved to the expected pin
    wrong_pin  — exactly one NEW endpoint appeared on a different pin
                 (names it — richer than a bare ✗, and free)
    uncertain  — evidence exists but conflicts (ambiguous_tie touching the
                 target, 2+ new endpoints in one tick, or no tracking);
                 never coerced into a boolean.

`ai_hint` (an advisory VLM fallback, M24/M29) is an OUTPUT-ONLY side channel:
evaluate_guidance_step() neither reads nor writes it — by construction the
advisory layer cannot influence the verdict (architecture plan §6.3/§6.4).
"""
from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass, field, replace
from typing import Literal

from app.vision.wire_tracer import WireTraceResult

GuidanceStatus = Literal["pending", "correct", "wrong_pin", "uncertain"]
GuidanceAdvanceMode = Literal["confirm", "auto"]


@dataclass
class GuidanceStep:
    step_id: str
    expected_pin_id: str            # the target pin — sole authoritative input
    expected_role: str | None = None    # display only (e.g. "TRIG"); never compared
    component_id: str | None = None     # ComponentSpec linkage; context only
    hint_color: str | None = None       # tutorial-text suggestion; NEVER used in matching
    # L2 is the safe default; L3 is enabled only after the profile-quality
    # gate in POST /api/guidance/step accepts it.
    advance_mode: GuidanceAdvanceMode = "confirm"


@dataclass
class GuidanceResult:
    step_id: str
    expected_pin_id: str
    status: GuidanceStatus
    actual_pin_id: str | None = None       # only for status=="wrong_pin"
    confidence: float = 0.0
    as_of_ms: float = 0.0
    ai_hint: dict | None = None            # advisory only; never affects status
    # Machine-readable explanation for an uncertain verdict. This is UI
    # evidence only; it is not another decision input.
    reason: str | None = None
    # Debug/audit provenance for the endpoint that produced a resolved
    # verdict.  These fields never participate in the verdict itself, but
    # prevent a whole-wire `new_pins` set from hiding which endpoint was used.
    source_wire_id: int | None = None
    source_endpoint: Literal["a", "b"] | None = None
    # Supplemental zero-training before/after evidence for the expected UNO
    # and component endpoints. Never upgrades the authoritative status by
    # itself; Serial/electrical verification remains a separate final layer.
    visual_check: dict | None = None


class GuidanceVerdictDebouncer:
    """Make guidance verdicts conservative across wire-trace ticks.

    ``evaluate_guidance_step`` remains a pure, single-tick function.  This
    adapter is the temporal policy around it: a ``correct`` verdict needs two
    consecutive observations, while a potentially accusatory ``wrong_pin``
    needs three matching observations in the latest four ticks.  A candidate
    that has not reached its promotion threshold is exposed as ``uncertain``;
    it is never silently carried forward as a prior answer.
    """

    def __init__(self, *, correct_hits: int = 2,
                 wrong_window: int = 4, wrong_hits: int = 3) -> None:
        self.correct_hits = max(1, int(correct_hits))
        self.wrong_window = max(1, int(wrong_window))
        self.wrong_hits = max(1, int(wrong_hits))
        self._step_id: str | None = None
        self._correct_streak = 0
        self._wrong_history: deque[str | None] = deque(maxlen=self.wrong_window)

    def reset(self) -> None:
        self._step_id = None
        self._correct_streak = 0
        self._wrong_history.clear()

    @staticmethod
    def _uncertain(raw: GuidanceResult) -> GuidanceResult:
        return replace(
            raw,
            status="uncertain",
            actual_pin_id=None,
            confidence=0.0,
            reason=raw.reason or "awaiting_confirmation",
            source_wire_id=None,
            source_endpoint=None,
        )

    def update(self, raw: GuidanceResult) -> GuidanceResult:
        if raw.step_id != self._step_id:
            self.reset()
            self._step_id = raw.step_id

        if raw.status == "correct":
            self._wrong_history.clear()
            self._correct_streak += 1
            if self._correct_streak < self.correct_hits:
                return self._uncertain(raw)
            return raw

        self._correct_streak = 0
        if raw.status == "wrong_pin":
            self._wrong_history.append(raw.actual_pin_id)
            counts = Counter(pin_id for pin_id in self._wrong_history if pin_id)
            if raw.actual_pin_id and counts[raw.actual_pin_id] >= self.wrong_hits:
                return raw
            return self._uncertain(raw)

        # ``pending`` and already-conflicted ``uncertain`` are safe to expose
        # immediately.  They also clear promotion history so an old answer
        # cannot be promoted after an occlusion or scene change.
        self._wrong_history.clear()
        return raw


def evaluate_guidance_step(
    step: GuidanceStep,
    wire_result: WireTraceResult,
    baseline_pin_ids: frozenset[str],
) -> GuidanceResult:
    """Pure function: latest trace + baseline snapshot -> guidance verdict.

    `baseline_pin_ids` is the set of occupied pins captured when the step was
    activated (see GuidanceState.set_step) — "new since this step started" is
    a set difference against it, so a wire that was already plugged into some
    other pin before the step began never counts as this step's wrong_pin.

    Not one line here does perception: `in`, `==`, and set difference over
    pin-id strings snap_endpoint() already resolved.
    """
    now_ms = wire_result.ts_ms
    if wire_result.board_tracking != "locked":
        return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                              confidence=0.0, as_of_ms=now_ms,
                              reason="board_not_tracked")

    if wire_result.suppressed_reason == "scale_below_minimum":
        return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                              confidence=0.0, as_of_ms=now_ms,
                              reason="scale_unready")

    endpoints = [ep for w in wire_result.wires for ep in (w.endpoint_a, w.endpoint_b)]

    def source_for_pin(pin_id: str) -> tuple[int | None, Literal["a", "b"] | None, float]:
        candidates: list[tuple[float, int, Literal["a", "b"]]] = []
        for wire in wire_result.wires:
            for side, endpoint in (("a", wire.endpoint_a), ("b", wire.endpoint_b)):
                if endpoint.kind == "pin" and endpoint.pin_id == pin_id:
                    candidates.append((float(endpoint.confidence), int(wire.wire_id), side))
        if not candidates:
            return None, None, 0.0
        confidence, wire_id, side = max(candidates, key=lambda item: item[0])
        return wire_id, side, confidence

    # A resolved 2-D endpoint is not proof that a Dupont ferrule is actually
    # inserted: a wire resting above the same hole can project to the same
    # pixel.  Live traces therefore carry attachment="unknown" until a
    # physical/motion cue is available.  Legacy injected traces have None and
    # retain their historical semantics for compatibility with old callers.
    for wire in wire_result.wires:
        resolved = [
            ep for ep in (wire.endpoint_a, wire.endpoint_b)
            if ep.kind == "pin" and ep.pin_id
        ]
        if wire.attachment == "resting":
            return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                                  confidence=0.0, as_of_ms=now_ms,
                                  reason="attachment_unverified")
        if wire.attachment == "unknown":
            # An unverified wire must not be used either as a success or as an
            # accusation: a resting tip over a neighbouring pin is still not
            # evidence of a wrong insertion.
            if any(ep.pin_id == step.expected_pin_id or ep.pin_id not in baseline_pin_ids
                   for ep in resolved):
                return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                                      confidence=0.0, as_of_ms=now_ms,
                                      reason="attachment_unverified")

    # A skeleton junction has no unique monocular continuation.  The wire
    # tracer intentionally exposes that evidence as ``ambiguous`` instead of
    # guessing a path, but the old guidance path only used the endpoint pin
    # ids and could still promote such a wire to ``correct``.  Block only
    # ambiguous wires that can participate in this step: an unrelated wire
    # already present in the baseline should not freeze every other step.
    for wire in wire_result.wires:
        if not (wire.ambiguous or wire.crossed_junction_count > 0):
            continue
        relevant = any(
            ep.kind == "pin" and ep.pin_id and (
                ep.pin_id == step.expected_pin_id
                or ep.pin_id not in baseline_pin_ids
            )
            for ep in (wire.endpoint_a, wire.endpoint_b)
        )
        if relevant:
            return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                                  confidence=0.0, as_of_ms=now_ms,
                                  reason="wire_path_ambiguous")

    # Is the target pin itself among an ambiguous_tie's candidates? An
    # endpoint sitting dead-centre between two pins, one of which is the
    # target, is CONFLICTING evidence — not absence of evidence. Reporting
    # "pending" would hide it; reporting "correct" would guess. Uncertain.
    for ep in endpoints:
        if ep.kind == "ambiguous_tie" and step.expected_pin_id in ep.candidates:
            return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                                  confidence=0.0, as_of_ms=now_ms,
                                  reason="endpoint_ambiguous")

    occupied_now = {ep.pin_id for ep in endpoints if ep.kind == "pin"}
    if step.expected_pin_id in occupied_now:
        source_wire_id, source_endpoint, conf = source_for_pin(step.expected_pin_id)
        return GuidanceResult(step.step_id, step.expected_pin_id, "correct",
                              confidence=conf, as_of_ms=now_ms,
                              source_wire_id=source_wire_id,
                              source_endpoint=source_endpoint)

    # Preserve wire identity while finding newly occupied pins. A flat
    # `occupied_now - baseline_pin_ids` set loses an important distinction:
    # two new pins may be the two ends of one wire, rather than two competing
    # wires. In that case there is no safe way to name the wrong pin.
    new_by_wire: list[tuple[WireInstance, list[str]]] = []
    for wire in wire_result.wires:
        new_ids: list[str] = []
        for endpoint in (wire.endpoint_a, wire.endpoint_b):
            if (endpoint.kind == "pin" and endpoint.pin_id
                    and endpoint.pin_id not in baseline_pin_ids
                    and endpoint.pin_id not in new_ids):
                new_ids.append(endpoint.pin_id)
        if new_ids:
            new_by_wire.append((wire, new_ids))

    if len(new_by_wire) == 1 and len(new_by_wire[0][1]) == 1:
        actual = new_by_wire[0][1][0]
        wire = new_by_wire[0][0]
        source_endpoint: Literal["a", "b"] = (
            "a" if wire.endpoint_a.kind == "pin" and wire.endpoint_a.pin_id == actual
            else "b"
        )
        endpoint = wire.endpoint_a if source_endpoint == "a" else wire.endpoint_b
        return GuidanceResult(step.step_id, step.expected_pin_id, "wrong_pin",
                              actual_pin_id=actual,
                              confidence=float(endpoint.confidence),
                              as_of_ms=now_ms,
                              source_wire_id=wire.wire_id,
                              source_endpoint=source_endpoint)
    if new_by_wire:
        # Multiple new endpoints either came from multiple wires or both ends
        # of one wire. Do not manufacture an accusation from that ambiguity.
        return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain",
                              confidence=0.0, as_of_ms=now_ms,
                              reason="multiple_new_endpoints")

    return GuidanceResult(step.step_id, step.expected_pin_id, "pending",
                          confidence=0.0, as_of_ms=now_ms)


def occupied_pin_ids(wire_result: WireTraceResult | None) -> frozenset[str]:
    """The set of pins currently holding a resolved wire endpoint. Used to
    snapshot `baseline_pin_ids` at step-activation time."""
    if wire_result is None:
        return frozenset()
    return frozenset(
        ep.pin_id
        for w in wire_result.wires
        for ep in (w.endpoint_a, w.endpoint_b)
        if ep.kind == "pin" and ep.pin_id is not None
    )


class GuidanceState:
    """Thread-safe holder for the active guidance step + latest verdict.

    Two writers, by design (same one-holder-per-question idiom as
    DetectionState/WireTraceState):
    - the API request thread activates/clears a step (set_step/clear), and
    - WireTraceWorker's tick writes the latest GuidanceResult (set_result).
    A single lock covers both so a step swap mid-tick can't interleave with
    a result write for the previous step: set_result() drops the result on
    the floor if its step_id no longer matches the active step.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._step: GuidanceStep | None = None
        self._baseline: frozenset[str] = frozenset()
        self._result: GuidanceResult | None = None
        self._counter = 0

    def next_step_id(self, expected_pin_id: str) -> str:
        with self._lock:
            self._counter += 1
            return f"step-{self._counter}-{expected_pin_id.lower()}"

    def set_step(self, step: GuidanceStep, baseline_pin_ids: frozenset[str]) -> None:
        with self._lock:
            self._step = step
            self._baseline = baseline_pin_ids
            self._result = None  # verdicts for the previous step don't carry over

    def clear(self) -> None:
        with self._lock:
            self._step = None
            self._baseline = frozenset()
            self._result = None

    def get_step(self) -> tuple[GuidanceStep, frozenset[str]] | None:
        with self._lock:
            if self._step is None:
                return None
            return self._step, self._baseline

    def set_result(self, result: GuidanceResult) -> None:
        with self._lock:
            if self._step is None or self._step.step_id != result.step_id:
                return  # step was swapped/cleared while this tick was in flight
            self._result = result

    def get_result(self) -> GuidanceResult | None:
        with self._lock:
            return self._result

    def snapshot(self) -> dict:
        """One consistent read for GET /api/guidance/state."""
        with self._lock:
            if self._step is None:
                return {"active": False, "step": None, "result": None}
            step = {
                "step_id": self._step.step_id,
                "expected_pin_id": self._step.expected_pin_id,
                "expected_role": self._step.expected_role,
                "component_id": self._step.component_id,
                "hint_color": self._step.hint_color,
                "advance_mode": self._step.advance_mode,
            }
            result = None
            if self._result is not None:
                result = {
                    "step_id": self._result.step_id,
                    "expected_pin_id": self._result.expected_pin_id,
                    "status": self._result.status,
                    "actual_pin_id": self._result.actual_pin_id,
                    "confidence": round(float(self._result.confidence), 3),
                    "as_of_ms": self._result.as_of_ms,
                    "ai_hint": self._result.ai_hint,
                }
                if self._result.source_wire_id is not None:
                    result["source_wire_id"] = self._result.source_wire_id
                if self._result.source_endpoint is not None:
                    result["source_endpoint"] = self._result.source_endpoint
                if self._result.reason is not None:
                    result["reason"] = self._result.reason
                if self._result.visual_check is not None:
                    result["visual_check"] = dict(self._result.visual_check)
            return {"active": True, "step": step, "result": result}
