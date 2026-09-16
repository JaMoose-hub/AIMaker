from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.verification.adapters import geometry_evidence, visual_evidence
from app.vision.guidance import GuidanceResult, GuidanceStep
from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult


STEP = GuidanceStep("step-a0", "A0", expected_role="AO")


def _trace(endpoint: WireEndpoint) -> WireTraceResult:
    return WireTraceResult(
        frame_id=3,
        ts_ms=1000.0,
        board_tracking="locked",
        wires=[WireInstance(
            wire_id=0,
            color="yellow",
            path_px=[],
            endpoint_a=endpoint,
            endpoint_b=WireEndpoint(kind="floating", px=(0.0, 0.0)),
            confidence=0.8,
            ambiguous=False,
        )],
    )


def test_geometry_pass_is_position_only_even_when_attachment_is_not_proven():
    trace = _trace(WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="A0", confidence=0.88))
    trace.wires[0].attachment = "unknown"
    raw = GuidanceResult("step-a0", "A0", "uncertain", reason="attachment_unverified")
    item = geometry_evidence(STEP, trace, raw, SimpleNamespace(confidence=0.93))
    assert item.status == "pass"
    assert item.score == 0.88
    assert item.details["scope"] == "board_endpoint"


def test_geometry_wrong_pin_names_actual_pin():
    trace = _trace(WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="A1", confidence=0.91))
    raw = GuidanceResult(
        "step-a0", "A0", "wrong_pin", actual_pin_id="A1", confidence=0.91
    )
    item = geometry_evidence(STEP, trace, raw, SimpleNamespace(confidence=0.95))
    assert item.status == "fail"
    assert item.reason == "wrong_pin"
    assert item.details["actual_pin"] == "A1"


def test_geometry_names_other_nearby_pin_even_when_attachment_is_unverified():
    trace = _trace(
        WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="A1", confidence=0.44)
    )
    trace.wires[0].attachment = "unknown"
    raw = GuidanceResult(
        "step-a0", "A0", "uncertain", reason="attachment_unverified"
    )
    item = geometry_evidence(STEP, trace, raw, SimpleNamespace(confidence=0.93))
    assert item.status == "uncertain"
    assert item.reason == "endpoint_near_other_pin"
    assert item.details["actual_pin"] == "A1"
    assert item.details["candidate_confidence"] == 0.44


def test_roi_candidate_waits_for_explicit_vlm_and_keeps_raw_score():
    item = visual_evidence(
        {
            "status": "candidate",
            "reason": "both_endpoints_changed",
            "confidence": 0.5,
            "board_change": 0.2,
            "component_change": 0.15,
        },
        now_ms=1000.0,
    )
    assert item.status == "uncertain"
    assert item.reason == "awaiting_manual_vlm"
    assert item.score == pytest.approx(0.0)
    assert item.details["raw_change_confidence"] == 0.5


def test_hand_occlusion_never_becomes_visual_failure_or_pass():
    item = visual_evidence(
        {"status": "uncertain", "reason": "hand_occlusion"}, now_ms=1000.0
    )
    assert item.status == "uncertain"
    assert item.reason == "hand_occlusion"


def _component_pose(*, tracking="locked", confidence=0.6):
    return SimpleNamespace(
        component_id="photoresistor-module",
        tracking=tracking,
        confidence=confidence,
        pins=(
            SimpleNamespace(id="VCC", x=100.0, y=100.0, visible=True),
            SimpleNamespace(id="GND", x=120.0, y=100.0, visible=True),
            SimpleNamespace(id="AO", x=160.0, y=100.0, visible=True),
        ),
    )


def test_photoresistor_geometry_accepts_both_targets_on_one_fragment():
    step = GuidanceStep(
        "photoresistor-ao",
        "A0",
        expected_role="AO",
        component_id="photoresistor-module",
    )
    trace = _trace(WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="A0", confidence=0.88))
    trace.wires[0].endpoint_b = WireEndpoint(kind="floating", px=(160.5, 100.5))
    raw = GuidanceResult("photoresistor-ao", "A0", "correct", confidence=0.88)

    item = geometry_evidence(
        step,
        trace,
        raw,
        SimpleNamespace(confidence=0.93),
        _component_pose(),
    )

    assert item.status == "pass"
    assert item.reason == "both_endpoints_near_targets"
    assert item.score >= 0.70
    assert item.details["scope"] == "independent_endpoints"
    assert item.details["component_pin"] == "AO"


