"""Polling must not repeatedly walk historical drawings or freeze live gates."""
from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.debug_sessions import router
from app.debug_sessions import DebugSessions
from test_debug_sessions import setup, _context
from test_assistant import service


def seeded(setup):
    owner, state = setup
    first = owner.create(_context(), "inspect", request_id="poll")
    sid = first["id"]
    conversation = owner.conversations[first["conversation_id"]]
    conversation["messages"] = [dict(id="message", role="assistant", text="password=private")]
    conversation["diagrams"] = [dict(id="drawing", design={"nested": [1, 2, 3]})]
    owner._save()
    return owner, state, sid, conversation


class UnreadHistory(list):
    def __iter__(self):
        raise AssertionError("unchanged polling traversed history")

    def __deepcopy__(self, memo):
        raise AssertionError("unchanged polling copied history")


def test_unchanged_session_skips_history_but_keeps_live_target_gate(setup):
    owner, state, sid, conversation = seeded(setup)
    full = owner.get(sid)
    conversation["messages"] = conversation["diagrams"] = UnreadHistory()
    owner.sessions[sid]["messages"] = UnreadHistory()
    owner.sessions[sid]["context"] = {"large_internal_request": UnreadHistory()}
    state.component_tests.target = "different-pi"
    compact = owner.get(sid, full["history_version"])
    assert compact["history_unchanged"] is True
    assert "messages" not in compact and "diagrams" not in compact
    assert compact["current_target"] is False
    assert compact["camera_current"] is True


def test_unchanged_conversation_does_not_copy_any_history(setup):
    owner, _, _, conversation = seeded(setup)
    full = owner.conversation(conversation["id"])
    conversation["messages"] = conversation["diagrams"] = UnreadHistory()
    result = owner.conversation_for_project(conversation["project_id"], full["history_version"])
    assert result["conversation"]["history_unchanged"] is True
    assert "messages" not in result["conversation"]


def test_message_and_diagram_mutations_invalidate_history_and_remain_redacted(setup):
    owner, _, sid, conversation = seeded(setup)
    old = owner.get(sid)
    assert "private" not in str(old["messages"])
    owner._add_message(owner.sessions[sid], dict(id="new", role="assistant", text="hello"))
    conversation["diagrams"].append(dict(id="second", design={"password": "hidden"}))
    owner._save()
    new = owner.get(sid, old["history_version"])
    assert new["history_version"] != old["history_version"]
    assert new["messages"][-1]["id"] == "new"
    assert new["diagrams"][-1]["design"]["password"] == "[REDACTED]"
    new["diagrams"][0]["design"]["nested"].append(99)
    assert conversation["diagrams"][0]["design"]["nested"] == [1, 2, 3]


def test_password_change_forces_fresh_redaction(setup):
    owner, state, sid, conversation = seeded(setup)
    conversation["messages"].append(dict(id="secret", role="assistant", text="new-credential"))
    owner._save()
    old = owner.get(sid)
    state.pi_deployer.config.password = SimpleNamespace(get_secret_value=lambda: "new-credential")
    new = owner.get(sid, old["history_version"])
    assert not new.get("history_unchanged")
    assert new["messages"][-1]["text"] == "[REDACTED]"


def test_restart_and_other_conversation_cannot_reuse_old_version(setup):
    owner, state, sid, conversation = seeded(setup)
    old = owner.get(sid)
    restarted = DebugSessions(state, owner.store, autostart=False)
    result = restarted.get(sid, old["history_version"])
    assert not result.get("history_unchanged") and result["messages"]
    other = owner._ensure_conversation("another-project")
    first = owner.conversation(conversation["id"])
    assert not owner.conversation(other["id"], first["history_version"]).get("history_unchanged")


def test_api_full_then_compact_and_legacy_reads(setup):
    owner, _, sid, conversation = seeded(setup)
    app = FastAPI()
    app.state.debug_sessions = owner
    app.include_router(router)
    with TestClient(app) as client:
        for path, key in [(f"/api/debug/sessions/{sid}", None), ("/api/debug/sessions", "active"),
                          (f"/api/debug/conversations?project_id={conversation['project_id']}", "conversation")]:
            response = client.get(path)
            assert response.headers["cache-control"] == "no-store"
            full = response.json()
            full = full[key] if key else full
            result = client.get(path, params={"history_version": full["history_version"],
                **({"project_id": conversation["project_id"]} if key == "conversation" else {})}).json()
            result = result[key] if key else result
            assert result["history_unchanged"] and "messages" not in result
            legacy = client.get(path).json()
            assert "messages" in (legacy[key] if key else legacy)


def test_assistant_read_retains_pagination_and_output_isolation(service):
    service.create("poll-chat")
    record = service._load("poll-chat")
    record["messages"] = [dict(id=str(i), text="text", role="user", payload={"items": [i]}) for i in range(80)]
    service._save(record)
    result = service.read("poll-chat", limit=5)
    assert result["total"] == 80 and result["before"] == 75 and len(result["messages"]) == 5
    result["messages"][0]["payload"]["items"].append(999)
    assert service._load("poll-chat")["messages"][75]["payload"]["items"] == [75]


def test_mobile_links_do_not_copy_large_history_or_include_cleared_owners(service):
    service.create("links")
    record = service.records["links"]
    record.update(context_epoch=2, cleared_debug_sessions=["cleared"],
        messages=[dict(epoch=2, session_id="current", payload=UnreadHistory()),
                  dict(epoch=1, session_id="old"), dict(epoch=2, session_id="archived", archived=True),
                  dict(epoch=2, session_id="cleared")],
        jobs=[dict(epoch=2, debug_session_id="job"), dict(epoch=1, debug_session_id="old-job")])
    assert service.debug_session_links("links") == {"current", "job"}
