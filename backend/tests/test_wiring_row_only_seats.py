"""An observed row can survive an unknown column without becoming a GPIO claim."""
from app import wiring_photo_pipeline as pipeline
from test_wiring_fast_photo_pipeline import fast_answer, fast_run
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, run


def row_only_seat(seat):
    return {**seat, "column": None,
            "orientation_anchor": "The board edge and centre distinguish this visible row.",
            "count_evidence": "Housing overlap prevents a supported column count."}


def test_fast_row_only_seats_remain_source_bound_without_assigning_gpio(tmp_path):
    review, selection, originals = fixture_inputs()

    def answer(roles):
        raw = fast_answer(roles)
        for view in raw["views"]:
            if view["role"] != "component_header":
                view["connectors"][0]["pin_seat"] = row_only_seat(view["connectors"][0]["pin_seat"])
        return raw

    result, calls = fast_run(tmp_path, review, selection, originals, answer=answer)
    assert len(calls) == 1 and result["cloud_call_count"] == 1
    for view in result["opinion"].views[:2]:
        connector = view.connectors[0]
        assert connector.pin_id is None
        assert connector.pin_seat.row == "inner" and connector.pin_seat.column is None
        assert connector.pin_seat.capture_id == review["slots"][view.role]["capture_id"]
        assert connector.pin_seat.source_sha256 == review["slots"][view.role]["sha256"]
        assert connector.pin_seat.source_size == review["slots"][view.role]["size"]
        assert connector.pin_seat.base_box == [.2, .3, .4, .5]
    archived = pipeline.ReviewOpinion.model_validate_json(result["opinion"].model_dump_json())
    assert archived.views[0].connectors[0].pin_seat.column is None
    assert "Keep row-only evidence" in calls[0]["prompt"]


def test_thorough_keeps_row_only_evidence_and_clears_unjustified_model_pin_name(tmp_path):
    review, selection, originals = fixture_inputs()
    selection["response_mode"] = "thorough"

    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        raw = opinion(pipeline.ROLES)
        examples = fast_answer(pipeline.ROLES)["views"]
        for view, example in zip(raw["views"], examples):
            if view["role"] != "component_header":
                view["connectors"][0]["pin_seat"] = row_only_seat(example["connectors"][0]["pin_seat"])
                view["connectors"][0]["contact"] = "uncertain"
                assert view["connectors"][0]["pin_id"] == "GPIO17"
        return raw

    result, calls = run(tmp_path, review, selection, originals, callback=answer)
    assert len(calls) == 2 and result["analysis_mode"] == "thorough"
    assert all(view.connectors[0].pin_id is None and view.connectors[0].pin_seat.column is None
               and view.connectors[0].pin_seat.row == "inner" for view in result["opinion"].views[:2])
    assert "preserve pin_seat with column=null" in calls[1]["prompt"]
    schema_column = pipeline.fast_review_schema()["$defs"]["PiPinSeat"]["properties"]["column"]
    assert any(option.get("type") == "null" for option in schema_column["anyOf"])
