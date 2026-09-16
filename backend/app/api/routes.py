"""REST endpoints (docs/api-contract.md §1)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.profiles.store import ProfileError, ProfileNotFoundError

router = APIRouter(prefix="/api")


@router.get('/inference/status')
def get_inference_status(request: Request):
    from app.vision.inference_status import inference_status
    return inference_status(request.app.state)


class QueryRequest(BaseModel):
    text: str
    locale: str | None = None


def _not_found(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error_code": "resource_not_found", "params": {"detail": detail}},
    )


def _profile_error(error: ProfileError, status_code: int = 500) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.error_code, "params": error.params},
    )


@router.get("/config")
async def get_config(request: Request) -> dict:
    cfg = request.app.state.config
    runtime = request.app.state.runtime_manager.snapshot()
    board_id = runtime.board_id
    # This is deliberately a read-only snapshot.  Loading through the store
    # picks up a newly captured reference after POST /api/calibrate without
    # making the detector's runtime state authoritative for the quality claim.
    from app.vision.profile_quality import inspect_profile_quality

    profile = request.app.state.profile_store.profile(board_id)
    accuracy = inspect_profile_quality(
        profile,
        request.app.state.profile_store.board_dir(board_id),
        camera_calibration_path=cfg.camera.calibration_path,
        min_pin_pitch_px=cfg.wire_trace.min_pin_pitch_px,
        min_px_per_mm=cfg.wire_trace.min_px_per_mm,
    )
    insertion_worker = request.app.state.insertion_vlm_worker
    return {
        "board_id": board_id,
        "runtime_revision": runtime.runtime_revision,
        "default_locale": cfg.default_locale,
        "video_size": [cfg.camera.width, cfg.camera.height],
        "detector": cfg.detector,
        "camera_source": cfg.camera.source,
        "realtime_tracking": cfg.realtime_tracking and board_id == 'raspberry-pi-5',
        "camera_capture_backend": cfg.camera.capture_backend,
        "component_vision": {
            "enabled": bool(cfg.component_vision.enabled),
            "primary_component_id": cfg.component_vision.primary_component_id,
            "components": [
                {
                    "id": target.id,
                    "model_path": str(target.model_path),
                    "profile_path": str(target.profile_path),
                    "input_size": target.input_size,
                    "confidence_threshold": target.confidence_threshold,
                    "keypoint_threshold": target.keypoint_threshold,
                }
                for target in cfg.component_vision.components
            ],
        },
        "accuracy": accuracy,
        "verification_runtime": {
            "vlm_enabled": bool(cfg.vlm.enabled),
            "vlm_provider": cfg.vlm.provider,
            "vlm_model": cfg.vlm.model,
            "vlm_insertion_enabled": bool(cfg.vlm.insertion_enabled),
            "vlm_timeout_s": float(cfg.vlm.timeout_s),
            "vlm_worker": (
                insertion_worker.diagnostics()
                if insertion_worker is not None
                else None
            ),
            "electrical_enabled": bool(
                cfg.electrical_verification.enabled
                and board_id == "arduino-uno-q"
            ),
        },
    }


@router.get("/boards/{board_id}")
async def get_board(board_id: str, request: Request):
    store = request.app.state.profile_store
    try:
        return store.raw(board_id)
    except ProfileNotFoundError as error:
        return _profile_error(error, 404)
    except ProfileError as e:
        return _profile_error(e)


@router.get("/boards/{board_id}/pins/{pin_id}")
async def get_pin(board_id: str, pin_id: str, request: Request):
    store = request.app.state.profile_store
    try:
        raw = store.raw(board_id)
    except ProfileNotFoundError as error:
        return _profile_error(error, 404)
    except ProfileError as e:
        return _profile_error(e)
    pin = next((p for p in raw.get("pins", []) if p.get("id") == pin_id), None)
    if pin is None:
        return _not_found(f"unknown pin '{pin_id}' on board '{board_id}'")
    return pin


@router.post("/query")
async def post_query(body: QueryRequest, request: Request) -> dict:
    service = request.app.state.query_service
    return service.answer(body.text, body.locale)
