from types import SimpleNamespace

import cv2
import numpy as np

from app.vision.endpoint_color import (
    _colour_mask,
    _pin_entry_mask,
    build_guided_board_endpoint_color_preview,
    build_guided_component_endpoint_color_preview,
    build_guided_endpoint_color_preview,
    inspect_guided_board_endpoint_color,
    inspect_guided_component_endpoint_color,
    inspect_guided_endpoint_colors,
    stabilize_endpoint_colour_samples,
)


def _pin(identifier: str, x: float, y: float, *, component: bool = False) -> SimpleNamespace:
    key = "id" if component else "pin_id"
    return SimpleNamespace(**{key: identifier, "x": x, "y": y, "visible": True})


def _scene(*, board_colour: tuple[int, int, int] | None, sensor_colour: tuple[int, int, int] | None):
    frame = np.full((220, 480, 3), 112, dtype=np.uint8)
    # The coloured insulation is deliberately outside the two component outlines.
    # The local sampler looks right from UNO Q and left from the Sensor module.
    if board_colour is not None:
        cv2.line(frame, (112, 110), (198, 110), board_colour, 5)
    if sensor_colour is not None:
        cv2.line(frame, (262, 110), (348, 110), sensor_colour, 5)

    detection = SimpleNamespace(
        outline_px=[[20, 60], [90, 60], [90, 160], [20, 160]],
        pins=[_pin("3V3", 90, 110), _pin("GND_P1", 90, 120)],
    )
    component_pose = SimpleNamespace(
        outline_px=[[370, 60], [440, 60], [440, 160], [370, 160]],
        pins=[_pin("VCC", 370, 110, component=True), _pin("GND", 370, 120, component=True)],
    )
    step = SimpleNamespace(expected_pin_id="3V3", expected_role="VCC")
    return frame, detection, component_pose, step


def test_guided_endpoint_color_reports_matching_coloured_insulation() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),  # yellow in BGR
        sensor_colour=(0, 255, 255),
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "yellow"
    assert result["component"]["color"] == "yellow"
    assert result["board"]["pin_proximity"] >= 0.95
    assert result["component"]["pin_proximity"] >= 0.95
    assert result["connection_proximity"] >= 0.95
    assert len(result["board"]["lab"]) == 3
    assert len(result["component"]["lab"]) == 3
    assert result["advisory"] is True


def test_temporal_colour_sampler_uses_consensus_and_marks_a_tie_uncertain() -> None:
    stable = stabilize_endpoint_colour_samples([
        {"color": "brown", "confidence": 0.9, "pin_proximity": 0.9, "pixels": 24, "lab": [30, 14, 18]},
        {"color": "brown", "confidence": 0.8, "pin_proximity": 0.8, "pixels": 20, "lab": [32, 13, 17]},
        {"color": "brown", "confidence": 0.85, "pin_proximity": 0.8, "pixels": 22, "lab": [31, 14, 18]},
        {"color": "red", "confidence": 0.7, "pin_proximity": 0.7, "pixels": 18, "lab": [35, 38, 25]},
        {"color": "red", "confidence": 0.7, "pin_proximity": 0.7, "pixels": 18, "lab": [35, 38, 25]},
    ])
    assert stable["color"] == "brown"
    assert stable["sample_count"] == 5
    assert stable["stable_hits"] == 3
    assert stable["temporal_stable"] is True
    assert stable["lab"] == [31.0, 14.0, 18.0]

    unstable = stabilize_endpoint_colour_samples([
        {"color": "brown", "confidence": 0.8, "pin_proximity": 0.8, "pixels": 20},
        {"color": "brown", "confidence": 0.8, "pin_proximity": 0.8, "pixels": 20},
        {"color": "red", "confidence": 0.8, "pin_proximity": 0.8, "pixels": 20},
        {"color": "red", "confidence": 0.8, "pin_proximity": 0.8, "pixels": 20},
        {"color": None, "confidence": 0.0, "pin_proximity": 0.0, "pixels": 0},
    ])
    assert unstable["temporal_stable"] is False
    assert unstable["ambiguous"] is True
    assert unstable["reason"] == "temporal_color_unstable"


