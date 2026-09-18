"""Live webcam focus control + an assisted focus sweep (docs/api-contract.md §9).

Why this exists: `camera.focus` in config.yaml only applies at cold start, so
tuning it meant edit -> restart -> look -> guess again. Worse, a manual focus
value is a bare driver number with no meaning to a human - there is no way to
know 10 is right and 50 is useless without measuring.

The sweep endpoint measures it: step the focus across its range, sample real
frames, score each with Laplacian variance over the region that actually
matters, and return the whole curve plus the peak. Measured on the C920 via
DirectShow 2026-08-01, the curve is unambiguous - focus 10 scored 944.7 while
focus 50 scored 77.8 (12x), with a sharp falloff either side - so picking the
peak is reliable rather than a coin toss between neighbouring values.

Honesty note on the metric: Laplacian variance is a per-pixel second
derivative, so it is NOT comparable across resolutions or across different
ROIs (this project already drew a wrong conclusion once by comparing 720p and
1080p variance directly - see docs/accuracy-improvement-plan.md §1.2). Within
one sweep it IS valid: same resolution, same ROI, only focus changes. Never
compare a score from one sweep against a score from another.

Endpoints follow the existing 200 + ok:true/false convention; real HTTP error
codes are reserved for malformed requests.
"""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.errors import expected_error
from app.api.camera_tuning import camera_mutation_guard

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

# Driver settle time after a focus change before the image is trustworthy.
# The C920's lens motor needs a moment; 0.5s was the value used for the
# measured sweep above (0.3s occasionally caught a frame mid-travel).
_SETTLE_S = 0.5
# Frames sampled per focus step. The score is the MAX over the samples, not
# the mean: a single motion-blurred or rolling-shutter-smeared frame should
# not penalise an otherwise sharp focus position.
_SAMPLES_PER_STEP = 5
# How long to wait for a genuinely new frame from the bus per sample.
_FRAME_WAIT_S = 0.5


class FocusBody(BaseModel):
    """Either a manual focus value, or auto:true to hand control back."""
    value: float | None = None
    auto: bool = False


class SweepBody(BaseModel):
    # C920 range is 0-250 in steps of 5; default to the region where the
    # measured peak lives, with enough margin to see the falloff on both
    # sides (a peak at the edge of the swept range is not a peak).
    start: float = Field(default=0.0, ge=0.0, le=1000.0)
    end: float = Field(default=60.0, ge=0.0, le=1000.0)
    step: float = Field(default=5.0, gt=0.0, le=250.0)
    apply_best: bool = True


def _device_source(state):
    """The live DeviceCameraSource, or None when the running source is not a
    physical camera (synthetic/window) or predates focus support."""
    source = getattr(state, "source", None)
    if source is None or not hasattr(source, "set_focus"):
        return None
    return source


def _sharpness_roi(frame: np.ndarray, detection) -> tuple[np.ndarray, str]:
    """The region the score is computed over.

    Prefer the tracked board: focusing on the desk is useless, and the desk
    is nearly featureless so its variance would swamp the signal with noise.
    Falls back to the centre third when the board is not located.
    """
    h, w = frame.shape[:2]
    outline = getattr(detection, "outline_px", None) if detection is not None else None
    if outline:
        pts = np.asarray(outline, dtype=np.float32)
        x0 = max(0, int(pts[:, 0].min()))
        x1 = min(w, int(np.ceil(pts[:, 0].max())))
        y0 = max(0, int(pts[:, 1].min()))
        y1 = min(h, int(np.ceil(pts[:, 1].max())))
        # Guard against a degenerate/offscreen outline.
        if x1 - x0 >= 32 and y1 - y0 >= 32:
            return frame[y0:y1, x0:x1], "board"
    return frame[h // 3: 2 * h // 3, w // 3: 2 * w // 3], "centre"


def _score(frame_bgr: np.ndarray, detection) -> tuple[float, str]:
    import cv2

    roi, kind = _sharpness_roi(frame_bgr, detection)
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()), kind


