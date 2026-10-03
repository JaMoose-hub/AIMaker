"""Isolated phone gateway checks; no webcam, Codex, Pi or OS trust changes."""
import asyncio
from datetime import datetime, timezone
import ipaddress
import plistlib
import socket
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID
from fastapi import FastAPI, Request, WebSocket
from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.websockets import WebSocketDisconnect
import uvicorn

from app.mobile_https import MobileHttpsProxy, create_certificates, phone_route


class Bytes(httpx.AsyncByteStream):
    def __init__(self, values):
        self.values = values

    async def __aiter__(self):
        for value in self.values:
            yield value


@pytest.fixture
def gateway(tmp_path):
    frontend = tmp_path / "frontend"
    (frontend / "assets").mkdir(parents=True)
    (frontend / "index.html").write_text("<html>Phone UI</html>", encoding="utf-8")
    (frontend / "assets" / "phone.js").write_text("console.log('phone')", encoding="utf-8")
    (frontend / "theme.js").write_text("window.theme='dark'", encoding="utf-8")
    (frontend / "brand").mkdir()
    (frontend / "brand" / "tinkro-symbol.svg").write_text("<svg/>", encoding="utf-8")
    (frontend / "brand" / "tinkro-dark.png").write_bytes(b"desktop-logo-png")
    certificates = tmp_path / "certificates"
    certificates.mkdir()
    (certificates / "rootCA.der").write_bytes(b"public-certificate")
    (certificates / "rootCA.mobileconfig").write_bytes(b"public-profile")
    (certificates / "rootCA-key.pem").write_bytes(b"private-key")
    captured = []
    async def handler(request):
        captured.append((request, await request.aread()))
        return httpx.Response(201, headers={"content-type": "application/json", "connection": "close"},
                              stream=Bytes([b'{"ok":', b'true}']))
    app = MobileHttpsProxy("http://127.0.0.1:8100", frontend, certificates,
                           client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return app, captured


def test_phone_static_and_public_ca_never_expose_keys(gateway):
    app, requests = gateway
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        redirect = client.get("/?code=123456", follow_redirects=False)
        assert redirect.status_code == 307 and redirect.headers["location"] == "/mobile?code=123456"
        assert client.get("/mobile").text == "<html>Phone UI</html>"
        assert client.get("/assets/phone.js").headers["cache-control"].endswith("immutable")
        assert client.get("/mobile-ca.crt").content == b"public-certificate"
        assert client.get("/mobile-ca.mobileconfig").content == b"public-profile"
        assert client.get("/rootCA-key.pem").status_code == 404
        assert client.get("/assets/%2e%2e/rootCA-key.pem").status_code == 404
        assert client.get("/docs").status_code == 404
    assert requests == []


def test_only_required_theme_and_brand_files_are_public(gateway):
    app, requests = gateway
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        theme = client.get("/theme.js")
        assert theme.status_code == 200 and theme.text == "window.theme='dark'"
        assert theme.headers["content-type"].startswith("application/javascript")
        logo = client.get("/brand/tinkro-symbol.svg")
        assert logo.status_code == 200 and logo.text == "<svg/>"
        assert logo.headers["content-type"] == "image/svg+xml"
        desktop_logo = client.get("/brand/tinkro-dark.png")
        assert desktop_logo.status_code == 200 and desktop_logo.content == b"desktop-logo-png"
        assert desktop_logo.headers["content-type"] == "image/png"
        assert client.head("/brand/tinkro-dark.png").content == b""
        assert client.head("/theme.js").content == b""
        assert client.post("/theme.js").status_code == 404
        assert client.post("/brand/tinkro-dark.png").status_code == 404
        assert client.get("/brand/other.svg").status_code == 404
    assert requests == []


@pytest.mark.parametrize("static_path", ["theme.js", "brand/tinkro-dark.png"])
def test_static_allowlist_still_rejects_resolved_outside_file(gateway, monkeypatch, static_path):
    app, requests = gateway
    original = type(app.frontend).resolve
    outside = app.certificates / "rootCA-key.pem"
    def resolved(path, *args, **kwargs):
        if path == app.frontend / static_path:
            return outside
        return original(path, *args, **kwargs)
    monkeypatch.setattr(type(app.frontend), "resolve", resolved)
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        assert client.get("/" + static_path).status_code == 404
    assert requests == []


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/mobile/context"), ("POST", "/api/mobile/pairings"),
    ("GET", "/api/mobile/desktop-session"), ("GET", "/api/mobile/web-config"),
    ("GET", "/api/pi/status"), ("POST", "/api/pi/deploy"),
    ("GET", "/api/config"), ("GET", "/video"), ("GET", "/api/mobile/captures/a/image"),
])
def test_desktop_and_hardware_routes_are_not_forwarded(gateway, method, path):
    app, requests = gateway
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        assert client.request(method, path).status_code == 404
    assert requests == []