def test_guided_endpoint_colours_can_be_sampled_independently() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),
        sensor_colour=(0, 255, 255),
    )

    board = inspect_guided_board_endpoint_color(frame, detection, step)
    component = inspect_guided_component_endpoint_color(frame, component_pose, step)

    assert board["color"] == "yellow"
    assert component["color"] == "yellow"

    board_preview = build_guided_board_endpoint_color_preview(frame, detection, step)
    component_preview = build_guided_component_endpoint_color_preview(frame, component_pose, step)
    for preview in (board_preview, component_preview):
        assert preview is not None
        image = cv2.imdecode(np.frombuffer(preview, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert image is not None
        assert image.shape[:2] == (340, 932)


def test_uno_entry_corridor_starts_closer_without_lowering_its_score_reference() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),
        sensor_colour=(0, 255, 255),
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    # Board pins are 10 px apart in this fixture: the HSV entry begins at
    # 2.4 pitches, while Pin-proximity scoring still starts at 3.2 pitches.
    assert result["board"]["inner_radius_px"] == 24.0
    assert result["board"]["proximity_reference_radius_px"] == 32.0
    assert result["board"]["pin_proximity"] >= 0.95


def test_pin_entry_fan_starts_near_pin_and_keeps_its_far_coverage() -> None:
    center = (100.0, 100.0)
    entry = _pin_entry_mask(
        (220, 220),
        center,
        (1.0, 0.0),
        pin_pitch_px=10.0,
        inner_radius_px=32.0,
        outer_radius_px=100.0,
        exclusion_outline=None,
    )
    yy, xx = np.nonzero(entry)
    radial = np.hypot(xx - center[0], yy - center[1])

    # The green fan begins just outside the Pin and still reaches the former
    # far edge (58 px for this 10 px-pitch fixture).
    assert radial.min() <= 4.1
    assert radial.max() >= 57.9


def test_sensor_entry_fan_can_extend_past_a_long_dupont_housing() -> None:
    center = (100.0, 100.0)
    entry = _pin_entry_mask(
        (220, 220),
        center,
        (1.0, 0.0),
        pin_pitch_px=10.0,
        inner_radius_px=32.0,
        outer_radius_px=100.0,
        exclusion_outline=None,
        entry_depth_px=60.0,
    )
    yy, xx = np.nonzero(entry)
    radial = np.hypot(xx - center[0], yy - center[1])

    # Sensor-only calibration ends at inner radius + 60 px instead of +36.
    assert radial.max() >= 91.9


def test_pin_entry_fan_allows_a_perspective_skewed_header_exit() -> None:
    center = (100.0, 100.0)
    entry = _pin_entry_mask(
        (220, 220),
        center,
        (0.0, -1.0),
        pin_pitch_px=10.0,
        inner_radius_px=32.0,
        outer_radius_px=100.0,
        exclusion_outline=None,
    )

    # A 45-degree departure is common when the pose outline's nearest edge is
    # perspective-skewed from the physical header. It must remain an eligible
    # near-Pin sample, while a sideward (90-degree) crossing wire stays out.
    assert entry[70, 130] != 0
    assert entry[100, 140] == 0


def test_guided_endpoint_color_reports_a_mismatch_without_declaring_failure() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),  # yellow
        sensor_colour=(0, 255, 0),  # green
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "mismatch"
    assert result["board"]["color"] == "yellow"
    assert result["component"]["color"] == "green"
    assert result["advisory"] is True


def test_component_header_normal_accepts_vertical_wire_from_an_off_center_pin() -> None:
    frame, detection, _component_pose, step = _scene(
        board_colour=(0, 255, 255),  # yellow
        sensor_colour=None,
    )
    # The Header is across the top edge. VCC is deliberately off-centre: the
    # old centroid-to-pin vector points up-right, whereas a female connector
    # correctly leaves straight up, normal to the Header edge.
    component_pose = SimpleNamespace(
        outline_px=[[370, 100], [440, 100], [440, 200], [370, 200]],
        pins=[
            _pin("VCC", 430, 105, component=True),
            _pin("GND", 410, 105, component=True),
            _pin("AO", 390, 105, component=True),
        ],
    )
    cv2.line(frame, (430, 0), (430, 100), (0, 255, 255), 5)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["component"]["color"] == "yellow"
    assert result["component"]["pin_proximity"] >= 0.9


