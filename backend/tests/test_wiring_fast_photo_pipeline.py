"""Single-call fast mode; synthetic pixels and fake generation only."""
from copy import deepcopy

import pytest

from app import wiring_photo_pipeline as pipeline
from test_wiring_photo_pipeline import fixture_inputs, run, save_result, WIRE


PINS = {"GPIO17": dict(index=11, design_row="inner", header="J8")}


def fast_answer(roles, marker_id="c1"):
    views = []
    for role in roles:
        module = role == "component_header"
        seat = None if module else dict(image_id=role, row="inner", column=6,
            base_box=[.2, .3, .4, .5], orientation_anchor="Visible board corner marks the first pair.",
            count_evidence="Five header positions precede this base, including empty pins.")
        views.append(dict(role=role, connectors=[dict(id=marker_id, wire_exit=[.5, .5],
            wire_color="red", visibility="clear", contact="uncertain", module_pin_id="TRIG" if module else None,
            pin_seat=seat, box=[.2, .3, .4, .5], evidence="Readable label beside the housing and red insulation at its mouth.")],
            header_observation=dict(state="housings_visible", evidence="Visible housings and other uncovered tips."),
            module_terminals=[dict(pin_id="AUX", state="uncovered", box=[.6, .3, .7, .5],
                evidence="Readable label beside a complete uncovered tip.")] if module else [],
            limitations="Some metal contacts are hidden."))
    return dict(views=views)


def fast_run(tmp_path, review=None, selection=None, originals=None, answer=None):
    default_review, default_selection, default_originals = fixture_inputs()
    review = review or default_review
    selection = selection or default_selection
    originals = originals or default_originals
    calls = []

    def generate(prompt, schema, paths, remaining):
        calls.append(dict(prompt=prompt, schema=schema, paths=paths, remaining=remaining))
        roles = list(dict.fromkeys(path.stem.split("-overview")[0].split("-detail")[0] for path in paths))
        return (answer(roles) if answer else fast_answer(roles)), {"model": "fixture"}

    result = pipeline.inspect_wiring_photos(review, selection, originals, PINS, {"TRIG", "AUX"}, [WIRE],
        tmp_path, generate=generate)
    return result, calls


def test_fast_uses_one_compact_call_and_preserves_seats_terminals_source_and_pixel_audit(tmp_path):
    review, selection, originals = fixture_inputs()
    result, calls = fast_run(tmp_path, review, selection, originals)
    assert len(calls) == result["cloud_call_count"] == 1
    assert result["analysis_mode"] == "fast"
    assert [stage["stage"] for stage in result["stages"]] == ["fast_photo_review"]
    assert result["pipeline_elapsed_ms"] >= result["preparation_ms"]
    assert result["stages"][0]["model_receipt"]["image_inputs"] == result["image_inputs"]
    pi = result["opinion"].views[0].connectors[0]
    assert pi.pin_id == "GPIO17" and pi.contact == "uncertain"
    assert pi.pin_seat.source_sha256 == review["slots"]["pi_side_a"]["sha256"]
    module = result["opinion"].views[-1]
    assert module.connectors[0].module_pin_id == "TRIG"
    assert module.module_terminals[0].pin_id == "AUX" and module.module_terminals[0].state == "uncovered"
    assert module.module_terminals[0].capture_id == review["slots"]["component_header"]["capture_id"]
    audit = result["exit_evidence"]["pi_side_a:c1"]
    assert audit["wire_exit"] == [.5, .5] and audit["wire_exit_px"] == [99.5, 49.5]
    assert audit["semantic_color"] == "red" and audit["local_color"]["name"] == "blue"
    assert result["opinion"].wire_paths == []


