"""Visible placement differs from inspecting metal hidden inside a connector."""
import json

from app import wiring_photo_pipeline as pipeline
from app.guided_wiring_review import _board_pins, _canonical_candidates, compare_candidates
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, PINS, WIRE


def test_pin_prompt_uses_design_layout_after_visual_landmark_and_position_checks():
    review, _, _ = fixture_inputs()
    pins = _board_pins()
    exits = {view["image_id"]: view for view in inventory(pipeline.ROLES)["images"]}
    prompt = pipeline._pin_prompt(review, list(pipeline.ROLES), exits, [], pins, {"TRIG"}, [])
    context = json.loads(prompt.split("Board pin references are naming references only: ", 1)[1])
    assert context["board_reference_kind"] == "design_geometry_not_image_evidence"
    for pin_id in ("GPIO17", "GPIO18"):
        ref = context["board_pins"][pin_id]
        assert ref["index"] == pins[pin_id]["index"]
        assert ref["design_row"] == pins[pin_id]["design_row"]
        assert ref["pos_mm"] == pins[pin_id]["pos_mm"]
    assert context["expected_wires"] == []
    assert "a printed numeral 1 is NOT required" in prompt
    assert "Do NOT count the exit inventory order or skip gaps/empty positions" in prompt
    assert "Hidden metal alone must NOT force contact=uncertain or pin_id=null" in prompt
    assert "base's actual row/column placement is obscured" in prompt
    assert "Visible placement cannot prove insertion depth, conductivity or electrical function" in prompt
    assert "Hidden tips are uncertain" not in prompt


def test_visible_base_can_keep_pin_but_obscured_position_is_still_guarded():
    review, _, _ = fixture_inputs()
    raw = opinion(pipeline.ROLES)
    raw["views"][0]["connectors"][0].update(
        contact="covers_pin", pin_evidence="Board end and housing base identify this row/column; metal is inside the housing.")
    raw["views"][1]["connectors"][0].update(
        contact="uncertain", pin_evidence="Other housings obscure the actual row/column at this base.")
    candidates = _canonical_candidates(pipeline.ReviewOpinion.model_validate(raw), review, PINS, {"TRIG"})
    assert candidates[0]["pin_id"] == "GPIO17" and candidates[0]["physical_pin"] == 11
    assert candidates[1]["pin_id"] is None and candidates[1]["physical_pin"] is None
    row = compare_candidates(candidates, [WIRE], PINS)[0]
    assert row["authority"] == "visual_advisory"
    assert row["same_wire"] == "uncertain" and row["diagnosis"]["status"] == "uncertain"