@router.get("/camera/focus")
async def get_focus(request: Request) -> dict:
    state = request.app.state
    source = _device_source(state)
    if source is None:
        return expected_error("not_a_device_camera")
    return {"ok": True, **source.focus_state()}


@router.post("/camera/focus", dependencies=[Depends(camera_mutation_guard)])
async def set_focus(body: FocusBody, request: Request) -> dict:
    state = request.app.state
    source = _device_source(state)
    if source is None:
        return expected_error("not_a_device_camera")
    if not body.auto and body.value is None:
        return expected_error("no_value")

    loop = asyncio.get_running_loop()
    target = None if body.auto else body.value
    accepted, read_back = await loop.run_in_executor(None, source.set_focus, target)
    return {"ok": True, "accepted": accepted, "read_back": read_back,
            "mode": "auto" if body.auto else "manual",
            "requested": target}


@router.post("/camera/focus/sweep", dependencies=[Depends(camera_mutation_guard)])
async def sweep_focus(body: SweepBody, request: Request) -> dict:
    """Step through focus values, score each on real frames, return the curve.

    Returns the FULL curve, not just the winner: a human reading the shape can
    tell a real peak from a flat/noisy scan, which a single number hides. If
    the best score sits at either end of the swept range the peak may be
    outside it - that is reported as `peak_at_edge` rather than silently
    returned as if it were an optimum.
    """
    state = request.app.state
    source = _device_source(state)
    if source is None:
        return expected_error("not_a_device_camera")
    if body.end < body.start:
        return expected_error("bad_range", start=body.start, end=body.end)

    bus = getattr(state, "frame_bus", None)
    if bus is None:
        return expected_error("no_frame_bus")
    detection_state = getattr(state, "detection_state", None)

    loop = asyncio.get_running_loop()
    values: list[float] = []
    v = float(body.start)
    while v <= body.end + 1e-9:
        values.append(round(v, 3))
        v += body.step
    if len(values) < 2:
        return expected_error("bad_range", sample_count=len(values))

    original = source.focus_state()
    curve: list[dict] = []
    roi_kinds: set[str] = set()

    for value in values:
        await loop.run_in_executor(None, source.set_focus, value)
        await asyncio.sleep(_SETTLE_S)
        detection = detection_state.get() if detection_state is not None else None
        best = -1.0
        samples = 0
        last_seq = bus.latest_seq  # property, not a method
        for _ in range(_SAMPLES_PER_STEP):
            slot = await loop.run_in_executor(
                None, bus.get_latest, _FRAME_WAIT_S, last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            score, kind = await loop.run_in_executor(None, _score, slot.frame, detection)
            roi_kinds.add(kind)
            samples += 1
            best = max(best, score)
        curve.append({"focus": value,
                      "sharpness": round(best, 1) if samples else None,
                      "samples": samples})

    scored = [p for p in curve if p["sharpness"] is not None]
    if not scored:
        # Leave the camera as we found it rather than parked at the last step.
        await loop.run_in_executor(
            None, source.set_focus,
            original.get("configured_focus") if original.get("manual") else None)
        return {**expected_error("no_frames"), "curve": curve}

    peak = max(scored, key=lambda p: p["sharpness"])
    peak_at_edge = peak["focus"] in (values[0], values[-1])

    applied = None
    if body.apply_best:
        await loop.run_in_executor(None, source.set_focus, peak["focus"])
        applied = peak["focus"]
    else:
        await loop.run_in_executor(
            None, source.set_focus,
            original.get("configured_focus") if original.get("manual") else None)

    log.info("focus sweep %.0f..%.0f step %.0f -> peak focus=%s sharpness=%.1f%s",
             body.start, body.end, body.step, peak["focus"], peak["sharpness"],
             " (AT RANGE EDGE)" if peak_at_edge else "")

    return {
        "ok": True,
        "best_focus": peak["focus"],
        "best_sharpness": peak["sharpness"],
        "peak_at_edge": peak_at_edge,
        "applied_focus": applied,
        "roi": sorted(roi_kinds),
        "curve": curve,
        "persist_focus_value": peak["focus"],
        "metric": "laplacian_variance_within_sweep_only",
    }
