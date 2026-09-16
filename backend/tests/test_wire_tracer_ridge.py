"""Tests for the M20/M21 hue-agnostic ridge channel + cross-method dedup.

Synthetic-imagery tests for segment_edge_ridge (a drawn "wire" of arbitrary
hue on a flat background must mask regardless of color; a wide blob must
not), plus pure-logic tests for _merge_cross_method_duplicates and the
trace_wires/trace plumbing of include_edge_agnostic.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.vision import wire_tracer
from app.vision.interface import PinDetection
from app.vision.wire_tracer import (
    COLOR_UNKNOWN,
    WireEndpoint,
    WireInstance,
    _merge_cross_method_duplicates,
    segment_edge_ridge,
    trace_wires,
    snap_endpoint,
)


def _frame_with_line(bgr_bg, bgr_line, thickness=5, size=(480, 640)) -> np.ndarray:
    frame = np.full((size[0], size[1], 3), bgr_bg, dtype=np.uint8)
    cv2.line(frame, (60, 100), (560, 350), bgr_line, thickness)
    return frame


# ------------------------------------------------------ segment_edge_ridge ----

def test_ridge_detects_dark_line_regardless_of_hue():
    """A dark line on a light desk masks whether it's gray, blue, or brown -
    the channel never consults hue."""
    for line in ((60, 60, 60), (120, 60, 40), (40, 60, 120)):  # gray, blue-ish, brown-ish
        frame = _frame_with_line(bgr_bg=(170, 170, 170), bgr_line=line)
        mask = segment_edge_ridge(frame)
        assert cv2.countNonZero(mask) > 500, f"line {line} not detected"


def test_ridge_detects_light_line_on_dark_background():
    """Polarity-agnostic: tophat side catches bright-on-dark."""
    frame = _frame_with_line(bgr_bg=(50, 50, 50), bgr_line=(210, 210, 210))
    assert cv2.countNonZero(segment_edge_ridge(frame)) > 500


def test_ridge_ignores_flat_background():
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    assert cv2.countNonZero(segment_edge_ridge(frame)) == 0


def test_ridge_ignores_wide_blob():
    """A big rectangle has contrast at its EDGES but its body is wider than
    any wire - the shared width filter must drop it."""
    frame = np.full((480, 640, 3), 170, dtype=np.uint8)
    cv2.rectangle(frame, (200, 150), (440, 330), (60, 60, 60), -1)
    mask = segment_edge_ridge(frame)
    # Edge rings may survive as thin structures; the blob interior must not.
    interior = mask[200:280, 260:380]
    assert cv2.countNonZero(interior) == 0


def test_ridge_respects_board_exclusion():
    frame = _frame_with_line(bgr_bg=(170, 170, 170), bgr_line=(60, 60, 60))
    full = cv2.countNonZero(segment_edge_ridge(frame))
    outline = [(0.0, 0.0), (640.0, 0.0), (640.0, 480.0), (0.0, 480.0)]
    excluded = cv2.countNonZero(segment_edge_ridge(frame, board_outline=outline))
    assert excluded < full * 0.2  # nearly everything inside the polygon is gone


def test_color_wire_crossing_board_is_kept_but_board_only_blob_is_removed():
    """Board suppression must not cut a wire that runs over the PCB.

    A colored component with no pixels outside the board remains a board
    artifact and is removed. A thin component that crosses the silhouette is
    retained so endpoint tracing can continue to the header.
    """
    frame = np.full((360, 520, 3), (170, 170, 170), dtype=np.uint8)
    cv2.line(frame, (20, 220), (430, 220), (0, 0, 235), 7)
    cv2.rectangle(frame, (180, 100), (320, 170), (0, 0, 235), -1)
    outline = [(80.0, 70.0), (430.0, 70.0), (430.0, 300.0), (80.0, 300.0)]

    mask = wire_tracer.segment_color(frame, "red", board_outline=outline)

    assert mask[220, 250] > 0  # the crossing wire survives inside the board
    assert mask[135, 250] == 0  # board-contained colored blob is suppressed


def test_pale_yellow_wire_survives_low_saturation_and_small_highlight_seam():
    """Regression for the real C920 pale-yellow Dupont false negative.

    The insulation measured around S=70 and had a four-pixel segmentation
    seam.  It must remain one traceable branch, not several short fragments.
    """
    frame = np.full((260, 640, 3), (170, 170, 170), dtype=np.uint8)
    yellow_hsv = np.uint8([[[27, 78, 220]]])
    yellow_bgr = tuple(
        int(channel)
        for channel in cv2.cvtColor(yellow_hsv, cv2.COLOR_HSV2BGR)[0, 0]
    )
    cv2.line(frame, (60, 130), (297, 130), yellow_bgr, 6)
    cv2.line(frame, (302, 130), (580, 130), yellow_bgr, 6)

    mask = wire_tracer.segment_color(frame, "yellow")
    skeleton = wire_tracer.skeletonize_mask(mask)
    branches = wire_tracer.trace_branches(skeleton, "yellow")

    assert len(branches) == 1
    assert len(branches[0].points) > 500


# ------------------------------------------------------------ trace_wires ----

def test_trace_wires_edge_channel_off_by_default():
    frame = _frame_with_line(bgr_bg=(170, 170, 170), bgr_line=(60, 60, 60))
    result = trace_wires(frame, colors=["red"])
    assert COLOR_UNKNOWN not in result


def test_trace_wires_edge_channel_finds_neutral_line():
    """A gray line matches no HSV band but the ridge channel traces it."""
    frame = _frame_with_line(bgr_bg=(170, 170, 170), bgr_line=(60, 60, 60))
    result = trace_wires(frame, colors=["red"], include_edge_agnostic=True)
    assert COLOR_UNKNOWN in result
    assert len(result[COLOR_UNKNOWN]) >= 1
    assert result[COLOR_UNKNOWN][0].color == COLOR_UNKNOWN


def test_trace_branches_marks_a_junction_as_ambiguous_evidence():
    """A crossing must not be treated as one confidently ordered wire path."""
    skeleton = np.zeros((220, 220), dtype=np.uint8)
    cv2.line(skeleton, (20, 110), (200, 110), 255, 1)
    cv2.line(skeleton, (110, 20), (110, 200), 255, 1)
    branches = wire_tracer.trace_branches(skeleton, "red")
    assert branches
    assert any(branch.junction_count > 0 for branch in branches)


def test_lattice_snap_rejects_same_row_neighbour_when_cross_error_is_large():
    """A radial 16px snap can choose the neighbouring pin; the projected
    header lattice must use the along-row coordinate for identity."""
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    # This endpoint is closer to neither pin in a useful 2-D sense, but its
    # along-row coordinate is clearly on D7's side of the lattice boundary.
    endpoint = snap_endpoint((104.0, 115.0), pins)
    assert endpoint.kind == "pin"
    assert endpoint.pin_id == "D7"


def test_lattice_snap_reports_neighbour_tie_instead_of_guessing():
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    endpoint = snap_endpoint((105.0, 100.0), pins)
    assert endpoint.kind == "ambiguous_tie"
    assert endpoint.candidates == ["D7", "D8"]


def test_lattice_uses_local_projected_pitch_under_perspective():
    """A stretched far end of a projected row must retain endpoint recall.

    The row is intentionally non-uniform, as a pin lattice becomes in a
    perspective view.  P3's local half-cell is wider than the row median;
    using only the median would incorrectly return floating for this valid
    terminal while the neighbouring cells remain safely excluded.
    """
    pins = [
        PinDetection(f"P{i}", x, 100.0, 0.9, header="J", index=i)
        for i, x in enumerate((100.0, 110.0, 122.0, 136.0, 152.0))
    ]
    endpoint = snap_endpoint((142.75, 104.0), pins)
    assert endpoint.kind == "pin"
    assert endpoint.pin_id == "P3"


def test_skeleton_tail_is_extrapolated_to_header_row_before_snapping():
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    # The mask stops at (91,91), while the straight wire tail points toward
    # the actual D7 row intersection at (100,100).
    path = [(91.0, 91.0), (88.0, 88.0), (84.0, 84.0), (80.0, 80.0),
            (76.0, 76.0)]
    result = wire_tracer._snap_path_endpoint(path, pins, at_start=True)
    assert result.kind == "pin"
    assert result.pin_id == "D7"


def test_tail_extrapolation_covers_a_real_dupont_housing_length():
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    # Coloured insulation ends 40 px (four 10 px pitches) before the row;
    # the black 9.9 mm female housing occupies the missing segment.
    path = [(100.0, 60.0), (100.0, 55.0), (100.0, 50.0),
            (100.0, 45.0), (100.0, 40.0)]
    result = wire_tracer._snap_path_endpoint(path, pins, at_start=True)
    assert result.kind == "pin"
    assert result.pin_id == "D7"


def test_tail_extrapolation_rejects_a_gap_longer_than_a_dupont_housing():
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    path = [(100.0, 55.0), (100.0, 50.0), (100.0, 45.0),
            (100.0, 40.0), (100.0, 35.0)]
    result = wire_tracer._snap_path_endpoint(path, pins, at_start=True)
    assert result.kind == "floating"


def test_tail_refinement_does_not_extrapolate_in_front_of_terminal():
    pins = [
        PinDetection("D7", 100.0, 100.0, 0.9, header="J", index=0),
        PinDetection("D8", 110.0, 100.0, 0.9, header="J", index=1),
        PinDetection("D9", 120.0, 100.0, 0.9, header="J", index=2),
    ]
    # This path starts above the row but proceeds through it.  The row
    # intersection is in front of the observed terminal, so it is not a
    # valid missing-tail extrapolation.
    path = [(110.0, 91.0), (110.0, 95.0), (110.0, 99.0),
            (110.0, 103.0), (110.0, 107.0)]
    assert wire_tracer._refine_endpoint_to_row(
        path, pins, at_start=True) is None


# ------------------------------------------- _merge_cross_method_duplicates ----

def _pin_ep(pin_id: str, conf: float = 0.8) -> WireEndpoint:
    return WireEndpoint(kind="pin", px=(1.0, 1.0), pin_id=pin_id, confidence=conf)


def _floating_ep() -> WireEndpoint:
    return WireEndpoint(kind="floating", px=(9.0, 9.0), confidence=0.0)


def _instance(color: str, a: WireEndpoint, b: WireEndpoint, conf: float = 0.8,
              wire_id: int = 0) -> WireInstance:
    return WireInstance(
        wire_id=wire_id, color=color, path_px=[(0.0, 0.0)], endpoint_a=a,
        endpoint_b=b, confidence=conf, ambiguous=False,
        detection_methods=["edge"] if color == COLOR_UNKNOWN else ["color"],
    )


def test_merge_same_pin_pair_across_methods():
    color_wire = _instance("red", _pin_ep("5V"), _pin_ep("D7"), conf=0.8, wire_id=0)
    edge_wire = _instance(COLOR_UNKNOWN, _pin_ep("D7"), _pin_ep("5V"), conf=0.6, wire_id=1)
    merged = _merge_cross_method_duplicates([color_wire, edge_wire])
    assert len(merged) == 1
    m = merged[0]
    assert m.color == "red"  # the color-band identity wins the label
    assert m.detection_methods == ["color", "edge"]
    assert m.confidence == 0.9  # max(0.8, 0.6) + 0.1 agreement bump


def test_merge_bump_caps_at_one():
    a = _instance("red", _pin_ep("5V"), _pin_ep("D7"), conf=0.95)
    b = _instance(COLOR_UNKNOWN, _pin_ep("5V"), _pin_ep("D7"), conf=0.9, wire_id=1)
    assert _merge_cross_method_duplicates([a, b])[0].confidence == 1.0


def test_different_pin_pairs_not_merged():
    a = _instance("red", _pin_ep("5V"), _pin_ep("D7"))
    b = _instance(COLOR_UNKNOWN, _pin_ep("5V"), _pin_ep("D8"), wire_id=1)
    assert len(_merge_cross_method_duplicates([a, b])) == 2


def test_floating_instances_never_merged():
    """A partial resolve is not proof both are the same wire - both stay."""
    a = _instance("red", _pin_ep("5V"), _floating_ep())
    b = _instance(COLOR_UNKNOWN, _pin_ep("5V"), _floating_ep(), wire_id=1)
    assert len(_merge_cross_method_duplicates([a, b])) == 2


def test_edge_only_pair_keeps_unknown_color():
    a = _instance(COLOR_UNKNOWN, _pin_ep("5V"), _pin_ep("D7"))
    b = _instance(COLOR_UNKNOWN, _pin_ep("D7"), _pin_ep("5V"), wire_id=1)
    merged = _merge_cross_method_duplicates([a, b])
    assert len(merged) == 1
    assert merged[0].color == COLOR_UNKNOWN


def test_ambiguous_junction_wires_are_not_cross_method_merged():
    a = _instance("red", _pin_ep("5V"), _pin_ep("D7"), conf=0.8)
    a.ambiguous = True
    a.crossed_junction_count = 1
    b = _instance(COLOR_UNKNOWN, _pin_ep("5V"), _pin_ep("D7"), conf=0.6, wire_id=1)
    b.ambiguous = True
    b.crossed_junction_count = 1
    assert len(_merge_cross_method_duplicates([a, b])) == 2
