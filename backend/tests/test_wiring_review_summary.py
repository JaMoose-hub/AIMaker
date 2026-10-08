"""Compact photo summaries retain exact per-wire human authority; no hardware/cloud."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.guided_wiring_review import (GuidedWiringReview, ReviewOpinion, ReviewWirePath,
                                     WiringReviewAction, _canonical_candidates, compare_candidates)


PINS = {"GND6": {"index": 6}, "GPIO17": {"index": 11}, "GPIO18": {"index": 12}}
WIRES = [dict(id=f"hc:{pin.lower()}", componentPin=pin, boardPin=board, connectionKind="direct")
         for pin, board in (("GND", "GND6"), ("TRIG", "GPIO17"), ("ECHO", "GPIO18"))]


def candidate(role, pin, index):
    return dict(id=f"{role}:c{index}", role=role, pin_id=pin,
                physical_pin=PINS.get(pin, {}).get("index"),
                color=("black", "blue", "green")[index], color_visibility="clear",
                contact="covers_pin", evidence="Visible housing base and wire.",
                pin_evidence="Visible pin label." if pin else "",
                limitations="Pin positions are obscured.")


def dialogue(candidates, paths=(), no_progress=0, views=None):
    review = dict(id="review-a", revision=1, round=1, component_id="hc-sr04", status="ready",
                  results=compare_candidates(candidates, WIRES, PINS, wire_paths=paths),
                  observations=candidates, reviews={}, no_progress_count=no_progress)
    if views is not None:
        review["last_opinion"] = dict(views=deepcopy(views))
        review["slots"] = {role: dict(capture_id=f"capture-{role}", sha256=str(index) * 64)
                           for index, role in enumerate(("pi_side_a", "pi_side_b", "component_header"))}
    session = dict(context={"locale": "zh-TW"}, status="awaiting_capture", phase="wiring_review",
                   wiring_review=review, wiring_dialogue=dict(id="flow-a", events=[], guide_round=0, epoch=0))
    service = SimpleNamespace(_add_message=lambda session, message: session.setdefault("messages", []).append(deepcopy(message)))
    controller = GuidedWiringReview(service)
    controller.sync_dialogue(session)
    return controller, session, session["wiring_dialogue"]["events"][-1]


def test_unlocated_pins_request_one_shared_view_instead_of_first_gnd_wire():
    candidates = [candidate(role, None, index) for role in ("pi_side_a", "component_header") for index in range(3)]
    controller, session, message = dialogue(candidates)
    summary = message["wiring_flow"]["summary"]
    assert summary["retake_role"] == "component_header"
    assert summary["headline"] == "零件接頭的腳位尚未確認。"
    assert "GND" not in summary["headline"] + summary["next_step"]
    assert summary["counts"] == dict(suspected=0, uncertain=3, no_issue_seen=0)
    assert message["wiring_flow"]["wire_id"] == "hc:gnd"
    assert len(summary["results"]) == 3 and not session["wiring_review"]["reviews"]


def test_known_module_pins_only_request_the_missing_pi_view():
    candidates = [candidate("component_header", wire["componentPin"], index) for index, wire in enumerate(WIRES)]
    candidates += [candidate("pi_side_a", None, index) for index in range(3)]
    controller, session, message = dialogue(candidates)
    summary = message["wiring_flow"]["summary"]
    assert summary["retake_role"] == "pi_side_b"
    assert summary["headline"] == "Pi 插接位置尚未確認。"
    assert "另一側" in summary["next_step"] and "零件" not in summary["next_step"]


def test_suspected_wire_wins_but_overview_cannot_confirm_a_different_wire():
    candidates = [candidate("pi_side_a", "GPIO17", 2), candidate("component_header", "ECHO", 2)]
    path = ReviewWirePath(wire_id="hc:echo", board_connector_id="pi_side_a:c2",
                         component_connector_id="component_header:c2", visibility="traceable",
                         evidence="A visible continuous route joins these identified housings.")
    controller, session, message = dialogue(candidates, [path])
    flow = message["wiring_flow"]
    assert flow["wire_id"] == "hc:echo" and flow["summary"]["results"][0]["wire_id"] == "hc:echo"
    assert "ECHO" in flow["summary"]["headline"] and "疑似" in flow["summary"]["headline"]
    assert flow["summary"]["retake_role"] is None
    assert "先斷電" in flow["summary"]["next_step"]
    wrong = WiringReviewAction(op="review", review_id="review-a", revision=1,
                               wire_id="hc:gnd", decision="confirmed")
    with pytest.raises(ValueError, match="wiring_dialogue_wire_mismatch"):
        controller.dialogue_guard(session, flow, wrong)
    controller.dialogue_guard(session, flow, wrong.model_copy(update={"wire_id": "hc:echo"}))
    assert session["wiring_review"]["reviews"] == {}


def test_summary_is_frozen_and_visible_routes_do_not_claim_test_pass():
    candidates = [candidate(role, wire["componentPin"] if role == "component_header" else wire["boardPin"], index)
                  for index, wire in enumerate(WIRES) for role in ("pi_side_a", "component_header")]
    paths = [ReviewWirePath(wire_id=wire["id"], board_connector_id=f"pi_side_a:c{index}",
                           component_connector_id=f"component_header:c{index}", visibility="traceable",
                           evidence="The route is directly visible between these housings.")
             for index, wire in enumerate(WIRES)]
    controller, session, message = dialogue(candidates, paths)
    original = deepcopy(message["wiring_flow"]["summary"])
    assert original["counts"]["no_issue_seen"] == 3
    assert "仍需親自確認" in original["headline"] and "通過" not in original["headline"]
    assert all(row["authority"] == "visual_advisory" for row in original["results"])
    session["wiring_review"]["results"][0]["expected"]["physical_pin"] = 99
    session["wiring_review"]["results"][0]["diagnosis"]["evidence"] = "changed later"
    session["wiring_review"]["revision"] += 1
    controller.sync_dialogue(session)
    assert message["wiring_flow"]["summary"] == original
    assert session["messages"][0]["wiring_flow"]["summary"] == original
    assert not session["wiring_review"]["reviews"]
    # A manually addressed suspicion remains in the frozen photo result: a
    # later clear wire must not make the whole photograph sound fault-free.
    session["wiring_review"]["results"][1]["diagnosis"]["status"] = "suspected"
    session["wiring_review"]["reviews"]["hc:trig"] = {"decision": "confirmed"}
    session["wiring_review"]["revision"] += 1
    controller.sync_dialogue(session)
    latest = session["wiring_dialogue"]["events"][-1]["wiring_flow"]["summary"]
    assert latest["counts"]["suspected"] == 1 and latest["headline"].startswith("GND")


def test_no_progress_limit_stops_the_retake_suggestion_and_keeps_manual_review():
    controller, session, message = dialogue([], no_progress=2)
    summary = message["wiring_flow"]["summary"]
    assert summary["retake_role"] is None and "無法確定" in summary["next_step"]
    assert controller.dialogue_projection(session, message)["actions"] == ["review", "changed"]
    assert summary["counts"]["uncertain"] == 3 and not session["wiring_review"]["reviews"]


def test_visible_uncovered_header_is_not_presented_as_blur_or_a_numbered_missing_wire():
    evidence = "模組四支針腳完整裸露，未見接頭套接。"
    views = [dict(role="component_header", connectors=[], limitations="標字仍未辨識。",
                  header_observation=dict(state="uncovered_pins", evidence=evidence))]
    controller, session, message = dialogue([], views=views, no_progress=2)
    summary = message["wiring_flow"]["summary"]
    assert summary["headline"] == "零件端可見裸露排針。"
    assert summary["observation"] == evidence and summary["observation_role"] == "component_header"
    assert summary["observation_source"] == dict(review_id="review-a", round=1, role="component_header",
                                                 capture_id="capture-component_header", sha256="2" * 64)
    assert summary["retake_role"] is None and "先斷電" in summary["next_step"]
    assert "看不清" not in summary["headline"] + summary["next_step"]
    assert all(row["diagnosis"]["status"] == "uncertain" for row in summary["results"])
    assert not session["wiring_review"]["reviews"]


def test_legacy_empty_connector_observation_is_quoted_without_inventing_a_fault():
    for evidence in ("模組四支針腳完整裸露，未見接頭套接。", "排針可見，但文字標籤無法辨識。"):
        views = [dict(role="component_header", connectors=[], limitations=evidence)]
        controller, session, message = dialogue([], views=views)
        summary = message["wiring_flow"]["summary"]
        assert summary["headline"] == "照片觀察：" + evidence
        assert summary["observation"] == evidence and summary["retake_role"] is None
        assert summary["counts"] == dict(suspected=0, uncertain=3, no_issue_seen=0)
        assert "接錯" not in summary["headline"] and not session["wiring_review"]["reviews"]


def test_detached_visible_connector_keeps_its_observation_but_not_an_attached_pin_identity():
    views = [dict(role=role, connectors=[], limitations="") for role in ("pi_side_a", "pi_side_b", "component_header")]
    views[-1]["connectors"] = [dict(id="c0", contact="detached", position="By the module header",
        pin_id="GND", pin_evidence="黑色插頭在排針旁，未套住針腳。", box=None,
        wire_color=dict(name="black", visibility="clear", evidence="Black insulation visible"),
        evidence="Visible unattached housing")]
    opinion = ReviewOpinion.model_validate(dict(views=views))
    slots = {role: dict(capture_id=f"capture-{role}", sha256="a" * 64) for role in ("pi_side_a", "pi_side_b", "component_header")}
    candidates = _canonical_candidates(opinion, dict(slots=slots), PINS, {"GND", "TRIG", "ECHO"})
    assert candidates[0]["pin_id"] is None and candidates[0]["contact"] == "detached"
    controller, session, message = dialogue(candidates, views=views)
    summary = message["wiring_flow"]["summary"]
    assert "未套接的接頭" in summary["headline"] and summary["retake_role"] is None
    assert summary["observation"] == views[-1]["connectors"][0]["pin_evidence"]
    assert all(row["diagnosis"]["status"] == "uncertain" for row in summary["results"])


def test_same_revision_legacy_projection_is_read_only_and_cannot_borrow_a_new_round():
    controller, session, message = dialogue([])
    message["wiring_flow"]["summary"] = dict(headline="零件接頭還看不清楚。")
    session["wiring_review"]["last_opinion"] = dict(views=[dict(role="component_header", connectors=[],
        limitations="模組四支針腳完整裸露，未見接頭套接。")])
    before = deepcopy(session)
    projected = controller.dialogue_projection(session, message)
    assert projected["summary"]["schema_version"] == 2 and "裸露" in projected["summary"]["headline"]
    assert projected["wire_id"] == message["wiring_flow"]["wire_id"]
    assert projected["actions"] == ["review", "capture", "crop", "changed"]
    assert session == before and message["wiring_flow"]["summary"] == dict(headline="零件接頭還看不清楚。")
    session["wiring_review"]["round"] += 1
    session["wiring_review"]["revision"] += 1
    session["wiring_review"]["status"] = "collecting"
    historical = controller.dialogue_projection(session, message)
    assert historical["summary"] == message["wiring_flow"]["summary"]
    assert not historical["current"] and not historical["can_act"] and historical["actions"] == []


def test_occluded_header_retains_a_retake_and_does_not_claim_exposed_pins():
    views = [dict(role="component_header", connectors=[], limitations="插接位置被遮住。",
                  header_observation=dict(state="occluded", evidence="線束遮住插頭底部。"))]
    controller, session, message = dialogue([], views=views)
    summary = message["wiring_flow"]["summary"]
    assert summary["retake_role"] == "component_header"
    assert summary["observation"] == "線束遮住插頭底部。"
    assert "裸露" not in summary["headline"] and "補拍" in summary["next_step"]