def test_board_edge_normal_accepts_vertical_wire_from_an_off_center_header_pin() -> None:
    frame, _detection, component_pose, step = _scene(
        board_colour=None,
        sensor_colour=(0, 255, 255),
    )
    # The top board header is off-centre. A centroid-to-Pin direction would
    # point up-right, but the Dupont connector leaves perpendicular to the
    # Header edge, straight up.
    detection = SimpleNamespace(
        outline_px=[[20, 100], [90, 100], [90, 200], [20, 200]],
        pins=[_pin("3V3", 80, 105), _pin("GND_P1", 60, 105)],
    )
    cv2.line(frame, (80, 0), (80, 100), (0, 255, 255), 5)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "yellow"
    assert result["board"]["pin_proximity"] >= 0.9


def test_pi5_vertical_header_follows_a_wire_bent_back_over_the_pcb() -> None:
    frame = np.full((260, 300, 3), 118, dtype=np.uint8)
    # Green Pi PCB with J8 along its upper edge. The black female housing sits
    # on Pin 1, then the red lead bends down-right over the board. A fixed PCB
    # outward normal would look upward and erase the entire real lead.
    cv2.rectangle(frame, (45, 70), (255, 235), (62, 112, 58), -1)
    cv2.line(frame, (92, 74), (99, 96), (18, 18, 18), 10)
    cv2.line(frame, (99, 96), (155, 205), (0, 0, 230), 6)
    detection = SimpleNamespace(
        board_id="raspberry-pi-5",
        outline_px=[[45, 70], [255, 70], [255, 235], [45, 235]],
        pins=[_pin("3V3_P1", 92, 74), _pin("5V_P2", 103, 74)],
    )
    step = SimpleNamespace(expected_pin_id="3V3_P1", expected_role="VCC")

    result = inspect_guided_board_endpoint_color(frame, detection, step)

    assert result["color"] == "red"
    assert result["direction_source"] == "adaptive_360"
    assert result["outward_direction"][1] > 0.65
    assert result["pin_proximity"] >= 0.75


def test_pi5_adaptive_direction_does_not_treat_the_broad_pcb_as_a_wire() -> None:
    frame = np.full((260, 300, 3), 118, dtype=np.uint8)
    cv2.rectangle(frame, (45, 70), (255, 235), (55, 135, 55), -1)
    detection = SimpleNamespace(
        board_id="raspberry-pi-5",
        outline_px=[[45, 70], [255, 70], [255, 235], [45, 235]],
        pins=[_pin("3V3_P1", 92, 74), _pin("5V_P2", 103, 74)],
    )
    step = SimpleNamespace(expected_pin_id="3V3_P1", expected_role="VCC")

    result = inspect_guided_board_endpoint_color(frame, detection, step)

    assert result["color"] is None
    assert result["direction_source"] == "pcb_edge"


def test_endpoint_colour_falls_back_when_an_edge_normal_is_degenerate() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),
        sensor_colour=(0, 255, 255),
    )

    # A transient detector frame can expose an outline but produce a zero
    # edge-normal. The centroid-to-Pin direction remains valid in this simple
    # scene and should keep the advisory check available.
    from app.vision.endpoint_color import _sample_endpoint_colour

    endpoint = _sample_endpoint_colour(
        frame,
        (90.0, 110.0),
        detection.outline_px,
        detection.pins,
        outward_override=(0.0, 0.0),
    )

    assert endpoint["color"] == "yellow"
    assert endpoint["reason"] == "color_sampled"


