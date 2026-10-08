"""Workflow Reset closes only idle photo history; fake API, hardware and cloud."""
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.debug_sessions import router
from test_debug_sessions import setup, _context


def idle_review(setup):
    service, state = setup
    context = _context()
    record = service.create(context, "Synthetic photo check", request_id="create-idle",
                            purpose="wiring_review", initial_action="collect")
    def no_hardware(*args, **kwargs):
        pytest.fail("Retiring an idle review must not stop/cancel hardware")
    state.pi_execution.action = state.component_tests.action = state.integration_trials.action = no_hardware
    app = FastAPI()
    app.state.debug_sessions, app.state.pi_deployer = service, state.pi_deployer
    app.include_router(router)
    return service, state, record["id"], app


@pytest.mark.parametrize("status", ["awaiting_capture", "paused"])
def test_reset_retires_idle_review_idempotently_without_hardware_or_model_calls(setup, status):
    service, state, sid, app = idle_review(setup)
    service.sessions[sid]["status"] = status
    context = deepcopy(service.sessions[sid]["context"])
    history = deepcopy(service.conversation(service.sessions[sid]["conversation_id"]))
    body = dict(action="stop_idle_wiring_review", request_id="confirmed-reset")
    with TestClient(app) as client:
        first = client.post(f"/api/debug/sessions/{sid}/actions", json=body)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "stopped"
        step = first.json()["step_rev"]
        again = client.post(f"/api/debug/sessions/{sid}/actions", json=body)
        assert again.status_code == 200 and again.json()["step_rev"] == step
    assert service.active()["active"] is None
    assert service.sessions[sid]["context"] == context
    assert service.conversation(history["id"])["messages"] == history["messages"]
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


@pytest.mark.parametrize("busy", ["model", "capture", "debug", "queued", "reserved", "program", "pending_action"])
def test_reset_rechecks_raced_busy_state_without_stopping_it(setup, busy):
    service, state, sid, app = idle_review(setup)
    session = service.sessions[sid]
    if busy == "model":
        session["phase"] = "wiring_review_analysing"
    elif busy == "capture":
        session["capture_pending"] = True
    elif busy == "debug":
        session["purpose"] = "debug"
    elif busy == "queued":
        state.pi_execution.jobs.append(dict(id="other-job", state="queued"))
    elif busy == "reserved":
        state.component_tests.runs.append(dict(id="other-test", project_id="other-project", reserved=True))
    elif busy == "program":
        state.pi_deployer.snapshot = lambda: dict(program="running", busy=False, pid=123)
    else:
        session["receipts"]["other-request"] = dict(signature="not-needed", state="pending")
    before = (session["status"], session["phase"], session["step_rev"])
    with TestClient(app) as client:
        response = client.post(f"/api/debug/sessions/{sid}/actions",
                               json=dict(action="stop_idle_wiring_review", request_id="confirmed-reset"))
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == ("hardware_work_active" if busy in {"queued", "reserved", "program"} else "other_debug_active")
    assert (session["status"], session["phase"], session["step_rev"]) == before
    assert "confirmed-reset" not in session["receipts"]
    assert not state.design_service.bridge.calls
