"""Publication ownership is separate from guide snapshots and paired devices."""
import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from test_mobile import context, setup
from test_mobile_api import app, auth


def test_idle_old_tabs_cannot_stop_current_publication(app, setup):
    service, phone, _ = setup
    sid = phone["session_id"]
    with TestClient(app) as client:
        started = client.post("/api/mobile/stream", headers=auth(phone), json={"publisher_id": "current"})
        assert started.status_code == 200
        assert "_publisher_id" not in started.json()
        before = len(service.rtc.closed)
        for body in [None, {}, {"publisher_id": "old-tab"}]:
            result = client.request("DELETE", "/api/mobile/stream", headers=auth(phone), json=body)
            assert result.status_code == 409
            assert result.json()["detail"] == "mobile_stream_publisher_changed"
            assert service.snapshot(sid)["stream"]["active"]
            assert len(service.rtc.closed) == before
        stopped = client.request("DELETE", "/api/mobile/stream", headers=auth(phone), json={"publisher_id": "current"})
        assert stopped.status_code == 200 and not stopped.json()["active"]


def test_delayed_stop_and_guide_updates_do_not_retire_replacement(setup):
    service, phone, _ = setup
    sid = phone["session_id"]

    async def run():
        await service.start_stream(sid, publisher_id="first")
        current = await service.start_stream(sid, publisher_id="second")
        for index in range(4):
            service.publish_context(context(context={"guide": {"index": index, "phase": "active"}}))
            with pytest.raises(HTTPException, match="mobile_stream_publisher_changed"):
                await service.stop_stream(sid, publisher_id="first")
            snapshot = service.snapshot(sid)
            assert snapshot["stream"]["active"]
            assert snapshot["stream"]["generation"] == current["generation"]
            assert "_publisher_id" not in snapshot["stream"]
        await service.stop_stream(sid, publisher_id="second")
        assert not service.snapshot(sid)["stream"]["active"]

    asyncio.run(run())


def test_start_waits_for_owned_stop_before_publishing_new_generation(setup):
    service, phone, _ = setup
    sid = phone["session_id"]

    async def run():
        await service.start_stream(sid, publisher_id="first")
        entered, release = asyncio.Event(), asyncio.Event()
        close = service.rtc.close

        async def slow_close(selected):
            entered.set()
            await release.wait()
            await close(selected)

        service.rtc.close = slow_close
        stopping = asyncio.create_task(service.stop_stream(sid, publisher_id="first"))
        await entered.wait()
        starting = asyncio.create_task(service.start_stream(sid, publisher_id="second"))
        await asyncio.sleep(0)
        assert not starting.done()
        release.set()
        await asyncio.gather(stopping, starting)
        assert service.snapshot(sid)["stream"]["active"]
        with pytest.raises(HTTPException):
            await service.stop_stream(sid, publisher_id="first")

    asyncio.run(run())


def test_legacy_stop_remains_available_for_legacy_publication(app, setup):
    _, phone, _ = setup
    with TestClient(app) as client:
        assert client.post("/api/mobile/stream", headers=auth(phone)).status_code == 200
        result = client.delete("/api/mobile/stream", headers=auth(phone))
        assert result.status_code == 200 and result.json()["active"] is False
