"""LAN TLS gateway for the phone web UI; never starts the camera backend.

Only the phone API is forwarded. The backend must trust forwarded client IPs
from loopback, while this gateway deliberately ignores incoming proxy headers.
Certificate creation writes local files only and does not change OS trust.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import mimetypes
from pathlib import Path
import plistlib
import re
from urllib.parse import urlsplit
from uuid import uuid4

import httpx


PHONE_ROUTES = {
    "/api/mobile/pair": {"POST"},
    "/api/mobile/session": {"GET", "DELETE"},
    "/api/mobile/join": {"POST"},
    "/api/mobile/conversation": {"GET"},
    "/api/mobile/messages": {"POST"},
    "/api/mobile/assets": {"POST"},
    "/api/mobile/stream": {"POST", "DELETE"},
    "/api/mobile/stream/offer": {"POST"},
    "/api/mobile/stream/metrics": {"POST"},
    "/api/mobile/stream-capture": {"POST"},
    "/api/mobile/capture-ticket": {"POST"},
    "/api/mobile/captures": {"POST"},
    "/api/mobile/view": {"GET", "PUT"},
    "/api/mobile/web-ca": {"GET"},
    "/api/mobile/web-ca-profile": {"GET"},
}
ASSET_ROUTE = re.compile(r"^/api/mobile/assets/[A-Za-z0-9_-]{1,100}/(?:file|thumbnail)$")
CAPTURE_ROUTE = re.compile(r"^/api/mobile/captures/[A-Za-z0-9_-]{1,100}$")
HOP_HEADERS = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization",
               b"te", b"trailer", b"transfer-encoding", b"upgrade"}
FORWARDED_HEADERS = {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
PUBLIC_STATIC = {"/theme.js": "application/javascript; charset=utf-8",
                 "/brand/tinkro-symbol.svg": "image/svg+xml",
                 "/brand/tinkro-dark.png": "image/png"}


def phone_route(path: str, method: str) -> bool:
    return method in PHONE_ROUTES.get(path, set()) or (
        method == "GET" and bool(ASSET_ROUTE.fullmatch(path) or CAPTURE_ROUTE.fullmatch(path)))


def upstream_headers(scope: dict) -> list[tuple[bytes, bytes]]:
    """Use socket identity, never a caller's forwarded/client-IP headers."""
    headers = [(k, v) for k, v in scope.get("headers", [])
               if k.lower() not in HOP_HEADERS | FORWARDED_HEADERS | {b"host"}]
    client = (scope.get("client") or ("", 0))[0]
    try:
        client = str(ipaddress.ip_address(client))
    except ValueError:
        raise ValueError("gateway client must have an IP address") from None
    headers.extend([(b"x-forwarded-for", client.encode("ascii")), (b"x-forwarded-proto", b"https")])
    return headers


