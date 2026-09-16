"""Scale-normalized wire snapping regression tests.

This deliberately tests source-frame geometry at several distances.  It is
not a substitute for a real desk capture, but it catches fixed-pixel tuning
regressions before they reach hardware validation.
"""
import cv2
import numpy as np

from app.vision.interface import PinDetection
from app.vision.wire_tracer import snap_endpoint, trace


def _run(scale: float):
    width, height = int(640 * scale), int(420 * scale)
    pins = [
        PinDetection("D7", 170 * scale, 160 * scale, 1.0,
                     header="JTOP", index=0),
        PinDetection("D8", 180 * scale, 160 * scale, 1.0,
                     header="JTOP", index=1),
        PinDetection("D9", 190 * scale, 160 * scale, 1.0,
                     header="JTOP", index=2),
    ]
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    # BGR red; length and thickness are scaled with the scene.
    cv2.line(frame,
             (round(170 * scale), round(160 * scale)),
             (round(330 * scale), round(225 * scale)),
             (0, 0, 235), max(2, round(4 * scale)), cv2.LINE_AA)
    return trace(frame, pins, 1, 1.0, "locked", colors=["red"])


def test_wire_pin_identity_is_stable_across_source_scales():
    results = [_run(scale) for scale in (0.75, 1.0, 1.5)]
    for result in results:
        resolved = [
            ep.pin_id
            for wire in result.wires
            for ep in (wire.endpoint_a, wire.endpoint_b)
            if ep.kind == "pin"
        ]
        assert "D7" in resolved
        assert result.geometry is not None
        assert 1.45 <= result.geometry["snap_radius_over_pitch"] <= 1.65


def test_midpoint_between_adjacent_pins_stays_ambiguous_across_scales():
    for scale in (0.75, 1.0, 1.5):
        pins = [
            PinDetection("D7", 170 * scale, 160 * scale, 1.0,
                         header="JTOP", index=0),
            PinDetection("D8", 180 * scale, 160 * scale, 1.0,
                         header="JTOP", index=1),
        ]
        endpoint = snap_endpoint((175 * scale, 160 * scale), pins,
                                 pitch_px=10 * scale)
        assert endpoint.kind == "ambiguous_tie"
        assert endpoint.candidates == ["D7", "D8"]


def test_endpoint_far_across_header_row_stays_floating_across_scales():
    for scale in (0.75, 1.0, 1.5):
        pins = [
            PinDetection("D7", 170 * scale, 160 * scale, 1.0,
                         header="JTOP", index=0),
            PinDetection("D8", 180 * scale, 160 * scale, 1.0,
                         header="JTOP", index=1),
        ]
        endpoint = snap_endpoint((170 * scale, 160 * scale + 1.6 * 10 * scale),
                                 pins, pitch_px=10 * scale)
        assert endpoint.kind == "floating"
