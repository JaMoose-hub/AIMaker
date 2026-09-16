"""GET /video - MJPEG stream (multipart/x-mixed-replace; boundary=frame).

Each connected client runs its own async generator that pulls the latest
frame from the FrameBus (skipping frames it is too slow for). Native MJPEG
camera frames are passed through directly; other sources are JPEG-encoded in
a threadpool executor so the event loop is never blocked.
"""
from __future__ import annotations

import asyncio
import logging

import cv2
import numpy as np
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

log = logging.getLogger(__name__)

router = APIRouter()

_BOUNDARY = "frame"
_MEDIA_TYPE = f"multipart/x-mixed-replace; boundary={_BOUNDARY}"
_WAIT_S = 0.5  # per get_latest call; loop continues while client is connected
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "X-Accel-Buffering": "no",
}


def _encode_jpeg(frame: np.ndarray, quality: int) -> bytes | None:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    return buf.tobytes() if ok else None


def _part(jpeg: bytes) -> bytes:
    return (
        f"--{_BOUNDARY}\r\n"
        f"Content-Type: image/jpeg\r\n"
        f"Content-Length: {len(jpeg)}\r\n\r\n"
    ).encode("ascii") + jpeg + b"\r\n"


@router.get("/video")
async def video(request: Request) -> StreamingResponse:
    bus = request.app.state.frame_bus
    quality = request.app.state.config.jpeg_quality

    async def gen():
        loop = asyncio.get_running_loop()
        last_seq = -1
        try:
            while True:
                if await request.is_disconnected():
                    break
                slot = await loop.run_in_executor(None, bus.get_latest, _WAIT_S, last_seq)
                if slot is None:
                    continue
                last_seq = slot.seq
                jpeg = slot.jpeg
                if jpeg is None:
                    jpeg = await loop.run_in_executor(
                        None, _encode_jpeg, slot.frame, quality
                    )
                if jpeg is None:
                    log.warning("JPEG encode failed for frame_id=%d", slot.frame_id)
                    continue
                yield _part(jpeg)
        except asyncio.CancelledError:
            # client disconnected mid-stream
            raise
        finally:
            log.debug("MJPEG client disconnected")

    return StreamingResponse(gen(), media_type=_MEDIA_TYPE, headers=_NO_CACHE_HEADERS)


@router.get("/frame.jpg")
async def frame_jpeg(request: Request) -> Response:
    """Return one complete latest frame for browsers that cannot paint MJPEG.

    Some embedded Chromium surfaces keep a multipart ``<img>`` request open
    without ever publishing its first decoded frame.  The frontend normally
    uses ``/video`` and falls back to this finite response only when that
    startup event does not arrive.
    """
    bus = request.app.state.frame_bus
    quality = request.app.state.config.jpeg_quality
    loop = asyncio.get_running_loop()
    slot = await loop.run_in_executor(None, bus.get_latest, _WAIT_S)
    if slot is None:
        return Response(
            status_code=503,
            headers={**_NO_CACHE_HEADERS, "Retry-After": "1"},
        )

    jpeg = slot.jpeg
    if jpeg is None:
        jpeg = await loop.run_in_executor(None, _encode_jpeg, slot.frame, quality)
    if jpeg is None:
        return Response(
            status_code=503,
            headers={**_NO_CACHE_HEADERS, "Retry-After": "1"},
        )

    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            **_NO_CACHE_HEADERS,
            "X-Frame-Id": str(slot.frame_id),
            "X-Frame-Seq": str(slot.seq),
        },
    )
