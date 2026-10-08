"""Source-bound terminal clues using synthetic observations/fake cloud only."""
from copy import deepcopy

from app.guided_wiring_review import (
    _canonical_module_terminals, _review_priority, _review_summary, compare_candidates,
)
from app.wiring_photo_pipeline import ReviewOpinion, ROLES
from test_debug_sessions import setup
from test_guided_wiring_review import _act, _analyse, _answer, _capture_stub, _photos, _start


PINS = {"GPIO25": {"index": 22, "design_row": "outer"}, "GPIO24": {"index": 18, "design_row": "outer"}}
WIRES = [dict(id="display:reset", boardPin="GPIO25", componentPin="RESET", connectionKind="direct"),
         dict(id="display:mode", boardPin="GPIO24", componentPin="MODE", connectionKind="direct")]
LABELS = {"RESET", "MODE", "OPTIONAL"}


def slot():
    return dict(capture_id="current-module", sha256="a" * 64, size=[1200, 1600], available=True)


def terminal(pin="RESET", state="uncovered", **extra):
    return dict(pin_id=pin, state=state, evidence=f"The {pin} label identifies a complete uncovered pin tip.",
                box=[.1, .2, .15, .3], capture_id=slot()["capture_id"],
                source_sha256=slot()["sha256"], source_size=slot()["size"], **extra)


def opinion(terminals=(), *, header_state="housings_visible", header_evidence="Housings and bare terminals coexist."):
    return ReviewOpinion(views=[dict(role=role, connectors=[], limitations="",
        module_terminals=list(terminals) if role == "component_header" else [],
        header_observation=dict(state=header_state, evidence=header_evidence)) for role in ROLES], wire_paths=[])


def canonical(raw=None, review=None):
    return _canonical_module_terminals(raw or opinion([terminal()]), review or dict(slots={"component_header": slot()}), LABELS)


def results(terms, candidates=()):
    return compare_candidates(list(candidates), WIRES, PINS, terminal_observations=terms, capture_plan="pi_rows_v1")


def assert_no_missing(rows):
    assert not any(row["diagnosis"].get("kind") == "unconnected_terminal" for row in rows)
    assert all(row["same_wire"] == "uncertain" for row in rows)


def test_visible_expected_terminal_yields_generic_missing_clue_without_connector_or_confirmation():
    raw = opinion([terminal()])
    before = raw.model_dump()
    terms = canonical(raw)
    rows = results(terms)
    reset = rows[0]
    finding = reset["diagnosis"]
    assert finding["status"] == "suspected" and finding["kind"] == "unconnected_terminal"
    assert finding["evidence"] == terms[0]["evidence"] and finding["terminal_observation"] == terms[0]
    assert finding["retake_roles"] == [] and finding["observed_component_pin"] is None
    assert finding["component_connector_id"] is None and finding["observed_board_pin"] is None
    assert reset["component_candidates"] == [] and reset["pi_candidates"] == []
    assert reset["same_wire"] == "uncertain" and "passed" not in reset and "confirmed" not in reset
    pending = sorted(rows, key=_review_priority)
    summary = _review_summary(dict(results=rows), pending, "zh-TW")
    assert summary["headline"] == "RESET 這個腳位疑似漏接。" and summary["retake_role"] is None
    assert "接線圖" in summary["next_step"] and "RESET" in summary["next_step"]
    assert "Pi Pin" not in summary["next_step"] and "補拍" not in summary["next_step"]
    assert len(summary["results"]) == 2 and raw.model_dump() == before


def test_visible_optional_terminal_without_expected_wire_is_not_a_fault():
    rows = results(canonical(opinion([terminal("OPTIONAL")])))
    assert_no_missing(rows)
    assert len(rows) == len(WIRES) and not any(row["expected"]["component_pin"] == "OPTIONAL" for row in rows)


def test_mixed_header_keeps_required_uncovered_clue_separate_from_other_covered_positions():
    covered = terminal("MODE", "covered")
    covered.update(box=[.3, .2, .35, .3], evidence="MODE has a visible housing over its terminal.")
    raw = opinion([covered, terminal()], header_state="housings_visible")
    rows = results(canonical(raw))
    assert rows[0]["diagnosis"]["kind"] == "unconnected_terminal"
    assert rows[1]["diagnosis"]["status"] == "uncertain"
    assert [row["wire_id"] for row in sorted(rows[::-1], key=_review_priority)][0] == "display:reset"


def test_uncertain_or_unidentified_terminals_and_empty_inventory_do_not_invent_absence():
    assert_no_missing(results(canonical(opinion([terminal(state="uncertain")]))))
    assert_no_missing(results(canonical(opinion([terminal(None)]))))
    assert_no_missing(results(canonical(opinion([terminal("UNKNOWN_LABEL")]))))
    assert_no_missing(results(canonical(opinion([]))))


