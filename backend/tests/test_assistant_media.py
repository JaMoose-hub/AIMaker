"""Media requests use saved files and one durable AI job; no actual AI calls."""
from copy import deepcopy
import json
import threading
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from fastapi import HTTPException

from test_assistant import FakeDesigns, body, settled
from app.assistant import AssistantService


class Assets:
    def __init__(self, path):
        self.path = path
        self.resolved = []

    def describe(self, aid):
        return dict(id=aid, type="video" if aid == "video" else "image",
                    url=f"/api/mobile/assets/{aid}/file", width=160, height=100)

    def resolve_images(self, ids):
        self.resolved.append(list(ids))
        return [self.path], [dict(asset_id=ids[0], timestamp=2.5)]


@pytest.fixture
def media_service(tmp_path):
    image = tmp_path / "photo.jpg"
    assert cv2.imwrite(str(image), np.zeros((100, 160, 3), np.uint8))
    assets = Assets(image)
    capture = dict(capture_id="capture", asset_id="image", conversation_id="main", project_id="main",
        project_revision=1, image_sha256="saved-hash", video_size=[160, 100], frame_id=1,
        detection={"tracking": "searching", "pins": []}, components=[], localization=[], wires=[])
    state = SimpleNamespace(design_service=FakeDesigns(),
        mobile_service=SimpleNamespace(assets=assets, get_capture=lambda cid: deepcopy(capture)))
    state.design_service.bridge.reply = {"answer": "From the saved image."}
    service = AssistantService(state, tmp_path / "history")
    service.create("main")
    return service, capture


def test_media_retry_calls_ai_once_and_followup_inherits_explicit_reference(media_service):
    service, _ = media_service
    request = body(asset_ids=["image"], source="mobile")
    service.send("main", request)
    first = settled(service, "main")
    service.send("main", request)
    assert len(first["jobs"]) == len(service.read("main")["jobs"]) == 1
    assert first["messages"][0]["attachments"][0]["asset_id"] == "image"
    assert first["messages"][0]["source"] == "mobile"
    service.send("main", body(request_id="followup", text="What about this?"))
    followup = settled(service, "main")
    assert followup["messages"][-2]["attachments"][0]["asset_id"] == "image"
    calls = service.state.design_service.bridge.calls
    assert len(calls) == 2 and all(call[2]["image_paths"] for call in calls)
    assert not service.state.design_service.calls
    # A new attachment replaces the previous reference; it is not accumulated.
    service.send("main", body(request_id="new", asset_ids=["second"]))
    settled(service, "main")
    assert service.state.mobile_service.assets.resolved[-1] == ["second"]


def test_round_and_clear_remove_implicit_media_reference(media_service):
    service, _ = media_service
    service.send("main", body(asset_ids=["image"]))
    settled(service, "main")
    service.send("main", body(request_id="next", round=1, stage="guide", target="wiring"))
    settled(service, "main")
    assert service.state.mobile_service.assets.resolved == [["image"]]
    assert service.state.design_service.calls  # original desktop text request path
    service.state.design_service.jobs["design-1"].update(status="completed", design=None, answer="Text advice")
    service.read("main")
    service.reset_context("main", "clear")
    assert "active_media" not in service._load("main")


def test_video_cannot_be_mixed_with_images_and_no_job_is_enqueued(media_service):
    service, _ = media_service
    with pytest.raises(HTTPException) as error:
        service.send("main", body(asset_ids=["video", "image"]))
    assert error.value.status_code == 422
    assert service.read("main")["jobs"] == []
    assert service.state.design_service.bridge.calls == []


def test_cleared_context_does_not_rebind_an_old_capture(media_service):
    service, capture = media_service
    service.reset_context("main", "clear")
    assert not service.bind_photo_reference("main", capture, {"context_epoch":0, "round":0})
    assert "active_media" not in service._load("main")
    assert service.bind_photo_reference("main", capture, {"context_epoch":1, "round":2})
    reference = service.read("main")["active_media"]
    assert reference["round"] == 2 and reference["attachments"][0]["capture_id"] == "capture"