def _upstream(value: str) -> str:
    parsed = urlsplit(value)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("upstream must be an explicit loopback HTTP address") from None
    if (parsed.scheme != "http" or not address.is_loopback or port is None or
            parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise ValueError("upstream must be an explicit loopback HTTP address")
    return value.rstrip("/")


class MobileHttpsProxy:
    def __init__(self, upstream: str, frontend: Path, certificates: Path, *, client_factory=None, websocket_connect=None):
        self.upstream = _upstream(upstream)
        self.frontend = Path(frontend).resolve()
        self.certificates = Path(certificates).resolve()
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(180, connect=5), follow_redirects=False, trust_env=False))
        self.websocket_connect = websocket_connect
        self.client = None

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)
        elif scope["type"] == "websocket":
            await self._websocket(scope, receive, send)

    async def _lifespan(self, receive, send):
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                self.client = self.client_factory()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                if self.client is not None:
                    await self.client.aclose()
                await send({"type": "lifespan.shutdown.complete"})
                return

    @staticmethod
    async def _reply(send, status, body=b"", content_type="text/plain; charset=utf-8", extra=(), *, head=False):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", content_type.encode()), (b"content-length", str(len(body)).encode()), *extra]})
        await send({"type": "http.response.body", "body": b"" if head else body})

    async def _http(self, scope, receive, send):
        path, method = scope["path"], scope["method"]
        if path == "/" and method in {"GET", "HEAD"}:
            query = scope.get("query_string", b"")
            await self._reply(send, 307, extra=[(b"location", b"/mobile" + (b"?"+query if query else b""))])
            return
        if method in {"GET", "HEAD"} and path in {"/mobile-ca.crt", "/mobile-ca.mobileconfig"}:
            filename = "rootCA.der" if path.endswith(".crt") else "rootCA.mobileconfig"
            mime = "application/x-x509-ca-cert" if filename.endswith(".der") else "application/x-apple-aspen-config"
            await self._file(send, self.certificates / filename, mime, head=method == "HEAD")
            return
        if method in {"GET", "HEAD"} and path in {"/mobile", "/mobile/"}:
            await self._file(send, self.frontend / "index.html", "text/html; charset=utf-8", head=method == "HEAD")
            return
        if method in {"GET", "HEAD"} and path in PUBLIC_STATIC:
            candidate = (self.frontend / path.lstrip("/")).resolve()
            if candidate.is_relative_to(self.frontend):
                await self._file(send, candidate, PUBLIC_STATIC[path], head=method == "HEAD")
                return
        if method in {"GET", "HEAD"} and path.startswith("/assets/"):
            candidate = (self.frontend / path.lstrip("/")).resolve()
            if candidate.is_relative_to(self.frontend / "assets"):
                await self._file(send, candidate, mimetypes.guess_type(str(candidate))[0] or "application/octet-stream", head=method == "HEAD", immutable=True)
                return
        if not phone_route(path, method):
            await self._reply(send, 404, b"This gateway exposes only the Tinkro phone companion.")
            return
        if self.client is None:
            await self._reply(send, 503, b"Phone gateway has not started.")
            return
        async def body():
            while True:
                item = await receive()
                if item["type"] == "http.disconnect":
                    raise asyncio.CancelledError
                if item["type"] == "http.request":
                    if item.get("body"):
                        yield item["body"]
                    if not item.get("more_body"):
                        return
        query = scope.get("query_string", b"").decode("ascii")
        url = self.upstream + path + ("?"+query if query else "")
        response = None
        try:
            request = self.client.build_request(method, url, headers=upstream_headers(scope), content=body())
            response = await self.client.send(request, stream=True)
            headers = [(k, v) for k, v in response.headers.raw if k.lower() not in HOP_HEADERS]
            await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
            async for chunk in response.aiter_raw():
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b""})
        except (httpx.HTTPError, ValueError):
            if response is None:
                await self._reply(send, 502, b"Tinkro backend unavailable. Start the existing backend on port 8100.")
        finally:
            if response is not None:
                await response.aclose()

    async def _file(self, send, path, mime, *, head=False, immutable=False):
        if not path.is_file():
            await self._reply(send, 404, b"File unavailable. Build the frontend or prepare the local certificates.")
            return
        body = await asyncio.to_thread(path.read_bytes)
        await self._reply(send, 200, body, mime,
                          [(b"cache-control", b"public, max-age=31536000, immutable" if immutable else b"no-store")], head=head)

    async def _websocket(self, scope, receive, send):
        await receive()
        if scope["path"] != "/api/mobile/events":
            await send({"type": "websocket.close", "code": 1008})
            return
        from websockets.asyncio.client import connect
        from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus
        connector = self.websocket_connect or connect
        query = scope.get("query_string", b"").decode("ascii")
        url = "ws" + self.upstream[4:] + scope["path"] + ("?"+query if query else "")
        # websockets creates its own handshake headers; never forward these.
        ignored = {b"sec-websocket-key", b"sec-websocket-version", b"sec-websocket-extensions", b"sec-websocket-protocol"}
        headers = [(k.decode("latin1"), v.decode("latin1")) for k, v in upstream_headers(scope) if k.lower() not in ignored]
        close_code, phone_left = 1013, False
        try:
            async with connector(url, additional_headers=headers, proxy=None, max_size=4*1024*1024, open_timeout=8) as upstream:
                await send({"type": "websocket.accept"})
                close_code = 1001
                async def to_backend():
                    nonlocal phone_left
                    while True:
                        item = await receive()
                        if item["type"] == "websocket.disconnect":
                            phone_left = True
                            return
                        if item["type"] == "websocket.receive":
                            await upstream.send(item.get("text") if item.get("text") is not None else item.get("bytes", b""))
                async def to_phone():
                    nonlocal close_code
                    async for item in upstream:
                        await send({"type": "websocket.send", "text": item} if isinstance(item, str)
                                   else {"type": "websocket.send", "bytes": item})
                    close_code = _close_code(getattr(upstream, "close_code", 1001))
                tasks = [asyncio.create_task(to_backend()), asyncio.create_task(to_phone())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except InvalidStatus as error:
            close_code = 1008 if error.response.status_code in {401, 403} else 1013
        except ConnectionClosed as error:
            close_code = _close_code(error.rcvd.code if error.rcvd is not None else None)
        except (OSError, InvalidHandshake, TimeoutError):
            close_code = 1013
        finally:
            if not phone_left:
                try:
                    await send({"type": "websocket.close", "code": close_code})
                except RuntimeError:
                    pass


def _close_code(code):
    # Reserved protocol status values cannot be sent in a close frame.
    return code if code in {1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014} or (
        isinstance(code, int) and 3000 <= code <= 4999) else 1011


def create_certificates(directory: Path, hosts: list[str]) -> dict:
    """Reuse this laptop's CA, issue a LAN leaf, export only public CA payloads."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    addresses = list(dict.fromkeys([str(ipaddress.ip_address(host)) for host in hosts] + ["127.0.0.1", "::1"]))
    ca_path, ca_key_path = directory / "rootCA.pem", directory / "rootCA-key.pem"
    if ca_path.is_file() != ca_key_path.is_file():
        raise ValueError("CA certificate/key pair is incomplete; preserve or restore the original pair")
    if ca_path.is_file():
        ca = x509.load_pem_x509_certificate(ca_path.read_bytes())
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        if ca.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != ca_key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
            raise ValueError("CA certificate/key mismatch")
        if ca.not_valid_after_utc <= now+timedelta(days=366):
            raise ValueError("Local CA expires soon; replace it and reinstall its public certificate on the phone")
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tinkro LAN Development CA")])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5))
              .not_valid_after(now+timedelta(days=365*5))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
                    encipher_only=False, decipher_only=False), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
              .sign(ca_key, hashes.SHA256()))
        ca_key_path.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Tinkro Phone Companion")]))
            .issuer_name(ca.subject).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=364))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(host)) for host in addresses]
                                                     + [x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
                    data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
                    encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    (directory / "server.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM)+ca.public_bytes(serialization.Encoding.PEM))
    (directory / "server-key.pem").write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_ca = ca.public_bytes(serialization.Encoding.DER)
    (directory / "rootCA.der").write_bytes(public_ca)
    fingerprint = ca.fingerprint(hashes.SHA256()).hex()
    identifier = "local.tinkro.lan-ca."+fingerprint[:16]
    profile = {"PayloadVersion": 1, "PayloadType": "Configuration", "PayloadIdentifier": identifier,
               "PayloadUUID": str(uuid4()), "PayloadDisplayName": "Tinkro LAN Development CA", "PayloadRemovalDisallowed": False,
               "PayloadContent": [{"PayloadVersion": 1, "PayloadType": "com.apple.security.root",
                   "PayloadIdentifier": identifier+".certificate", "PayloadUUID": str(uuid4()),
                   "PayloadDisplayName": "Tinkro LAN Development CA", "PayloadContent": public_ca}]}
    (directory / "rootCA.mobileconfig").write_bytes(plistlib.dumps(profile))
    result = {"directory": str(directory), "addresses": addresses, "ca_sha256": fingerprint,
              "server_certificate": str(directory / "server.pem"), "server_key": str(directory / "server-key.pem"),
              "phone_certificate": str(directory / "rootCA.der"), "phone_profile": str(directory / "rootCA.mobileconfig")}
    (directory / "certificate-info.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cert = sub.add_parser("certificates")
    cert.add_argument("--directory", required=True, type=Path)
    cert.add_argument("--lan-host", required=True, action="append")
    serve = sub.add_parser("serve")
    serve.add_argument("--directory", required=True, type=Path)
    serve.add_argument("--frontend", required=True, type=Path)
    serve.add_argument("--upstream", default="http://127.0.0.1:8100")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", default=8443, type=int)
    args = parser.parse_args()
    if args.command == "certificates":
        print(json.dumps(create_certificates(args.directory, args.lan_host), indent=2))
        return
    import uvicorn
    if not (args.frontend / "index.html").is_file():
        parser.error("frontend/dist/index.html missing; run npm run build in frontend first")
    for name in ("server.pem", "server-key.pem"):
        if not (args.directory / name).is_file():
            parser.error("TLS files missing; run setup-mobile-web-https.ps1 first")
    app = MobileHttpsProxy(args.upstream, args.frontend, args.directory)
    uvicorn.run(app, host=args.host, port=args.port, ssl_certfile=str(args.directory / "server.pem"),
                ssl_keyfile=str(args.directory / "server-key.pem"), proxy_headers=False,
                access_log=False, timeout_graceful_shutdown=3)


if __name__ == "__main__":
    main()