def test_conflicting_same_terminal_states_or_shared_location_labels_suppress_missing_claim():
    assert_no_missing(results(canonical(opinion([terminal(), terminal(state="covered")]))))
    assert_no_missing(results(canonical(opinion([terminal(), terminal(state="uncertain")]))))
    assert_no_missing(results(canonical(opinion([terminal(), terminal("MODE")]))))


def test_visible_housing_on_same_label_prevents_conflicting_missing_claim():
    connector = dict(id="component_header:c1", role="component_header", pin_id=None, module_pin_id="RESET",
        module_pin_evidence="RESET identifies this visible housing.", pin_evidence="Housing covers terminal.",
        contact="covers_pin", color="blue", color_visibility="clear", evidence="A housing is visible.", physical_pin=None)
    assert_no_missing(results(canonical(), [connector]))


def test_unbound_stale_sources_and_pi_view_terminal_lists_cannot_accuse_module_pin():
    raw = opinion([terminal()])
    for field, bad in (("capture_id", "old-module"), ("source_sha256", "b" * 64), ("source_size", [1600, 1200])):
        changed = raw.model_copy(deep=True)
        setattr(changed.views[-1].module_terminals[0], field, bad)
        assert canonical(changed) == []
    unbound = raw.model_copy(deep=True)
    unbound.views[-1].module_terminals[0].capture_id = None
    assert canonical(unbound) == []
    wrong_role = raw.model_copy(deep=True)
    wrong_role.views[0].module_terminals = wrong_role.views[-1].module_terminals
    wrong_role.views[-1].module_terminals = []
    assert canonical(wrong_role) == []
    replaced = dict(slots={"component_header": dict(slot(), capture_id="replacement")})
    assert canonical(raw, replaced) == []


def test_legacy_prose_about_a_named_bare_pin_is_not_reinterpreted_as_structured_evidence():
    legacy = opinion([], header_state="housings_visible", header_evidence="RESET and OPTIONAL tips are exposed.")
    assert canonical(legacy) == []
    assert_no_missing(results(canonical(legacy)))


def tft_analysis(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    # This fake bridge exercises the retained two-stage contract explicitly.
    service.sessions[sid]["response_mode"] = "thorough"
    _act(service, sid, context, "start", component_id="mrd-tf240-8p-cs")
    _photos(service, sid, context)
    answer = _answer(context, component_id="mrd-tf240-8p-cs")
    module = next(view for view in answer["views"] if view["role"] == "component_header")
    module["connectors"] = [c for c in module["connectors"] if c["pin_id"] != "RES"]
    module["header_observation"] = dict(state="housings_visible", evidence="Six housings and two complete bare tips.")
    module["module_terminals"] = [
        dict(pin_id="RES", state="uncovered", evidence="RES label identifies the complete uncovered terminal tip.", box=[.4, .2, .45, .3]),
        dict(pin_id="BLK", state="uncovered", evidence="BLK label identifies the complete uncovered terminal tip.", box=[.7, .2, .75, .3])]
    review = _analyse(service, state, sid, context, answer)
    return service, state, sid, context, review


def test_production_fresh_analysis_records_terminals_and_prioritises_missing_required_tft_pin(setup):
    service, state, sid, context, review = tft_analysis(setup)
    assert review["status"] == "ready" and len(review["results"]) == 7
    assert {term["pin_id"] for term in review["terminal_observations"]} == {"RES", "BLK"}
    res = next(row for row in review["results"] if row["expected"]["component_pin"] == "RES")
    assert res["diagnosis"]["kind"] == "unconnected_terminal"
    assert all(row["expected"]["component_pin"] != "BLK" for row in review["results"])
    assert review["reviews"] == {} and len(state.design_service.bridge.calls) == 2
    assert service.sessions[sid]["context"]["guide_confirmations"] == context["guide_confirmations"]
    assert not state.pi_execution.jobs and not state.component_tests.actions


def test_cached_analysis_revalidates_terminal_sources_and_new_photo_clears_current_terminal_results(setup):
    service, state, sid, context, _ = tft_analysis(setup)
    internal = service.sessions[sid]["wiring_review"]
    internal["results"] = []  # Exercise production's saved-opinion reconstruction path.
    _act(service, sid, context, "analyse")
    review = service.get(sid)["wiring_review"]
    res = next(row for row in review["results"] if row["expected"]["component_pin"] == "RES")
    assert res["diagnosis"]["kind"] == "unconnected_terminal" and len(state.design_service.bridge.calls) == 2
    assert review["terminal_observations"]
    _act(service, sid, context, "capture", role="component_header")
    fresh = service.get(sid)["wiring_review"]
    assert fresh["terminal_observations"] == [] and fresh["results"] == []
    assert not state.pi_execution.jobs and not state.component_tests.actions
