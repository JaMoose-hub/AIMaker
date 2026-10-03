"""All generations use fakes and tmp_path; no Codex, camera, SSH or Pi calls."""
import json
import threading
import time
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.assistant import AssistantService, Checklist, SendRequest, builtin_checklist
from app.api.assistant import router
from app.api.design import DesignService
from app.designs import GenerateRequest, demo_design, DesignProposal
from app.project_images import ProjectImageStore


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.reply = {"answer": "Text planning only", "checklist": builtin_checklist("en")}
        self.gate = None

    def generate(self, prompt, schema, **options):
        self.calls.append((prompt, schema, options))
        if self.gate:
            assert self.gate.wait(3)
        if isinstance(self.reply, Exception):
            raise self.reply
        return deepcopy(self.reply)


class FakeDesigns:
    def __init__(self):
        self.bridge = FakeBridge()
        self.calls, self.jobs, self.retry_calls = [], {}, []

    def submit(self, request):
        # Ensure the real prompt builder accepts nested, validated history.
        from app.design_prompt import build_design_prompt
        build_design_prompt(request)
        self.calls.append(request)
        jid = f"design-{len(self.calls)}"
        self.jobs[jid] = {"id": jid, "status": "generating", "design": None}
        return {"job_id": jid}

    def get(self, jid):
        return deepcopy(self.jobs[jid])

    def retry_image(self, jid):
        self.retry_calls.append(jid)
        retry = "retry-" + jid
        self.jobs[retry] = {"id": retry, "status": "generating", "design": None}
        return {"job_id": retry}


@pytest.fixture
def service(tmp_path):
    return AssistantService(SimpleNamespace(design_service=FakeDesigns()), tmp_path)


def body(**changes):
    data = dict(request_id="request-1", text="Please help", stage="design", design=GenerateRequest(
        prompt="Please help", component_ids=["hc-sr04", "mrd-tf240-8p-cs"], locale="en", model="fake", effort="low"))
    data.update(changes)
    return SendRequest(**data)


def settled(service, cid):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        record = service.read(cid)
        if not any(j["status"] == "running" and not j.get("design_job_id") for j in record["jobs"]):
            return record
        time.sleep(.005)
    pytest.fail("Fake job did not settle")


def test_builtin_demo_is_isolated_and_never_calls_ai(service):
    main = service.create("main", project_id="real-project")
    demo = service.create("demo", "demo", "en")
    assert all(m["source"] == "demo" and m["created_at"] is None for m in demo["messages"])
    confirmed = service.confirm("demo", 1, "builtin", "confirm")
    assert confirmed["demo"]["state"] == "result_pending"
    assert confirmed["demo"]["result"]["source"] == "demo"
    assert confirmed["demo"]["result"]["component_ids"] == ["hc-sr04", "mrd-tf240-8p-cs"]
    assert service.read("main") == main
    assert service.state.design_service.calls == []
    assert service.state.design_service.bridge.calls == []
    assert service.confirm("demo", 1, "builtin", "confirm")["jobs"] == confirmed["jobs"]


def test_text_discussion_only_plans_and_invalidates_confirmation(service):
    service.create("demo", "demo", "en")
    original = service.confirm("demo", 1, "builtin", "confirm")["demo"]["result"]
    service.state.design_service.bridge.reply["checklist"]["requirements"][2] = "Warn below 15 cm"
    service.send("demo", body(stage="guide"))
    result = settled(service, "demo")
    assert result["demo"]["revision"] == 2
    assert result["demo"]["confirmed_revision"] is None
    assert result["demo"]["result"] == original  # retained but not a new result
    assert not service.state.design_service.calls
    assert service.state.design_service.bridge.calls[0][2]["restricted_tools"] is True
    with pytest.raises(HTTPException) as error:
        service.confirm("demo", 2, "builtin", "second-confirm")
    assert error.value.status_code == 409
    restored = service.restore_checklist("demo")
    assert restored["demo"]["revision"] == 3
    service.confirm("demo", 3, "builtin", "restored")
    assert len(service.state.design_service.bridge.calls) == 1


def test_catalog_rejects_unsupported_electronics_and_structural_motor():
    checklist = builtin_checklist("en")
    for patch in ({"component_ids": ["motor"]}, {"component_ids": ["hc-sr04", "hc-sr04"]},
                  {"structure": [{"kind": "motor", "quantity": 1, "purpose": "drive"}]}):
        with pytest.raises(ValidationError):
            Checklist.model_validate({**checklist, **patch})


