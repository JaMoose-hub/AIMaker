"""Archived bytes remain viewable, without restoring any executable session."""
from copy import deepcopy
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.debug_sessions import router
from app.debug_sessions import DebugSessions
from test_debug_sessions import setup, _context, _diagnosed
from test_guided_wiring_review import _capture_stub, _start, _photos


def test_restart_keeps_original_photos_viewable_but_review_and_actions_stale(setup):
    service, state = setup
    _capture_stub(service)
    sid, context = _start(service)
    _photos(service, sid, context)
    originals = {entry["id"]: service.evidence(sid, entry["id"]) for entry in service.sessions[sid]["evidence"]}
    stored_confirmations = deepcopy(context["guide_confirmations"])
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    result = restored.get(sid)
    assert result["status"] == "paused" and result["phase"] == "backend_restarted"
    assert result["wiring_review"]["status"] == "stale"
    assert all(not slot["available"] for slot in result["wiring_review"]["slots"].values())
    assert all(not entry["available"] and not entry["current"] and entry["display_available"] for entry in result["evidence"])
    assert sid not in restored.images and restored.sessions[sid]["context"] is None
    app = FastAPI()
    app.state.debug_sessions = restored
    app.include_router(router)
    with TestClient(app) as client:
        for capture_id, original in originals.items():
            response = client.get(f"/api/debug/sessions/{sid}/evidence/{capture_id}")
            assert response.status_code == 200 and response.content == original
            assert response.headers["content-type"] == "image/jpeg"
    with pytest.raises(ValueError, match="restart_requires_new_session"):
        restored.action(sid, "continue", "no-replay", context=context)
    restored.tick(sid)
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs
    assert context["guide_confirmations"] == stored_confirmations


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_archive_never_serves_substitute_bytes(setup, damage):
    service, state = setup
    sid = _diagnosed(service, _context())
    entry = service._capture(sid, "hc_target")
    path = service._image_archive_path(sid, entry["id"], "overview")
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"a different photograph")
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert not restored.get(sid)["evidence"][0]["display_available"]
    with pytest.raises(ValueError, match="capture_expired"):
        restored.evidence(sid, entry["id"])


def test_archive_paths_and_unknown_capture_views_are_bounded(setup):
    service, _ = setup
    sid = _diagnosed(service, _context())
    entry = service._capture(sid, "hc_target")
    for args in [("../escape", entry["id"], "overview"), (sid, "../../escape", "overview"),
                 (sid, entry["id"], "../../escape")]:
        with pytest.raises(ValueError, match="invalid_capture_identity"):
            service._image_archive_path(*args)
    with pytest.raises(ValueError, match="capture_view_not_found"):
        service.evidence_view(sid, entry["id"], "../../escape")
    with pytest.raises(ValueError, match="capture_not_found"):
        service.evidence_view(sid, "0" * 32)


def test_memory_expiry_keeps_verified_photo_history_only(setup):
    service, state = setup
    sid = _diagnosed(service, _context())
    entry = service._capture(sid, "hc_target")
    original = service.evidence(sid, entry["id"])
    service.sessions[sid].update(status="paused", updated_at=time.time() - 901)
    service._expire_images()
    assert sid not in service.images
    saved = service.get(sid)["evidence"][0]
    assert not saved["available"] and not saved["current"]
    assert service.evidence(sid, entry["id"]) == original
    assert not state.design_service.bridge.calls and not state.pi_execution.jobs


def test_named_view_archive_keeps_its_bytes_and_mime_after_restart(setup):
    service, state = setup
    sid = _diagnosed(service, _context())
    original_capture = service.capture_fn
    def with_view(*args, **kwargs):
        images, metadata = original_capture(*args, **kwargs)
        images["pi_pins"] = b"\x89PNG\r\n\x1a\noriginal-crop"
        return images, metadata
    service.capture_fn = with_view
    entry = service._capture(sid, "hc_target")
    crop = service.evidence_view(sid, entry["id"], "pi_pins")
    restored = DebugSessions(state, service.store, service.capture_fn, autostart=False)
    assert restored.evidence_view(sid, entry["id"], "pi_pins") == crop
    assert crop[1] == "image/png" and not restored.images
