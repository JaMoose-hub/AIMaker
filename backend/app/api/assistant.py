from typing import Literal
from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel, Field
from app.assistant import SendRequest
from app.designs import GenerateRequest

router = APIRouter(prefix="/api/assistant/conversations", tags=["assistant"])


class Create(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    kind: Literal["project", "demo"] = "project"
    locale: Literal["zh-TW", "en"] = "zh-TW"
    project_id: str | None = Field(default=None, max_length=100)


class Import(BaseModel):
    source_id: str = Field(min_length=1, max_length=150)
    messages: list[dict] = Field(max_length=1000)
    kind: Literal["legacy-design", "legacy-debug"] = "legacy-design"


class Confirm(BaseModel):
    revision: int = Field(ge=1)
    mode: Literal["builtin", "ai"]
    request_id: str = Field(min_length=1, max_length=100)
    generation: GenerateRequest | None = None


class Reset(BaseModel):
    mode: Literal["clear", "wiring"]
    round: int = Field(default=0, ge=0)


class Retry(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)


def guarded(fn):
    try:
        return fn()
    except OSError as error:
        raise HTTPException(503, "Conversation storage unavailable; existing project preserved") from error


@router.post("")
def create(body: Create, request: Request):
    return guarded(lambda: request.app.state.assistant.create(body.id, body.kind, body.locale, body.project_id))


@router.get("/{cid}")
def read(cid: str, request: Request, before: int | None = Query(default=None, ge=0), limit: int = Query(default=50, ge=1, le=100)):
    return guarded(lambda: request.app.state.assistant.read(cid, before, limit))


@router.post("/{cid}/messages", status_code=202)
def send(cid: str, body: SendRequest, request: Request):
    return guarded(lambda: request.app.state.assistant.send(cid, body))


@router.post("/{cid}/import")
def import_messages(cid: str, body: Import, request: Request):
    return guarded(lambda: request.app.state.assistant.import_messages(cid, body.source_id, body.messages, body.kind))


@router.post("/{cid}/confirm")
def confirm(cid: str, body: Confirm, request: Request):
    return guarded(lambda: request.app.state.assistant.confirm(cid, body.revision, body.mode, body.request_id, body.generation))


@router.post("/{cid}/restore-checklist")
def restore(cid: str, request: Request):
    return guarded(lambda: request.app.state.assistant.restore_checklist(cid))


@router.post("/{cid}/reset")
def reset(cid: str, body: Reset, request: Request):
    return guarded(lambda: request.app.state.assistant.reset_context(cid, body.mode, body.round))


@router.post("/{cid}/jobs/{jid}/retry-image")
def retry(cid: str, jid: str, body: Retry, request: Request):
    return guarded(lambda: request.app.state.assistant.retry_image(cid, jid, body.request_id))