def test_confirm_freezes_revision_before_true_generation(service):
    service.create("demo", "demo", "en")
    result = service.confirm("demo", 1, "ai", "generate", body().design)
    frozen = deepcopy(result["jobs"][0]["checklist"])
    assert result["demo"]["state"] == "generating"
    assert service.state.design_service.calls[0].generate_image
    assert service.state.design_service.calls[0].current is None
    assert len(service.state.design_service.calls) == 1
    service.confirm("demo", 1, "ai", "generate", body().design)
    assert len(service.state.design_service.calls) == 1
    with pytest.raises(HTTPException):
        service.restore_checklist("demo")
    assert service.read("demo")["jobs"][0]["checklist"] == frozen
    design = demo_design()
    design["source"] = "ai"
    service.state.design_service.jobs["design-1"].update(status="completed", design=design)
    completed = service.read("demo")
    assert completed["demo"]["result_source"] == "ai"
    assert completed["demo"]["result"] == design
    assert completed["jobs"][0]["usage"] is None


def test_persists_work_id_before_model_and_deduplicates_retry(service):
    service.create("demo", "demo", "en")
    gate = service.state.design_service.bridge.gate = threading.Event()
    first = service.send("demo", body())
    disk = json.loads((service.root / "demo.json").read_text(encoding="utf-8"))
    assert disk["jobs"][0]["id"] == first["jobs"][0]["id"]
    service.send("demo", body())
    assert len(service.read("demo")["jobs"]) == 1
    with pytest.raises(HTTPException):
        service.send("demo", body(text="different"))
    gate.set()
    settled(service, "demo")
    assert len(service.state.design_service.bridge.calls) == 1


def test_storage_failure_makes_no_model_or_design_call(service, monkeypatch):
    service.create("demo", "demo", "en")
    def fail(record):
        raise OSError("disk full")
    monkeypatch.setattr(service, "_save", fail)
    with pytest.raises(OSError):
        service.send("demo", body())
    assert not service.state.design_service.bridge.calls
    assert not service.state.design_service.calls


def test_restart_keeps_unknown_jobs_and_never_replays(service):
    service.create("main")
    record = service._load("main")
    record["jobs"].append(dict(id="unknown", request_id="old", status="running"))
    service._save(record)
    restarted = AssistantService(service.state, service.root)
    assert restarted.read("main")["jobs"][0]["status"] == "unknown"
    assert not service.state.design_service.calls


def test_generation_recovers_by_id_on_refresh(service):
    service.create("main")
    service.send("main", body())
    settled(service, "main")
    restarted = AssistantService(service.state, service.root)
    assert restarted.read("main")["jobs"][0]["design_job_id"] == "design-1"
    service.state.design_service.jobs["design-1"].update(status="completed", answer="done")
    assert restarted.read("main")["messages"][-1]["text"] == "done"
    assert len(restarted.read("main")["messages"]) == 2
    assert len(service.state.design_service.calls) == 1


def test_migration_backs_up_and_deduplicates_without_inventing_times(service):
    service.create("main")
    messages = [dict(role="user", text="before"), dict(role="assistant", text="reply")]
    service.import_messages("main", "legacy", messages)
    service.import_messages("main", "legacy", messages)
    result = service.read("main")
    assert len(result["messages"]) == 2
    assert all(m["created_at"] is None for m in result["messages"])
    assert [m["text"] for m in result["messages"]] == ["before", "reply"]
    assert len(list((service.root / "imports").glob("*.json"))) == 1


def test_pagination_and_bounded_model_history(service):
    service.create("main")
    service.import_messages("main", "many", [dict(role="user", text=str(i)) for i in range(140)])
    last = service.read("main", limit=30)
    assert last["before"] == 110 and last["messages"][0]["text"] == "110"
    assert service.read("main", before=110, limit=30)["messages"][-1]["text"] == "109"
    assert len(service._recent(service._load("main"))) == 20
    service.send("main", body())
    settled(service, "main")
    assert len(service.state.design_service.calls[0].conversation) == 20


def test_clear_and_wiring_archive_do_not_delete_raw_records(service):
    service.create("main")
    service.import_messages("main", "design", [dict(role="user", text="design")])
    service.import_messages("main", "debug", [dict(role="assistant", text="test old", round=1)], "legacy-debug")
    result = service.reset_context("main", "wiring", 2)
    assert result["messages"][1]["archived"]
    assert not result["messages"][0].get("archived")
    cleared = service.reset_context("main", "clear")
    assert len(cleared["messages"]) == 2
    assert service._recent(service._load("main")) == []


def test_cross_stage_routes_design_once_without_applying_it(service):
    service.create("main")
    service.state.design_service.bridge.reply = {"capability": "design", "answer": "New appearance"}
    service.send("main", body(stage="guide"))
    result = settled(service, "main")
    assert len(service.state.design_service.bridge.calls) == 1
    assert len(service.state.design_service.calls) == 1
    assert result["jobs"][0]["stage"] == "guide"
    assert result["jobs"][0]["capability"] == "design"
    assert result["project_id"] is None


def test_direct_answer_does_not_start_another_capability(service):
    service.create("main")
    service.state.design_service.bridge.reply = {"capability": "answer", "answer": "English answer"}
    service.send("main", body(stage="deploy"))
    result = settled(service, "main")
    assert result["messages"][-1]["text"] == "English answer"
    assert service.state.design_service.bridge.calls[0][0].startswith("Reply entirely in English")
    assert not service.state.design_service.calls


