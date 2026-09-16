"""REST endpoints for guided-wiring steps (M22).

Contract (docs/api-contract.md §8): expected outcomes are HTTP 200 with
ok:true/false — real HTTP errors are reserved for malformed requests, same
convention as POST /api/calibrate and POST /api/cameras/select.

POST   /api/guidance/step   activate a step (snapshots baseline occupancy)
GET    /api/guidance/state  current step + latest verdict (authoritative,
                            sync read — the WS guidance_check stream is a
                            latest-only convenience, not the only channel)
DELETE /api/guidance/step   deactivate guidance
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.errors import expected_error
from app.vision.guidance import GuidanceStep, occupied_pin_ids
from app.vision.endpoint_color import (
    build_guided_board_endpoint_color_preview,
    build_guided_component_endpoint_color_preview,
    inspect_guided_board_endpoint_color,
    inspect_guided_component_endpoint_color,
    stabilize_endpoint_colour_samples,
)
from app.verification.models import VerificationEvidence

log = logging.getLogger(__name__)

router = APIRouter()

_COLOR_SAMPLE_FRAME_COUNT = 5
_COLOR_SAMPLE_FRAME_TIMEOUT_S = 0.18


def _fail(error_code: str, **params: object) -> dict[str, object]:
    payload = expected_error(error_code, **params)
    payload.update(params)
    return payload


def _publish_verification(state, *, frame_id: int, now_ms: float) -> None:
    verification_state = getattr(state, "verification_state", None)
    broadcaster = getattr(state, "broadcaster", None)
    if verification_state is None or broadcaster is None:
        return
    message = verification_state.message(state.config.board, frame_id, now_ms)
    if message is not None:
        broadcaster.publish_threadsafe(message)


def _apply_final_wiring_outcome(state, outcome: dict) -> None:
    """Keep API polling a safe fallback for injected/test VLM workers."""
    verification_state = getattr(state, "verification_state", None)
    if verification_state is None:
        return
    step_id = str(outcome.get("step_id", ""))
    if not step_id or outcome.get("status") not in {"complete", "error"}:
        return
    now_ms = time.monotonic() * 1000.0
    if outcome.get("status") == "complete":
        verification_state.set_final_visual_result(
            step_id,
            outcome.get("connections", []),
            note=str(outcome.get("note", "")),
            now_ms=now_ms,
        )
    else:
        verification_state.set_final_visual_error(
            step_id,
            error=str(outcome.get("error", "vlm_failed")),
            now_ms=now_ms,
        )
    _publish_verification(
        state,
        frame_id=int(outcome.get("frame_id", 0) or 0),
        now_ms=now_ms,
    )


class GuidanceStepBody(BaseModel):
    expected_pin_id: str = Field(min_length=1)
    expected_role: str | None = None
    component_id: str | None = None
    hint_color: str | None = None
    step_id: str | None = None  # optional caller-supplied id (plans use this)
    # L2/manual confirmation is the safe default. L3/auto requires the
    # profile quality gate below.
    advance_mode: Literal["confirm", "auto"] = "confirm"


@router.post("/api/guidance/step")
async def set_guidance_step(body: GuidanceStepBody, request: Request) -> dict:
    state = request.app.state
    profile = state.profile
    known_pins = {p.id for p in profile.pins}
    if body.expected_pin_id not in known_pins:
        # Expected outcome (caller asked for a pin this board doesn't have),
        # not a malformed request: 200 + ok:false, name the problem.
        return _fail(
            "unknown_pin",
            pin_id=body.expected_pin_id,
            board_id=profile.board.id,
        )

    if body.advance_mode == "auto":
        from app.vision.profile_quality import inspect_profile_quality

        quality = inspect_profile_quality(
            profile,
            state.profile_store.board_dir(state.config.board),
            camera_calibration_path=state.config.camera.calibration_path,
            min_pin_pitch_px=state.config.wire_trace.min_pin_pitch_px,
            min_px_per_mm=state.config.wire_trace.min_px_per_mm,
        )
        if not quality["physical_gate_ready"]:
            return _fail(
                "physical_gate_unready",
                warnings=list(quality["warnings"]),
            )

    guidance_state = state.guidance_state
    step_id = body.step_id or guidance_state.next_step_id(body.expected_pin_id)
    step = GuidanceStep(
        step_id=step_id,
        expected_pin_id=body.expected_pin_id,
        expected_role=body.expected_role,
        component_id=body.component_id,
        hint_color=body.hint_color,
        advance_mode=body.advance_mode,
    )
    # Baseline = pins occupied RIGHT NOW: endpoints already resolved before
    # this step began must never count as this step's "new" wire.
    baseline = occupied_pin_ids(state.wire_state.get())
    guidance_state.set_step(step, baseline)
    verification_state = getattr(state, "verification_state", None)
    if verification_state is not None:
        electrical_config = getattr(state.config, "electrical_verification", None)
        electrical_enabled = bool(
            electrical_config is not None and electrical_config.enabled
        )
        verification_state.set_step(
            step.step_id,
            step.expected_pin_id,
            step.expected_role,
            step.component_id,
            electrical_available=bool(
                electrical_enabled
                and step.expected_pin_id.upper() == "A0"
                and (step.expected_role or "").upper() == "AO"
            ),
            electrical_unavailable_reason=(
                "electrical_not_applicable"
                if electrical_enabled
                else "electrical_not_configured"
            ),
        )
    log.info("guidance step activated: %s -> %s (baseline: %s)",
             step_id, body.expected_pin_id, sorted(baseline) or "empty")
    return {
        "ok": True,
        "step_id": step_id,
        "advance_mode": body.advance_mode,
        "baseline_pin_ids": sorted(baseline),
    }


@router.get("/api/guidance/state")
async def get_guidance_state(request: Request) -> dict:
    result = request.app.state.guidance_state.snapshot()
    verification_state = getattr(request.app.state, "verification_state", None)
    if verification_state is not None:
        result["verification"] = verification_state.snapshot()
    return result


@router.post("/api/guidance/geometry-check")
async def request_guidance_geometry_check(request: Request) -> dict:
    """Start one five-frame manual, independent-endpoint geometry check."""
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    verification_state = getattr(state, "verification_state", None)
    if verification_state is None or getattr(state, "wire_worker", None) is None:
        return _fail("geometry_unavailable")
    target = verification_state.target()
    if (
        target is not None
        and target.step_id == step.step_id
        and target.geometry_requested
        and not target.geometry_complete
    ):
        return _fail("geometry_busy")
    detection = state.detection_state.get()
    if detection is None or detection.tracking != "locked":
        return _fail("board_not_ready", board_id=state.config.board)
    if step.component_id and step.expected_role:
        component_pose = state.component_pose_state.get(step.component_id)
        if (
            component_pose is None
            or component_pose.tracking not in {"locked", "stale"}
            or component_pose.component_id != step.component_id
        ):
            return _fail("component_not_ready", component_id=step.component_id)
        if not any(
            pin.id == step.expected_role and pin.visible
            for pin in component_pose.pins
        ):
            return _fail("target_not_visible", pin_id=step.expected_role)
    if not verification_state.request_geometry(step.step_id):
        return _fail("geometry_not_started")
    wake_wire_worker = getattr(state.wire_worker, "wake", None)
    if callable(wake_wire_worker):
        wake_wire_worker()
    now_ms = time.monotonic() * 1000.0
    slot = state.frame_bus.get_latest(timeout=0.0)
    _publish_verification(
        state,
        frame_id=slot.frame_id if slot is not None else 0,
        now_ms=now_ms,
    )
    target = verification_state.target()
    return {
        "ok": True,
        "status": "collecting",
        "step_id": step.step_id,
        "generation": target.geometry_generation if target is not None else 0,
        "sample_target": 5,
        "required_agreement": 3,
    }


@router.get("/api/guidance/geometry-check")
async def get_guidance_geometry_check(request: Request) -> dict:
    verification_state = getattr(request.app.state, "verification_state", None)
    if verification_state is None:
        return {**_fail("geometry_unavailable"), "status": "unavailable"}
    snapshot = verification_state.snapshot()
    if not snapshot["active"]:
        return {**_fail("no_active_step"), "status": "idle"}
    target = snapshot["target"]
    evidence = snapshot["evidence"]["geometry"]
    if not target["geometry_requested"]:
        status = "idle"
    elif target["geometry_complete"]:
        status = "complete"
    else:
        status = "collecting"
    return {
        "ok": True,
        "status": status,
        "step_id": target["step_id"],
        "generation": target["geometry_generation"],
        "evidence": evidence,
    }


def _capture_guidance_colour_endpoint(state, endpoint: str, step, slot):
    """Inspect one coherent camera slot; callers handle the burst timing."""
    if endpoint == "board":
        detection = state.detection_state.get()
        if detection is None or detection.tracking != "locked":
            return None, None, "board_not_ready"
        result = inspect_guided_board_endpoint_color(slot.frame, detection, step)
        preview = build_guided_board_endpoint_color_preview(slot.frame, detection, step)
    else:
        component_pose = state.component_pose_state.get(step.component_id)
        if (
            component_pose is None
            or component_pose.component_id != step.component_id
            or component_pose.tracking not in {"locked", "stale"}
        ):
            return None, None, "component_not_ready"
        result = inspect_guided_component_endpoint_color(slot.frame, component_pose, step)
        preview = build_guided_component_endpoint_color_preview(slot.frame, component_pose, step)
    if result.get("reason") == "target_not_visible":
        return None, None, "target_not_visible"
    return result, preview, None


@router.post("/api/guidance/color-check/{endpoint}")
async def request_guidance_color_check(
    endpoint: Literal["board", "component"],
    request: Request,
) -> dict:
    """Save a five-frame local HSV + Lab sample for one physical wire end."""
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    if not step.expected_role or not step.component_id:
        return _fail("component_pin_missing")

    captures: list[tuple[object, dict, bytes | None]] = []
    last_seq: int | None = None
    first_error: str | None = None
    for index in range(_COLOR_SAMPLE_FRAME_COUNT):
        if index == 0:
            slot = state.frame_bus.get_latest(timeout=0.0)
        else:
            slot = await asyncio.to_thread(
                state.frame_bus.get_latest,
                timeout=_COLOR_SAMPLE_FRAME_TIMEOUT_S,
                newer_than=last_seq,
            )
        if slot is None:
            break
        last_seq = slot.seq
        result, preview, error = _capture_guidance_colour_endpoint(state, endpoint, step, slot)
        if error is not None:
            first_error = first_error or error
            continue
        captures.append((slot, result, preview))

    if not captures:
        if first_error == "target_not_visible":
            return _fail(first_error)
        if first_error == "board_not_ready":
            return _fail(first_error, board_id=state.config.board)
        if first_error == "component_not_ready":
            return _fail(first_error, component_id=step.component_id)
        return _fail("no_frame")

    result = stabilize_endpoint_colour_samples(sample for _slot, sample, _preview in captures)
    selected = next(
        (capture for capture in reversed(captures) if capture[1].get("color") == result.get("color")),
        captures[-1],
    )
    slot, _selected_sample, preview = selected
    if preview is not None:
        state.guidance_color_preview.set(endpoint, preview)
    status = "ambiguous" if result.get("ambiguous") else "sampled" if result.get("color") else "unknown"
    return {
        "ok": True,
        "endpoint": endpoint,
        "step_id": step.step_id,
        "frame_id": slot.frame_id,
        "status": status,
        "sample": result,
        "advisory": True,
    }


@router.get("/api/guidance/color-check/image/{endpoint}")
async def get_guidance_color_check_image(
    endpoint: Literal["board", "component"],
    request: Request,
) -> Response:
    """Return the saved raw frame plus one endpoint's exact HSV sampling sector."""
    preview_state = getattr(request.app.state, "guidance_color_preview", None)
    image = preview_state.get(endpoint) if preview_state is not None else None
    if image is None:
        return Response(status_code=404)
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/guidance/color-vlm-check")
async def request_guidance_color_vlm_check(request: Request) -> dict:
    """Queue one manual VLM opinion about the two visible wire colours.

    This is deliberately independent from both the fast local colour sampler
    and the VLM connector-insertion check.  It never publishes verification
    evidence or changes the guided lesson's score/gates.
    """
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    worker = getattr(state, "wire_color_vlm_worker", None)
    if worker is None:
        return _fail("vlm_unavailable")
    diagnostics = worker.diagnostics()
    if diagnostics.get("queued") or diagnostics.get("inflight"):
        return _fail("vlm_busy")
    if not step.expected_role or not step.component_id:
        return _fail("component_pin_missing")
    slot = state.frame_bus.get_latest(timeout=0.0)
    if slot is None:
        return _fail("no_frame")
    detection = state.detection_state.get()
    if detection is None or detection.tracking != "locked":
        return _fail("board_not_ready", board_id=state.config.board)
    component_pose = state.component_pose_state.get(step.component_id)
    if (
        component_pose is None
        or component_pose.component_id != step.component_id
        or component_pose.tracking not in {"locked", "stale"}
    ):
        return _fail("component_not_ready", component_id=step.component_id)
    if not any(pin.pin_id == step.expected_pin_id and pin.visible for pin in detection.pins):
        return _fail("target_not_visible", pin_id=step.expected_pin_id)
    if not any(pin.id == step.expected_role and pin.visible for pin in component_pose.pins):
        return _fail("target_not_visible", pin_id=step.expected_role)
    if not worker.submit(step, slot.frame, detection, component_pose, frame_id=slot.frame_id):
        return _fail("vlm_retry_later")
    return {"ok": True, "status": "queued", "step_id": step.step_id}


