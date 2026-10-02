"""New wiring rounds detach chat history, never execute or delete evidence."""
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.debug_sessions import router
from app.debug_sessions import DebugSessions
from test_debug_sessions import setup, _context


def stopped_check(service, project_id="collab-debug", request_id="old"):
    context = _context()
    context["project"]["id"] = project_id
    result = service.create(context, "舊接線問題", purpose="wiring_review", request_id=request_id)
    service.action(result["id"], "stop", "stop-" + request_id)
    return result, context


def test_restart_empty_round_persists_without_deleting_other_project_or_evidence(setup):
    service, state = setup
    old, context = stopped_check(service)
    foreign, _ = stopped_check(service, "other", "foreign")
    old_history = service.conversation(old["conversation_id"])
    foreign_history = service.conversation(foreign["conversation_id"])
    original = deepcopy(context["project"])
    fresh = service.restart_conversation(original["id"], "restart", old["conversation_id"])["conversation"]
    assert fresh["id"] != old["conversation_id"]
    assert fresh["messages"] == fresh["check_ids"] == fresh["diagrams"] == fresh["evidence"] == []
    assert service.conversation(old["conversation_id"])["messages"] == old_history["messages"]
    assert not service.get(old["id"])["conversation_current"]
    assert service.conversation_for_project("other")["conversation"] == foreign_history
    assert context["project"] == original
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert restored.conversation_for_project(original["id"])["conversation"]["id"] == fresh["id"]
    assert restored.get(old["id"])["messages"] == old_history["messages"]
    # Even a late historical update cannot win the current conversation query.
    restored.conversations[old["conversation_id"]]["updated_at"] = 1e20
    assert restored.conversation_for_project(original["id"])["conversation"]["id"] == fresh["id"]
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


def test_restart_retry_is_idempotent_after_backend_reload_and_stale_tabs_cannot_resume(setup):
    service, state = setup
    old, context = stopped_check(service)
    first = service.restart_conversation(context["project"]["id"], "retry", old["conversation_id"])
    with pytest.raises(ValueError, match="conversation_restarted"):
        service.create(context, "舊接線問題", purpose="wiring_review", request_id="old")
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert restored.restart_conversation(context["project"]["id"], "retry", old["conversation_id"]) == first
    with pytest.raises(ValueError, match="conversation_restarted"):
        restored.create(context, "舊頁面", purpose="wiring_review", conversation_id=old["conversation_id"])
    with pytest.raises(ValueError, match="conversation_restarted"):
        restored.restart_conversation(context["project"]["id"], "stale", old["conversation_id"])
    # Existing startup intentionally forgets create-request receipts. A retry
    # without an explicit conversation ID must still bind to the fresh round.
    next_check = restored.create(context, "新接線問題", purpose="wiring_review", request_id="old")
    assert next_check["conversation_id"] == first["conversation"]["id"]
    assert [m["text"] for m in next_check["messages"]] == ["新接線問題"]
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


@pytest.mark.parametrize("blocker", ["own", "foreign", "queued", "reserved", "program"])
def test_restart_refuses_unstopped_work_and_preserves_history(setup, blocker):
    service, state = setup
    old, context = stopped_check(service)
    if blocker in {"own", "foreign"}:
        live = deepcopy(context)
        if blocker == "foreign":
            live["project"]["id"] = "other"
        service.create(live, "待處理", purpose="wiring_review", request_id="live")
    elif blocker == "queued":
        state.pi_execution.jobs.append(dict(id="external", state="queued"))
    elif blocker == "reserved":
        state.component_tests.runs.append(dict(project_id=context["project"]["id"], reserved=True))
    else:
        state.pi_deployer.snapshot = lambda: dict(program="running")
    before = service.conversation(old["conversation_id"])
    unchanged = deepcopy(service.conversations)
    with pytest.raises(ValueError, match="ai_stop_unconfirmed|other_debug_active|hardware_work_active"):
        service.restart_conversation(context["project"]["id"], "restart")
    assert service.conversations == unchanged
    assert service.conversation(old["conversation_id"]) == before
    assert not state.design_service.bridge.calls


