"""Collaborative physical-debug sessions; fixed actions only."""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.debug import Context
from app.debug_support import sanitize
from app.guided_wiring_review import WiringReviewAction


router = APIRouter(prefix="/api/debug", tags=["debug"])


class WiringTarget(BaseModel):
    component_id: str = Field(min_length=1, max_length=100)
    wire_id: str = Field(min_length=1, max_length=150)


class SessionContext(Context):
    guide_confirmations: dict[str, dict] = Field(default_factory=dict)
    guide_run: int = Field(default=0, ge=0)
    wiring_target: WiringTarget | None = None


class CreateSession(BaseModel):
    context: SessionContext
    symptom: str = Field(min_length=1, max_length=2000)
    model: str | None = Field(default=None, max_length=150)
    effort: str | None = Field(default=None, max_length=20)
    response_mode: Literal["fast", "thorough"] = "fast"
    request_id: str = Field(min_length=1, max_length=100)
    purpose: Literal["debug", "wiring_review"] = "debug"
    conversation_id: str | None = Field(default=None, max_length=100)
    initial_action: Literal["message", "capture", "collect"] | None = None


class SessionAction(BaseModel):
    action: Literal["ready", "capture", "continue", "message", "stop", "start_trial", "analyse", "context_changed", "start_debug", "prepare_wiring", "wiring_review"]
    request_id: str = Field(min_length=1, max_length=100)
    context: SessionContext | None = None
    text: str | None = Field(default=None, max_length=2000)
    response_mode: Literal["fast", "thorough"] | None = None
    wiring_review: WiringReviewAction | None = None


def _guard(request, fn):
    try:
        return fn()
    except (ValueError, KeyError, SyntaxError, TypeError) as error:
        password = request.app.state.pi_deployer.config.password.get_secret_value()
        raise HTTPException(409, sanitize(str(error), password)) from error


@router.get("/sessions")
def active(request: Request, project_id: str | None = None):
    return _guard(request, lambda: request.app.state.debug_sessions.active(project_id))


@router.post("/sessions")
def create(body: CreateSession, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.create(
        body.context.model_dump(), body.symptom, body.model, body.effort, body.request_id,
        response_mode=body.response_mode, purpose=body.purpose, conversation_id=body.conversation_id,
        initial_action=body.initial_action))


@router.get("/sessions/{session_id}")
def get(session_id: str, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.get(session_id))


@router.post("/sessions/{session_id}/actions")
def action(session_id: str, body: SessionAction, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.action(
        session_id, body.action, body.request_id,
        context=body.context.model_dump() if body.context else None, text=body.text,
        response_mode=body.response_mode, wiring_review=body.wiring_review.model_dump() if body.wiring_review else None))


@router.get("/sessions/{session_id}/evidence/{capture_id}")
def evidence(session_id: str, capture_id: str, request: Request, view: str = "overview"):
    data, mime = _guard(request, lambda: request.app.state.debug_sessions.evidence_view(session_id, capture_id, view))
    return Response(data, media_type=mime, headers={"Cache-Control": "no-store"})


@router.get("/conversations")
def conversation_for_project(request: Request, project_id: str):
    return _guard(request, lambda: request.app.state.debug_sessions.conversation_for_project(project_id))


class RestartConversation(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)
    expected_conversation_id: str | None = Field(default=None, min_length=1, max_length=100)


@router.post("/conversations/restart")
def restart_conversation(body: RestartConversation, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.restart_conversation(
        body.project_id, body.request_id, body.expected_conversation_id))


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: str, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.conversation(conversation_id))


class DiagramRequest(BaseModel):
    context: SessionContext


@router.post("/conversations/{conversation_id}/diagrams")
def create_diagram(conversation_id: str, body: DiagramRequest, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.create_diagram(conversation_id, body.context.model_dump()))


@router.get("/conversations/{conversation_id}/diagrams/{snapshot_id}")
def diagram(conversation_id: str, snapshot_id: str, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.diagram(conversation_id, snapshot_id))
