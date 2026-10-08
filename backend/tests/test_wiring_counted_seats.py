"""Synthetic photo responses: counted candidates and source-bound partial retakes."""
from copy import deepcopy

import pytest

from app import wiring_photo_pipeline as pipeline
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, run, save_result


PINS = {
    "candidate-inner": dict(index=7, design_row="inner", header="J8"),
    "candidate-outer": dict(index=8, design_row="outer", header="J8"),
}


def seat(role="pi_side_a", row="outer", column=4):
    return dict(image_id=role, row=row, column=column, base_box=[.2, .3, .4, .5],
                orientation_anchor="Board corner establishes the Pin 1/2 end.",
                count_evidence="Three positions, including two uncovered pins, precede this base.")


def connector_view(role="pi_side_a", **changes):
    raw = opinion([role])["views"][0]
    raw["connectors"][0].update(pin_seat=seat(role), **changes)
    return pipeline.ViewInventory.model_validate(raw)


def routes():
    return [dict(wire_id="wire", board_connector_id="pi_side_b:c1",
                 component_connector_id="component_header:c1", visibility="traceable",
                 evidence="A unique physical marking follows the visible route.")]


def answer_with_routes(prompt, schema):
    if "POC EXIT INVENTORY:" in prompt:
        return inventory(pipeline.ROLES)
    raw = opinion(pipeline.ROLES)
    raw["wire_paths"] = routes()
    return raw


def test_archived_observations_do_not_acquire_counted_seats_or_route_sources():
    raw = opinion(pipeline.ROLES)
    raw["wire_paths"] = routes()
    parsed = pipeline.ReviewOpinion.model_validate(raw)
    assert all(c.pin_seat is None for v in parsed.views for c in v.connectors)
    assert parsed.wire_paths[0].source_refs == []
    assert parsed.views[0].connectors[0].pin_id == "GPIO17"


def test_cloud_seat_schema_exposes_visual_evidence_without_server_receipts():
    schema = pipeline.pin_review_schema()
    fields = schema["$defs"]["PiPinSeat"]["properties"]
    assert set(fields) == {"image_id", "row", "column", "base_box", "orientation_anchor", "count_evidence"}
    assert "source_refs" not in schema["$defs"]["ReviewWirePath"]["properties"]
    assert "PathSource" not in schema["$defs"]
    assert set(schema["$defs"]["PiPinSeat"]["required"]) == set(fields)


def test_profile_derivation_ignores_model_pin_name_colour_and_requested_row():
    review, _, _ = fixture_inputs()
    slot = {**review["slots"]["pi_side_a"], "target_row": "inner"}
    view = connector_view(pin_id="invented-expected-pin", contact="uncertain")
    result = pipeline._bind_pin_seats(view, slot, PINS).connectors[0]
    assert result.pin_id == "candidate-outer" and result.contact == "uncertain"
    assert result.pin_seat.row == "outer" and result.pin_seat.column == 4
    assert result.pin_seat.capture_id == slot["capture_id"]
    assert result.pin_seat.source_sha256 == slot["sha256"]
    assert result.pin_seat.source_size == slot["size"]
    result.pin_seat.row = "inner"
    assert pipeline._bind_pin_seats(view, slot, PINS).connectors[0].pin_id == "candidate-inner"


def test_missing_or_foreign_seat_cannot_turn_model_pin_name_into_a_new_finding():
    review, _, _ = fixture_inputs()
    for changes in ({"pin_seat": None}, {"pin_seat": seat("pi_side_b")}, {"contact": "detached"}):
        raw = opinion(["pi_side_a"])["views"][0]
        raw["connectors"][0].update(pin_seat=seat())
        raw["connectors"][0].update(changes)
        view = pipeline._bind_pin_seats(pipeline.ViewInventory.model_validate(raw),
                                       review["slots"]["pi_side_a"], PINS)
        assert view.connectors[0].pin_id is None
        assert view.connectors[0].pin_seat is None


def test_malformed_base_and_count_do_not_coerce_into_a_plausible_seat():
    for patch in ({"base_box": [.4, .2, .3, .5]}, {"base_box": [0., 0., 1.1, .5]},
                  {"base_box": [0., 0., float("nan"), .5]}, {"column": True},
                  {"column": 21}, {"orientation_anchor": "  "}, {"count_evidence": ""}):
        with pytest.raises(ValueError):
            pipeline.PiPinSeat.model_validate({**seat(), **patch})


def test_prompt_counts_empty_positions_and_allows_partial_contact_candidates():
    review, _, _ = fixture_inputs()
    exits = {v["image_id"]: v for v in inventory(pipeline.ROLES)["images"]}
    prompt = pipeline._pin_prompt(review, list(pipeline.ROLES), exits, [], PINS, {"TRIG"}, [])
    assert "Do NOT count the exit inventory order or skip gaps/empty positions" in prompt
    assert "contact=uncertain and remain a" in prompt
    assert "One useful\nview suffices" in prompt
    assert "reconcile their reversed perspective" in prompt
    assert "not an observed row" in prompt


def test_partial_retake_preserves_unchanged_view_and_source_valid_route(tmp_path):
    review, selection, originals = fixture_inputs()
    first, _ = run(tmp_path, review, selection, originals, callback=answer_with_routes)
    save_result(review, first)
    retained = deepcopy(review["last_opinion"]["views"][1])
    assert len(first["opinion"].wire_paths[0].source_refs) == 2
    review["slots"]["pi_side_a"]["capture_id"] = "retake-a"

    def partial(prompt, schema):
        return inventory(["pi_side_a"]) if "POC EXIT INVENTORY:" in prompt else opinion(["pi_side_a"])

    updated, calls = run(tmp_path, review, selection, originals, callback=partial)
    assert updated["changed_roles"] == ["pi_side_a"] and len(calls) == 2
    assert updated["opinion"].views[1].model_dump() == retained
    assert len(updated["opinion"].wire_paths) == 1
    assert updated["opinion"].wire_paths[0].source_refs == first["opinion"].wire_paths[0].source_refs


def test_same_connector_id_on_replaced_photo_cannot_reuse_or_invent_route(tmp_path):
    review, selection, originals = fixture_inputs()
    first, _ = run(tmp_path, review, selection, originals, callback=answer_with_routes)
    save_result(review, first)
    review["slots"]["pi_side_b"]["capture_id"] = "retake-b"

    def partial(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(["pi_side_b"])
        raw = opinion(["pi_side_b"])
        raw["wire_paths"] = routes()  # module source is not supplied to this turn
        return raw

    updated, calls = run(tmp_path, review, selection, originals, callback=partial)
    assert updated["opinion"].wire_paths == [] and len(calls) == 2


def test_cached_route_requires_all_source_stamps_and_current_endpoint_ids(tmp_path):
    review, selection, originals = fixture_inputs()
    first, _ = run(tmp_path, review, selection, originals, callback=answer_with_routes)
    save_result(review, first)
    views = first["opinion"].views
    keys = pipeline.role_input_keys(review, selection)
    wires = [dict(id="wire")]
    for mutation in ("source_hash", "legacy_receipt", "missing_endpoint"):
        cached = deepcopy(review)
        path = cached["last_opinion"]["wire_paths"][0]
        if mutation == "source_hash":
            path["source_refs"][0]["source_sha256"] = "different"
        elif mutation == "legacy_receipt":
            path.pop("source_refs")
        else:
            path["board_connector_id"] = "pi_side_b:absent"
        assert pipeline._merge_wire_paths(cached, [], ["pi_side_a"], keys, views, wires) == []
