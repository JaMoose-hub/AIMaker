"""Concept-only motors must never expand the supported hardware workflow."""
import copy
import json

import pytest

from app.debug_support import identity, validate_project
from app.design_prompt import build_design_prompt
from app.designs import DesignProposal, GenerateRequest, compile_design, proposal_schema
from app.project_images import ProjectImageStore, build_image_prompt
from test_maker import proposal
from test_project_images import setup, submit


MOTORS = [{"kind": "motor", "quantity": 2, "purpose": "Visible under the chassis, image only"}]


def test_concept_motors_do_not_change_any_hardware_or_build_data():
    raw = proposal()
    base = compile_design(DesignProposal.model_validate(raw), "distance monitor")
    visual = compile_design(DesignProposal.model_validate({**raw, "concept_only_parts": MOTORS}),
                            "distance monitor", current=base)
    assert visual["concept_only_parts"] == MOTORS
    assert base["concept_only_parts"] == []
    for key in ("component_ids", "parameters", "wiring", "bom", "code", "logic", "requirements",
                "unresolved", "assembly", "instructions", "tests", "profile_versions"):
        assert visual[key] == base[key], key
    assert validate_project(visual) == validate_project(base)
    assert identity({"project": visual, "code": visual["code"]}, "pi") == identity(
        {"project": base, "code": base["code"]}, "pi")
    assert visual["revision"] == base["revision"] + 1


@pytest.mark.parametrize("parts", [
    [{"kind": "servo", "quantity": 1, "purpose": "visual"}],
    [{"kind": "battery", "quantity": 1, "purpose": "visual"}],
    [{"kind": "motor", "quantity": 0, "purpose": "visual"}],
    [{"kind": "motor", "quantity": 33, "purpose": "visual"}],
    [{"kind": "motor", "quantity": 1, "purpose": ""}],
    [{**MOTORS[0], "gpio": 12}],
    MOTORS * 2, None,
])
def test_concept_part_schema_rejects_expanded_scope_and_invalid_values(parts):
    with pytest.raises(ValueError):
        DesignProposal.model_validate({**proposal(), "concept_only_parts": parts})


def test_motor_is_still_forbidden_as_a_real_module_or_structural_bom_item():
    for override in ({"component_ids": ["motor"]},
                     {"assembly": {"description": "cart", "parts": MOTORS}}):
        with pytest.raises(ValueError):
            DesignProposal.model_validate({**proposal(), **override})


def test_prompts_keep_motor_appearance_separate_and_respect_revision_scope():
    design = compile_design(DesignProposal.model_validate({**proposal(), "concept_only_parts": MOTORS}), "cart")
    for intent in ("design", "auto", "ask"):
        body = GenerateRequest(prompt="Keep the body and add a motor", component_ids=["hc-sr04"],
                               current=design, intent=intent, design_mode="fixed")
        prompt = build_design_prompt(body)
        context = json.loads(prompt.split("Context: ", 1)[1])
        assert context["current_design"]["concept_only_parts"] == MOTORS
        assert "concept_only_parts" in prompt
    fresh = body.model_copy(update={"intent": "design", "design_mode": "free"})
    assert "concept_only_parts" not in json.loads(build_design_prompt(fresh).split("Context: ", 1)[1])["current_design"]
    prompt = build_image_prompt(design, editing=True)
    assert "Show the motors listed in concept_only_parts" in prompt
    assert "No motor power leads" in prompt
    assert "EDIT TARGET" in prompt
    assert json.loads(prompt.split("Design context: ", 1)[1])["concept_only_parts"] == MOTORS
    old = copy.deepcopy(design)
    old.pop("concept_only_parts")
    assert "No motors:" in build_image_prompt(old)
    assert "concept_only_parts" in proposal_schema()["required"]


def test_mock_generation_persists_motor_image_metadata_without_hardware(tmp_path):
    bridge, client, service = setup(tmp_path)
    raw = {**proposal(), "concept_only_parts": MOTORS}
    bridge.generate = lambda *args, **kwargs: raw
    job = submit(client, service)
    assert job["status"] == "completed"
    assert job["design"]["concept_only_parts"] == MOTORS
    assert "Show the motors listed" in bridge.image_calls[0][0]
    restored = ProjectImageStore(tmp_path).load_job(job["id"])
    assert restored["design"]["concept_only_parts"] == MOTORS
    assert "motor" not in job["design"]["component_ids"]