def test_explicit_no_media_snapshot_cannot_inherit_a_later_photo(media_service):
    service, _ = media_service
    service.send("main", body(asset_ids=["image"]))
    settled(service, "main")
    service.send("main", body(request_id="no-reference", stage="guide", target="wiring", inherit_media=False))
    result = settled(service, "main")
    assert result["jobs"][-1]["resolved_asset_ids"] == []
    assert "attachments" not in result["messages"][-1]
    assert service.state.mobile_service.assets.resolved == [["image"]]


@pytest.mark.parametrize("field,value", [("conversation_id", "other"), ("project_id", "other"), ("project_revision", 2)])
def test_saved_photo_is_bound_to_its_project_and_version(media_service, field, value):
    service, capture = media_service
    capture[field] = value
    with pytest.raises(HTTPException) as error:
        service.send("main", body(capture_id="capture"))
    assert error.value.status_code == 409
    assert service.read("main")["jobs"] == []


def test_photo_question_reads_saved_normalized_file(media_service):
    service, _ = media_service
    service.send("main", body(capture_id="capture"))
    result = settled(service, "main")
    assert result["jobs"][0]["status"] == "completed"
    prompt, _, options = service.state.design_service.bridge.calls[0]
    assert "saved-hash" in prompt and "navigation hints" in prompt
    assert options["image_paths"] == [service.state.mobile_service.assets.path]
    assert result["messages"][-1]["capture_id"] == "capture"


def test_wire_check_uses_existing_photo_contract_and_retains_uncertainty(media_service):
    from test_photo_wiring import opinion
    from app.photo_wiring import canonical_plan
    service, capture = media_service
    plan = canonical_plan()
    capture.update(runtime_revision=1, camera_id="phone", captured_at="2026-10-02",
        catalog_version=plan["catalog_version"], profile_versions=plan["profile_versions"], wires=plan["wires"])
    wire = capture["wires"][0]
    service.state.design_service.bridge.reply = opinion([wire])
    service.send("main", body(capture_id="capture", check_scope="one", wire_id=wire["wire_id"]))
    result = settled(service, "main")
    assert result["jobs"][0]["status"] == "completed"
    assert result["messages"][-1]["photo_results"][0]["verdict"] == "uncertain"
    assert len(service.state.design_service.bridge.calls) == 1


def test_debug_replies_persist_without_desktop_import(media_service):
    service, _ = media_service
    record = service._load("main")
    record["jobs"].append(dict(id="linked", request_id="debug", status="running", debug_session_id="session",
        stage="guide", capability="debug", round=0, epoch=0, request={"text": "question"}))
    service._save(record)
    messages = [dict(id="answer", role="assistant", text="Backend reply", session_id="session")]
    service.state.debug_sessions = SimpleNamespace(get=lambda sid: dict(phase="ready", model_busy=False,
        conversation_id="debug-conversation", messages=messages))
    result = service.read("main")
    assert result["jobs"][0]["status"] == "completed"
    assert result["messages"][0]["text"] == "Backend reply"
    service.import_messages("main", "debug:debug-conversation", messages, "legacy-debug")
    assert len(service.read("main")["messages"]) == 1
    restored = AssistantService(service.state, service.root)
    assert restored.read("main")["messages"][0]["text"] == "Backend reply"


def test_backend_history_watcher_saves_debug_answer_without_ui_poll(media_service):
    service, _ = media_service
    record = service._load("main")
    record["jobs"].append(dict(id="linked", request_id="debug", status="running", debug_session_id="session",
        stage="guide", capability="debug", round=0, epoch=0, request={"text": "question"}))
    service._save(record)
    service.state.debug_sessions = SimpleNamespace(get=lambda sid: dict(phase="ready", model_busy=False,
        conversation_id="debug-conversation", messages=[dict(id="answer", role="assistant", text="Saved autonomously")]))
    worker = threading.Thread(target=service._persist_debug_reply, args=("main", "linked"))
    worker.start()
    worker.join(3)
    assert not worker.is_alive()
    # Read the persisted file directly; no frontend/server read triggered the merge.
    disk = json.loads((service.root / "main.json").read_text(encoding="utf-8"))
    assert disk["jobs"][0]["status"] == "completed"
    assert disk["messages"][0]["text"] == "Saved autonomously"
