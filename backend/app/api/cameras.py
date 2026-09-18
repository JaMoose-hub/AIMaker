"""GET /api/cameras, POST /api/cameras/select (docs/api-contract.md §7).

Lets the user pick, from the running app, which physical camera index is the
live feed - without an assistant/operator manually setting
BOARDVISION_CAMERA__DEVICE_INDEX and restarting the whole backend process.

Only meaningful when config.camera.source == "device" (checked the same way
GET /api/config already exposes it: request.app.state.config.camera.source -
reused here, not re-derived). In "synthetic" mode there is no physical
camera to enumerate or switch, so both endpoints degrade to an
explicitly-empty/not_applicable response rather than erroring.

Windows/OpenCV exclusive-access constraint (empirically verified in this
codebase's development, see app/capture/sources.py's DeviceCameraSource):
opening a SECOND cv2.VideoCapture on an index some other capture handle
already holds open fails or misbehaves. GET /api/cameras must therefore never
open a second handle on the index the app's own CaptureService is currently
reading from - it sources that entry's thumbnail from the live FrameBus
instead, and only opens fresh handles (briefly, then releases) for every
OTHER index.

HTTP 200 in ALL expected outcomes for POST /api/cameras/select (success or a
recognised failure code), mirroring POST /api/calibrate's established
convention exactly. Real HTTP error codes are reserved for malformed request
bodies (FastAPI/pydantic -> 422) or genuinely unexpected server errors.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import sys

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.errors import expected_error
from app.api.camera_tuning import camera_mutation_guard
from app.capture.sources import frame_has_signal, read_signal_frame

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_THUMB_W, _THUMB_H = 160, 90
_THUMB_JPEG_QUALITY = 70
_CURRENT_FRAME_TIMEOUT_S = 0.5
# Per-index wall-clock cap for probing an OTHER (non-current) index, so a
# device whose driver stalls on open can't hang this endpoint. asyncio.wait_for
# only stops US waiting - the underlying cv2.VideoCapture() call keeps running
# to completion in its executor thread in the background - but that is enough
# to bound the *response*, which is the actual requirement.
_PROBE_TIMEOUT_S = 1.5


def _eye_indices(capture_api: str) -> set[int]:
    """Read device metadata only; R1 must never be opened by the DShow probe."""
    if sys.platform != "win32":
        return set()
    try:
        import cv2
        from cv2_enumerate_cameras import enumerate_cameras
        api = cv2.CAP_DSHOW if capture_api == "dshow" else cv2.CAP_MSMF
        return {camera.index for camera in enumerate_cameras(api)
                if (camera.vid, camera.pid) == (0x0B05, 0x1D9D)}
    except ImportError:
        return set()

class SelectRequest(BaseModel):
    index: int


def _fail(error: str) -> dict:
    return expected_error(error)


def _encode_thumbnail(frame) -> str | None:
    """Downscale to ~160x90 (preserving aspect) and JPEG+base64 encode."""
    import cv2

    h, w = frame.shape[:2]
    if w <= 0 or h <= 0:
        return None
    scale = min(_THUMB_W / w, _THUMB_H / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    small = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), _THUMB_JPEG_QUALITY])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _probe_other_index(index: int, width: int, height: int,
                       capture_api: str = "dshow", buffer_size: int = 1) -> dict:
    """Briefly open `index` (which must NOT be the index the app's own
    CaptureService already holds - see module docstring), grab a bounded
    warm-up window, and release immediately. Runs in a worker thread
    (blocking cv2 calls).
    Never raises - any failure just means "unavailable".

    capture_api mirrors CameraConfig.capture_api and MUST match the API the
    live stream uses: observed live 2026-07-29, probing via MSMF while the
    active stream held the device via DirectShow first wedged the whole
    MSMF FrameServer session (open() hanging forever even in fresh
    processes, USB replug required) and later killed the backend process
    outright when the camera-picker UI triggered this endpoint. DirectShow
    opens of a busy device fail fast instead of hanging."""
    import cv2

    api = cv2.CAP_DSHOW if capture_api == "dshow" else cv2.CAP_MSMF
    cap = None
    frame = None
    ok = False
    saw_black = False
    try:
        # Keep this in lock-step with DeviceCameraSource's candidate order.
        # The driver-default candidate intentionally does not set dimensions:
        # some cameras only produce a valid low-resolution stream in their
        # native mode after both requested MJPG/YUY2 modes fail.
        for codec in ("MJPG", "YUY2", None):
            cap = cv2.VideoCapture(index, api)
            if not cap.isOpened():
                cap.release()
                cap = None
                continue
            try:
                buffer_prop = getattr(cv2, "CAP_PROP_BUFFERSIZE", None)
                if buffer_prop is not None:
                    cap.set(buffer_prop, max(1, min(int(buffer_size), 8)))
                if codec is not None:
                    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*codec))
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                frame, saw_frame = read_signal_frame(cap)
                ok = frame is not None
            except Exception:
                log.debug("camera probe %d: %s read/config failed", index, codec or "default", exc_info=True)
                ok, frame = False, None
                saw_frame = False
            if ok:
                break
            saw_black = saw_black or saw_frame
            cap.release()
            cap = None
        if not ok or not frame_has_signal(frame):
            entry = {"index": index, "available": False, "is_current": False}
            if saw_black:
                entry["signal_status"] = "black"
            return entry
        h, w = frame.shape[:2]
        entry = {"index": index, "available": True, "is_current": False,
                  "width": int(w), "height": int(h)}
        thumb = _encode_thumbnail(frame)
        if thumb is not None:
            entry["thumbnail_b64"] = thumb
        return entry
    except Exception:
        log.exception("camera probe %d: unexpected error", index)
        return {"index": index, "available": False, "is_current": False}
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                log.debug("camera probe %d: release failed", index, exc_info=True)


def _current_index(state) -> int | None:
    source = getattr(state, "source", None)
    if source is None:
        return None
    try:
        return int(source.current_index)
    except Exception:
        log.debug("camera source has no usable current_index", exc_info=True)
        return None


@router.get("/cameras")
async def get_cameras(request: Request) -> dict:
    state = request.app.state
    config = state.config
    if config.camera.source != "device":
        return {"cameras": []}

    current = _current_index(state)
    width, height = config.camera.width, config.camera.height
    max_index = config.camera.max_probe_index

    indices = list(range(0, max_index + 1))
    eye_indices = await asyncio.to_thread(_eye_indices, config.camera.capture_api)
    if current is not None and current not in indices:
        indices.append(current)  # always represent the live index, even if
        indices.sort()           # it's outside the configured probe range

    loop = asyncio.get_running_loop()
    results: dict[int, dict] = {}

    async def probe(i: int) -> None:
        if i in eye_indices:
            results[i] = {"index": i, "available": False, "is_current": False,
                          "source": "xreal", "name": "R1 + Eye"}
            return
        if i == current:
            # Never open a second handle on the index we already hold open -
            # source the thumbnail from the live FrameBus instead.
            slot = await loop.run_in_executor(
                None, state.frame_bus.get_latest, _CURRENT_FRAME_TIMEOUT_S
            )
            has_signal = slot is not None and frame_has_signal(slot.frame)
            entry: dict = {"index": i, "available": has_signal, "is_current": True}
            if slot is not None and not has_signal:
                entry["signal_status"] = "black"
            if has_signal and slot is not None:
                h, w = slot.frame.shape[:2]
                entry["width"] = int(w)
                entry["height"] = int(h)
                thumb = await loop.run_in_executor(None, _encode_thumbnail, slot.frame)
                if thumb is not None:
                    entry["thumbnail_b64"] = thumb
            results[i] = entry
            return
        try:
            entry = await asyncio.wait_for(
                loop.run_in_executor(None, _probe_other_index, i, width, height,
                                     config.camera.capture_api,
                                     config.camera.buffer_size),
                timeout=_PROBE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            entry = {"index": i, "available": False, "is_current": False}
        results[i] = entry

    await asyncio.gather(*(probe(i) for i in indices))
    return {"cameras": [results[i] for i in indices]}


@router.post("/cameras/select", dependencies=[Depends(camera_mutation_guard)])
async def post_cameras_select(body: SelectRequest, request: Request) -> JSONResponse:
    state = request.app.state
    config = state.config

    if config.camera.source != "device":
        return JSONResponse(status_code=200, content=_fail("not_applicable"))

    max_index = config.camera.max_probe_index
    if body.index < 0 or body.index > max_index:
        return JSONResponse(status_code=200, content=_fail("invalid_index"))

    if body.index in await asyncio.to_thread(_eye_indices, config.camera.capture_api):
        return JSONResponse(status_code=200, content=_fail("not_applicable"))

    current = _current_index(state)
    if current is not None and body.index == current:
        return JSONResponse(status_code=200, content=_fail("same_as_current"))

    # The switch attempt itself IS the availability check (per docs/api-
    # contract.md §7): actually opening the device and confirming it yields
    # a frame is the only reliable signal on Windows/OpenCV (see
    # DeviceCameraSource.switch_to docstring) - a separate pre-probe here
    # would just open the same handle twice for no added certainty.
    loop = asyncio.get_running_loop()
    ok, width, height = await loop.run_in_executor(None, state.source.switch_to, body.index)
    if not ok:
        return JSONResponse(status_code=200, content=_fail("open_failed"))

    return JSONResponse(
        status_code=200,
        content={"ok": True, "index": body.index, "width": width, "height": height},
    )
