"""Optional advisory VLM endpoints.

The validation endpoint is useful even without a model: it lets an edge VLM
or a test fixture prove it obeys the fixed schema.  The ask endpoint never
participates in pin snapping, guidance, or electrical verification.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/vlm")


class ValidateSceneBody(BaseModel):
    response_text: str = Field(min_length=1, max_length=2_000_000)


class AskSceneBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    image_b64: str | None = Field(default=None, max_length=20_000_000)
    cv: dict = Field(default_factory=dict)
    ocr: list[dict] = Field(default_factory=list)
    board_profile: dict = Field(default_factory=dict)


@router.post("/validate")
async def validate_scene(body: ValidateSceneBody, request: Request) -> dict:
    service = request.app.state.vlm_service
    return service.validate(body.response_text).as_dict()


@router.post("/ask")
async def ask_scene(body: AskSceneBody, request: Request) -> dict:
    service = request.app.state.vlm_service
    return service.ask(
        body.prompt,
        body.image_b64,
        body.cv,
        body.ocr,
        body.board_profile,
    ).as_dict()