def test_failed_planning_preserves_previous_checklist(service):
    before = service.create("demo", "demo", "en")["demo"]["checklist"]
    service.state.design_service.bridge.reply = RuntimeError("fake unavailable")
    service.send("demo", body())
    result = settled(service, "demo")
    assert result["jobs"][0]["status"] == "failed"
    assert result["demo"]["checklist"] == before
    assert result["demo"]["confirmed_revision"] is None


def test_image_only_retry_is_idempotent_and_keeps_canonical_demo(service):
    service.create("demo", "demo", "en")
    service.confirm("demo", 1, "ai", "generate", body().design)
    design = demo_design(); design.update(source="ai", image_error="fake image failure")
    service.state.design_service.jobs["design-1"].update(status="completed", design=design)
    job = service.read("demo")["jobs"][0]
    service.retry_image("demo", job["id"], "retry")
    service.retry_image("demo", job["id"], "retry")
    assert service.state.design_service.retry_calls == ["design-1"]
    assert service.read("demo")["demo"]["builtin_fingerprint"]


def test_api_errors_and_identity_guards(service):
    app = FastAPI(); app.state.assistant = service; app.include_router(router)
    client = TestClient(app)
    assert client.post("/api/assistant/conversations", json={"id": "main"}).status_code == 200
    assert client.post("/api/assistant/conversations", json={"id": "main", "kind": "demo"}).status_code == 409
    assert client.post("/api/assistant/conversations", json={"id": "../escape"}).status_code == 422
    assert client.get("/api/assistant/conversations/main?before=-1").status_code == 422


def test_actual_context_replaces_client_claims_and_keeps_full_code(service):
    from pydantic import SecretStr
    pi = SimpleNamespace(snapshot=lambda: {"connected": False, "program": "unknown", "logs": ["password=secret"] * 90, "password": "secret"},
                         config=SimpleNamespace(password=SecretStr("secret")))
    service.state.pi_deployer = pi
    service.state.component_tests = SimpleNamespace(snapshot=lambda project_id: {"active": None, "results": [dict(project_id=project_id)] * 10})
    code = "# manual draft\n" * 2000
    context = service._context(body(context={"pi": {"program": "running"}, "debug_context": {"code": code}}))
    assert context["pi"]["program"] == "unknown"
    assert len(context["pi"]["logs"]) == 60
    assert "secret" not in json.dumps(context)
    assert context["code"] == code and len(context["tests"]["results"]) == 4


def test_stable_conversation_can_discuss_candidate_without_rebinding_confirmed_project(service):
    service.create("main", project_id="confirmed")
    request = body(context={"workspace_project_id": "confirmed"})
    request.design.current = {"id": "candidate", "revision": 2}
    service.send("main", request)
    result = settled(service, "main")
    assert result["project_id"] == "confirmed"
    assert result["jobs"][0]["version"] == {"project_id": "candidate", "revision": 2}


def test_round_reset_archives_both_sides_of_runtime_advice_not_cross_stage_design(service):
    service.create("main")
    service.state.design_service.bridge.reply = {"capability": "answer", "answer": "Runtime advice"}
    service.send("main", body(stage="deploy"))
    settled(service, "main")
    result = service.reset_context("main", "wiring", 1)
    assert len(result["messages"]) == 2 and all(message.get("archived") for message in result["messages"])


def test_demo_generation_uses_current_language_after_switch(service):
    service.create("demo", "demo", "zh-TW")
    service.confirm("demo", 1, "ai", "generate-en", body().design)
    assert service.state.design_service.calls[0].locale == "en"


def test_existing_debug_continues_text_only_and_never_finishes_before_dispatch(service):
    service.create("main", project_id="project")
    started, release = threading.Event(), threading.Event()
    calls = []
    def action(sid, action_name, request_id, **options):
        calls.append((sid, action_name, request_id, options))
        started.set(); assert release.wait(3)
    service.state.debug_sessions = SimpleNamespace(get=lambda sid: {
        "binding": {"project_id": "project"}, "phase": "awaiting_user", "model_busy": False}, action=action)
    request = body(stage="deploy", target="debug", context={"debug_session_id":"check", "debug_context":{"code":"# full draft\n" * 2000}})
    request.design.current = {"id":"project", "revision":1}
    service.send("main", request); assert started.wait(2)
    assert service.read("main")["jobs"][0]["status"] == "running"
    release.set(); settled(service,"main")
    assert service.read("main")["jobs"][0]["status"] == "completed"
    assert calls[0][1] == "message" and len(calls[0][3]["context"]["code"]) > 16000
    assert not service.state.design_service.calls and not service.state.design_service.bridge.calls
    cleared = service.reset_context("main", "clear")
    assert cleared["cleared_debug_sessions"] == ["check"]
    followup = request.model_copy(update={"request_id":"after-clear"})
    service.send("main", followup); settled(service, "main")
    assert len(calls) == 1  # old text context is not revived
    assert service.state.design_service.calls[-1].intent == "ask"
