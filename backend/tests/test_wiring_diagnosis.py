"""Synthetic connector observations only; no actual photo, cloud or GPIO proof."""
from copy import deepcopy

import pytest

from app.guided_wiring_review import ReviewWirePath, compare_candidates
from test_guided_wiring_review import setup, _start, _capture_stub, _photos, _analyse, _answer, _act


PINS = {"GPIO17": {"index": 11}, "GPIO18": {"index": 12}}
WIRE = dict(id="hc:trig", boardPin="GPIO17", componentPin="TRIG", connectionKind="direct")


def candidate(role, pin, physical=None):
    return dict(id=f"{role}:c1", role=role, pin_id=pin, physical_pin=physical,
        color="blue", color_visibility="clear", contact="covers_pin", evidence="Visible insertion and insulation.")


def path(**extra):
    return ReviewWirePath.model_validate(dict(wire_id="hc:trig", board_connector_id="pi_side_a:c1",
        component_connector_id="component_header:c1", visibility="traceable",
        evidence="Continuous route visibly connects these housings; not inferred from colour.", **extra))


def analyse(candidates, paths=(), wire=WIRE):
    return compare_candidates(candidates, [wire], PINS, wire_paths=paths)[0]


def test_colour_only_never_identifies_a_wrong_pin_or_a_match():
    items = [candidate("pi_side_a", "GPIO18", 12), candidate("component_header", "TRIG")]
    before = deepcopy(items)
    result = analyse(items)
    assert result["diagnosis"]["status"] == "uncertain"
    assert result["diagnosis"]["observed_physical_pin"] is None
    assert result["same_wire"] == "uncertain"
    assert items == before


def test_independently_traced_wrong_pi_pin_is_a_suspicion_not_a_confirmation():
    result = analyse([candidate("pi_side_a", "GPIO18", 12), candidate("component_header", "TRIG")], [path()])
    assert result["diagnosis"]["status"] == "suspected"
    assert result["expected"]["physical_pin"] == 11
    assert result["diagnosis"]["observed_physical_pin"] == 12
    assert result["authority"] == "visual_advisory"
    assert "confirmed" not in result


def test_wrong_module_pin_requires_a_traced_expected_pi_endpoint():
    result = analyse([candidate("pi_side_a", "GPIO17", 11), candidate("component_header", "ECHO")], [path()])
    assert result["diagnosis"]["status"] == "suspected"
    assert result["diagnosis"]["observed_component_pin"] == "ECHO"


@pytest.mark.parametrize("fault", ["hidden", "missing_id", "missing_pin", "detached", "duplicate_paths", "divider", "unrelated"])
def test_ambiguous_or_unsupported_routes_cannot_accuse_a_pin(fault):
    items = [candidate("pi_side_a", "GPIO18", 12), candidate("component_header", "TRIG")]
    paths, wire = [path()], deepcopy(WIRE)
    if fault == "hidden":
        paths[0].visibility = "partial"
    elif fault == "missing_id":
        paths[0].board_connector_id = "pi_side_a:not-in-photo"
    elif fault == "missing_pin":
        items[0]["pin_id"] = None
    elif fault == "detached":
        items[0]["contact"] = "detached"
    elif fault == "duplicate_paths":
        paths.append(path())
    elif fault == "divider":
        wire["connectionKind"] = "divider"
    elif fault == "unrelated":
        items[1]["pin_id"] = "ECHO"
    result = analyse(items, paths, wire)
    assert result["diagnosis"]["status"] == "uncertain"
    assert result["diagnosis"]["observed_physical_pin"] is None


def test_visible_expected_route_is_not_a_functional_or_electrical_pass():
    result = analyse([candidate("pi_side_a", "GPIO17", 11), candidate("component_header", "TRIG")], [path()])
    assert result["diagnosis"]["status"] == "no_issue_seen"
    assert result["authority"] == "visual_advisory"
    assert "passed" not in result and "confirmed" not in result


def test_unknown_module_endpoint_requests_only_its_missing_view():
    result = analyse([candidate("pi_side_a", "GPIO17", 11), candidate("pi_side_b", "GPIO17", 11),
        candidate("component_header", None)], [path()])
    assert result["diagnosis"]["retake_roles"] == ["component_header"]
    assert "TRIG" in result["next_step"] and "補拍零件接頭" in result["next_step"]


def test_visible_pin_on_one_side_does_not_request_another_photo_of_that_pin():
    result = analyse([candidate("pi_side_a", "GPIO17", 11), candidate("component_header", "TRIG")])
    assert result["diagnosis"]["status"] == "uncertain"  # The strand still isn't established.
    assert result["diagnosis"]["retake_roles"] == []
    assert "藍色 TRIG 線" in result["next_step"] and "接線圖中標示的應接位置" in result["next_step"]
    assert "Pi Pin" not in result["next_step"]
    assert "補拍" not in result["next_step"]


def test_uncertain_reply_surfaces_actual_photo_observations_instead_of_colour_template():
    pi = candidate("pi_side_a", None)
    pi["limitations"] = "兩排針重疊，Pin 1 起點被遮住。"
    module = candidate("component_header", "TRIG")
    module["pin_evidence"] = "TRIG 標字上方可見藍線插頭。"
    result = analyse([pi, module])
    assert result["diagnosis"]["status"] == "uncertain"
    assert pi["limitations"] in result["diagnosis"]["evidence"]
    assert module["pin_evidence"] in result["diagnosis"]["evidence"]
    assert result["diagnosis"]["retake_roles"] == ["pi_side_b"]
    assert "板角方向" in result["next_step"]


def wrong_trig_answer(context):
    answer = _answer(context)
    wires = [w for w in context["project"]["wiring"] if w["componentId"] == "hc-sr04"]
    index = next(i for i, wire in enumerate(wires) if wire["componentPin"] == "TRIG")
    for view in answer["views"]:
        if view["role"] != "component_header":
            view["connectors"][index]["pin_id"] = "GPIO18"
    answer["wire_paths"] = [dict(wire_id=wires[index]["id"], board_connector_id=f"pi_side_a:c{index}",
        component_connector_id=f"component_header:c{index}", visibility="traceable",
        evidence="The wire route is visible between the identified housings.")]
    return answer


def test_three_selected_photos_produce_one_analysis_and_prioritise_the_wrong_pin(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    result = _analyse(service, state, sid, context, wrong_trig_answer(context))
    row = next(row for row in result["results"] if row["expected"]["component_pin"] == "TRIG")
    assert row["diagnosis"]["status"] == "suspected"
    assert row["expected"]["physical_pin"] == 11 and row["diagnosis"]["observed_physical_pin"] == 12
    assert len(state.design_service.bridge.calls) == 2
    assert result["reviews"] == {}
    assert not state.pi_execution.jobs


def test_partial_retake_cannot_reuse_a_previous_route_accusation(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    _analyse(service, state, sid, context, wrong_trig_answer(context))
    _act(service, sid, context, "capture", role="pi_side_a")
    result = _analyse(service, state, sid, context, wrong_trig_answer(context))
    assert all(row["diagnosis"]["status"] == "uncertain" for row in result["results"])
    assert service.sessions[sid]["wiring_review"]["last_opinion"]["wire_paths"] == []
    assert len(state.design_service.bridge.calls) == 4
    assert not state.pi_execution.jobs
