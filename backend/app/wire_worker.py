"""Wire-trace worker thread (M17 — real-time integration of app.vision.wire_tracer).

Loop, on its own throttled cadence (NOT the pose-tracking frame rate - wire
tracing costs ~45-90ms/frame across up to 9 colors, see
docs/wire-recognition-design.md §5): pull the latest camera frame, read the
latest *already-computed* board pose (read-only - this thread never
recomputes pose, it only reads VisionWorker's most recent DetectionState),
run app.vision.wire_tracer.trace(), store the result in WireTraceState, and
publish a "wire_trace" WS message through the SAME DetectionBroadcaster
VisionWorker already uses (app.api.ws.DetectionBroadcaster - no second
broadcaster, no new WS route; see docs/api-contract.md §2).

Why its own thread, not folded into VisionWorker._run(): folding a
~45-90ms/frame cost into the pose-tracking loop would degrade the
already-shipped, already-tested <100ms/frame detection cadence - the exact
reasoning docs/wiring-verification-architecture.md §9 "Rejected #1" already
applied once for a different worker. WireTraceWorker is FrameBus's fourth
independent reader (MJPEG client, VisionWorker, and - per the
wiring-verification design - WiringWorker are the other three);
FrameBus.get_latest() is documented multi-reader-safe, so FrameBus itself
needed no changes.

Publish policy: every tick that completes without an exception publishes,
whether or not `wires` differs from the previous tick. A "did it change"
diff was considered and rejected: interval_s already caps the publish rate
to something a WS client can handle (default 0.5s = 2Hz, far under the 30Hz
detection_hz ceiling), so a diff step would add bookkeeping without reducing
any load that actually matters.
"""
from __future__ import annotations

from dataclasses import replace
import logging
import threading
import time
from typing import Callable

from app.capture.bus import FrameBus
from app.vision import wire_tracer
from app.vision.guidance import (
    GuidanceResult,
    GuidanceState,
    GuidanceVerdictDebouncer,
    evaluate_guidance_step,
)
from app.vision.guided_roi import GuidedRoiVerifier
from app.verification.adapters import geometry_evidence
from app.verification.state import VerificationState
from app.vision.wire_state import WireTraceState
from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult
from app.vision.temporal import AttachmentClassifier, WireTraceStabilizer
from app.vision_worker import DetectionState

log = logging.getLogger(__name__)

# Practical subset of wire_tracer.WIRE_COLOR_BANDS (9 total) checked each
# tick by default. Narrowed, not exhaustive, for two reasons:
#  - per-tick cost scales with color count (each color = one more HSV mask +
#    skeletonize pass; ~45-90ms/frame total across all 9, see
#    docs/wire-recognition-design.md §5) - checking 5 instead of 9 cuts that
#    proportionally.
#  - red (5V/3.3V power) + yellow/green (common signal-wire colors) + brown
#    (common GND-wire color) + blue (common signal-wire color) cover the
#    common demo-circuit case with hue bands that segment reliably in THIS
#    environment. white/gray/black remain excluded: the design doc (§2a) is
#    explicit that hue-based segmentation has materially lower recall for
#    low-saturation colors, and live testing on 2026-07-28 showed why that
#    matters in practice, not just in theory - "black" alone matched desk
#    shadows/cables heavily enough to produce ~97 spurious wires in a
#    single frame. "blue" was tried the same day and failed for a related
#    reason (desk surface + a laptop bezel matched it too, ~22,000 px false
#    positive vs. ~7,800 px for the one real wire present) but was FIXED on
#    2026-07-29, not just left excluded like black: a real blue dupont wire
#    was sampled live and the false-positive bezel pixels turned out to be
#    separable from it by saturation alone (bezel S median 77 vs. wire S
#    median 144, near-identical hue) - see the WIRE_COLOR_BANDS["blue"]
#    comment in wire_tracer.py for the exact numbers. "brown" was added
#    2026-07-28 the same way: sampled against a real coffee/brown wire, its
#    saturation floor (unlike black's near-zero one) excludes the
#    near-neutral shadows that sank black. Leaving black/white/gray wires
#    unrecognized by default remains a known, documented limitation (design
#    doc §6) - low-saturation colors don't have an equivalent separating
#    signal available. Re-enable per-deployment via config.yaml's
#    wire_trace.colors if a demo's lighting/desk turns out friendlier than
#    this one was.
DEFAULT_COLORS: list[str] = ["red", "yellow", "green", "brown", "blue"]