def test_photoresistor_geometry_accepts_independent_endpoint_fragments():
    step = GuidanceStep(
        "photoresistor-ao",
        "A0",
        expected_role="AO",
        component_id="photoresistor-module",
    )
    board_fragment = WireInstance(
        wire_id=1,
        color="yellow",
        path_px=[],
        endpoint_a=WireEndpoint(
            kind="pin", px=(10.0, 10.0), pin_id="A0", confidence=0.42
        ),
        endpoint_b=WireEndpoint(kind="floating", px=(40.0, 40.0)),
        confidence=0.42,
        ambiguous=True,
    )
    sensor_fragment = WireInstance(
        wire_id=2,
        color="yellow",
        path_px=[],
        endpoint_a=WireEndpoint(kind="floating", px=(160.5, 100.5)),
        endpoint_b=WireEndpoint(kind="floating", px=(190.0, 130.0)),
        confidence=0.40,
        ambiguous=False,
    )
    trace = WireTraceResult(
        frame_id=3,
        ts_ms=1000.0,
        board_tracking="locked",
        wires=[board_fragment, sensor_fragment],
        geometry={"snap_radius_px": 15.0},
    )
    raw = GuidanceResult("photoresistor-ao", "A0", "correct", confidence=0.42)

    item = geometry_evidence(
        step,
        trace,
        raw,
        SimpleNamespace(confidence=0.93),
        _component_pose(),
    )

    assert item.status == "pass"
    assert item.score >= 0.70
    assert item.details["board_wire_id"] == 1
    assert item.details["component_wire_id"] == 2
    assert item.details["same_wire_fragment"] is False


def test_photoresistor_geometry_extends_visible_tail_across_black_dupont_housing():
    step = GuidanceStep(
        "photoresistor-vcc",
        "3V3",
        expected_role="VCC",
        component_id="photoresistor-module",
    )
    board_fragment = WireInstance(
        wire_id=1,
        color="yellow",
        path_px=[(10.0, 10.0), (20.0, 5.0)],
        endpoint_a=WireEndpoint(
            kind="pin", px=(10.0, 10.0), pin_id="3V3", confidence=0.92
        ),
        endpoint_b=WireEndpoint(kind="floating", px=(20.0, 5.0)),
        confidence=0.82,
        ambiguous=False,
    )
    # The yellow insulation stops 75 px before VCC at the black female
    # housing. The local tail runs upward into the visible wire, so its
    # outward continuation points down to VCC at (100, 100).
    sensor_path = [(100.0, 25.0 - 5.0 * index) for index in range(18)]
    sensor_fragment = WireInstance(
        wire_id=2,
        color="yellow",
        path_px=sensor_path,
        endpoint_a=WireEndpoint(kind="floating", px=sensor_path[0]),
        endpoint_b=WireEndpoint(kind="floating", px=sensor_path[-1]),
        confidence=0.76,
        ambiguous=False,
    )
    trace = WireTraceResult(
        frame_id=8,
        ts_ms=1000.0,
        board_tracking="locked",
        wires=[board_fragment, sensor_fragment],
        geometry={"snap_radius_px": 15.0},
    )

    item = geometry_evidence(
        step,
        trace,
        GuidanceResult("photoresistor-vcc", "3V3", "correct", confidence=0.92),
        SimpleNamespace(confidence=0.93),
        _component_pose(),
    )

    assert item.status == "pass"
    assert item.details["component_assignment_method"] == "directional_extrapolation"
    assert item.details["component_distance_px"] == pytest.approx(75.0)
    assert item.details["component_extension_px"] == pytest.approx(75.0)
    assert item.details["component_cross_track_px"] == pytest.approx(0.0)


def test_photoresistor_directional_extension_reports_the_pin_lane_it_hits():
    step = GuidanceStep(
        "photoresistor-vcc",
        "3V3",
        expected_role="VCC",
        component_id="photoresistor-module",
    )
    trace = _trace(
        WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="3V3", confidence=0.9)
    )
    # Same physical housing gap, but the tail lane is aligned with GND at x=120.
    trace.wires[0].path_px = [
        (120.0, -60.0 + 5.0 * index) for index in range(18)
    ]
    trace.wires[0].endpoint_b = WireEndpoint(
        kind="floating", px=trace.wires[0].path_px[-1]
    )

    item = geometry_evidence(
        step,
        trace,
        GuidanceResult("photoresistor-vcc", "3V3", "correct", confidence=0.9),
        SimpleNamespace(confidence=0.93),
        _component_pose(),
    )

    assert item.status == "uncertain"
    assert item.reason == "component_endpoint_near_other_pin"
    assert item.details["actual_pin"] == "GND"
    assert item.details["component_assignment_method"] == "directional_extrapolation"


def test_photoresistor_geometry_reports_sensor_endpoint_near_another_pin():
    step = GuidanceStep(
        "photoresistor-ao",
        "A0",
        expected_role="AO",
        component_id="photoresistor-module",
    )
    trace = _trace(WireEndpoint(kind="pin", px=(10.0, 10.0), pin_id="A0", confidence=0.88))
    trace.wires[0].endpoint_b = WireEndpoint(kind="floating", px=(120.5, 100.0))
    raw = GuidanceResult("photoresistor-ao", "A0", "correct", confidence=0.88)

    item = geometry_evidence(
        step,
        trace,
        raw,
        SimpleNamespace(confidence=0.93),
        _component_pose(),
    )

    assert item.status == "uncertain"
    assert item.reason == "component_endpoint_near_other_pin"
    assert item.details["actual_pin"] == "GND"
