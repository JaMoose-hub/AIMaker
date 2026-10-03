"""Paired phone API and loopback-only desktop companion controls."""
from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path
import tempfile
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.designs import GenerateRequest
from app.mobile import MAX_UPLOAD
from app.mobile_web import ROOT as WEB_ROOT, web_configuration

router = APIRouter(prefix="/api/mobile", tags=["mobile"])


def desktop(request):
    host = request.client.host if request.client else ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if not local:
        raise HTTPException(403, "mobile_desktop_control_requires_loopback")


def identity(request, sid=None):
    service = request.app.state.mobile_service
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        paired = service.authorize(header[7:])
        if sid is not None and sid != paired:
            raise HTTPException(403, "mobile_session_mismatch")
        return paired
    desktop(request)
    if sid is None:
        raise HTTPException(401, "mobile_session_required")
    service.require(sid)
    return sid


class ContextBody(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="Tinkro", max_length=200)
    stage: Literal["design", "guide", "deploy"] = "design"
    target: Literal["auto", "design", "wiring", "debug"] = "auto"
    design: GenerateRequest
    context: dict = Field(default_factory=dict)
    round: int = Field(default=0, ge=0)


class PairingBody(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)


class PairBody(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")
    device_name: str = Field(default="iPhone", min_length=1, max_length=100)


class MessageBody(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=8000)
    asset_ids: list[str] = Field(default_factory=list, max_length=4)
    inherit_media: bool = True
    context_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = None
    capture_id: str | None = None
    check_scope: Literal["one", "all"] | None = None
    wire_id: str | None = None


class OfferBody(BaseModel):
    sdp: str = Field(min_length=1, max_length=200000)
    type: Literal["offer"]
    role: Literal["publisher", "viewer"]
    generation: int = Field(ge=1)
    session_id: str | None = None


class StreamBody(BaseModel):
    bitrate_kbps: Literal[3000, 8000, 12000] = 8000


class StreamMetricsBody(BaseModel):
    generation: int = Field(ge=1, strict=True)
    capture_fps: float | None = Field(default=None, ge=0, le=240, allow_inf_nan=False, strict=True)
    send_fps: float | None = Field(default=None, ge=0, le=240, allow_inf_nan=False, strict=True)
    send_bitrate_kbps: float | None = Field(default=None, ge=0, le=100000, allow_inf_nan=False, strict=True)
    width: int | None = Field(default=None, ge=1, le=16384, strict=True)
    height: int | None = Field(default=None, ge=1, le=16384, strict=True)
    rtt_ms: float | None = Field(default=None, ge=0, le=600000, allow_inf_nan=False, strict=True)
    quality_limitation_reason: str | None = Field(default=None, max_length=64)


class CaptureBody(BaseModel):
    capture_source: Literal["camera_photo", "phone_frame"] = "camera_photo"
    ticket_id: str = Field(min_length=1, max_length=100)
    asset_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = None


class ViewBody(BaseModel):
    capture_id: str | None = None
    wire_id: str | None = None
    session_id: str | None = None


@router.post("/context")
def context(body: ContextBody, request: Request):
    desktop(request)
    return request.app.state.mobile_service.publish_context(body.model_dump())


@router.post("/pairings")
def pairing(body: PairingBody, request: Request):
    desktop(request)
    web = web_configuration()
    base = body.base_url or (web["base_url"] if web["available"] else str(request.base_url))
    return request.app.state.mobile_service.create_pairing(body.conversation_id, base)


@router.get("/web-config")
def web_config(request: Request):
    desktop(request)
    return web_configuration()


@router.get("/web-ca")
def web_ca():
    path = WEB_ROOT / "rootCA.der"
    if not path.is_file():
        raise HTTPException(404, "mobile_web_https_not_configured")
    return FileResponse(path, media_type="application/x-x509-ca-cert", filename="Tinkro-Local-CA.cer")


@router.get("/web-ca-profile")
def web_ca_profile():
    path = WEB_ROOT / "rootCA.mobileconfig"
    if not path.is_file():
        raise HTTPException(404, "mobile_web_https_not_configured")
    return FileResponse(path, media_type="application/x-apple-aspen-config", filename="Tinkro-Local-CA.mobileconfig")


@router.post("/pair")
def pair(body: PairBody, request: Request):
    return request.app.state.mobile_service.pair(body.code, body.device_name)


@router.get("/session")
def session(request: Request, session_id: str | None = None):
    return request.app.state.mobile_service.snapshot(identity(request, session_id))


@router.delete("/session", status_code=204)
async def disconnect(request: Request):
    service = request.app.state.mobile_service
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "mobile_session_required")
    await service.disconnect(service.authorize(header[7:]))
    return Response(status_code=204)


@router.get("/desktop-session")
def desktop_session(request: Request, conversation_id: str):
    desktop(request)
    return request.app.state.mobile_service.desktop_snapshot(conversation_id)


@router.post("/join")
async def join(request: Request):
    return await request.app.state.mobile_service.join(identity(request))


@router.get("/conversation")
def conversation(request: Request, before: int | None = Query(default=None, ge=0), limit: int = Query(default=50, ge=1, le=100), session_id: str | None = None):
    service = request.app.state.mobile_service
    sid = identity(request, session_id)
    return request.app.state.assistant.read(service.require(sid)["conversation_id"], before, limit)