# Adjacent 2.54 mm header pins need at least this much source-frame separation
# before endpoint snapping is allowed to make a physical wiring claim. The
# density gate below is also required; both match tools/scale_quality.py's
# physical gate and are only applied to real pipeline sources by build_app
# unless a caller overrides them.
DEFAULT_RUNTIME_MIN_PIN_PITCH_PX = 18.0
DEFAULT_RUNTIME_MIN_PX_PER_MM = 8.0

# How long each tick waits for a *newer* frame to show up before giving up
# and returning to the interval_s throttle wait. Deliberately short: we
# already throttled via interval_s, so this is just a small grace window for
# a frame that is about to land (FrameBus wakes waiters via notify_all() the
# instant put() runs), not a second independent throttle. Keeping it short
# also bounds stop()'s worst-case extra latency if the thread happens to be
# inside this wait when stop() is called (get_latest() only wakes early on a
# new frame, not on our stop Event).
_FRAME_WAIT_TIMEOUT_S = 0.1
_DETECTION_SYNC_TIMEOUT_S = 0.08
_GEOMETRY_BURST_INTERVAL_S = 0.05


def _endpoint_message(
    ep: WireEndpoint,
    video_size: tuple[int, int] | None = None,
    canonical_px: tuple[float, float] | None = None,
) -> dict:
    """Serialize a WireEndpoint per docs/api-contract.md §2's exact shape:
    "pin" carries pin_id (no px); "floating" carries px (no pin_id);
    "ambiguous_tie" carries px + candidates instead of pin_id."""
    msg: dict = {"kind": ep.kind, "confidence": round(float(ep.confidence), 3)}
    if ep.kind == "pin":
        msg["pin_id"] = ep.pin_id
    elif ep.kind == "floating":
        msg["px"] = [round(float(ep.px[0]), 1), round(float(ep.px[1]), 1)]
    else:  # ambiguous_tie
        msg["px"] = [round(float(ep.px[0]), 1), round(float(ep.px[1]), 1)]
        msg["candidates"] = list(ep.candidates)
    if ep.distance_px is not None:
        msg["distance_px"] = round(float(ep.distance_px), 1)
    if ep.margin_px is not None:
        msg["margin_px"] = round(float(ep.margin_px), 1)
    if ep.snap_margin_px is not None:
        msg["snap_margin_px"] = round(float(ep.snap_margin_px), 1)
    # For a resolved pin, the endpoint's internal ``px`` is intentionally the
    # observed wire/skeleton terminal.  The normalized connection coordinate
    # must instead point at the live projected pin; otherwise downstream
    # consumers see a systematic ferrule/cut-mask offset while the pin_id is
    # correct.  Legacy/injected results without pin_positions retain the old
    # endpoint px as a compatibility fallback.
    normalized_source = canonical_px if ep.kind == "pin" and canonical_px is not None else ep.px
    if video_size is not None:
        width, height = video_size
        if width > 0 and height > 0:
            # `px` remains intentionally omitted for a resolved pin to keep
            # the original API shape, but normalized_px is useful to every
            # downstream consumer and is resolution-independent.
            msg["normalized_px"] = [
                round(float(normalized_source[0]) / width, 6),
                round(float(normalized_source[1]) / height, 6),
            ]
    return msg


