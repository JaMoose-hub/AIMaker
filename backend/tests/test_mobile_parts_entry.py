"""Presentation entry tests: no hardware, real phone, upload, or AI requests."""
import asyncio
from fastapi.testclient import TestClient

from test_mobile import setup, context
from test_mobile_api import app, auth


def test_default_phone_context_does_not_request_hardware_comparison(setup):
    service, phone, _ = setup
    assert service.snapshot(phone["session_id"])["context"]["ui"] == {"parts_check": False}


def test_parts_entry_is_opt_in_and_changes_only_presentation_without_invalidating_stream(setup):
    service, phone, _ = setup
    sid = phone["session_id"]
    desktop = context(stage="design")
    published = service.publish_context(desktop)
    asyncio.run(service.join(sid))
    asyncio.run(service.start_stream(sid))
    before = service.snapshot(sid)
    closed_before = list(service.rtc.closed)
    assert before["context"]["ui"]["parts_check"] is False

    for requested in (True, False, True):
        updated = service.publish_context({**desktop, "ui": {"parts_check": requested}})
        current = service.snapshot(sid)
        assert updated["context_id"] == published["context_id"] == current["context_id"]
        assert current["context"]["ui"]["parts_check"] is requested
        assert current["stream"]["active"] is True
        assert current["stream"]["generation"] == before["stream"]["generation"]
    assert service.rtc.closed == closed_before
    assert not service.state.assistant.sent


def test_loopback_desktop_request_is_published_to_paired_phone_and_design_stage_only(app, setup):
    service, phone, _ = setup
    with TestClient(app, client=("127.0.0.1", 4444)) as client:
        for stage, expected in (("design", True), ("guide", False), ("deploy", False)):
            result = client.post("/api/mobile/context", json={**context(stage=stage), "ui": {"parts_check": True}})
            assert result.status_code == 200
            assert result.json()["ui"]["parts_check"] is expected
            asyncio.run(service.join(phone["session_id"]))
            status = client.get("/api/mobile/session", headers=auth(phone))
            assert status.status_code == 200
            assert status.json()["context"]["ui"]["parts_check"] is expected
