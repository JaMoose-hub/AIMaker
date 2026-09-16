"""Controller discovery and atomic runtime selection endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.runtime import RuntimeSwitchError

router = APIRouter(prefix="/api/controllers")


class ControllerSelectRequest(BaseModel):
    board_id: str


@router.get("")
async def get_controllers(request: Request) -> dict[str, object]:
    return request.app.state.runtime_manager.controllers()


@router.post("/select")
async def select_controller(
    body: ControllerSelectRequest,
    request: Request,
):
    try:
        result = await asyncio.to_thread(
            request.app.state.runtime_manager.select,
            body.board_id,
            request.app.state,
        )
    except RuntimeSwitchError as exc:
        return JSONResponse(
            status_code=(404 if exc.error_code == "controller_not_found" else 409),
            content={
                "ok": False,
                "error_code": exc.error_code,
                "params": exc.params,
            },
        )
    return result
