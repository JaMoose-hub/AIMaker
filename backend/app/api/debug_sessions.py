"""Collaborative physical-debug sessions; fixed actions only."""
from __future__ import annotations
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.api.debug import Context
from app.debug_support import sanitize


router = APIRouter(prefix="/api/debug/sessions", tags=["debug"])


class SessionContext(Context):
    guide_confirmations: dict[str, dict] = Field(default_factory=dict)
    guide_run: int = Field(default=0, ge=0)


class CreateSession(BaseModel):
    context: SessionContext
    symptom: str = Field(min_length=1, max_length=2000)
    model: str | None = Field(default=None, max_length=150)
    effort: str | None = Field(default=None, max_length=20)
    response_mode: Literal["fast", "thorough"] = "fast"
    request_id: str = Field(min_length=1, max_length=100)


class SessionAction(BaseModel):
    action: Literal["ready", "capture", "continue", "message", "stop", "start_trial", "analyse", "context_changed"]
    request_id: str = Field(min_length=1, max_length=100)
    context: SessionContext | None = None
    text: str | None = Field(default=None, max_length=2000)
    response_mode: Literal["fast", "thorough"] | None = None


def _guard(request, fn):
    try:
        return fn()
    except (ValueError, KeyError, SyntaxError, TypeError) as error:
        password = request.app.state.pi_deployer.config.password.get_secret_value()
        raise HTTPException(409, sanitize(str(error), password)) from error


@router.get("")
def active(request: Request, project_id: str | None = None):
    return _guard(request, lambda: request.app.state.debug_sessions.active(project_id))


@router.post("")
def create(body: CreateSession, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.create(
        body.context.model_dump(), body.symptom, body.model, body.effort, body.request_id,
        response_mode=body.response_mode))


@router.get("/{session_id}")
def get(session_id: str, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.get(session_id))


@router.post("/{session_id}/actions")
def action(session_id: str, body: SessionAction, request: Request):
    return _guard(request, lambda: request.app.state.debug_sessions.action(
        session_id, body.action, body.request_id,
        context=body.context.model_dump() if body.context else None, text=body.text,
        response_mode=body.response_mode))


@router.get("/{session_id}/evidence/{capture_id}")
def evidence(session_id: str, capture_id: str, request: Request):
    data = _guard(request, lambda: request.app.state.debug_sessions.evidence(session_id, capture_id))
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
