"""Presentation checks using synthetic observations, without cloud/hardware work."""
from app.guided_wiring_review import _review_summary, compare_candidates
from app.wiring_photo_pipeline import ReviewWirePath


PINS = {"GPIO17": {"index": 11, "design_row": "inner"},
        "GPIO18": {"index": 12, "design_row": "outer"}}
ECHO = dict(id="sensor:echo", boardPin="GPIO18", componentPin="ECHO", connectionKind="direct")
TRIG = dict(id="sensor:trig", boardPin="GPIO17", componentPin="TRIG", connectionKind="direct")


def candidate(role, ident, pin, colour, *, module=False):
    return dict(id=f"{role}:{ident}", role=role, pin_id=None if module else pin,
                physical_pin=PINS.get(pin, {}).get("index"), module_pin_id=pin if module else None,
                module_pin_evidence="Printed label identifies this housing." if module else "",
                pin_evidence="Board anchor and housing position are visible." if not module else "Base hidden by PCB.",
                contact="uncertain" if module else "covers_pin", color=colour, color_visibility="clear",
                evidence="Visible housing and wire.", limitations="")


def make_review(*, board_colour="yellow", module_colour="purple", locale="zh-TW", no_progress=0):
    items = [candidate("pi_side_a", "b", "GPIO18", board_colour),
             candidate("component_header", "m", "ECHO", module_colour, module=True)]
    rows = compare_candidates(items, [ECHO], PINS, locale, capture_plan="pi_rows_v1")
    review = dict(id="copy-check", round=1, slots={}, results=rows, observations=items,
                  capture_plan="pi_rows_v1", no_progress_count=no_progress)
    return rows[0], _review_summary(review, rows, locale)


def test_colour_difference_is_presented_as_a_clue_with_label_colour_and_diagram():
    row, summary = make_review()
    assert summary["headline"] == "ECHO 這條線疑似接錯，請先核對。"
    assert summary["next_step"] == "沿紫色 ECHO 線，核對接線圖中標示的應接位置。"
    assert "紫色" in summary["evidence"] and "黃色" in summary["evidence"] and "線色不同" in summary["evidence"]
    assert "插牢" not in summary["headline"] + summary["next_step"]
    assert row["diagnosis"]["status"] == row["same_wire"] == "uncertain"
    assert row["expected"]["board_pin"] == "GPIO18"
    assert row["expected"]["physical_pin"] == 12 and row["expected"]["bcm"] == 18


def test_hidden_contact_does_not_become_a_request_to_reseat_clear_module():
    row, summary = make_review(board_colour="purple")
    assert summary["headline"] == "照片尚未找出明確的接線疑點。"
    assert "逐線核對" in summary["next_step"]
    assert "紫色 ECHO 線" in row["next_step"] and "接線圖" in row["next_step"]
    assert "插牢" not in summary["next_step"] and "插接狀態待確認" not in summary["headline"]
    assert summary["retake_role"] is None and row["diagnosis"]["status"] == "uncertain"


def test_unknown_wire_colour_is_not_filled_from_design_or_red_wire_anchor():
    row, summary = make_review(board_colour="unknown", module_colour="unknown")
    assert "ECHO 這條線" in summary["next_step"]
    assert all(text not in summary["next_step"] for text in ("紅色", "紫色", "Pin 12", "GPIO18"))
    assert row["wire_colors"]["component"]["name"] == "unknown"


def test_reciprocal_swap_guidance_names_both_observed_wires_and_keeps_numbers_in_details():
    items = [candidate("pi_side_a", "t", "GPIO17", "purple"),
             candidate("pi_side_a", "e", "GPIO18", "yellow"),
             candidate("component_header", "t", "TRIG", "yellow", module=True),
             candidate("component_header", "e", "ECHO", "purple", module=True)]
    rows = compare_candidates(items, [TRIG, ECHO], PINS)
    summary = _review_summary(dict(results=rows), rows, "zh-TW")
    assert summary["headline"] == "TRIG 與 ECHO 疑似接反。"
    assert "黃色 TRIG 線" in summary["next_step"] and "紫色 ECHO 線" in summary["next_step"]
    assert "接線圖" in summary["next_step"] and "Pi Pin" not in summary["next_step"] + summary["evidence"]
    assert rows[0]["expected"]["physical_pin"] == 11 and rows[0]["diagnosis"]["candidate_physical_pin"] == 12
    assert all(row["same_wire"] == "uncertain" for row in rows)


def test_traced_miswire_keeps_diagnosis_but_guides_by_component_and_diagram():
    items = [candidate("pi_side_a", "b", "GPIO17", "purple"),
             candidate("component_header", "m", "ECHO", "purple", module=True)]
    items[1].update(pin_id="ECHO", contact="covers_pin")
    path = ReviewWirePath(wire_id=ECHO["id"], board_connector_id="pi_side_a:b",
                         component_connector_id="component_header:m", visibility="traceable",
                         evidence="Visible route connects these housings.")
    row = compare_candidates(items, [ECHO], PINS, wire_paths=[path])[0]
    assert row["diagnosis"]["status"] == "suspected" and row["same_wire"] == "consistent"
    assert "紫色 ECHO 線" in row["next_step"] and "接線圖" in row["next_step"]
    assert "Pi Pin" not in row["next_step"] and row["diagnosis"]["observed_physical_pin"] == 11


def test_repeat_analysis_does_not_replace_colour_clue_with_generic_uncertainty():
    row, summary = make_review(no_progress=2)
    assert "ECHO 這條線疑似接錯" in summary["headline"] and "線色不同" in summary["evidence"]
    assert "紫色 ECHO 線" in summary["next_step"] and "接線圖" in summary["next_step"]
    assert "看不清楚" not in summary["next_step"] and "無法確定" not in summary["next_step"]
    assert row["diagnosis"]["status"] == "uncertain"


def test_actual_uncovered_header_observation_keeps_its_specific_guidance():
    items = [candidate("pi_side_a", "b", "GPIO18", "yellow")]
    rows = compare_candidates(items, [ECHO], PINS)
    review = dict(id="uncovered", round=1, slots={}, results=rows, observations=items,
                  last_opinion=dict(views=[dict(role="component_header", connectors=[],
                    header_observation=dict(state="uncovered_pins", evidence="Four complete bare pin tips are visible."))]))
    summary = _review_summary(review, rows, "zh-TW")
    assert summary["headline"] == "零件端可見裸露排針。"
    assert "核對插接狀態" in summary["next_step"] and summary["retake_role"] is None
    assert "Four complete bare pin tips" in summary["observation"]


def test_english_guidance_also_uses_observed_colour_and_diagram_without_raw_pin_task():
    row, summary = make_review(locale="en")
    assert "The ECHO wire may be miswired" in summary["headline"] and "colours differ" in summary["evidence"]
    assert "the purple ECHO wire" in summary["next_step"] and "wiring diagram" in summary["next_step"]
    assert "Pi Pin" not in summary["next_step"] and "seating" not in summary["next_step"]
    assert row["expected"]["physical_pin"] == 12 and row["diagnosis"]["status"] == "uncertain"