def _wire_message(
    wire: WireInstance,
    video_size: tuple[int, int] | None = None,
    pin_positions: dict[str, tuple[float, float]] | None = None,
) -> dict:
    pin_position = None
    if wire.endpoint_a.kind == "pin" and wire.endpoint_a.pin_id:
        pin_position = (pin_positions or {}).get(wire.endpoint_a.pin_id)
    endpoint_a_msg = _endpoint_message(wire.endpoint_a, video_size, pin_position)
    pin_position = None
    if wire.endpoint_b.kind == "pin" and wire.endpoint_b.pin_id:
        pin_position = (pin_positions or {}).get(wire.endpoint_b.pin_id)
    endpoint_b_msg = _endpoint_message(wire.endpoint_b, video_size, pin_position)

    msg = {
        "wire_id": wire.wire_id,
        "color": wire.color,
        "confidence": round(float(wire.confidence), 3),
        "ambiguous": bool(wire.ambiguous),
        "detection_methods": list(wire.detection_methods),
        "path": [[round(float(x), 1), round(float(y), 1)] for x, y in wire.path_px],
        "endpoint_a": endpoint_a_msg,
        "endpoint_b": endpoint_b_msg,
    }
    if wire.crossed_junction_count:
        msg["crossed_junction_count"] = int(wire.crossed_junction_count)
    if wire.attachment is not None:
        msg["attachment"] = wire.attachment
        msg["attachment_confidence"] = round(float(wire.attachment_confidence), 3)
    if video_size is not None:
        width, height = video_size
        if width > 0 and height > 0:
            msg["path_normalized"] = [
                [round(float(x) / width, 6), round(float(y) / height, 6)]
                for x, y in wire.path_px
            ]
            endpoints = (wire.endpoint_a, wire.endpoint_b)
            pin_ids = [ep.pin_id for ep in endpoints if ep.kind == "pin" and ep.pin_id]
            kinds = [ep.kind for ep in endpoints]
            # A live 2-D pin match is still only a geometric candidate.  The
            # tracer deliberately marks attachment as "unknown" until a
            # physical/motion cue proves insertion, and a junction walk is
            # not a unique wire path. Neither may be presented as clean
            # connection evidence.
            if wire.ambiguous or wire.attachment in ("unknown", "resting"):
                connection_status = "uncertain"
            elif all(ep.kind == "pin" for ep in endpoints):
                connection_status = "candidate"
            elif any(ep.kind == "ambiguous_tie" for ep in endpoints):
                connection_status = "uncertain"
            elif any(ep.kind == "pin" for ep in endpoints):
                connection_status = "partial"
            else:
                connection_status = "floating"
            # This is a geometric candidate only.  Electrical validity is
            # deliberately left to the Rule Engine; a VLM never upgrades it.
            msg["connection"] = {
                "status": connection_status,
                "pin_ids": pin_ids,
                "endpoint_kinds": kinds,
                "confidence": round(float(wire.confidence), 3),
            }
    return msg


def wire_trace_message(result: WireTraceResult, board_id: str) -> dict:
    """Serialize a WireTraceResult to the WS wire format (docs/api-contract.md §2).

    board_id is a constructor-level parameter of WireTraceWorker (not a
    field of WireTraceResult itself - unlike DetectionResult, WireTraceResult
    carries no board_id; the worker supplies it, same as it supplies the
    "type" envelope field).
    """
    wire_messages = [
        _wire_message(w, result.video_size, result.pin_positions)
        for w in result.wires
    ]
    if result.video_size is not None:
        for wire_msg, wire in zip(wire_messages, result.wires):
            connection = wire_msg.get("connection")
            if isinstance(connection, dict):
                connection["endpoints"] = [
                    {
                        "object_id": board_id if endpoint.kind == "pin" else None,
                        "pin": endpoint.pin_id if endpoint.kind == "pin" else None,
                        "kind": endpoint.kind,
                        "position": wire_msg[key].get("normalized_px"),
                    }
                    for endpoint, key in ((wire.endpoint_a, "endpoint_a"),
                                          (wire.endpoint_b, "endpoint_b"))
                ]
    msg = {
        "type": "wire_trace",
        "board_id": board_id,
        "frame_id": result.frame_id,
        "ts_ms": result.ts_ms,
        "board_tracking": result.board_tracking,
        "wires": wire_messages,
    }
    if result.video_size is not None:
        msg["video_size"] = [result.video_size[0], result.video_size[1]]
    if result.geometry is not None:
        msg["geometry"] = {
            key: round(float(value), 4)
            for key, value in result.geometry.items()
        }
    if result.suppressed_reason is not None:
        msg["suppressed_reason"] = result.suppressed_reason
    return msg


def guidance_check_message(g: GuidanceResult, trace: WireTraceResult, board_id: str) -> dict:
    """Serialize a GuidanceResult to the WS "guidance_check" shape
    (docs/api-contract.md §2; design doc §3b). actual_pin_id only appears for
    wrong_pin — same only-when-meaningful field policy as _endpoint_message.
    """
    msg: dict = {
        "type": "guidance_check",
        "board_id": board_id,
        "step_id": g.step_id,
        "frame_id": trace.frame_id,
        "ts_ms": g.as_of_ms,
        "board_tracking": trace.board_tracking,
        "expected_pin_id": g.expected_pin_id,
        "status": g.status,
        "confidence": round(float(g.confidence), 3),
        "ai_hint": g.ai_hint,
    }
    if g.status == "wrong_pin":
        msg["actual_pin_id"] = g.actual_pin_id
    if g.source_wire_id is not None:
        msg["source_wire_id"] = g.source_wire_id
    if g.source_endpoint is not None:
        msg["source_endpoint"] = g.source_endpoint
    if g.reason is not None:
        msg["reason"] = g.reason
    if g.visual_check is not None:
        msg["visual_check"] = dict(g.visual_check)
    return msg