def test_phone_body_bearer_and_real_client_ip_reach_one_backend(gateway):
    app, requests = gateway
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        response = client.post("/api/mobile/messages?session_id=phone", content=b"prompt",
            headers={"Authorization": "Bearer paired", "X-Forwarded-For": "127.0.0.1",
                     "X-Forwarded-Proto": "http", "X-Real-IP": "127.0.0.1", "Forwarded": "for=127.0.0.1"})
        assert response.status_code == 201 and response.json() == {"ok": True}
        assert "connection" not in response.headers
    request, body = requests[0]
    assert str(request.url) == "http://127.0.0.1:8100/api/mobile/messages?session_id=phone"
    assert body == b"prompt"
    assert request.headers["authorization"] == "Bearer paired"
    assert request.headers["x-forwarded-for"] == "192.168.50.50"
    assert request.headers["x-forwarded-proto"] == "https"
    assert "x-real-ip" not in request.headers and "forwarded" not in request.headers


def test_proxy_only_accepts_loopback_upstream(tmp_path):
    for address in ("http://192.168.1.10:8100", "https://127.0.0.1:8100", "http://localhost:8100", "http://127.0.0.1:8100/api"):
        with pytest.raises(ValueError):
            MobileHttpsProxy(address, tmp_path, tmp_path)
    assert phone_route("/api/mobile/web-ca", "GET")
    assert phone_route("/api/mobile/assets/asset_one/file", "GET")
    assert phone_route("/api/mobile/session", "DELETE")
    assert phone_route("/api/mobile/stream/metrics", "POST")
    assert not phone_route("/api/mobile/stream/metrics", "GET")


def test_phone_stream_profile_and_diagnostics_reach_the_same_backend(gateway):
    app, requests = gateway
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        profile = client.post("/api/mobile/stream", json={"bitrate_kbps": 12000}, headers={"Authorization": "Bearer paired"})
        metrics = client.post("/api/mobile/stream/metrics", json={"generation": 3, "send_fps": 30}, headers={"Authorization": "Bearer paired"})
        assert profile.status_code == metrics.status_code == 201
        assert client.get("/api/mobile/stream/metrics").status_code == 404
    assert len(requests) == 2
    import json
    assert json.loads(requests[0][1]) == {"bitrate_kbps": 12000}
    assert json.loads(requests[1][1]) == {"generation": 3, "send_fps": 30}
    assert requests[1][0].headers["authorization"] == "Bearer paired"
    assert requests[1][0].headers["x-forwarded-for"] == "192.168.50.50"


def test_websocket_relay_preserves_client_and_cleans_up_on_disconnect(gateway):
    app, _ = gateway
    delivered, details = [], []
    class Socket:
        def __aiter__(self):
            return self
        async def __anext__(self):
            if not delivered:
                delivered.append("state")
                return '{"type":"state"}'
            await asyncio.Event().wait()
        async def send(self, value):
            delivered.append(value)
    class Connection:
        async def __aenter__(self):
            return Socket()
        async def __aexit__(self, *args):
            delivered.append("closed")
    def connector(url, **kwargs):
        details.append((url, kwargs))
        return Connection()
    app.websocket_connect = connector
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        with client.websocket_connect("/api/mobile/events?token=paired", headers={"X-Forwarded-For": "127.0.0.1"}) as ws:
            assert ws.receive_json() == {"type": "state"}
            ws.send_text("ack")
    assert "closed" in delivered
    url, options = details[0]
    assert url == "ws://127.0.0.1:8100/api/mobile/events?token=paired"
    assert dict(options["additional_headers"])["x-forwarded-for"] == "192.168.50.50"
    assert options["proxy"] is None
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/pi/events"):
                pass
        assert denied.value.code == 1008
    assert len(details) == 1


@pytest.mark.parametrize("status,code", [(403, 1008), (503, 1013)])
def test_websocket_upstream_rejection_maps_to_policy_or_temporary_error(gateway, status, code):
    from websockets.datastructures import Headers
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    app, _ = gateway
    class Connection:
        async def __aenter__(self):
            raise InvalidStatus(Response(status, "Rejected", Headers()))
        async def __aexit__(self, *args):
            pass
    app.websocket_connect = lambda *args, **kwargs: Connection()
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        with pytest.raises(WebSocketDisconnect) as rejected:
            with client.websocket_connect("/api/mobile/events?token=expired"):
                pass
        assert rejected.value.code == code


