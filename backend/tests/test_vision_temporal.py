from __future__ import annotations

from app.vision.interface import PinDetection
from app.vision.temporal import AttachmentClassifier, WireTraceStabilizer
from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult


def _wire(pin_id: str, frame_id: int, *, other: str = "floating") -> WireTraceResult:
    a = WireEndpoint(kind="pin", px=(100.0, 100.0), pin_id=pin_id,
                     confidence=0.9)
    if other == "floating":
        b = WireEndpoint(kind="floating", px=(260.0, 160.0), confidence=0.0)
    else:
        b = WireEndpoint(kind="pin", px=(260.0, 160.0), pin_id=other,
                         confidence=0.9)
    wire = WireInstance(
        wire_id=99,
        color="blue",
        path_px=[(100.0, 100.0), (180.0, 130.0), (260.0, 160.0)],
        endpoint_a=a,
        endpoint_b=b,
        confidence=0.9,
        ambiguous=False,
    )
    return WireTraceResult(frame_id=frame_id, ts_ms=float(frame_id),
                           board_tracking="locked", wires=[wire])


def _empty(frame_id: int) -> WireTraceResult:
    return WireTraceResult(frame_id=frame_id, ts_ms=float(frame_id),
                           board_tracking="locked", wires=[])


def test_new_wire_requires_two_observations():
    fuser = WireTraceStabilizer()
    assert fuser.update(_wire("D7", 1)).wires == []
    stable = fuser.update(_wire("D7", 2))
    assert len(stable.wires) == 1
    assert stable.wires[0].wire_id == 0
    assert stable.wires[0].endpoint_a.pin_id == "D7"


def test_conflicting_pin_observations_become_ambiguous_then_recover():
    fuser = WireTraceStabilizer()
    fuser.update(_wire("D8", 1))
    fuser.update(_wire("D7", 2))
    uncertain = fuser.update(_wire("D7", 3))
    assert uncertain.wires[0].ambiguous is True
    assert uncertain.wires[0].endpoint_a.kind == "ambiguous_tie"
    assert uncertain.wires[0].endpoint_a.candidates == ["D7", "D8"]

    recovered = fuser.update(_wire("D7", 4))
    assert recovered.wires[0].ambiguous is False
    assert recovered.wires[0].endpoint_a.kind == "pin"
    assert recovered.wires[0].endpoint_a.pin_id == "D7"


def test_latest_ambiguous_observation_overrides_an_older_pin_vote():
    fuser = WireTraceStabilizer()
    fuser.update(_wire("D7", 1))
    fuser.update(_wire("D7", 2))
    tie = WireEndpoint(kind="ambiguous_tie", px=(100.0, 100.0),
                        candidates=["D7", "D8"], confidence=0.0)
    result = WireTraceResult(
        frame_id=3, ts_ms=3.0, board_tracking="locked",
        wires=[WireInstance(
            wire_id=99, color="blue",
            path_px=[(100.0, 100.0), (260.0, 160.0)],
            endpoint_a=tie, endpoint_b=_wire("D7", 3).wires[0].endpoint_b,
            confidence=0.8, ambiguous=True,
        )],
    )
    stable = fuser.update(result)
    assert stable.wires[0].endpoint_a.kind == "ambiguous_tie"


def test_latest_floating_observation_overrides_an_older_pin_vote():
    fuser = WireTraceStabilizer()
    fuser.update(_wire("D7", 1))
    fuser.update(_wire("D7", 2))
    fuser.update(_wire("D7", 3))

    latest = _wire("D7", 4).wires[0]
    latest.endpoint_a = WireEndpoint(
        kind="floating", px=(100.0, 100.0), confidence=0.0
    )
    stable = fuser.update(WireTraceResult(
        frame_id=4, ts_ms=4.0, board_tracking="locked", wires=[latest]
    ))

    assert stable.wires[0].endpoint_a.kind == "floating"
    assert stable.wires[0].endpoint_a.pin_id is None
    assert stable.wires[0].endpoint_a.confidence == 0.0


def test_missing_wire_is_not_rendered_while_track_is_retained():
    fuser = WireTraceStabilizer()
    fuser.update(_wire("D7", 1))
    assert fuser.update(_wire("D7", 2)).wires
    assert fuser.update(_empty(3)).wires == []
    # A reappearance reconnects to the retained track and keeps its id.
    assert fuser.update(_wire("D7", 4)).wires[0].wire_id == 0


def test_searching_clears_old_tracks():
    fuser = WireTraceStabilizer()
    fuser.update(_wire("D7", 1))
    fuser.update(_wire("D7", 2))
    searching = WireTraceResult(frame_id=3, ts_ms=3.0,
                                board_tracking="searching", wires=[])
    assert fuser.update(searching).wires == []
    assert fuser.update(_wire("D7", 4)).wires == []


def test_same_colour_tracks_prefer_pin_identity_when_geometry_crosses():
    def make(pin_id: str, x: float, frame_id: int) -> WireTraceResult:
        wire = WireInstance(
            wire_id=99, color="blue",
            path_px=[(x, 100.0), (x + 40.0, 120.0)],
            endpoint_a=WireEndpoint(kind="pin", px=(x, 100.0), pin_id=pin_id, confidence=0.9),
            endpoint_b=WireEndpoint(kind="floating", px=(x + 40.0, 120.0), confidence=0.0),
            confidence=0.9, ambiguous=False,
        )
        return WireTraceResult(frame_id=frame_id, ts_ms=float(frame_id),
                               board_tracking="locked", wires=[wire])

    fuser = WireTraceStabilizer()
    first = WireTraceResult(
        frame_id=1, ts_ms=1.0, board_tracking="locked",
        wires=[make("D7", 100.0, 1).wires[0], make("D8", 130.0, 1).wires[0]],
    )
    fuser.update(first)
    second = WireTraceResult(
        frame_id=2, ts_ms=2.0, board_tracking="locked",
        wires=[make("D7", 130.0, 2).wires[0], make("D8", 100.0, 2).wires[0]],
    )
    stable = fuser.update(second)
    by_id = {wire.endpoint_a.pin_id: wire.wire_id for wire in stable.wires}
    assert by_id == {"D7": 0, "D8": 1}