def test_guided_gnd_accepts_second_electrically_equivalent_gnd_pin() -> None:
    frame, _detection, component_pose, _step = _scene(
        board_colour=None,
        sensor_colour=(0, 255, 255),
    )
    detection = SimpleNamespace(
        outline_px=[[20, 60], [90, 60], [90, 160], [20, 160]],
        pins=[_pin("GND_P1", 90, 80), _pin("GND_P2", 90, 120)],
    )
    cv2.line(frame, (112, 120), (198, 120), (0, 255, 255), 5)
    step = SimpleNamespace(expected_pin_id="GND_P1", expected_role="VCC")

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "yellow"
    # The larger near-Pin fan may observe either physical GND header, but the
    # two pins are electrically equivalent and this HSV result stays advisory.
    assert result["board"]["pin_id"] in {"GND_P1", "GND_P2"}


def test_photoresistor_housing_calibration_raises_score_without_moving_entry_gate() -> None:
    frame, detection, _component_pose, step = _scene(
        board_colour=(0, 255, 255),
        sensor_colour=None,
    )
    # The yellow insulation appears only at the far edge of the same narrow
    # entry corridor after a deliberately long black Sensor housing.
    cv2.line(frame, (262, 110), (289, 110), (0, 255, 255), 5)
    pins = [
        _pin("VCC", 370, 110, component=True),
        _pin("GND", 370, 125, component=True),
        _pin("AO", 370, 140, component=True),
    ]
    uncalibrated_pose = SimpleNamespace(
        outline_px=[[370, 60], [440, 60], [440, 160], [370, 160]],
        pins=pins,
    )
    calibrated_pose = SimpleNamespace(
        component_id="photoresistor-module",
        outline_px=uncalibrated_pose.outline_px,
        pins=pins,
    )

    uncalibrated = inspect_guided_endpoint_colors(frame, detection, uncalibrated_pose, step)
    calibrated = inspect_guided_endpoint_colors(frame, detection, calibrated_pose, step)

    assert uncalibrated["status"] == "match"
    assert calibrated["status"] == "match"
    assert calibrated["component"]["pin_proximity"] >= 0.75
    assert calibrated["component"]["pin_proximity"] >= uncalibrated["component"]["pin_proximity"] + 0.20
    # The inner sampling/entry gate was not expanded for the calibration.
    assert calibrated["component"]["inner_radius_px"] == uncalibrated["component"]["inner_radius_px"]


def test_guided_endpoint_color_stays_unknown_when_coloured_insulation_is_not_visible() -> None:
    frame, detection, component_pose, step = _scene(board_colour=None, sensor_colour=None)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "unknown"
    assert result["board"]["color"] is None
    assert result["component"]["color"] is None


def test_guided_endpoint_color_preview_marks_the_same_local_sampling_regions() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),
        sensor_colour=(0, 255, 255),
    )

    jpeg = build_guided_endpoint_color_preview(frame, detection, component_pose, step)
    assert jpeg is not None
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert image is not None
    assert image.shape[:2] == (340, 1404)


def test_live_c920_brown_sample_is_not_rejected_or_mislabeled_as_orange() -> None:
    # Measured from the user's C920 raw-frame preview on 2026-08-11.
    hsv = np.array([[[7, 64, 115]]], dtype=np.uint8)

    assert int(_colour_mask(hsv, "brown")[0, 0]) > 0
    assert int(_colour_mask(hsv, "orange")[0, 0]) == 0


def test_live_c920_bright_low_saturation_brown_is_not_mislabeled_as_red() -> None:
    # Captured from the user's UNO Q GND endpoint on 2026-08-12. The brighter
    # brown was previously outside the brown V ceiling (175), leaving only the
    # broad red mask to classify the actual brown insulation.
    hsv = np.array([[[5, 118, 188]]], dtype=np.uint8)

    assert int(_colour_mask(hsv, "brown")[0, 0]) > 0
    assert int(_colour_mask(hsv, "red")[0, 0]) > 0


