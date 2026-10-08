"""Saved crops are ready inputs, not missing photos or already inspected images."""
from copy import deepcopy
import json

import pytest

from app.assistant import SendRequest
from test_wiring_chat_flow import chat, act, analysed, photos


def request(published, **values):
    return SendRequest.model_validate(dict(request_id="crop-question", text="框選有送給 AI 嗎？", stage="guide",
        target="wiring", design=published["design"], context=published["context"], round=0, **values))


def context(state, published):
    return state.assistant._wiring_chat_context(state.assistant._load("shared-conversation"), request(published))


def test_saved_crop_keeps_accepted_photos_ready_without_exposing_photo_payloads(chat):
    app, state, mobile, phone, published, sid, path = chat
    initial = context(state, published)
    assert initial["collecting_photos"] and not initial["photos_ready"]
    photos(state)
    accepted = deepcopy(state.debug_sessions.sessions[sid]["wiring_review"]["slots"]["component_header"]["photo_acceptance"])
    act(state, "crop", role="component_header", crop=[.1, .2, .8, .9])
    review = state.debug_sessions.sessions[sid]["wiring_review"]
    review["slots"]["component_header"]["password"] = "slot-secret-must-not-leak"
    answer = context(state, published)
    assert review["status"] == "collecting" and review["slots"]["component_header"]["photo_acceptance"] == accepted
    assert answer["photos_ready"] and answer["needs_analysis"] and not answer["collecting_photos"]
    assert answer["capture_plan"] == "pi_rows_v1"
    assert answer["photos"]["component_header"] == dict(present=True, available=True, accepted=True, crop_saved=True, target_row=None)
    assert answer["photos"]["pi_side_a"] == dict(present=True, available=True, accepted=True, crop_saved=False, target_row="inner")
    assert not answer["has_completed_analysis"] and answer["observations"] == [] and answer["results"] == []
    assert answer["image_access"] == "none_in_this_text_reply"
    serialized = json.dumps(answer)
    assert "slot-secret-must-not-leak" not in serialized and "image_url" not in serialized and "data:image" not in serialized
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_completed_analysis_context_must_match_current_capture_hash_crop_and_scope(chat):
    app, state, mobile, phone, published, sid, path = chat
    analysed(state, sid)
    review = state.debug_sessions.sessions[sid]["wiring_review"]
    answer = context(state, published)
    assert answer["has_completed_analysis"] and not answer["needs_analysis"] and answer["results"]
    original = deepcopy(review)
    calls = len(state.design_service.bridge.calls)
    changes = (
        lambda value: value["slots"]["component_header"].update(crop=[.1, .1, .8, .8]),
        lambda value: value["slots"]["component_header"].update(capture_id="replaced-capture"),
        lambda value: value["slots"]["component_header"].update(sha256="f" * 64),
        lambda value: value.update(component_id="mrd-tf240-8p-cs"),
        lambda value: value.update(analysis_revision=None),
    )
    for change in changes:
        review.clear(); review.update(deepcopy(original)); change(review)
        answer = context(state, published)
        assert not answer["has_completed_analysis"] and answer["results"] == [] and answer["observations"] == []
    assert len(state.design_service.bridge.calls) == calls and not state.pi_execution.jobs


def test_text_after_crop_gets_ready_state_without_images_or_a_media_bypass(chat, monkeypatch):
    app, state, mobile, phone, published, sid, path = chat
    photos(state)
    act(state, "crop", role="component_header", crop=[.1, .2, .8, .9])
    before = deepcopy(state.debug_sessions.sessions[sid]["wiring_review"])
    with pytest.raises(Exception) as error:
        state.assistant.send("shared-conversation", request(published, asset_ids=["ordinary-photo"], inherit_media=False))
    assert error.value.status_code == 409 and error.value.detail == "wiring_photo_collection_in_progress"
    calls = []
    state.pi_deployer.snapshot = lambda: dict(connected=False, logs=[])
    def reply(prompt, schema, **kwargs):
        calls.append((prompt, kwargs))
        return dict(answer="框選已儲存，請按開始分析才會送出照片。")
    state.design_service.bridge.generate = reply
    class ImmediateThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args
        def start(self):
            self.target(*self.args)
    monkeypatch.setattr("app.assistant.threading.Thread", ImmediateThread)
    result = state.assistant.send("shared-conversation", request(published))
    assert result["jobs"][-1]["status"] == "completed", result["jobs"][-1].get("error")
    assert len(calls) == 1 and not calls[0][1].get("image_paths")
    assert '"collecting_photos": false' in calls[0][0] and '"needs_analysis": true' in calls[0][0]
    assert "Saving a crop does not send it to AI" in calls[0][0]
    assert state.debug_sessions.sessions[sid]["wiring_review"] == before and not state.pi_execution.jobs