@router.get("/api/guidance/color-vlm-check")
async def get_guidance_color_vlm_check(request: Request) -> dict:
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return {**_fail("no_active_step"), "status": "idle"}
    step, _baseline = active
    worker = getattr(state, "wire_color_vlm_worker", None)
    if worker is None:
        return {**_fail("vlm_unavailable"), "status": "unavailable"}
    diagnostics = worker.diagnostics()
    if diagnostics.get("inflight"):
        return {"ok": True, "status": "inflight", "step_id": step.step_id}
    if diagnostics.get("queued"):
        return {"ok": True, "status": "queued", "step_id": step.step_id}
    outcome = diagnostics.get("last_outcome")
    if isinstance(outcome, dict) and outcome.get("step_id") == step.step_id:
        return {"ok": outcome.get("status") != "error", **outcome}
    return {"ok": True, "status": "idle", "step_id": step.step_id}


@router.get("/api/guidance/color-vlm-check/image")
async def get_guidance_color_vlm_check_image(request: Request) -> Response:
    """Return the exact raw-camera composite supplied to the wire-colour VLM."""
    worker = getattr(request.app.state, "wire_color_vlm_worker", None)
    if worker is None:
        return Response(status_code=404)
    image = worker.preview_jpeg()
    if image is None:
        return Response(status_code=404)
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/guidance/visual-check")
async def request_guidance_visual_check(request: Request) -> dict:
    """Freeze one current frame and queue exactly one insertion VLM check."""
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    worker = getattr(state, "insertion_vlm_worker", None)
    if worker is None:
        return _fail("vlm_unavailable")

    diagnostics = worker.diagnostics()
    if (
        diagnostics.get("queued_step_id") == step.step_id
        or diagnostics.get("inflight_step_id") == step.step_id
    ):
        return _fail("vlm_busy")

    slot = state.frame_bus.get_latest(timeout=0.0)
    if slot is None:
        return _fail("no_frame")
    if not step.expected_role:
        return _fail("component_pin_missing")
    # VLM is an explicit frozen-image check. Pose is optional context for
    # enlarged crops, never a button gate; the worker falls back to the raw
    # full-resolution frame if current landmarks are unavailable.
    detection = state.detection_state.get()
    component_pose = state.component_pose_state.get(step.component_id)
    accepted = worker.submit(step, slot.frame, detection, component_pose)
    if not accepted:
        return _fail("vlm_retry_later")
    now_ms = time.monotonic() * 1000.0
    verification_state = getattr(state, "verification_state", None)
    if verification_state is not None:
        verification_state.update(
            step.step_id,
            [
                VerificationEvidence.uncertain(
                    "visual",
                    "vlm_checking",
                    as_of_ms=now_ms,
                    method="vlm_insertion",
                )
            ],
            now_ms=now_ms,
        )
        _publish_verification(state, frame_id=slot.frame_id, now_ms=now_ms)
    return {"ok": True, "status": "queued", "step_id": step.step_id}