def test_websocket_normal_backend_close_is_preserved(gateway):
    app, _ = gateway
    class Socket:
        close_code = 1000
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
    class Connection:
        async def __aenter__(self):
            return Socket()
        async def __aexit__(self, *args):
            pass
    app.websocket_connect = lambda *args, **kwargs: Connection()
    with TestClient(app, client=("192.168.50.50", 50200)) as client:
        with client.websocket_connect("/api/mobile/events?token=paired") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
            assert closed.value.code == 1000


def test_phone_disconnect_does_not_send_another_close_frame(gateway):
    app, _ = gateway
    messages, upstream_closed = [], []
    class Socket:
        def __aiter__(self):
            return self
        async def __anext__(self):
            await asyncio.Event().wait()
    class Connection:
        async def __aenter__(self):
            return Socket()
        async def __aexit__(self, *args):
            upstream_closed.append(True)
    app.websocket_connect = lambda *args, **kwargs: Connection()
    async def run():
        incoming = iter([{"type": "websocket.connect"}, {"type": "websocket.disconnect", "code": 1000}])
        async def receive():
            return next(incoming)
        async def send(message):
            messages.append(message)
        await app({"type": "websocket", "path": "/api/mobile/events", "client": ("192.168.50.50", 123),
                   "headers": [], "query_string": b"token=paired"}, receive, send)
    asyncio.run(run())
    assert messages == [{"type": "websocket.accept"}]
    assert upstream_closed == [True]


def test_local_ca_leaf_san_and_public_profile_are_verifiable(tmp_path):
    info = create_certificates(tmp_path, ["192.168.50.141"])
    ca = x509.load_pem_x509_certificate((tmp_path / "rootCA.pem").read_bytes())
    leaf = x509.load_pem_x509_certificate((tmp_path / "server.pem").read_bytes())
    leaf.verify_directly_issued_by(ca)
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert not leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    assert ExtendedKeyUsageOID.SERVER_AUTH in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ipaddress.ip_address("192.168.50.141") in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
    assert (leaf.not_valid_after_utc - datetime.now(timezone.utc)).days <= 364
    profile = plistlib.loads((tmp_path / "rootCA.mobileconfig").read_bytes())
    exported = profile["PayloadContent"][0]["PayloadContent"]
    assert exported == (tmp_path / "rootCA.der").read_bytes()
    assert x509.load_der_x509_certificate(exported).fingerprint(hashes.SHA256()).hex() == info["ca_sha256"]
    assert b"PRIVATE KEY" not in (tmp_path / "rootCA.mobileconfig").read_bytes()
    original_ca = (tmp_path / "rootCA.pem").read_bytes()
    create_certificates(tmp_path, ["192.168.50.142"])
    assert (tmp_path / "rootCA.pem").read_bytes() == original_ca
    updated_leaf = x509.load_pem_x509_certificate((tmp_path / "server.pem").read_bytes())
    assert ipaddress.ip_address("192.168.50.142") in updated_leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)


def test_incomplete_existing_ca_is_preserved(tmp_path):
    (tmp_path / "rootCA.pem").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        create_certificates(tmp_path, ["192.168.50.141"])
    assert (tmp_path / "rootCA.pem").read_text(encoding="utf-8") == "preserve"


def test_real_http_and_websocket_backend_observe_phone_not_loopback(gateway):
    """Exercise uvicorn's trusted-loopback middleware and actual relay sockets."""
    upstream = FastAPI()
    @upstream.post("/api/mobile/assets")
    async def uploaded(request: Request):
        return {"client": request.client.host, "body": (await request.body()).decode(),
                "authorization": request.headers.get("authorization")}
    @upstream.websocket("/api/mobile/events")
    async def events(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"client": ws.client.host, "token": ws.query_params.get("token")})
        await ws.close()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(upstream, log_level="critical", proxy_headers=True,
                                           forwarded_allow_ips="127.0.0.1", ws="websockets-sansio"))
    worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    worker.start()
    try:
        deadline = time.monotonic()+5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        app, _ = gateway
        app.upstream = f"http://127.0.0.1:{port}"
        app.client_factory = lambda: httpx.AsyncClient(trust_env=False)
        with TestClient(app, client=("192.168.50.50", 50200)) as client:
            reply = client.post("/api/mobile/assets", content=b"new-photo", headers={"Authorization": "Bearer paired"})
            assert reply.json() == {"client": "192.168.50.50", "body": "new-photo", "authorization": "Bearer paired"}
            with client.websocket_connect("/api/mobile/events?token=paired") as ws:
                assert ws.receive_json() == {"client": "192.168.50.50", "token": "paired"}
    finally:
        server.should_exit = True
        worker.join(5)
        listener.close()
    assert not worker.is_alive()