@router.post("/messages", status_code=202)
def message(body: MessageBody, request: Request):
    sid = identity(request, body.session_id)
    return request.app.state.mobile_service.send(sid, body.model_dump(exclude={"session_id"}))


@router.post("/assets")
async def upload(request: Request, file: UploadFile = File(...), upload_id: str = Form(...)):
    service = request.app.state.mobile_service
    sid = identity(request)
    session = service.snapshot(sid)
    service.root.mkdir(parents=True, exist_ok=True)
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=service.root, suffix=".upload", delete=False) as pending:
            path = Path(pending.name)
            count = 0
            while chunk := await file.read(1024*1024):
                count += len(chunk)
                if count > MAX_UPLOAD:
                    raise HTTPException(413, "mobile_upload_size_limit")
                pending.write(chunk)
        return await asyncio.to_thread(service.assets.ingest, path,
            conversation_id=session["conversation_id"], session_id=sid, upload_id=upload_id,
            filename=file.filename, content_type=file.content_type)
    finally:
        await file.close()
        if path is not None:
            path.unlink(missing_ok=True)


def asset_access(request, aid):
    service = request.app.state.mobile_service
    if request.headers.get("authorization", "").startswith("Bearer "):
        sid = identity(request)
        service.assets.authorize(aid, service.require(sid)["conversation_id"])
    else:
        desktop(request)
    return service.assets


@router.get("/assets/{aid}/file")
def asset_file(aid: str, request: Request):
    assets = asset_access(request, aid)
    return FileResponse(assets.path(aid), media_type=assets.describe(aid)["mime"], headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.get("/assets/{aid}/thumbnail")
def asset_thumbnail(aid: str, request: Request):
    return FileResponse(asset_access(request, aid).path(aid, thumbnail=True), media_type="image/jpeg")


@router.post("/stream")
async def start_stream(request: Request, body: StreamBody | None = None, session_id: str | None = None):
    return await request.app.state.mobile_service.start_stream(identity(request, session_id),
        bitrate_kbps=body.bitrate_kbps if body else 8000)


@router.post("/stream/metrics")
def stream_metrics(body: StreamMetricsBody, request: Request):
    return request.app.state.mobile_service.publisher_metrics(identity(request), body.model_dump())


@router.post("/stream/offer")
async def offer(body: OfferBody, request: Request):
    service = request.app.state.mobile_service
    sid = identity(request, body.session_id)
    return await service.rtc.offer(sid, body.sdp, body.type, body.role, body.generation)


@router.delete("/stream")
async def stop_stream(request: Request, session_id: str | None = None):
    return await request.app.state.mobile_service.stop_stream(identity(request, session_id))


class StreamCaptureBody(BaseModel):
    generation: int = Field(ge=1, strict=True)
    context_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    session_id: str | None = None


@router.post("/stream-capture")
async def stream_capture(body: StreamCaptureBody, request: Request):
    return await request.app.state.mobile_service.capture_stream(identity(request, body.session_id),
        body.model_dump(exclude={"session_id"}))


@router.post("/capture-ticket")
def ticket(request: Request, session_id: str | None = None):
    return request.app.state.mobile_service.capture_ticket(identity(request, session_id))


@router.post("/captures")
async def capture(body: CaptureBody, request: Request):
    sid = identity(request, body.session_id)
    return await request.app.state.mobile_service.finalize_capture(sid, body.model_dump(exclude={"session_id"}))


@router.get("/captures/{cid}")
def captured(cid: str, request: Request):
    service = request.app.state.mobile_service
    if request.headers.get("authorization", "").startswith("Bearer "):
        return service.capture(cid, identity(request))
    desktop(request)
    return service.capture(cid)


@router.get("/view")
def get_view(request: Request, session_id: str | None = None):
    return request.app.state.mobile_service.view(identity(request, session_id))


@router.put("/view")
def put_view(body: ViewBody, request: Request):
    return request.app.state.mobile_service.view(identity(request, body.session_id), body.model_dump(exclude={"session_id"}))


@router.websocket("/events")
async def events(ws: WebSocket):
    service = ws.app.state.mobile_service
    sid = cid = None
    try:
        if ws.query_params.get("token"):
            sid = service.authorize(ws.query_params["token"])
        else:
            desktop(ws)
            cid = ws.query_params.get("conversation_id")
            if not cid:
                raise HTTPException(422, "mobile_conversation_required")
        await ws.accept()
    except HTTPException:
        await ws.close(code=1008)
        return
    listener = service.subscribe(sid=sid, cid=cid)
    receiver = asyncio.create_task(ws.receive())
    waiting = None
    try:
        initial = service.snapshot(sid) if sid else service.desktop_snapshot(cid)["session"]
        await ws.send_json({"type": "state", "session": initial})
        while True:
            waiting = asyncio.create_task(listener[3].get())
            done, _ = await asyncio.wait({waiting, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                if receiver.result().get("type") == "websocket.disconnect":
                    break
                receiver = asyncio.create_task(ws.receive())
            if waiting in done:
                packet = waiting.result()
                await ws.send_json(packet)
                if sid and packet.get("type") == "disconnected":
                    await ws.close(code=1000)
                    break
            else:
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        service.unsubscribe(listener)
        receiver.cancel()
        if waiting is not None:
            waiting.cancel()
        await asyncio.gather(receiver, *([waiting] if waiting else []), return_exceptions=True)