def test_fast_schema_is_compact_strict_and_prompt_does_not_include_answers_or_symptoms():
    schema = pipeline.fast_review_schema()
    assert set(schema["properties"]) == {"views"}
    assert "wire_color" in schema["$defs"]["FastConnector"]["properties"]
    assert "pin_seat" in schema["$defs"]["FastConnector"]["properties"]
    for name in ("PiPinSeat", "ModuleTerminalObservation"):
        assert not {"capture_id", "source_sha256", "source_size"} & schema["$defs"][name]["properties"].keys()

    def strict_objects(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
                assert node["additionalProperties"] is False
            for child in node.values():
                strict_objects(child)
        elif isinstance(node, list):
            for child in node:
                strict_objects(child)

    strict_objects(schema)
    review, _, _ = fixture_inputs()
    review.update(symptom="CANARY_SYMPTOM", results=[dict(evidence="CANARY_OLD_FINDING")],
                  expected_wires=[dict(boardPin="CANARY_EXPECTED_PIN")])
    prompt = pipeline._fast_prompt(review, list(pipeline.ROLES), [], PINS, {"TRIG", "AUX"})
    assert not any(token in prompt for token in ("CANARY_SYMPTOM", "CANARY_OLD_FINDING", "CANARY_EXPECTED_PIN"))
    assert "PHOTOGRAPHING TARGET" in prompt and "complete free metal tip" in prompt
    assert "repeated local pin pitch" in prompt and "Missing exit observations never imply" in prompt


def test_thorough_retains_two_stages_and_cache_budget_while_fast_needs_one(tmp_path):
    review, selection, originals = fixture_inputs()
    assert pipeline.model_calls_needed(review, selection) == 1
    selection["response_mode"] = "thorough"
    assert pipeline.model_calls_needed(review, selection) == 2
    result, calls = run(tmp_path, review, selection, originals)
    assert len(calls) == result["cloud_call_count"] == 2
    assert result["analysis_mode"] == "thorough"
    assert [stage["stage"] for stage in result["stages"]] == ["exit_inventory", "pin_review"]
    save_result(review, result)
    assert pipeline.model_calls_needed(review, selection) == 1


def test_bad_fast_coordinates_or_duplicate_ids_fail_without_an_automatic_second_call(tmp_path):
    for fault in ("point", "duplicate", "roles"):
        calls = []
        review, selection, originals = fixture_inputs()

        def generate(prompt, schema, paths, remaining):
            calls.append(True)
            raw = fast_answer(pipeline.ROLES)
            if fault == "point":
                raw["views"][0]["connectors"][0]["wire_exit"] = [1.1, .5]
            elif fault == "duplicate":
                raw["views"][0]["connectors"] *= 2
            else:
                raw["views"][1]["role"] = "pi_side_a"
            return raw, {}

        with pytest.raises(ValueError):
            pipeline.inspect_wiring_photos(review, selection, originals, PINS, {"TRIG"}, [WIRE], tmp_path,
                                          generate=generate)
        assert calls == [True]


def test_fast_partial_retake_replaces_changed_ids_and_preserves_unmodified_observations(tmp_path):
    review, selection, originals = fixture_inputs()
    first, _ = fast_run(tmp_path, review, selection, originals)
    save_result(review, first)
    old_module = deepcopy(review["last_opinion"]["views"][-1])
    review["slots"]["pi_side_a"]["capture_id"] = "new-capture"
    updated, calls = fast_run(tmp_path, review, selection, originals,
                              answer=lambda roles: fast_answer(roles, marker_id="new1"))
    assert len(calls) == 1 and len(calls[0]["paths"]) == 1
    assert updated["changed_roles"] == ["pi_side_a"]
    assert updated["opinion"].views[-1].model_dump() == old_module
    assert "pi_side_a:c1" not in updated["exit_evidence"]
    assert updated["exit_evidence"]["pi_side_a:new1"]["capture_id"] == "new-capture"


def test_visible_housing_without_visible_mouth_retains_identity_without_inventing_exit_colour(tmp_path):
    def answer(roles):
        raw = fast_answer(roles)
        connector = raw["views"][-1]["connectors"][0]
        connector.update(wire_exit=None, wire_color="purple", visibility="uncertain")
        return raw

    result, calls = fast_run(tmp_path, answer=answer)
    assert len(calls) == 1
    module = result["opinion"].views[-1].connectors[0]
    assert module.module_pin_id == "TRIG" and module.pin_id is None
    assert module.wire_color.name == "unknown"
    assert module.wire_color.visibility == "not_visible"
    assert "component_header:c1" not in result["exit_evidence"]
