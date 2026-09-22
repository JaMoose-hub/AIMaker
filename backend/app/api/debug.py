from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Literal
from app.debug_support import sanitize

router = APIRouter(prefix="/api/debug", tags=["debug"])


class Context(BaseModel):
    project: dict | None = None
    code: str = Field(default="", max_length=200000)
    test_keys: dict[str, str] = Field(default_factory=dict)
    entry: dict = Field(default_factory=dict)


class Diagnose(BaseModel):
    context: Context
    case_id: str | None = None


class Action(BaseModel):
    action: Literal["analyse", "apply", "restore"]
    context: Context
    model: str | None = Field(default=None, max_length=150)
    effort: str | None = Field(default=None, max_length=20)
    candidate_id: str | None = None
    confirmed: bool = False


class Trial(BaseModel):
    context: Context
    request_id: str = Field(min_length=1, max_length=100)


class TrialAction(BaseModel):
    action: Literal["stop", "visual"]
    context: Context | None = None
    observed: bool = False


def guarded(fn, request: Request):
    try:
        return fn()
    except (ValueError, KeyError, SyntaxError, TypeError) as error:
        password = request.app.state.debug_cases.pi.config.password.get_secret_value()
        raise HTTPException(409, sanitize(str(error), password)) from error


@router.post("/cases")
def diagnose(body: Diagnose, request: Request):
    return guarded(lambda: request.app.state.debug_cases.diagnose(body.context.model_dump(), body.case_id), request)


@router.get("/cases/{case_id}")
def case(case_id: str, request: Request):
    return guarded(lambda: request.app.state.debug_cases.get(case_id), request)


@router.post("/cases/{case_id}/actions")
def case_action(case_id: str, body: Action, request: Request):
    service = request.app.state.debug_cases
    context = body.context.model_dump()
    if body.action == "analyse":
        return guarded(lambda: service.analyse(case_id, context, body.model, body.effort), request)
    if not body.confirmed:
        raise HTTPException(409, "confirmation_required")
    if body.action == "apply":
        return guarded(lambda: service.apply(case_id, body.candidate_id, context), request)
    return guarded(lambda: service.restore(case_id, context), request)


@router.get("/trials")
def trials(request: Request, project_id: str | None = None):
    return request.app.state.integration_trials.status(project_id)


@router.post("/trials")
def trial(body: Trial, request: Request):
    context = body.context.model_dump()
    guarded(lambda: request.app.state.integration_trials.validate(context), request)
    return guarded(lambda: {"job_id": request.app.state.pi_execution.submit("trial", context, body.request_id)}, request)


@router.post("/trials/{run_id}/actions")
def trial_action(run_id: str, body: TrialAction, request: Request):
    return guarded(lambda: request.app.state.integration_trials.action(run_id, body.action, body.context.model_dump() if body.context else None, body.observed), request)