def test_live_c920_brown_wins_over_its_overlapping_red_pixels() -> None:
    # This mid-saturation brown falls inside the broad red band as well. The
    # endpoint classifier must use the complete candidate segment, not a
    # lexical red/brown tie break.
    bgr = cv2.cvtColor(
        np.array([[[7, 104, 115]]], dtype=np.uint8),
        cv2.COLOR_HSV2BGR,
    )[0, 0]
    colour = tuple(int(value) for value in bgr)
    frame, detection, component_pose, step = _scene(
        board_colour=colour,
        sensor_colour=colour,
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "brown"
    assert result["component"]["color"] == "brown"


def test_live_c920_dark_red_brown_is_not_mislabeled_as_bright_red() -> None:
    # Measured on the darker stripe of the user's current C920 Dupont ribbon.
    # Hue alone says red, so value must be part of the endpoint decision.
    bgr = cv2.cvtColor(
        np.array([[[1, 216, 85]]], dtype=np.uint8),
        cv2.COLOR_HSV2BGR,
    )[0, 0]
    colour = tuple(int(value) for value in bgr)
    frame, detection, component_pose, step = _scene(
        board_colour=colour,
        sensor_colour=colour,
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "brown"
    assert result["component"]["color"] == "brown"


def test_live_c920_bright_red_remains_red() -> None:
    bgr = cv2.cvtColor(
        np.array([[[2, 180, 210]]], dtype=np.uint8),
        cv2.COLOR_HSV2BGR,
    )[0, 0]
    colour = tuple(int(value) for value in bgr)
    frame, detection, component_pose, step = _scene(
        board_colour=colour,
        sensor_colour=colour,
    )

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "match"
    assert result["board"]["color"] == "red"
    assert result["component"]["color"] == "red"


def test_guided_endpoint_color_supports_black_and_white_insulation() -> None:
    for colour_name, bgr in (("black", (20, 20, 20)), ("white", (255, 255, 255))):
        frame, detection, component_pose, step = _scene(
            board_colour=bgr,
            sensor_colour=bgr,
        )

        result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

        assert result["status"] == "match"
        assert result["board"]["color"] == colour_name
        assert result["component"]["color"] == colour_name


def test_neutral_blob_is_not_accepted_as_wire_insulation() -> None:
    frame, detection, component_pose, step = _scene(board_colour=None, sensor_colour=None)
    # A broad black area in the board sampling sector is not a thin wire.
    cv2.rectangle(frame, (112, 85), (198, 135), (20, 20, 20), -1)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["board"]["color"] is None
    assert result["status"] == "unknown"


def test_crossing_colour_only_in_outer_sector_is_not_taken_as_pin_evidence() -> None:
    frame, detection, component_pose, step = _scene(board_colour=None, sensor_colour=None)
    # Both red patches lie in the large outward sectors, but leave a large gap
    # after the expected black connector housing. They are crossing evidence,
    # not an endpoint association, and must not receive a Pin score.
    cv2.line(frame, (158, 110), (198, 110), (0, 0, 255), 5)
    cv2.line(frame, (262, 110), (300, 110), (0, 0, 255), 5)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["status"] == "unknown"
    assert result["board"]["color"] is None
    assert result["component"]["color"] is None


def test_visual_pin_fan_does_not_promote_an_adjacent_ribbon_colour() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),  # target: yellow
        sensor_colour=(0, 255, 255),
    )
    # This red conductor stays inside the 60-degree visual guide fan but
    # outside the only decision corridor that follows the target connector.
    cv2.line(frame, (112, 145), (198, 145), (0, 0, 255), 4)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["board"]["color"] == "yellow"
    assert result["board"].get("ambiguous") is not True


def test_near_pin_fan_includes_an_adjacent_ribbon_conductor_as_advisory_evidence() -> None:
    frame, detection, component_pose, step = _scene(
        board_colour=(0, 255, 255),  # target: yellow
        sensor_colour=(0, 255, 255),
    )
    # A neighbouring ribbon conductor is one full header pitch below the
    # target. The deliberately wide near-Pin fan sees it; colour is therefore
    # advisory only and this must not be used to assert electrical correctness.
    cv2.line(frame, (112, 120), (198, 120), (0, 0, 255), 4)

    result = inspect_guided_endpoint_colors(frame, detection, component_pose, step)

    assert result["advisory"] is True
    assert result["board"]["color"] in {"yellow", "red"}
