"""Module label recognition remains distinct from attachment and Pi row evidence."""
from copy import deepcopy

from app import wiring_photo_pipeline as pipeline
from app.guided_wiring_review import _canonical_candidates, _review_summary, compare_candidates
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, run, PINS, WIRE


def canonical(raw):
    review, _, _ = fixture_inputs()
    return _canonical_candidates(pipeline.ReviewOpinion.model_validate(raw), review,
                                 PINS, {"VCC", "TRIG", "ECHO", "GND"})


def module_observation(*, board_visible=False, explicit=True):
    raw = opinion(pipeline.ROLES)
    for view in raw["views"]:
        item = view["connectors"][0]
        if view["role"] == "component_header":
            item.update(contact="uncertain", pin_id=None,
                        pin_evidence="The PCB edge hides pin-facing attachment.")
            if explicit:
                item.update(module_pin_id="TRIG", module_pin_evidence="TRIG is printed over the second housing.")
        elif not board_visible:
            item.update(contact="uncertain", pin_id=None, pin_evidence="Pi rows overlap at the housing bases.")
    return raw


def summary(candidates, *, paths=()):
    pins = {"GPIO17": {"index": 11, "design_row": "inner"}}
    rows = compare_candidates(candidates, [WIRE], pins, wire_paths=paths, capture_plan="pi_rows_v1")
    review = dict(id="module-review", round=1, slots={}, results=rows, capture_plan="pi_rows_v1")
    return rows[0], _review_summary(review, rows, "zh-TW")


def test_existing_structured_labels_survive_hidden_attachment_without_attached_pins():
    # Exact production shape: four readable labels, each with contact=uncertain.
    raw = module_observation(explicit=False)
    template = raw["views"][-1]["connectors"][0]
    raw["views"][-1]["connectors"] = [
        dict(deepcopy(template), id=f"c{index}", pin_id=pin,
             pin_evidence=f"{pin} label corresponds to housing {index}; attachment hidden by the PCB.")
        for index, pin in enumerate(("VCC", "TRIG", "ECHO", "GND"), 1)]
    before = deepcopy(raw)
    found = canonical(raw)
    module = [c for c in found if c["role"] == "component_header"]
    assert [c["module_pin_id"] for c in module] == ["VCC", "TRIG", "ECHO", "GND"]
    assert all(c["pin_id"] is None and c["contact"] == "uncertain" for c in module)
    assert all(c["module_pin_evidence"] for c in module)
    assert raw == before  # no rewrite of archived/source model evidence


def test_detached_invalid_and_unsupported_module_labels_cannot_supply_identity():
    for updates in (dict(contact="detached"), dict(module_pin_id="GPIO17"), dict(module_pin_evidence=" ")):
        raw = module_observation()
        raw["views"][-1]["connectors"][0].update(updates)
        found = canonical(raw)[-1]
        assert found["module_pin_id"] is None and found["pin_id"] is None
        row, _ = summary(canonical(raw))
        assert row["diagnosis"]["retake_roles"] == ["component_header"]
    raw = module_observation()
    raw["views"][0]["connectors"][0].update(module_pin_id="TRIG", module_pin_evidence="Visible nearby label")
    pi = canonical(raw)[0]
    assert pi["module_pin_id"] is None and pi["pin_id"] is None and pi["physical_pin"] is None


def test_two_stage_pipeline_preserves_module_identity_without_adding_cloud_calls(tmp_path):
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        assert "MODULE ROLE (component_header)" in prompt
        assert "rules apply ONLY to Pi photographs" in prompt
        assert "an uncovered pin tip is NOT required" in prompt
        assert "leave ambiguous pin_id null" in prompt
        assert "module_pin_id" in schema["$defs"]["ReviewConnector"]["properties"]
        return module_observation()
    result, calls = run(tmp_path, callback=answer)
    assert len(calls) == 2
    module = result["opinion"].views[-1].connectors[0]
    assert module.module_pin_id == "TRIG" and module.pin_id is None and module.contact == "uncertain"
    assert module.wire_color.name == "red"  # retain the POC exit observation


def test_readable_module_with_hidden_attachment_moves_to_pi_instead_of_module_retake():
    row, compact = summary(canonical(module_observation()))
    assert row["diagnosis"]["retake_roles"] == ["pi_side_a"]
    assert row["wire_colors"]["component"]["name"] == "blue"
    assert compact["retake_role"] == "pi_side_a" and compact["retake_target_row"] == "inner"
    assert compact["headline"] == "零件標字與接頭位置已辨識，接著核對 Pi。"
    assert "補拍零件" not in compact["next_step"]
    assert row["diagnosis"]["status"] == "uncertain" and row["same_wire"] == "uncertain"


def test_visible_route_and_equal_colors_do_not_promote_hidden_module_attachment():
    candidates = canonical(module_observation(board_visible=True))
    path = pipeline.ReviewWirePath(wire_id=WIRE["id"], board_connector_id="pi_side_a:c1",
                                  component_connector_id="component_header:c1", visibility="traceable",
                                  evidence="A continuous route is visible between housings.")
    row, compact = summary(candidates, paths=[path])
    assert row["comparison"] == "similar" and row["same_wire"] == "uncertain"
    assert row["diagnosis"]["status"] == "uncertain"
    assert row["diagnosis"]["observed_component_pin"] is None
    assert row["diagnosis"]["retake_roles"] == [] and compact["retake_role"] is None
    assert compact["headline"] == "照片尚未找出明確的接線疑點。" and "逐線核對" in compact["next_step"]
    assert "插牢" not in compact["next_step"]


def test_ambiguous_module_label_housing_relationship_still_requests_module_photo():
    raw = module_observation(explicit=False)
    raw["views"][-1]["limitations"] = "The labels and housing positions are occluded."
    row, compact = summary(canonical(raw))
    assert row["diagnosis"]["retake_roles"] == ["component_header"]
    assert not row["diagnosis"]["module_identity_known"]
    assert compact["retake_role"] == "component_header"


def test_old_prose_is_not_parsed_to_invent_structured_module_identity():
    raw = module_observation(explicit=False)
    raw["views"][-1]["limitations"] = "TRIG label and housing order appear clear."
    raw["views"][-1]["connectors"][0]["pin_evidence"] = "TRIG may be visible."
    model = pipeline.ReviewOpinion.model_validate(raw)
    assert model.views[-1].connectors[0].module_pin_id is None
    found = canonical(raw)[-1]
    assert found["module_pin_id"] is None and found["pin_id"] is None
