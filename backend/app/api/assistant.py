from typing import Literal
from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel, Field
from app.assistant import SendRequest, TestHelpMetadata, TestHelpAction
from app.designs import GenerateRequest
from app.api.debug_sessions import SessionContext
from app.guided_wiring_review import WiringReviewAction

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
    test_help: TestHelpMetadata | None = None


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


class WiringFlowAction(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    message_id: str = Field(min_length=1, max_length=100)
    flow_id: str = Field(min_length=1, max_length=100)
    action: WiringReviewAction
    context: SessionContext | None = None


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
    return guarded(lambda: request.app.state.assistant.import_messages(cid, body.source_id, body.messages, body.kind,
        body.test_help.model_dump() if body.test_help else None))


@router.post("/{cid}/test-help")
def test_help_action(cid: str, body: TestHelpAction, request: Request):
    from app.api.mobile import desktop
    desktop(request)
    try:
        return guarded(lambda: request.app.state.mobile_service.test_help_action(cid, body.model_dump()))
    except (ValueError, KeyError) as error:
        raise HTTPException(409, str(error)) from error


@router.post("/{cid}/confirm")
def confirm(cid: str, body: Confirm, request: Request):
    return guarded(lambda: request.app.state.assistant.confirm(cid, body.revision, body.mode, body.request_id, body.generation))


@router.post("/{cid}/wiring-flow")
def wiring_flow_action(cid: str, body: WiringFlowAction, request: Request):
    from app.api.mobile import desktop
    desktop(request)
    return guarded(lambda: request.app.state.assistant.wiring_flow_action(cid, body.model_dump()))


@router.get("/{cid}/wiring-flow/receipts/{request_id}")
def wiring_flow_receipt(cid: str, request_id: str, request: Request):
    from app.api.mobile import desktop
    desktop(request)
    if not 0 < len(request_id) <= 100:
        raise HTTPException(422, "Invalid request ID")
    return guarded(lambda: request.app.state.assistant.wiring_flow_receipt(cid, request_id))


@router.post("/{cid}/restore-checklist")
def restore(cid: str, request: Request):
    return guarded(lambda: request.app.state.assistant.restore_checklist(cid))


@router.post("/{cid}/reset")
def reset(cid: str, body: Reset, request: Request):
    return guarded(lambda: request.app.state.assistant.reset_context(cid, body.mode, body.round))


@router.post("/{cid}/jobs/{jid}/retry-image")
def retry(cid: str, jid: str, body: Retry, request: Request):
    return guarded(lambda: request.app.state.assistant.retry_image(cid, jid, body.request_id))
