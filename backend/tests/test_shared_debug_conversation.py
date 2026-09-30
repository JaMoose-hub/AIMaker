"""Shared wiring/debug conversation: real state machine with fake camera/Pi/model."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.debug_sessions import router
from app.debug_sessions import DebugSessions
from app.component_testing import TEMPLATE_VERSION, CAMERA_TEMPLATE_VERSION, wire_key
from test_debug_sessions import setup, _context, _diagnosed, _run


def target_context():
    context = _context()
    wire = next(w for w in context["project"]["wiring"] if w["componentId"] == "hc-sr04")
    context["wiring_target"] = dict(component_id=wire["componentId"], wire_id=wire["id"])
    return context


def no_diagnosis(*args, **kwargs):
    pytest.fail("wiring review attempted an SSH diagnosis")


@pytest.mark.parametrize("initial_action", ["message", "capture"])
def test_locale_switch_changes_next_ai_reply_without_resetting_wiring(setup, initial_action):
    service, state = setup
    context = {**target_context(), "locale": "zh-TW"}
    result = service.create(context, "請說明這條線", purpose="wiring_review",
                            initial_action=initial_action, request_id="language-start")
    service.tick(result["id"])
    before = service.get(result["id"])
    assert "in Traditional Chinese." in state.design_service.bridge.calls[-1][0]
    english = {**context, "locale": "en"}
    service.action(result["id"], "message", "language-en", context=english, text="這一步怎麼接？")
    service.tick(result["id"])
    prompt = state.design_service.bridge.calls[-1][0]
    assert prompt.startswith("RESPONSE LANGUAGE:") and "in English." in prompt
    assert "takes precedence" in prompt and "這一步怎麼接？" in prompt
    after = service.get(result["id"])
    assert after["binding"] == before["binding"]
    assert after["conversation_id"] == before["conversation_id"]
    assert after["wiring_target"] == before["wiring_target"]
    assert after["evidence"] == before["evidence"]
    assert after["messages"][:len(before["messages"])] == before["messages"]
    assert not state.pi_execution.jobs and not state.component_tests.actions
    service.action(result["id"], "message", "language-zh", context=context, text="繼續說明")
    service.tick(result["id"])
    assert "in Traditional Chinese." in state.design_service.bridge.calls[-1][0]


def test_offline_text_review_never_captures_probes_or_starts_hardware(setup):
    service, state = setup
    context = target_context()
    context.update(guide_confirmations={}, test_keys={})
    state.pi_deployer.snapshot = lambda: dict(connected=False, program="unknown")
    state.debug_cases.diagnose = no_diagnosis
    service.capture_fn = no_diagnosis
    created = service.create(context, "這條線要接哪裡？", purpose="wiring_review", request_id="review")
    service.tick(created["id"])
    result = service.get(created["id"])
    assert result["purpose"] == "wiring_review"
    assert result["hardware_blocker"] == "debug_start_required"
    assert not result["hardware_ready"] and result["wiring_edit_ready"]  # no prior program/job to reconcile
    assert not state.pi_execution.jobs and not result["evidence"]
    assert len(state.design_service.bridge.calls) == 1
    assert state.design_service.bridge.images == [[]]
    assert result["messages"][-1]["diagram_refs"][0]["wire_ids"] == [context["wiring_target"]["wire_id"]]
    assert "TEXT-ONLY" in state.design_service.bridge.calls[0][0]


def test_review_photo_advisory_cannot_escalate_but_start_debug_can(setup):
    service, state = setup
    context = target_context()
    original_diagnose = state.debug_cases.diagnose
    state.debug_cases.diagnose = no_diagnosis
    result = service.create(context, "看看接線", purpose="wiring_review", initial_action="capture", request_id="review")
    sid = result["id"]
    service.tick(sid)
    result = service.get(sid)
    assert len(result["evidence"]) == 1 and result["budget"]["model_calls"] == 1
    assert result["phase"] == "awaiting_user" and not state.pi_execution.jobs
    # Navigating or re-sending the same context cannot grant hardware authority.
    service.action(sid, "context_changed", "navigation", context=context)
    assert service.get(sid)["purpose"] == "wiring_review"
    state.debug_cases.diagnose = original_diagnose
    promoted = service.action(sid, "start_debug", "explicit", context=context)
    assert promoted["purpose"] == "debug" and promoted["status"] == "diagnosing"
    assert promoted["budget"]["model_calls"] == 1
    assert promoted["conversation_id"] == result["conversation_id"]
    service.tick(sid)
    assert state.debug_cases.cases and not state.pi_execution.jobs


@pytest.mark.parametrize("selection", [dict(component_id="hc-sr04", wire_id="unknown"),
                                      dict(component_id="mrd-tf240-8p-cs", wire_id="hc-sr04:echo")])
def test_wire_target_must_belong_to_selected_component(setup, selection):
    service, state = setup
    context = _context()
    context["wiring_target"] = selection
    with pytest.raises(ValueError, match="invalid_wiring_target"):
        service.create(context, "看接線", purpose="wiring_review")
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_confirmation_addition_preserves_chat_budget_and_pending_ready_step(setup):
    service, state = setup
    complete = _context()
    partial = deepcopy(complete)
    wire = next(w for w in partial["project"]["wiring"] if w["componentId"] == "mrd-tf240-8p-cs")
    del partial["guide_confirmations"][wire["id"]]
    partial["test_keys"].pop("mrd-tf240-8p-cs")
    sid = _diagnosed(service, partial)
    service.tick(sid)
    before = service.get(sid)
    assert before["phase"] == "prepare_near"  # HC is ready despite unrelated TFT pin.
    result = service.action(sid, "context_changed", "one-confirmation", context=complete)
    assert result["phase"] == "prepare_near"
    assert result["messages"] == before["messages"] and result["budget"] == before["budget"]
    assert result["evidence"][0]["current"] is True
    service.action(sid, "ready", "near", context=complete)
    assert len(state.pi_execution.jobs) == 1


def test_actual_confirmation_removal_invalidates_actions_without_losing_conversation(setup):
    service, state = setup
    context = target_context()
    sid = _diagnosed(service, context)
    service.tick(sid)
    service.action(sid, "ready", "near", context=context)
    before = service.get(sid)
    changed = deepcopy(context)
    changed["guide_confirmations"].pop(context["wiring_target"]["wire_id"])
    changed["test_keys"].pop("hc-sr04")
    result = service.action(sid, "context_changed", "removed", context=changed)
    assert result["conversation_id"] == before["conversation_id"] and result["messages"] == before["messages"]
    assert state.pi_execution.jobs[0]["state"] == "cancelled"
    assert result["phase"] == "awaiting_user" and result["evidence"][0]["current"] is False
    assert result["budget"] == before["budget"]
    with pytest.raises(ValueError, match="invalid_phase"):
        service.action(sid, "ready", "old-ready", context=changed)


def test_explicit_new_check_has_separate_budget_and_shared_persisted_history(setup):
    service, state = setup
    context = target_context()
    first = service.create(context, "原來問題", purpose="wiring_review", request_id="first")
    service.tick(first["id"])
    service.sessions[first["id"]]["budget"]["model_calls"] = 6
    service.action(first["id"], "stop", "stop")
    second = service.create(context, "接著檢查", purpose="wiring_review", conversation_id=first["conversation_id"], request_id="second")
    assert second["id"] != first["id"] and second["budget"]["model_calls"] == 0
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][0]["session_id"] == first["id"]
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    conversation = restored.conversation(second["conversation_id"])
    assert conversation["messages"] == second["messages"]
    assert restored.get(second["id"])["phase"] == "backend_restarted"
    assert len(state.design_service.bridge.calls) == 1


def test_valid_historical_runs_adopted_without_attempts_and_tft_needs_human(setup):
    service, state = setup
    context = _context()
    hc = _run("hc-old", "hc-sr04", context, "finished", "passed")
    hc.update(reserved=False, evidence="new_echo_samples")
    tft = _run("tft-camera", "mrd-tf240-8p-cs", context, "finished", "passed")
    tft.update(reserved=False, evidence="camera_advisory")
    for run in (hc, tft):
        run.update(revision=context["project"]["revision"],
                   template_version=CAMERA_TEMPLATE_VERSION if run["camera_assisted"] else TEMPLATE_VERSION,
                   wiring_hash=hashlib.sha256(json.dumps(wire_key([wire for wire in context["project"]["wiring"]
                       if wire["componentId"] == run["component_id"]])).encode()).hexdigest())
    stale = {**hc, "id": "different-pi", "target_id": "other"}
    state.component_tests.runs = [hc, stale, tft]
    result = service.create(context, "問一下", purpose="wiring_review", request_id="adopt")
    assert [item["run_id"] for item in result["adopted_tests"]] == ["hc-old"]
    assert result["test_attempts"] == {} and result["budget"]["tests"] == {}
    tft["evidence"] = "user_visual_confirmation"
    service._adopt_tests(service.sessions[result["id"]])
    assert len(service.get(result["id"])["adopted_tests"]) == 2
    assert not state.pi_execution.jobs
    for field, value in (("template_version", "old-v0"), ("wiring_hash", "wrong"), ("revision", -1), ("outcome", "failed")):
        altered = {**hc, field: value, "id": "newer-invalid"}
        state.component_tests.runs = [hc, altered]
        service._adopt_tests(service.sessions[result["id"]])
        assert not service.get(result["id"])["adopted_tests"]


def test_prepare_wiring_does_not_stop_unowned_work_and_still_allows_read_only_chat(setup):
    service, state = setup
    context = target_context()
    result = service.create(context, "看接線", request_id="start")
    state.pi_execution.jobs.append(dict(id="other", kind="test", state="running", run_id=None))
    prepared = service.action(result["id"], "prepare_wiring", "prepare", context=context)
    assert prepared["purpose"] == "wiring_review" and not prepared["wiring_edit_ready"]
    assert prepared["phase"] == "awaiting_user" and state.pi_execution.jobs[0]["state"] == "running"
    state.debug_cases.diagnose = no_diagnosis
    service.action(result["id"], "message", "msg", context=context, text="這是地線嗎")
    service.tick(result["id"])
    assert not service.get(result["id"])["evidence"]


def test_capture_views_mime_history_and_frozen_diagram_api(setup):
    service, state = setup
    context = target_context()
    original = service.capture_fn
    def capture(*args, **kwargs):
        images, meta = original(*args, **kwargs)
        images.update(pi_pins=b"\x89PNG\r\n\x1a\npi", component_pins=b"\x89PNG\r\n\x1a\nmodule")
        meta["views"] = [dict(name=name, encoding="png" if name != "overview" else "jpeg") for name in images]
        meta.update(mode="pin_crops", same_frame=False, capture_skew_ms=90,
                    selection={"elapsed_ms": 651, "candidate_count": 8})
        return images, meta
    service.capture_fn = capture
    state.debug_sessions = service
    app = FastAPI()
    app.state.debug_sessions, app.state.pi_deployer = service, state.pi_deployer
    app.include_router(router)
    client = TestClient(app)
    result = client.post("/api/debug/sessions", json=dict(context=context, symptom="拍這一步", purpose="wiring_review",
                          initial_action="capture", request_id="api-photo")).json()
    service.tick(result["id"])
    current = service.get(result["id"])
    entry = current["evidence"][0]
    assert (entry["mode"], entry["same_frame"], entry["capture_skew_ms"]) == ("pin_crops", False, 90)
    assert entry["selection"]["elapsed_ms"] == 651
    assert len(state.design_service.bridge.images[0]) == 3 and current["budget"]["model_calls"] == 1
    response = client.get(entry["url"] + "?view=pi_pins")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert client.get(entry["url"] + "?view=../other").status_code == 409
    conversation = client.get("/api/debug/conversations", params={"project_id": context["project"]["id"]}).json()["conversation"]
    assert conversation["evidence"][0]["session_id"] == result["id"]
    snapshot = client.get(f"/api/debug/conversations/{conversation['id']}/diagrams/{current['diagram_id']}").json()
    assert snapshot["source_type"] == "design_diagram" and snapshot["target"] == context["wiring_target"]
    context["project"]["title"] = "changed later"
    assert service.diagram(conversation["id"], snapshot["id"])["design"]["title"] != "changed later"


def test_context_update_during_cloud_reply_discards_stale_answer(setup):
    service, state = setup
    context = target_context()
    result = service.create(context, "看看", purpose="wiring_review", initial_action="capture", request_id="race")
    changed = deepcopy(context)
    changed["code"] += "\n# newer draft"
    generate = state.design_service.bridge.generate
    def racing_generate(*args, **kwargs):
        answer = generate(*args, **kwargs)
        service.action(result["id"], "context_changed", "new-context", context=changed)
        return answer
    state.design_service.bridge.generate = racing_generate
    service.tick(result["id"])
    current = service.get(result["id"])
    assert not current["observations"] and len(current["messages"]) == 1
    assert current["phase"] == "awaiting_user" and not state.pi_execution.jobs


def test_thorough_inspection_charges_each_call_and_cannot_overrun_six(setup, monkeypatch):
    service, state = setup
    context = target_context()
    result = service.create(context, "仔細看", purpose="wiring_review", initial_action="capture", response_mode="thorough", request_id="deep")
    service.sessions[result["id"]]["budget"]["model_calls"] = 5
    def inspector(target, images, metadata, *, generate, **kwargs):
        schema = {"required": ["seen"]}
        generate("one", schema, image_paths=[])
        generate("two", schema, image_paths=[])
        pytest.fail("exceeded six calls")
    monkeypatch.setattr("app.debug_capture.inspect_debug_wiring", inspector)
    service.tick(result["id"])
    current = service.get(result["id"])
    assert current["budget"]["model_calls"] == 6 and len(state.design_service.bridge.calls) == 1
    assert current["phase"] == "model_limit" and not state.pi_execution.jobs


def test_selected_wire_change_during_capture_cannot_rebind_old_photo(setup):
    service, state = setup
    context = target_context()
    result = service.create(context, "拍這條", purpose="wiring_review", initial_action="capture", request_id="race-photo")
    changed = deepcopy(context)
    wire = next(w for w in context["project"]["wiring"] if w["componentId"] == "hc-sr04" and w["id"] != context["wiring_target"]["wire_id"])
    changed["wiring_target"] = dict(component_id=wire["componentId"], wire_id=wire["id"])
    original = service.capture_fn
    def racing_capture(*args, **kwargs):
        image = original(*args, **kwargs)
        service.action(result["id"], "context_changed", "target-changed", context=changed)
        return image
    service.capture_fn = racing_capture
    service.tick(result["id"])
    current = service.get(result["id"])
    assert not current["evidence"] and not state.design_service.bridge.calls
    assert current["wiring_target"]["wire_id"] == wire["id"] and current["phase"] == "awaiting_user"


def test_multi_wire_model_references_validated_and_frozen_snapshot_retained(setup):
    service, state = setup
    context = _context()  # Debug page has no selected guide wire.
    selected = [wire["id"] for wire in context["project"]["wiring"][:2]]
    original = state.design_service.bridge.generate
    def with_references(*args, **kwargs):
        answer = original(*args, **kwargs)
        answer.update(wire_ids=[*selected, "not-in-project", selected[0]], initial_focus_wire_id=selected[1])
        return answer
    state.design_service.bridge.generate = with_references
    result = service.create(context, "說明兩條線", purpose="wiring_review", request_id="refs")
    service.tick(result["id"])
    reply = service.get(result["id"])["messages"][-1]
    reference = reply["diagram_refs"][0]
    assert reference["wire_ids"] == selected and reference["initial_focus_wire_id"] == selected[1]
    first_snapshot = service.diagram(result["conversation_id"], reference["snapshot_id"])
    for index in range(34):
        later = deepcopy(context)
        later["project"]["title"] = f"後續設計 {index}"
        service.create_diagram(result["conversation_id"], later)
    assert service.diagram(result["conversation_id"], reference["snapshot_id"]) == first_snapshot
    # Explicit invalid references cannot fall back to a misleading guide wire.
    state.design_service.bridge.generate = lambda *args, **kwargs: dict(seen="", visibility="uncertain", suggested_action="ask_user",
        explanation="一般回答", next_step="", wire_ids=["not-in-project"], initial_focus_wire_id="not-in-project")
    service.action(result["id"], "message", "other-reply", context=context, text="另個問題")
    service.tick(result["id"])
    assert not service.get(result["id"])["messages"][-1].get("diagram_refs")


def test_unknown_pi_with_prior_invocation_or_pid_blocks_actual_wiring_edit(setup):
    service, state = setup
    context = target_context()
    state.pi_deployer.snapshot = lambda: dict(connected=False, program="unknown", invocation_id="prior-live-run")
    result = service.create(context, "離線看接線", purpose="wiring_review", request_id="offline-known")
    assert not result["wiring_edit_ready"]
    state.pi_deployer.snapshot = lambda: dict(connected=False, program="stopped", pid=345)
    assert not service.get(result["id"])["wiring_edit_ready"]
    service.tick(result["id"])
    assert not state.pi_execution.jobs and not service.get(result["id"])["evidence"]


def test_changed_render_facts_create_new_diagram_even_when_design_unchanged(setup, monkeypatch):
    from app import debug_diagrams
    service, state = setup
    context = target_context()
    result = service.create(context, "看這條線", purpose="wiring_review", request_id="render-version")
    old = service.diagram(result["conversation_id"], result["diagram_id"])
    original = debug_diagrams.build_diagram_snapshot
    def new_render(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        snapshot["render_snapshot"]["modules"][0]["canonical_orientation"] = "new orientation facts"
        return snapshot
    monkeypatch.setattr(debug_diagrams, "build_diagram_snapshot", new_render)
    newer = service.create_diagram(result["conversation_id"], context)
    assert newer["id"] != old["id"]
    assert service.diagram(result["conversation_id"], old["id"]) == old


@pytest.mark.parametrize("program", ["stopped", "unknown"])
def test_fixed_component_uses_its_own_preflight_but_never_bypasses_unknown_pi(setup, program):
    service, state = setup
    context = _context()
    sid = service.create(context, "HC測距異常", request_id="target-gate")["id"]
    service.tick(sid)
    case = state.debug_cases.cases["case1"]
    case["issues"] = [dict(reason="spi_missing", component_id="mrd-tf240-8p-cs", next_action="prepare_environment")]
    case["evidence"] = dict(environment_error="spi_missing", pi=dict(program=program))
    service.tick(sid)
    service.tick(sid)
    current = service.get(sid)
    assert current["trial_hardware_blocker"] == "spi_missing"
    if program == "unknown":
        assert not current["hardware_ready"] and current["status"] == "paused"
        assert not state.pi_execution.jobs
    else:
        assert current["hardware_ready"] and current["phase"] == "prepare_near"
        service.action(sid, "ready", "near", context=context)
        assert len(state.pi_execution.jobs) == 1 and state.pi_execution.jobs[0]["state"] == "queued"
        # The queue remains the final owner of the actual target preflight.
        state.pi_execution.jobs[0].update(state="blocked", error="target_dependency_missing")
        service.tick(sid)
        assert service.get(sid)["phase"] == "test_preflight_blocked"
