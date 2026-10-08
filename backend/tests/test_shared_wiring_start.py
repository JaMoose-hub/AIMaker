"""Direct photo-guidance entry uses fake services; no camera, cloud or Pi work."""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.assistant import AssistantService
from test_debug_sessions import _context
from test_shared_test_help import fixture


def request_payload(**changes):
    return {"request_id": "direct-start-1", "context_epoch": 0, "context": _context(),
            "component_id": "hc-sr04", "model": "fake", "effort": "low", "response_mode": "fast", **changes}


def post(client, payload):
    return client.post("/api/assistant/conversations/shared-conversation/wiring-review/start", json=payload)


def test_direct_entry_creates_the_current_shared_photo_question_without_work(tmp_path):
    app, state, *_ = fixture(tmp_path)
    # A confirmed project may reach the photo entry before its first chat message.
    record = state.assistant._load("shared-conversation")
    record["project_id"] = None
    state.assistant._save(record)
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        response = post(client, request_payload())
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["resumed"] is False
    assert result["debug_session_id"] == result["debug_session"]["id"]
    assert result["debug_session"]["purpose"] == "wiring_review"
    assert result["debug_session"]["wiring_review"]["status"] == "collecting"
    assert result["debug_session"]["evidence"] == []
    assert result["conversation"]["id"] == "shared-conversation"
    assert result["conversation"]["project_id"] == request_payload()["context"]["project"]["id"]
    current = [m for m in result["conversation"]["messages"] if m.get("wiring_flow", {}).get("current")]
    assert len(current) == 1 and current[0]["wiring_flow"]["role"] == "pi_side_a"
    assert current[0]["wiring_flow"]["can_act"]
    assert not any(m.get("test_help_offer") for m in result["conversation"]["messages"])
    assert "wiring_review_starts" not in result["conversation"]
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs and not state.component_tests.actions


def test_retry_after_assistant_reload_reuses_one_session_and_one_question(tmp_path):
    app, state, *_ = fixture(tmp_path)
    payload = request_payload()
    first = state.assistant.start_wiring_review("shared-conversation", payload)
    before = deepcopy(state.debug_sessions.sessions[first["debug_session_id"]]["wiring_review"])
    state.assistant = AssistantService(state, tmp_path / "assistant")
    retry = state.assistant.start_wiring_review("shared-conversation", payload)
    assert retry["debug_session_id"] == first["debug_session_id"] and retry["resumed"] is False
    assert retry["conversation"]["total"] == first["conversation"]["total"]
    assert len(state.debug_sessions.sessions) == 1
    assert state.debug_sessions.sessions[first["debug_session_id"]]["wiring_review"] == before
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_new_explicit_resume_preserves_the_review_and_other_component_history(tmp_path):
    app, state, *_ = fixture(tmp_path)
    payload = request_payload()
    first = state.assistant.start_wiring_review("shared-conversation", payload)
    session = state.debug_sessions.sessions[first["debug_session_id"]]
    session["wiring_review_components"] = {"mrd-tf240-8p-cs": {"retained": "other component"}}
    session["wiring_review"]["reviews"]["retained"] = dict(decision="unsure", source="human")
    before = deepcopy(session["wiring_review"])
    resumed = state.assistant.start_wiring_review("shared-conversation", {**payload, "request_id": "resume-2"})
    assert resumed["resumed"] is True and resumed["debug_session_id"] == session["id"]
    assert session["wiring_review"] == before
    assert session["wiring_review_components"] == {"mrd-tf240-8p-cs": {"retained": "other component"}}
    assert resumed["conversation"]["total"] == first["conversation"]["total"]


def test_other_component_or_functional_case_is_never_superseded(tmp_path):
    for kind in ("component", "functional"):
        app, state, *_ = fixture(tmp_path / kind)
        payload = request_payload()
        if kind == "component":
            first = state.assistant.start_wiring_review("shared-conversation", payload)
            attempted = {**payload, "request_id": "different-component", "component_id": "mrd-tf240-8p-cs"}
        else:
            first = state.debug_sessions.create(_context(), "existing functional case", request_id="functional")
            attempted = payload
        session = state.debug_sessions.sessions[first.get("debug_session_id", first.get("id"))]
        before = deepcopy(session)
        with pytest.raises(HTTPException, match="wiring_review_session_active"):
            state.assistant.start_wiring_review("shared-conversation", attempted)
        assert session == before and len(state.debug_sessions.sessions) == 1
        assert not state.pi_execution.jobs and not state.design_service.bridge.calls


def test_stale_epoch_workspace_and_request_conflict_do_not_start_new_work(tmp_path):
    for mismatch in ("epoch", "code", "round", "revision", "request"):
        app, state, mobile, *_ = fixture(tmp_path / mismatch)
        payload = request_payload()
        if mismatch == "request":
            state.assistant.start_wiring_review("shared-conversation", payload)
            payload = {**payload, "response_mode": "thorough"}
            expected = "request_id_conflict"
        else:
            expected = "wiring_review_context_changed"
            if mismatch == "epoch": payload["context_epoch"] += 1
            if mismatch == "code": payload["context"]["code"] += "\n# stale edit"
            if mismatch == "round": payload["context"]["guide_run"] += 1
            if mismatch == "revision": payload["context"]["project"]["revision"] += 1
        before = deepcopy(state.debug_sessions.sessions)
        with pytest.raises(HTTPException, match=expected):
            state.assistant.start_wiring_review("shared-conversation", payload)
        assert state.debug_sessions.sessions == before
        assert not state.pi_execution.jobs and not state.design_service.bridge.calls