@router.get("/api/guidance/visual-check")
async def get_guidance_visual_check(request: Request) -> dict:
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return {**_fail("no_active_step"), "status": "idle"}
    step, _baseline = active
    worker = getattr(state, "insertion_vlm_worker", None)
    if worker is None:
        return {**_fail("vlm_unavailable"), "status": "unavailable"}
    diagnostics = worker.diagnostics()
    if diagnostics.get("inflight_step_id") == step.step_id:
        return {"ok": True, "status": "inflight", "step_id": step.step_id}
    if diagnostics.get("queued_step_id") == step.step_id:
        return {"ok": True, "status": "queued", "step_id": step.step_id}
    outcome = diagnostics.get("last_outcome")
    if isinstance(outcome, dict) and outcome.get("step_id") == step.step_id:
        return {"ok": outcome.get("status") != "error", **outcome}
    return {"ok": True, "status": "idle", "step_id": step.step_id}


@router.get("/api/guidance/visual-check/image")
async def get_guidance_visual_check_image(request: Request) -> Response:
    """Return the exact full-frame/crop composite used by the insertion VLM."""
    worker = getattr(request.app.state, "insertion_vlm_worker", None)
    image = worker.preview_jpeg() if worker is not None else None
    if image is None:
        return Response(status_code=404)
    return Response(content=image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/api/guidance/final-check")
async def request_guidance_final_check(request: Request) -> dict:
    """Queue one visual check for all three completed photoresistor wires."""
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    if step.expected_pin_id.upper() != "A0" or (step.expected_role or "").upper() != "AO":
        return _fail("final_check_not_ready")
    worker = getattr(state, "final_wiring_vlm_worker", None)
    if worker is None:
        return _fail("vlm_unavailable")
    diagnostics = worker.diagnostics()
    if diagnostics.get("queued") or diagnostics.get("inflight"):
        return _fail("final_check_busy")
    slot = state.frame_bus.get_latest(timeout=0.0)
    if slot is None:
        return _fail("no_frame")
    # Final VLM check is also snapshot-based. Its worker uses any available
    # pose outlines for detail panels, or the full frame when poses are absent.
    detection = state.detection_state.get()
    component_pose = state.component_pose_state.get(step.component_id)
    if not worker.submit(
        slot.frame,
        detection,
        component_pose,
        step_id=step.step_id,
    ):
        return _fail("final_check_retry_later")
    verification_state = getattr(state, "verification_state", None)
    if verification_state is not None:
        now_ms = time.monotonic() * 1000.0
        verification_state.set_final_visual_pending(step.step_id, now_ms=now_ms)
        _publish_verification(state, frame_id=slot.frame_id, now_ms=now_ms)
    return {"ok": True, "status": "queued", "step_id": step.step_id}


@router.get("/api/guidance/final-check")
async def get_guidance_final_check(request: Request) -> dict:
    worker = getattr(request.app.state, "final_wiring_vlm_worker", None)
    if worker is None:
        return {**_fail("vlm_unavailable"), "status": "unavailable"}
    diagnostics = worker.diagnostics()
    if diagnostics.get("inflight"):
        return {"ok": True, "status": "inflight"}
    if diagnostics.get("queued"):
        return {"ok": True, "status": "queued"}
    outcome = diagnostics.get("last_outcome")
    if isinstance(outcome, dict):
        _apply_final_wiring_outcome(request.app.state, outcome)
        return {"ok": outcome.get("status") != "error", **outcome}
    return {"ok": True, "status": "idle"}


@router.get("/api/guidance/final-check/image")
async def get_guidance_final_check_image(request: Request) -> Response:
    """Return the exact four-panel JPEG most recently sent to the final VLM."""
    worker = getattr(request.app.state, "final_wiring_vlm_worker", None)
    if worker is None:
        return Response(status_code=404)
    image = worker.preview_jpeg()
    if image is None:
        return Response(status_code=404)
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/guidance/electrical-check")
async def request_guidance_electrical_check(request: Request) -> dict:
    """Explicitly start/restart the final Sensor AO -> UNO Q A0 challenge."""
    state = request.app.state
    active = state.guidance_state.get_step()
    if active is None:
        return _fail("no_active_step")
    step, _baseline = active
    verification_state = getattr(state, "verification_state", None)
    if verification_state is None:
        return _fail("electrical_unavailable")
    target = verification_state.target()
    if (
        target is None
        or target.step_id != step.step_id
        or not target.electrical_supported
    ):
        return _fail("electrical_not_applicable")
    if getattr(state, "electrical_worker", None) is None:
        return _fail("electrical_unavailable")
    if not verification_state.request_electrical(step.step_id):
        return _fail("electrical_not_started")
    now_ms = time.monotonic() * 1000.0
    _publish_verification(state, frame_id=0, now_ms=now_ms)
    return {
        "ok": True,
        "status": "started",
        "step_id": step.step_id,
        "generation": verification_state.target().electrical_generation,
    }


@router.delete("/api/guidance/step")
async def clear_guidance_step(request: Request) -> dict:
    request.app.state.guidance_state.clear()
    verification_state = getattr(request.app.state, "verification_state", None)
    if verification_state is not None:
        verification_state.clear()
    return {"ok": True}
