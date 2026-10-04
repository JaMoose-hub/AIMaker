"""HTTP/WS protocol and media boundaries; no live application or camera."""
from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.mobile import router
from test_mobile import setup, context


@pytest.fixture
def app(setup):
    service, phone, clock = setup
    instance = FastAPI()
    instance.state.mobile_service = service
    instance.state.assistant = service.state.assistant
    instance.include_router(router)
    return instance


def auth(phone):
    return {"Authorization": "Bearer "+phone["token"]}


def jpeg():
    data = BytesIO()
    Image.new("RGB", (64, 48), "red").save(data, "JPEG")
    return data.getvalue()


def test_remote_cannot_publish_context_or_read_desktop_but_paired_phone_can_chat(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        assert client.post("/api/mobile/context", json=context()).status_code == 403
        assert client.get("/api/mobile/desktop-session", params={"conversation_id": phone["conversation_id"]}).status_code == 403
        assert client.get("/api/mobile/session").status_code == 403
        response = client.get("/api/mobile/session", headers=auth(phone))
        assert response.status_code == 200 and response.json()["session_id"] == phone["session_id"]
        response = client.get("/api/mobile/conversation", params={"before": 10, "limit": 5}, headers=auth(phone))
        assert response.json()["before"] == 10 and response.json()["limit"] == 5
        response = client.post("/api/mobile/messages", headers=auth(phone), json=dict(request_id="one", text="Hello", context_id=phone["context_id"]))
        assert response.status_code == 202 and response.json()["id"] == phone["conversation_id"]
        assert service.state.assistant.sent[0][1]["source"] == "mobile"
        mismatch = client.get("/api/mobile/session", headers=auth(phone), params={"session_id": "wrong"})
        assert mismatch.status_code == 403


def test_loopback_publishes_context_and_pairing_json(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        response = client.post("/api/mobile/context", json=context())
        assert response.status_code == 200
        response = client.post("/api/mobile/pairings", json=dict(conversation_id=phone["conversation_id"], base_url="http://192.168.1.5:8100"))
        assert response.status_code == 200
        pair = response.json()
        result = client.post("/api/mobile/pair", json=dict(code=pair["code"], device_name="Second phone"))
        assert result.status_code == 200 and result.json()["context_id"] == phone["context_id"]
        assert client.post("/api/mobile/pair", json=dict(code=pair["code"])).status_code == 401


def test_multipart_retry_and_asset_file_authorization(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        arguments = dict(headers=auth(phone), data={"upload_id": "test-upload"}, files={"file": ("photo.jpg", jpeg(), "image/jpeg")})
        first = client.post("/api/mobile/assets", **arguments)
        assert first.status_code == 200
        asset = first.json()
        assert client.post("/api/mobile/assets", **arguments).json()["id"] == asset["id"]
        assert client.get(asset["url"]).status_code == 403
        response = client.get(asset["url"], headers=auth(phone))
        assert response.status_code == 200 and response.headers["content-type"] == "image/jpeg"
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == (asset["width"], asset["height"])
        assert client.get(asset["thumbnail_url"], headers=auth(phone)).status_code == 200
        service.publish_context(context("other-conversation"))
        pair = service.create_pairing("other-conversation", "http://192.168.1.5:8100")
        other = service.pair(pair["code"], "Other")
        assert client.get(asset["url"], headers=auth(other)).status_code == 403
    assert not list(service.root.glob("*.upload"))


@pytest.mark.parametrize("locale,count", [("en", 1), ("zh-TW", 3)])
def test_photo_only_message_accepts_uploaded_images_without_a_typed_prompt(app, setup, locale, count):
    service, phone, _ = setup
    published = context()
    published["design"]["locale"] = locale
    service.publish_context(published)
    pair = service.create_pairing(phone["conversation_id"], "http://192.168.1.5:8100")
    phone = service.pair(pair["code"], "Test phone")
    with TestClient(app, client=("192.168.1.10", 5000), raise_server_exceptions=False) as client:
        ids = []
        for index in range(count):
            response = client.post("/api/mobile/assets", headers=auth(phone),
                data={"upload_id": f"photo-only-{index}"}, files={"file": (f"photo-{index}.jpg", jpeg(), "image/jpeg")})
            assert response.status_code == 200
            ids.append(response.json()["id"])
        response = client.post("/api/mobile/messages", headers=auth(phone),
            json=dict(request_id="photo-only", asset_ids=ids, context_id=phone["context_id"], inherit_media=False))
        assert response.status_code == 202
    sent = service.state.assistant.sent[0][1]
    assert sent["asset_ids"] == ids and sent["source"] == "mobile"
    assert sent["text"].startswith("請分析" if locale == "zh-TW" else "Please analyze")


def test_blank_message_without_explicit_media_is_a_client_error(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000), raise_server_exceptions=False) as client:
        response = client.post("/api/mobile/messages", headers=auth(phone),
            json=dict(request_id="blank", text="  ", context_id=phone["context_id"]))
        assert response.status_code == 422
    assert service.state.assistant.sent == []


def test_photo_only_retry_shares_one_saved_reply_and_all_images_with_desktop(app, setup, tmp_path):
    from app.assistant import AssistantService
    from app.api.assistant import router as assistant_router
    from test_assistant import FakeDesigns, settled

    service, phone, _ = setup
    service.state.design_service = FakeDesigns()
    service.state.design_service.bridge.reply = {"answer": "The three saved photos are visible."}
    service.state.mobile_service = service
    assistant = AssistantService(service.state, tmp_path / "history")
    assistant.create(phone["conversation_id"])
    service.state.assistant = app.state.assistant = assistant
    app.include_router(assistant_router)
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        ids = []
        for index in range(3):
            response = client.post("/api/mobile/assets", headers=auth(phone),
                data={"upload_id": f"retry-photo-{index}"}, files={"file": (f"photo-{index}.jpg", jpeg(), "image/jpeg")})
            assert response.status_code == 200
            ids.append(response.json()["id"])
        payload = dict(request_id="same-photo-request", text="  ", asset_ids=ids,
            context_id=phone["context_id"], inherit_media=False)
        assert client.post("/api/mobile/messages", headers=auth(phone), json=payload).status_code == 202
        settled(assistant, phone["conversation_id"])
        assert client.post("/api/mobile/messages", headers=auth(phone), json=payload).status_code == 202
        mobile = client.get("/api/mobile/conversation", headers=auth(phone)).json()
        desktop = client.get(f"/api/assistant/conversations/{phone['conversation_id']}").json()
    assert mobile == desktop and len(mobile["jobs"]) == 1
    assert mobile["jobs"][0]["status"] == "completed"
    assert mobile["messages"][0]["text"].startswith("Please analyze")
    assert [item["asset_id"] for item in mobile["messages"][0]["attachments"]] == ids
    assert mobile["messages"][-1]["text"] == "The three saved photos are visible."
    calls = service.state.design_service.bridge.calls
    assert len(calls) == 1
    assert calls[0][2]["image_paths"] == [service.assets.path(aid) for aid in ids]
    assert all(path.exists() for path in calls[0][2]["image_paths"])


def test_stream_requires_generation_and_matching_phone_session(app, setup):
    _, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        started = client.post("/api/mobile/stream", headers=auth(phone))
        assert started.status_code == 200 and started.json()["generation"] == 1
        assert client.post("/api/mobile/capture-ticket", headers=auth(phone)).status_code == 409
        offer = client.post("/api/mobile/stream/offer", headers=auth(phone), json=dict(sdp="offer", type="offer", role="publisher"))
        assert offer.status_code == 422
        assert client.delete("/api/mobile/stream", headers=auth(phone)).json()["active"] is False


def test_stream_profile_and_client_stats_http_validation(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        assert client.post("/api/mobile/stream", headers=auth(phone), json={"bitrate_kbps": 6000}).status_code == 422
        started = client.post("/api/mobile/stream", headers=auth(phone), json={"bitrate_kbps": 12000})
        assert started.status_code == 200 and started.json()["bitrate_kbps"] == 12000
        generation = started.json()["generation"]
        payload = dict(generation=generation, capture_fps=30, send_fps=29.9, send_bitrate_kbps=7000,
                       width=1080, height=1920, rtt_ms=12, quality_limitation_reason="none")
        sent = client.post("/api/mobile/stream/metrics", headers=auth(phone), json=payload)
        assert sent.status_code == 200 and sent.json()["send_bitrate_kbps"] == 7000
        snapshot = client.get("/api/mobile/session", headers=auth(phone)).json()["stream"]
        assert snapshot["publisher_stats"]["width"] == 1080
        assert not snapshot["publisher_connected"] and not snapshot["can_capture"]
        for field, value in [("send_fps", "NaN"), ("send_fps", True), ("rtt_ms", -1), ("height", 3.5), ("generation", "1")]:
            assert client.post("/api/mobile/stream/metrics", headers=auth(phone), json={**payload, field: value}).status_code == 422
        assert client.post("/api/mobile/stream/metrics", json=payload).status_code == 403
        # No-body callers retain the original API, and older stats cannot revive it.
        restarted = client.post("/api/mobile/stream", headers=auth(phone))
        assert restarted.json()["bitrate_kbps"] == 8000
        assert client.post("/api/mobile/stream/metrics", headers=auth(phone), json=payload).status_code == 409
        assert client.delete("/api/mobile/stream", headers=auth(phone)).status_code == 200
        assert client.post("/api/mobile/stream/metrics", headers=auth(phone), json={**payload, "generation": restarted.json()["generation"]}).status_code == 409


def test_websocket_delivers_same_shared_view_revision(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        with client.websocket_connect("/api/mobile/events?token="+phone["token"]) as ws:
            initial = ws.receive_json()
            assert initial["type"] == "state" and initial["session"]["view"]["revision"] == 0
            service.view(phone["session_id"], dict(capture_id=None, wire_id=None))
            changed = ws.receive_json()
            assert changed["session"]["view"]["revision"] == 1
    assert not service.listeners


def test_delete_session_requires_own_bearer_and_closes_phone_events(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("192.168.1.10", 5000)) as client:
        with client.websocket_connect("/api/mobile/events?token="+phone["token"]) as ws:
            assert ws.receive_json()["session"]["session_id"] == phone["session_id"]
            assert client.delete("/api/mobile/session", params={"session_id": phone["session_id"]}).status_code == 401
            response = client.delete("/api/mobile/session", headers=auth(phone))
            assert response.status_code == 204 and response.content == b""
            assert ws.receive_json() == {"type": "disconnected", "session": None, "reason": "phone_disconnected"}
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
            assert closed.value.code == 1000
        assert client.get("/api/mobile/session", headers=auth(phone)).status_code == 401
        assert client.delete("/api/mobile/session", headers=auth(phone)).status_code == 401
    with TestClient(app, client=("127.0.0.1", 5000)) as desktop:
        assert desktop.get("/api/mobile/desktop-session", params={"conversation_id": phone["conversation_id"]}).json()["session"] is None
        assert desktop.post("/api/mobile/pairings", json={"conversation_id": phone["conversation_id"]}).status_code == 200
    assert not service.listeners


def test_delete_ignores_other_session_parameter_and_desktop_without_bearer(app, setup):
    service, phone, _ = setup
    pair = service.create_pairing(phone["conversation_id"], "http://192.168.1.5:8100")
    other = service.pair(pair["code"], "Other phone")
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        assert client.delete("/api/mobile/session", params={"session_id": other["session_id"]}).status_code == 401
        assert client.delete("/api/mobile/session", params={"session_id": other["session_id"]}, headers=auth(phone)).status_code == 204
        assert client.get("/api/mobile/session", headers=auth(other)).status_code == 200
        assert client.get("/api/mobile/session", headers=auth(phone)).status_code == 401
