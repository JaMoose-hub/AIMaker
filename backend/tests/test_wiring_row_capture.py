"""Row-target collection and AI context; synthetic pixels/fake cloud, no GPIO."""
from copy import deepcopy
import hashlib
import json

from app import wiring_photo_pipeline as pipeline
from app.guided_wiring_review import (
    WiringReviewAction, _board_pins, _canonical_candidates, _review_summary, compare_candidates,
)
from test_debug_sessions import setup
from test_guided_wiring_review import _act, _capture_stub, _photos, _start, _with_confirmations
from test_mobile_wiring_review import _pixels
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, run, save_result, PINS, WIRE


def row_inputs():
    review, selection, originals = fixture_inputs()
    review["capture_plan"] = pipeline.ROW_CAPTURE_PLAN
    for role, slot in review["slots"].items():
        slot["target_row"] = pipeline.capture_target_row(review, role)
    return review, selection, originals


def test_new_capture_and_dialogue_bind_row_targets_without_confirming_wires(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    original_context = deepcopy(context)
    guide = service.guided_wiring_review
    guide.enable_dialogue(sid, "row-dialogue", 0, 0)
    session = service.sessions[sid]
    first = deepcopy(session["wiring_dialogue"]["events"][-1])
    assert first["wiring_flow"]["capture_plan"] == "pi_rows_v1"
    assert first["wiring_flow"]["target_row"] == "inner" and "靠板中央" in first["text"]
    _photos(service, sid, context)
    for role, target in (("pi_side_a", "inner"), ("pi_side_b", "outer"), ("component_header", None)):
        slot = session["wiring_review"]["slots"][role]
        entry = next(e for e in session["evidence"] if e["id"] == slot["capture_id"])
        assert slot["target_row"] == entry["target_row"] == target
        assert entry["capture_plan"] == "pi_rows_v1" and entry["sha256"] == slot["sha256"]
    assert any("靠板邊緣" in event["text"] for event in session["wiring_dialogue"]["events"])
    assert session["wiring_review"]["reviews"] == {} and session["context"] == original_context
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_phone_import_freezes_target_with_its_source_and_legacy_import_stays_generic(setup):
    service, state = setup
    sid, context = _start(service)
    raw = _pixels()
    provenance = dict(size=[96, 72], sha256=hashlib.sha256(raw).hexdigest(), asset_id="phone-asset")
    for role, target in (("pi_side_a", "inner"), ("pi_side_b", None)):
        review = service.sessions[sid]["wiring_review"]
        if target is None:
            review.pop("capture_plan")
        body = WiringReviewAction(op="capture", role=role, review_id=review["id"], revision=review["revision"])
        service.guided_wiring_review.import_photo(sid, body, raw, provenance=provenance, still_current=lambda: True)
        slot = service.sessions[sid]["wiring_review"]["slots"][role]
        entry = service.sessions[sid]["evidence"][-1]
        assert slot["target_row"] == entry["target_row"] == target
        assert slot["provenance"]["asset_id"] == "phone-asset"
        assert slot["sha256"] == entry["sha256"] == provenance["sha256"]
        assert slot["source"] == "phone_upload" and "photo_acceptance" not in slot
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_legacy_component_switch_preserves_generic_photos_until_explicit_new_round(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    review = service.sessions[sid]["wiring_review"]
    review.pop("capture_plan")
    service.guided_wiring_review.enable_dialogue(sid, "old-dialogue", 0, 0)
    old_event = deepcopy(service.sessions[sid]["wiring_dialogue"]["events"][-1])
    _photos(service, sid, context)
    before = deepcopy(review["slots"]["pi_side_a"])
    _act(service, sid, context, "start", component_id="mrd-tf240-8p-cs")
    current = service.sessions[sid]["wiring_review"]
    assert current.get("capture_plan") is None and current["slots"]["pi_side_a"] == before
    assert current["slots"]["pi_side_a"]["target_row"] is None
    affected = {w["id"] for w in context["project"]["wiring"] if w["componentId"] == "mrd-tf240-8p-cs"}
    changed = _with_confirmations(context, {k: v for k, v in context["guide_confirmations"].items() if k not in affected})
    _act(service, sid, changed, "changed", component_id="mrd-tf240-8p-cs")
    current = service.sessions[sid]["wiring_review"]
    assert current["capture_plan"] == "pi_rows_v1" and all(slot is None for slot in current["slots"].values())
    projected = service.guided_wiring_review.dialogue_projection(service.sessions[sid], old_event)
    assert projected.get("capture_plan") is None and not projected["current"]
    assert old_event["text"].startswith("拍 Pi 第一側")


def test_both_cloud_stages_receive_source_bound_row_targets_including_crops(tmp_path):
    review, selection, originals = row_inputs()
    review["slots"]["pi_side_a"]["crop"] = [.1, .1, .8, .8]
    result, calls = run(tmp_path, review, selection, originals)
    assert len(calls) == 2
    assert "PHOTOGRAPHING TARGET" in calls[0]["prompt"] and "or a verified row" in calls[0]["prompt"]
    assert "physical pin numbers" in calls[0]["prompt"] and "expected_wires" not in calls[0]["prompt"]
    assert "not an observed row" in calls[1]["prompt"] and "leave ambiguous pin_id null" in calls[1]["prompt"]
    first = json.loads(calls[0]["prompt"].split("Images are attached in this order:\n")[-1])
    second = json.loads(calls[1]["prompt"].split("Board pin references are naming references only: ")[-1])
    assert first == second["images_in_order"] and second["capture_plan"] == "pi_rows_v1"
    assert [row["requested_row"] for row in first] == ["inner", "inner", "outer", None]
    for stage in result["stages"]:
        assert stage["model_receipt"]["image_inputs"] == result["image_inputs"]
    assert result["pipeline_version"] == pipeline.PIPELINE_VERSION


def test_legacy_sources_and_unbound_slots_cannot_gain_row_meaning(tmp_path):
    review, selection, originals = row_inputs()
    review.pop("capture_plan")
    result, calls = run(tmp_path, review, selection, originals)
    assert all(row["requested_row"] is None for row in result["image_inputs"])
    review["capture_plan"] = "pi_rows_v1"
    review["slots"]["pi_side_a"].pop("target_row")
    review["slots"]["pi_side_b"]["target_row"] = "inner"  # mismatched metadata cannot be proof
    assert pipeline.source_target_row(review, "pi_side_a") is None
    assert pipeline.source_target_row(review, "pi_side_b") is None


def test_capture_plan_and_slot_target_changes_invalidate_old_analysis_keys(tmp_path):
    review, selection, originals = row_inputs()
    result, _ = run(tmp_path, review, selection, originals)
    save_result(review, result)
    previous = pipeline.role_input_keys(review, selection)
    review.pop("capture_plan")
    assert all(pipeline.role_input_keys(review, selection)[role] != previous[role] for role in pipeline.ROLES)
    assert pipeline.model_calls_needed(review, selection) == 2
    review["capture_plan"] = "pi_rows_v1"
    review["slots"]["pi_side_a"]["target_row"] = "outer"
    assert pipeline.changed_roles(review, selection) == ["pi_side_a"]
    assert pipeline.model_calls_needed(review, selection) == 2


def test_row_target_never_supplies_a_missing_pin_or_human_confirmation(tmp_path):
    review, selection, originals = row_inputs()
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        raw = opinion(pipeline.ROLES)
        for view in raw["views"]:
            if view["role"] != "component_header":
                for connector in view["connectors"]:
                    connector.update(pin_id=None, pin_evidence="The two rows overlap; insertion is hidden.")
        return raw
    result, calls = run(tmp_path, review, selection, originals, callback=answer)
    candidates = _canonical_candidates(result["opinion"], review, PINS, {"TRIG"})
    assert all(c["pin_id"] is None and c["physical_pin"] is None for c in candidates if c["role"] != "component_header")
    rows = compare_candidates(candidates, [WIRE], _board_pins(), capture_plan=review["capture_plan"])
    assert rows[0]["diagnosis"]["status"] == "uncertain" and rows[0]["authority"] == "visual_advisory"
    assert "Pi 內排（靠板中央）" in rows[0]["next_step"] and len(calls) == 2
    review.update(id="row-review", observations=candidates, results=rows, last_opinion=result["opinion"].model_dump())
    summary = _review_summary(review, rows, "zh-TW")
    assert summary["retake_target_row"] == "inner"


def test_legacy_and_row_summaries_keep_distinct_retake_wording():
    rows = [dict(wire_id=f"wire-{i}", expected=dict(component_pin="TRIG"),
                 diagnosis=dict(status="uncertain", retake_roles=["pi_side_a"], evidence="Hidden insertion"),
                 next_step="Check insertion", evidence="Hidden insertion") for i in range(2)]
    review = dict(id="review", round=1, slots={}, results=rows)
    legacy = _review_summary(review, rows, "zh-TW")
    assert "第一側" in legacy["next_step"] and legacy["retake_target_row"] is None
    review["capture_plan"] = "pi_rows_v1"
    current = _review_summary(review, rows, "zh-TW")
    assert "Pi 內排（靠板中央）" in current["next_step"] and current["retake_target_row"] == "inner"
    assert current["observation"] == ""  # no visible row claimed from the target
    # Geometry-derived design targets must not follow arbitrary candidates or
    # revert to the old alternating-side heuristic when the Pi inventory is empty.
    pins = _board_pins()
    assert pins["GPIO17"]["design_row"] == "inner" and pins["GPIO18"]["design_row"] == "outer"
    module = dict(id="component_header:c1", role="component_header", pin_id="TRIG", physical_pin=None,
                  color="blue", color_visibility="clear", contact="covers_pin", evidence="Visible label")
    unrelated = {**module, "id": "pi_side_a:c1", "role": "pi_side_a", "pin_id": None}
    inner = compare_candidates([module, unrelated], [WIRE], pins, capture_plan="pi_rows_v1")[0]
    outer_wire = {**WIRE, "boardPin": "GPIO18"}
    outer = compare_candidates([module], [outer_wire], pins, capture_plan="pi_rows_v1")[0]
    assert inner["diagnosis"]["retake_roles"] == ["pi_side_a"]
    assert outer["diagnosis"]["retake_roles"] == ["pi_side_b"]
    assert inner["diagnosis"]["observed_board_pin"] is outer["diagnosis"]["observed_board_pin"] is None
    no_geometry = compare_candidates([module, unrelated], [WIRE], PINS, capture_plan="pi_rows_v1")[0]
    assert no_geometry["diagnosis"]["retake_roles"] == ["pi_side_a", "pi_side_b"]
    assert "內排" in no_geometry["next_step"] and "外排" in no_geometry["next_step"]
    review["results"] = [no_geometry, {**deepcopy(no_geometry), "wire_id": "wire-2"}]
    unclear = _review_summary(review, review["results"], "zh-TW")
    assert unclear["retake_role"] is None and unclear["retake_target_row"] is None
