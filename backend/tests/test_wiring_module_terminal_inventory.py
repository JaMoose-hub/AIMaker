"""Module terminal observations use synthetic images and fake cloud responses only."""
from copy import deepcopy

import pytest

from app import wiring_photo_pipeline as pipeline
from test_wiring_photo_pipeline import fixture_inputs, inventory, opinion, run, save_result, PINS


def terminal(pin_id="TRIG", state="uncovered", **fields):
    return dict(pin_id=pin_id, state=state, evidence="Printed label is beside a completely uncovered tip.",
                box=[.1, .2, .3, .4], **fields)


def test_archived_views_have_no_invented_terminal_observations():
    old = pipeline.ReviewOpinion.model_validate(opinion(pipeline.ROLES))
    assert all(view.module_terminals == [] for view in old.views)
    assert all(view.module_terminals == [] for view in
               pipeline.ReviewOpinion.model_validate(old.model_dump()).views)


def test_terminal_cloud_schema_and_prompt_separate_presence_from_expected_connections():
    schema = pipeline.pin_review_schema()
    fields = schema["$defs"]["ModuleTerminalObservation"]["properties"]
    assert set(fields) == {"pin_id", "state", "evidence", "box"}
    assert set(schema["$defs"]["ModuleTerminalObservation"]["required"]) == set(fields)
    assert schema["$defs"]["ModuleTerminalObservation"]["additionalProperties"] is False
    review, _, _ = fixture_inputs()
    exits = {view["image_id"]: view for view in inventory(pipeline.ROLES)["images"]}
    prompt = pipeline._pin_prompt(review, list(pipeline.ROLES), exits, [], PINS, {"TRIG"}, [])
    assert "EVERY visible module terminal" in prompt
    assert "covered and\nuncovered terminals together" in prompt
    assert "complete metal tip" in prompt and "pin_id=null" in prompt
    assert "Expected connections do not imply observed terminals" in prompt
    assert "an observation, not automatically a wiring fault" in prompt


def test_mixed_terminals_survive_exit_fusion_with_only_server_owned_source_stamps(tmp_path):
    review, selection, originals = fixture_inputs()

    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        raw = opinion(pipeline.ROLES)
        for view in raw["views"]:
            view["module_terminals"] = [terminal(capture_id="invented", source_sha256="wrong", source_size=[1, 1]),
                                        terminal(None, "covered"), terminal("unknown-catalog-label", "uncertain")]
        raw["views"][-1]["header_observation"] = dict(state="housings_visible", evidence="Both housings and bare tips are visible.")
        return raw

    result, calls = run(tmp_path, review, selection, originals, callback=answer)
    module = result["opinion"].views[-1]
    assert len(calls) == 2 and len(module.connectors) == 1
    assert module.header_observation.state == "housings_visible"
    assert [entry.pin_id for entry in module.module_terminals] == ["TRIG", None, None]
    assert [entry.state for entry in module.module_terminals] == ["uncovered", "covered", "uncertain"]
    slot = review["slots"]["component_header"]
    assert all(entry.capture_id == slot["capture_id"] and entry.source_sha256 == slot["sha256"]
               and entry.source_size == slot["size"] for entry in module.module_terminals)
    assert all(view.module_terminals == [] for view in result["opinion"].views[:-1])


def test_invalid_terminal_regions_or_empty_evidence_are_rejected():
    for patch in ({"box": [.4, .2, .3, .5]}, {"box": [0., 0., 1.2, .5]},
                  {"box": [0., 0., float("nan"), .5]}, {"evidence": "  "}, {"state": "absent"}):
        with pytest.raises(ValueError):
            pipeline.ModuleTerminalObservation.model_validate({**terminal(), **patch})
    assert pipeline.ModuleTerminalObservation.model_validate({**terminal(None, "uncertain"), "box": None}).pin_id is None


def test_partial_retake_keeps_unchanged_module_terminals_then_replaces_them(tmp_path):
    review, selection, originals = fixture_inputs()

    def initial(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        raw = opinion(pipeline.ROLES)
        raw["views"][-1]["module_terminals"] = [terminal()]
        return raw

    result, _ = run(tmp_path, review, selection, originals, callback=initial)
    save_result(review, result)
    original_terminals = deepcopy(review["last_opinion"]["views"][-1]["module_terminals"])
    review["slots"]["pi_side_a"]["capture_id"] = "retaken-pi"

    def partial(prompt, schema):
        return inventory(["pi_side_a"]) if "POC EXIT INVENTORY:" in prompt else opinion(["pi_side_a"])

    updated, _ = run(tmp_path, review, selection, originals, callback=partial)
    assert updated["opinion"].views[-1].model_dump()["module_terminals"] == original_terminals
    save_result(review, updated)
    review["slots"]["component_header"]["capture_id"] = "retaken-module"

    def replacement(prompt, schema):
        return inventory(["component_header"]) if "POC EXIT INVENTORY:" in prompt else opinion(["component_header"])

    replaced, _ = run(tmp_path, review, selection, originals, callback=replacement)
    assert replaced["opinion"].views[-1].module_terminals == []