def test_restart_api_validates_binding_and_does_not_clear_foreign_round(setup):
    service, state = setup
    old, context = stopped_check(service)
    app = FastAPI()
    app.state.debug_sessions, app.state.pi_deployer = service, state.pi_deployer
    app.include_router(router)
    client = TestClient(app)
    route = "/api/debug/conversations/restart"
    assert client.post(route, json={"project_id": "", "request_id": "r"}).status_code == 422
    body = dict(project_id=context["project"]["id"], request_id="r", expected_conversation_id=old["conversation_id"])
    response = client.post(route, json=body)
    assert response.status_code == 200
    assert client.post(route, json=body).json() == response.json()
    assert client.post(route, json={**body, "project_id": "other"}).status_code == 409
    fresh = client.get("/api/debug/conversations", params={"project_id": body["project_id"]}).json()["conversation"]
    assert fresh["id"] == response.json()["conversation"]["id"] and fresh["messages"] == []
    assert client.get(f"/api/debug/conversations/{old['conversation_id']}").json()["messages"]
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


def migrated_check(setup):
    service, state = setup
    context = _context()
    old = service.create(context, "Wi-Fi 接線檢查", purpose="wiring_review", request_id="wifi")
    # The connection target includes the SSH host, so switching to the direct
    # Ethernet IP changes it even when the physical Pi is unchanged.
    state.component_tests.target = "wired-pi-target"
    state.pi_deployer.snapshot = lambda: dict(program="stopped", connected=True)
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert restored.active()["active"] is None
    assert restored.get(old["id"])["phase"] == "backend_restarted"
    return restored, state, old, context


def test_restart_after_ssh_address_change_archives_read_only_history_without_stopping_hardware(setup):
    service, state, old, context = migrated_check(setup)
    history = service.conversation(old["conversation_id"])
    session_before = deepcopy(service.sessions[old["id"]])
    app = FastAPI()
    app.state.debug_sessions, app.state.pi_deployer = service, state.pi_deployer
    app.include_router(router)
    client = TestClient(app)
    body = dict(project_id=context["project"]["id"], request_id="wired-restart",
                expected_conversation_id=old["conversation_id"])
    response = client.post("/api/debug/conversations/restart", json=body)
    assert response.status_code == 200, response.text
    fresh = response.json()["conversation"]
    assert fresh["id"] != old["conversation_id"] and fresh["messages"] == fresh["check_ids"] == []
    assert service.conversation(old["conversation_id"])["messages"] == history["messages"]
    # Do not claim a previous target's hardware has stopped or mutate its check.
    assert service.sessions[old["id"]] == session_before
    assert not service.get(old["id"])["conversation_current"]
    assert client.post("/api/debug/conversations/restart", json=body).json() == response.json()
    assert not state.component_tests.actions and not state.pi_execution.jobs
    assert not state.design_service.bridge.calls


@pytest.mark.parametrize("blocker", ["queued", "reserved_test", "reserved_trial", "running", "unknown_pid", "busy"])
def test_migrated_history_never_bypasses_current_hardware_checks(setup, blocker):
    service, state, old, context = migrated_check(setup)
    if blocker == "queued":
        state.pi_execution.jobs.append(dict(id="external", state="queued"))
    elif blocker in {"reserved_test", "reserved_trial"}:
        runner = state.component_tests if blocker == "reserved_test" else state.integration_trials
        runner.runs.append(dict(project_id=context["project"]["id"], reserved=True))
    else:
        status = {"running": dict(program="running"), "unknown_pid": dict(program="unknown", pid=12),
                  "busy": dict(program="stopped", busy=True)}[blocker]
        state.pi_deployer.snapshot = lambda: status
    before = deepcopy(service.conversations)
    with pytest.raises(ValueError, match="hardware_work_active"):
        service.restart_conversation(context["project"]["id"], "blocked-restart", old["conversation_id"])
    assert service.conversations == before
    assert not state.component_tests.actions and not state.design_service.bridge.calls


@pytest.mark.parametrize("variant", ["same_target", "live", "different_pause", "has_context"])
def test_only_restored_read_only_checks_on_previous_targets_can_be_archived(setup, variant):
    service, state, old, context = migrated_check(setup)
    session = service.sessions[old["id"]]
    if variant == "same_target":
        session["binding"]["target_id"] = state.component_tests.target
    elif variant == "live":
        session.update(status="awaiting_capture", phase="capture_needed")
    elif variant == "different_pause":
        session["phase"] = "waiting_for_stop"
    else:
        session["context"] = context
    before = deepcopy(service.conversations)
    with pytest.raises(ValueError, match="ai_stop_unconfirmed"):
        service.restart_conversation(context["project"]["id"], "blocked-restart", old["conversation_id"])
    assert service.conversations == before
