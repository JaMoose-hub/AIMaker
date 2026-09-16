"""Minimal controls for the R1 + Eye stream session."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, model_validator

router = APIRouter(prefix="/api/glasses")


class GlassesSettings(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: Literal[30, 60] = 30
    denoise: Literal["original", "clean", "strong"] = "clean"

    @model_validator(mode="after")
    def supported_resolution(self):
        if (self.width, self.height) not in (
            (1920, 1080), (2048, 1512), (1080, 1920), (720, 1280),
        ):
            raise ValueError("Unsupported Eye resolution")
        return self


@router.get("/stream")
async def stream_status(request: Request):
    return await asyncio.to_thread(request.app.state.glasses_stream.snapshot)


@router.put("/stream")
async def configure_stream(body: GlassesSettings, request: Request):
    return await asyncio.to_thread(
        request.app.state.glasses_stream.configure, body.model_dump(),
    )


@router.delete("/stream")
async def stop_stream(request: Request):
    return await asyncio.to_thread(request.app.state.glasses_stream.restore)