class WireTraceWorker:
    def __init__(
        self,
        bus: FrameBus,
        detection_state: DetectionState,
        state: WireTraceState,
        board_id: str,
        publish: Callable[[dict], None] | None = None,
        interval_s: float = 0.5,
        guidance_interval_s: float = 0.3,
        colors: list[str] | None = None,
        guidance_state: GuidanceState | None = None,
        component_pose_state=None,
        include_edge_agnostic: bool = False,
        min_pin_pitch_px: float | None = None,
        min_px_per_mm: float | None = None,
        verification_state: VerificationState | None = None,
    ) -> None:
        self._bus = bus
        self._detection_state = detection_state
        self._state = state
        self._board_id = board_id
        self._publish = publish
        self._interval_s = max(interval_s, 0.0)
        self._guidance_interval_s = max(guidance_interval_s, 0.0)
        self._colors = list(colors) if colors is not None else list(DEFAULT_COLORS)
        # Optional: when provided, each tick also evaluates the active
        # guidance step against the fresh trace (M22). Same thread, same
        # tick, ~<1ms of set/string comparisons — deliberately NOT a new
        # worker (design doc §3a: cost is snap_endpoint-scale, and a
        # separate cadence would let verdicts lag the trace they're about).
        self._guidance_state = guidance_state
        self._component_pose_state = component_pose_state
        self._include_edge_agnostic = include_edge_agnostic  # M21; see WireTraceConfig
        self._min_pin_pitch_px = (
            None if min_pin_pitch_px is None else max(0.0, float(min_pin_pitch_px))
        )
        self._min_px_per_mm = (
            None if min_px_per_mm is None else max(0.0, float(min_px_per_mm))
        )
        self._verification_state = verification_state
        self._stabilizer = WireTraceStabilizer()
        self._attachment_classifier = AttachmentClassifier()
        self._guidance_debouncer = GuidanceVerdictDebouncer()
        self._guided_roi = GuidedRoiVerifier()
        self._guidance_step_id: str | None = None
        self._guidance_step_ref = None
        self._tick_count = 0
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def set_board_id(self, board_id: str) -> None:
        """Retarget public messages after an atomic controller switch."""
        self._board_id = str(board_id)
        self._stabilizer.reset()
        self._attachment_classifier.reset()
        self._guidance_debouncer.reset()
        self._guided_roi.reset()
        self._guidance_step_id = None
        self._guidance_step_ref = None
        self._wake.set()

    def _geometry_collection_active(self) -> bool:
        if self._verification_state is None:
            return False
        target = self._verification_state.target()
        return bool(
            target is not None
            and target.geometry_requested
            and not target.geometry_complete
        )

    def _effective_interval_s(self) -> float:
        """Shorten the wire-trace throttle while a guidance step is active."""
        if self._geometry_collection_active():
            return min(self._interval_s, _GEOMETRY_BURST_INTERVAL_S)
        if self._guidance_state is not None and self._guidance_state.get_step() is not None:
            return min(self._interval_s, self._guidance_interval_s)
        return self._interval_s

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name="wire-trace-worker", daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Interrupt the cadence wait, e.g. after a manual geometry request."""
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _synchronize_detection(self, slot, *, newer_than: int = -1):
        """Pair a frame with the pose computed from that exact frame.

        FrameBus is latest-only and the vision/wire workers are independent
        readers. Without this check, a moving board can be traced with a
        different frame's pin projection and land on a plausible neighbouring
        pin. Waiting briefly is preferable to guessing; the next cadence
        retries if the detector is slower.
        """
        deadline = time.monotonic() + _DETECTION_SYNC_TIMEOUT_S
        current = slot
        while not self._stop.is_set():
            synchronized = self._detection_state.get_synchronized()
            if synchronized is not None and synchronized[0].seq > newer_than:
                return synchronized

            # Compatibility path for injected tests/callers that set only a
            # DetectionResult. Production uses the atomic pair above.
            detection = self._detection_state.get()
            if detection is not None and detection.frame_id == current.frame_id:
                return current, detection

            # If the vision worker has already advanced beyond the original
            # slot, move to the current frame rather than pairing across time.
            latest = self._bus.get_latest(timeout=0.0)
            if latest is not None and latest.seq >= current.seq:
                current = latest
                detection = self._detection_state.get()
                if detection is not None and detection.frame_id == current.frame_id:
                    return current, detection

            if time.monotonic() >= deadline:
                break
            self._stop.wait(timeout=0.004)
        return None, None

    def _publish_result(self, result: WireTraceResult) -> None:
        self._state.set(result)
        if self._publish is not None:
            try:
                self._publish(wire_trace_message(result, self._board_id))
            except Exception:
                log.exception("wire_trace publish failed")

    def _publish_guidance(
        self,
        result: WireTraceResult,
        frame_bgr=None,
        detection=None,
        geometry_result: WireTraceResult | None = None,
    ) -> None:
        """Evaluate/publish guidance against the same result, if active."""
        if self._guidance_state is None:
            return
        active = self._guidance_state.get_step()
        if active is None:
            self._guidance_debouncer.reset()
            self._guided_roi.reset()
            self._guidance_step_id = None
            self._guidance_step_ref = None
            return
        step, baseline = active
        try:
            raw_verdict = evaluate_guidance_step(step, result, baseline)
            # A guide restart intentionally reuses stable plan IDs such as
            # ``photoresistor-vcc``. Compare the activation object as well as
            # its text ID so temporal guidance state is always reset.
            if step is not self._guidance_step_ref:
                self._guidance_debouncer.reset()
                self._guidance_step_id = step.step_id
                self._guidance_step_ref = step
            verdict = self._guidance_debouncer.update(raw_verdict)
            component_pose = (
                self._component_pose_state.get(step.component_id)
                if self._component_pose_state is not None
                else None
            )
            visual_check = self._guided_roi.update(
                step, frame_bgr, detection, component_pose
            ) if frame_bgr is not None else None
            verdict.visual_check = visual_check
            if self._verification_state is not None:
                geometry_trace = geometry_result or result
                geometry_item = geometry_evidence(
                    step,
                    geometry_trace,
                    raw_verdict,
                    detection,
                    component_pose,
                )
                self._verification_state.add_geometry_sample(
                    step.step_id,
                    geometry_item,
                    frame_id=geometry_trace.frame_id,
                    now_ms=float(geometry_trace.ts_ms),
                )
        except Exception:
            log.exception("guidance evaluation failed (step %s)", step.step_id)
            return
        self._guidance_state.set_result(verdict)
        if self._publish is not None:
            try:
                self._publish(guidance_check_message(verdict, result, self._board_id))
                if self._verification_state is not None:
                    verification_message = self._verification_state.message(
                        self._board_id, result.frame_id, result.ts_ms
                    )
                    if verification_message is not None:
                        self._publish(verification_message)
            except Exception:
                log.exception("guidance_check publish failed")

    def _run(self) -> None:
        last_seq = -1
        while not self._stop.is_set():
            # Throttle FIRST - this is the "on its own cadence, NOT per-frame"
            # cost control (see module docstring). Waiting on the Event (not
            # time.sleep) lets stop() interrupt immediately instead of up to
            # interval_s late. Active guidance uses the shorter configured
            # cadence, while idle tracing keeps the normal cost guard.
            self._wake.wait(timeout=self._effective_interval_s())
            self._wake.clear()
            if self._stop.is_set():
                break

            slot = self._bus.get_latest(timeout=_FRAME_WAIT_TIMEOUT_S, newer_than=last_seq)
            if slot is None:
                continue  # no new frame since our last tick - nothing to trace

            slot, detection = self._synchronize_detection(slot, newer_than=last_seq)
            if slot is None or detection is None:
                # No same-frame pose: do not trace against stale geometry.
                continue
            # The synchronizer may have advanced to a newer bus slot while
            # waiting for the matching detector result; do not process that
            # same slot again on the next cadence.
            last_seq = slot.seq

            if detection.tracking != "locked":
                # Clear an old wire overlay as soon as pose confidence is no
                # longer authoritative. Keeping the last wire visible here
                # looks like a still-valid connection on a moving/occluded
                # board, so a short blank interval is safer.
                self._stabilizer.reset()
                self._attachment_classifier.reset()
                empty = WireTraceResult(
                    frame_id=slot.frame_id,
                    ts_ms=slot.ts_ms,
                    board_tracking=detection.tracking,
                    wires=[],
                    video_size=(int(slot.frame.shape[1]), int(slot.frame.shape[0])),
                )
                self._publish_result(empty)
                self._publish_guidance(empty, slot.frame, detection)
                last_seq = slot.seq
                continue

            # A pose can be geometrically valid while the delivered stream is
            # too small for safe header assignment. Do this check before the
            # expensive color/skeleton pass: a low-scale frame must not turn a
            # nearby pixel into a published connection candidate.
            pitch_px = wire_tracer.projected_pin_pitch(detection.pins)
            px_per_mm = pitch_px / 2.54 if pitch_px > 0.0 else 0.0
            scale_blocked = (
                self._min_pin_pitch_px is not None
                and (pitch_px <= 0.0 or pitch_px < self._min_pin_pitch_px)
            ) or (
                self._min_px_per_mm is not None
                and (px_per_mm <= 0.0 or px_per_mm < self._min_px_per_mm)
            )
            if scale_blocked:
                self._stabilizer.reset()
                self._attachment_classifier.reset()
                blocked = WireTraceResult(
                    frame_id=slot.frame_id,
                    ts_ms=slot.ts_ms,
                    board_tracking=detection.tracking,
                    wires=[],
                    video_size=(int(slot.frame.shape[1]), int(slot.frame.shape[0])),
                    geometry={
                        "pitch_px": round(float(pitch_px), 3),
                        "px_per_mm": round(float(px_per_mm), 4),
                        "min_pitch_px": round(float(self._min_pin_pitch_px), 3)
                        if self._min_pin_pitch_px is not None else 0.0,
                        "min_px_per_mm": round(float(self._min_px_per_mm), 4)
                        if self._min_px_per_mm is not None else 0.0,
                        "snap_radius_px": 0.0,
                        "snap_radius_over_pitch": 0.0,
                    },
                    suppressed_reason="scale_below_minimum",
                )
                self._publish_result(blocked)
                self._publish_guidance(blocked, slot.frame, detection)
                continue

            try:
                trace_kwargs = {
                    "include_edge_agnostic": self._include_edge_agnostic,
                }
                if self._geometry_collection_active():
                    # Sensor-side colour often stops at the black female
                    # housing and becomes a board-disconnected fragment. Keep
                    # it only as private manual-geometry evidence; the public
                    # overlay remains board-scoped below.
                    trace_kwargs["include_floating"] = True
                raw_result = wire_tracer.trace(
                    slot.frame,
                    detection.pins,
                    slot.frame_id,
                    slot.ts_ms,
                    detection.tracking,
                    self._colors,
                    detection.wire_exclusion_px or detection.outline_px,
                    **trace_kwargs,
                )
            except Exception:
                log.exception("wire_tracer.trace failed (frame_id=%d)", slot.frame_id)
                continue

            # Board-disconnected fragments are useful for the Sensor endpoint
            # check but must not clutter or weaken the normal public overlay.
            public_input = replace(
                raw_result,
                wires=[
                    wire
                    for wire in raw_result.wires
                    if not (
                        wire.endpoint_a.kind == "floating"
                        and wire.endpoint_b.kind == "floating"
                    )
                ],
            )
            # Stabilize only the public board-scoped trace. Manual geometry
            # consumes raw_result so five observations do not first pay a
            # second temporal-confirmation delay.
            result = self._stabilizer.update(public_input)
            # A 2-D snap alone cannot prove insertion.  Use only consecutive
            # board motion plus raw endpoint motion; otherwise keep the live
            # attachment explicitly unknown.
            result = self._attachment_classifier.update(result, detection.pins)
            self._tick_count += 1
            if self._tick_count % 20 == 0 and result.geometry:
                log.info(
                    "scale-sanity pitch=%.2fpx px/mm=%.3f radius/pitch=%.3f",
                    result.geometry.get("pitch_px", 0.0),
                    result.geometry.get("px_per_mm", 0.0),
                    result.geometry.get("snap_radius_over_pitch", 0.0),
                )
            self._publish_result(result)

            # M22: evaluate the active guidance step (if any) against this
            # same fresh result — pure set/string comparison, no second
            # perception pass.
            self._publish_guidance(
                result,
                slot.frame,
                detection,
                geometry_result=raw_result,
            )