def test_pi_queue_and_reserved_remote_run_block_collection_without_cancel(tmp_path):
    for work in ("queue", "remote"):
        app, state, *_ = fixture(tmp_path / work)
        if work == "queue": state.pi_execution.jobs.append(dict(id="other-job", state="queued"))
        else: state.component_tests.runs[0]["reserved"] = True
        before = deepcopy(state.pi_execution.jobs), deepcopy(state.component_tests.runs)
        with pytest.raises(HTTPException, match="pi_busy_for_wiring"):
            state.assistant.start_wiring_review("shared-conversation", request_payload())
        assert not state.debug_sessions.sessions
        assert (state.pi_execution.jobs, state.component_tests.runs) == before
        assert not state.component_tests.actions and not state.design_service.bridge.calls


def test_parallel_start_requests_share_one_authoritative_photo_flow(tmp_path):
    app, state, *_ = fixture(tmp_path)
    payload = request_payload()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: state.assistant.start_wiring_review("shared-conversation", item),
                                (payload, {**payload, "request_id": "second-browser"})))
    assert len({result["debug_session_id"] for result in results}) == 1
    assert len(state.debug_sessions.sessions) == 1
    messages = state.assistant.read("shared-conversation")["messages"]
    assert len([m for m in messages if m.get("wiring_flow", {}).get("kind") == "photo_request"]) == 1
    assert not state.pi_execution.jobs and not state.design_service.bridge.calls


@pytest.mark.parametrize("slow_phase", ["create", "save"])
def test_slow_review_start_does_not_hold_native_receive_lock(tmp_path, monkeypatch, slow_phase):
    _, state, mobile, phone, *_ = fixture(tmp_path)
    sid = phone["session_id"]
    generation = asyncio.run(mobile.start_stream(sid))["generation"]
    target, method = (state.debug_sessions, "create") if slow_phase == "create" else (state.assistant, "_save")
    original = getattr(target, method)
    entered, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method, delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(state.assistant.start_wiring_review, "shared-conversation", request_payload())
        received_while_busy = False
        try:
            assert entered.wait(2)
            receipt = pool.submit(mobile.on_receive, sid, generation, 20,
                                  mobile.clock(), mobile.wall(), (1920, 1080))
            try:
                receipt.result(timeout=.3)
                received_while_busy = True
            except TimeoutError:
                pass
        finally:
            release.set()
        start.result(timeout=2)
        receipt.result(timeout=2)
    assert received_while_busy, "slow review workflow blocked native phone reception"
    stream = mobile.snapshot(sid)["stream"]
    assert stream["active"] and stream["generation"] == generation and stream["received_frames"] == 20
    assert not mobile.rtc.closed and not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_review_start_serializes_workspace_commits_without_serializing_receipts(tmp_path, monkeypatch):
    _, state, mobile, phone, published, _ = fixture(tmp_path)
    sid = phone["session_id"]
    generation = asyncio.run(mobile.start_stream(sid))["generation"]
    original = state.debug_sessions.create
    entered, release = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(*args, **kwargs)

    monkeypatch.setattr(state.debug_sessions, "create", delayed)
    changed = deepcopy(published)
    changed["context"]["debug_context"]["code"] += "\n# next workspace revision"
    with ThreadPoolExecutor(max_workers=3) as pool:
        start = pool.submit(state.assistant.start_wiring_review, "shared-conversation", request_payload())
        try:
            assert entered.wait(2)
            publication = pool.submit(mobile.publish_context, changed)
            with pytest.raises(TimeoutError):
                publication.result(timeout=.1)
            receipt = pool.submit(mobile.on_receive, sid, generation, 21,
                                  mobile.clock(), mobile.wall(), (1920, 1080))
            receipt.result(timeout=.3)
        finally:
            release.set()
        started = start.result(timeout=2)
        committed = publication.result(timeout=2)
    assert started["debug_session_id"] in state.debug_sessions.sessions
    assert committed["context"]["debug_context"]["code"] == changed["context"]["debug_context"]["code"]
    assert mobile.snapshot(sid)["stream"]["received_frames"] == 21
    assert not mobile.rtc.closed and not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_cleared_or_stopped_review_requires_a_new_explicit_case(tmp_path):
    for change in ("clear", "stop"):
        app, state, *_ = fixture(tmp_path / change)
        payload = request_payload()
        first = state.assistant.start_wiring_review("shared-conversation", payload)
        if change == "clear":
            state.assistant.reset_context("shared-conversation", "clear")
            expected = "wiring_review_context_changed"
        else:
            state.debug_sessions.action(first["debug_session_id"], "stop", "explicit-stop")
            expected = "wiring_review_start_expired"
        before = deepcopy(state.debug_sessions.sessions)
        with pytest.raises(HTTPException, match=expected):
            state.assistant.start_wiring_review("shared-conversation", payload)
        assert state.debug_sessions.sessions == before
        assert not state.pi_execution.jobs and not state.design_service.bridge.calls