def test_reversed_skeleton_path_keeps_endpoint_sides_stable():
    first = _wire("D7", 1, other="D8")
    reversed_wire = first.wires[0]
    reversed_wire = WireInstance(
        wire_id=99,
        color=reversed_wire.color,
        path_px=list(reversed(reversed_wire.path_px)),
        endpoint_a=reversed_wire.endpoint_b,
        endpoint_b=reversed_wire.endpoint_a,
        confidence=reversed_wire.confidence,
        ambiguous=False,
    )
    second = WireTraceResult(
        frame_id=2, ts_ms=2.0, board_tracking="locked",
        wires=[reversed_wire],
    )

    fuser = WireTraceStabilizer()
    fuser.update(first)
    stable = fuser.update(second)
    assert len(stable.wires) == 1
    assert stable.wires[0].endpoint_a.pin_id == "D7"
    assert stable.wires[0].endpoint_b.pin_id == "D8"


def test_track_match_radius_scales_with_pin_pitch():
    fuser = WireTraceStabilizer()
    assert fuser.match_radius_px == 48.0
    assert fuser._effective_match_radius(0.0) == 48.0
    # The 4 px/pitch case is clamped down to avoid cross-track association.
    assert fuser._effective_match_radius(4.0) == 24.0
    assert fuser._effective_match_radius(10.0) == 47.5
    # High-resolution motion is allowed more room, but never unbounded.
    assert fuser._effective_match_radius(40.0) == 96.0


def test_temporal_track_buffers_honor_configured_windows():
    fuser = WireTraceStabilizer(
        confirm_hits=2, confirm_window=4, vote_window=8,
    )
    fuser.update(_wire("D7", 1))
    assert fuser._tracks[0].seen.maxlen == 4
    assert fuser._tracks[0].history.maxlen == 8

    # One visible sample, two misses, then a reappearance still has two hits
    # in the configured four-tick confirmation window.  With the old hardcoded
    # deque(maxlen=3), this would incorrectly remain unconfirmed.
    fuser.update(_empty(2))
    fuser.update(_empty(3))
    stable = fuser.update(_wire("D7", 4))
    assert len(stable.wires) == 1


def _attachment_frame(frame_id: int, endpoint_x: float, pin_x: float):
    wire = WireInstance(
        wire_id=0, color="blue",
        path_px=[(endpoint_x, 100.0), (260.0, 160.0)],
        endpoint_a=WireEndpoint(kind="pin", px=(pin_x, 100.0),
                                pin_id="D7", confidence=0.9),
        endpoint_b=WireEndpoint(kind="floating", px=(260.0, 160.0)),
        confidence=0.9, ambiguous=False, attachment="unknown",
    )
    result = WireTraceResult(
        frame_id=frame_id, ts_ms=float(frame_id), board_tracking="locked",
        wires=[wire], geometry={"pitch_px": 10.0},
    )
    pins = [PinDetection("D7", pin_x, 100.0, 1.0, True, "JDIGITAL", 7)]
    return result, pins


def test_attachment_remains_unknown_without_board_motion():
    classifier = AttachmentClassifier()
    result = None
    for frame_id in range(1, 8):
        frame, pins = _attachment_frame(frame_id, 100.0, 100.0)
        result = classifier.update(frame, pins)
    assert result is not None
    assert result.wires[0].attachment == "unknown"
    assert result.wires[0].attachment_confidence == 0.0


def test_attachment_marks_inserted_when_raw_endpoint_follows_pin():
    classifier = AttachmentClassifier()
    result = None
    for frame_id, x in enumerate((100.0, 104.0, 108.0, 112.0), 1):
        frame, pins = _attachment_frame(frame_id, x, x)
        result = classifier.update(frame, pins)
    assert result is not None
    assert result.wires[0].attachment == "inserted"
    assert result.wires[0].attachment_confidence > 0.5


def test_attachment_marks_resting_when_raw_endpoint_does_not_follow_pin():
    classifier = AttachmentClassifier()
    result = None
    for frame_id, pin_x in enumerate((100.0, 104.0, 108.0, 112.0), 1):
        frame, pins = _attachment_frame(frame_id, 100.0, pin_x)
        result = classifier.update(frame, pins)
    assert result is not None
    assert result.wires[0].attachment == "resting"
    assert result.wires[0].attachment_confidence > 0.5


def test_attachment_conflict_does_not_hide_as_old_inserted():
    classifier = AttachmentClassifier()
    result = None
    for frame_id, x in enumerate((100.0, 104.0, 108.0, 112.0), 1):
        frame, pins = _attachment_frame(frame_id, x, x)
        result = classifier.update(frame, pins)
    assert result.wires[0].attachment == "inserted"

    # A fresh resting observation is conflicting evidence, not permission to
    # keep publishing the old inserted verdict.
    frame, pins = _attachment_frame(5, 100.0, 116.0)
    result = classifier.update(frame, pins)
    assert result.wires[0].attachment == "unknown"
