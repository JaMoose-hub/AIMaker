"""Safari pairing, proxy identity, and full-size photo ingestion without hardware."""
import json
import socket

from fastapi.testclient import TestClient
from PIL import Image
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.mobile_web import web_configuration
from test_mobile import setup
from test_mobile_api import app, auth


def test_https_pairing_is_a_camera_scannable_browser_url(setup):
    service, phone, _ = setup
    pair = service.create_pairing(phone["conversation_id"], "https://192.168.50.141:8443")
    assert pair["base_urls"] == ["https://192.168.50.141:8443"]
    assert pair["web_url"] == "https://192.168.50.141:8443/mobile?code=" + pair["code"]
    # Native development builds can still consume the old JSON contract.
    assert json.loads(pair["qr_payload"])["code"] == pair["code"]
    assert service.create_pairing(phone["conversation_id"], "http://192.168.50.141:8100")["web_url"] is None


def test_stale_https_configuration_is_not_advertised_as_running(tmp_path):
    assert web_configuration(tmp_path)["available"] is False
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        (tmp_path / "connection.json").write_text(json.dumps({"base_url": f"https://192.168.50.141:{port}"}))
        assert web_configuration(tmp_path)["available"] is False
        listener.listen()
        assert web_configuration(tmp_path)["available"] is True
    assert web_configuration(tmp_path)["available"] is False


def test_proxy_phone_stays_remote_for_desktop_only_controls(app, setup):
    _, phone, _ = setup
    wrapped = ProxyHeadersMiddleware(app, trusted_hosts=["127.0.0.1"])
    forwarded = {"X-Forwarded-For": "192.168.50.20", "X-Forwarded-Proto": "https"}
    with TestClient(wrapped, client=("127.0.0.1", 5000)) as client:
        assert client.get("/api/mobile/desktop-session", params={"conversation_id": phone["conversation_id"]}, headers=forwarded).status_code == 403
        assert client.get("/api/mobile/session", headers=forwarded).status_code == 403
        assert client.get("/api/mobile/session", headers={**forwarded, **auth(phone)}).status_code == 200


def test_desktop_pairing_prefers_running_https_entry_point(app, setup, monkeypatch):
    _, phone, _ = setup
    monkeypatch.setattr("app.api.mobile.web_configuration", lambda: {"available": True, "base_url": "https://192.168.50.141:8443"})
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        result = client.post("/api/mobile/pairings", json={"conversation_id": phone["conversation_id"]}).json()
        assert result["web_url"].startswith("https://192.168.50.141:8443/mobile?code=")


def ingest(service, phone, source, filename):
    return service.assets.ingest(source, conversation_id=phone["conversation_id"], session_id=phone["session_id"],
        upload_id="test-photo", filename=filename, content_type="image/heic" if filename.endswith("heic") else "image/jpeg")


def test_heic_upload_preserves_original_and_decodes_full_dimensions(setup, tmp_path):
    service, phone, _ = setup
    source = tmp_path / "camera.heic"
    Image.new("RGB", (120, 80), "green").save(source, "HEIF", quality=95)
    asset = ingest(service, phone, source, source.name)
    assert (asset["width"], asset["height"]) == (120, 80)
    assert (asset["original_width"], asset["original_height"]) == (120, 80)
    assert asset["analysis_limited"] is False
    assert (service.assets.root / asset["id"] / "original.bin").read_bytes() == source.read_bytes()


def test_portrait_photo_normalizes_exif_and_reports_source_dimensions(setup, tmp_path):
    service, phone, _ = setup
    source = tmp_path / "portrait.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (120, 80), "red").save(source, "JPEG", exif=exif)
    asset = ingest(service, phone, source, source.name)
    assert (asset["width"], asset["height"]) == (80, 120)
    assert (asset["original_width"], asset["original_height"]) == (80, 120)
    with Image.open(service.assets.path(asset["id"])) as normalized:
        assert normalized.size == (80, 120)
        assert normalized.getexif().get(274, 1) == 1


def test_analysis_limit_keeps_full_camera_file_and_does_not_upscale(setup, tmp_path):
    service, phone, _ = setup
    source = tmp_path / "large.jpg"
    Image.new("RGB", (4000, 3200), "green").save(source, "JPEG")
    asset = ingest(service, phone, source, source.name)
    assert (asset["original_width"], asset["original_height"]) == (4000, 3200)
    assert asset["width"] * asset["height"] <= 12_000_000
    assert abs(asset["width"] / asset["height"] - 1.25) < .001
    assert asset["analysis_limited"] is True
    assert (service.assets.root / asset["id"] / "original.bin").read_bytes() == source.read_bytes()
