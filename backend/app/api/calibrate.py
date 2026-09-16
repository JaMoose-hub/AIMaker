"""POST /api/calibrate (docs/api-contract.md §6).

Turns 4 user-aligned guide-rectangle corners + the current camera frame into
the canonical reference asset for the currently active board (config.board),
then hot-swaps the running VisionWorker onto a freshly-loaded pipeline
detector. Only one board is loaded per running instance; there is no
board_id request parameter.

HTTP 200 in ALL expected outcomes (success or a recognised failure code);
actual HTTP error status is reserved for malformed request bodies (handled
automatically by FastAPI/pydantic -> 422) or genuinely unexpected server
errors.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.errors import expected_error
from app.profiles.store import ProfileError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_FRAME_TIMEOUT_S = 1.0

class CalibrateRequest(BaseModel):
    corners_px: list[list[float]]


def _fail(error: str, **details) -> dict:
    clean = {key: value for key, value in details.items() if value is not None}
    payload = expected_error(error, **clean)
    # Keep diagnostics at top level for old clients while `params` is the
    # locale-neutral public error contract.
    payload.update(clean)
    return payload


@router.post("/calibrate")
async def post_calibrate(body: CalibrateRequest, request: Request) -> JSONResponse:
    # Lazy import: app.vision (CV pipeline, developed in parallel; pulls in
    # cv2/numpy-heavy code) must not be a hard import-time dependency of the
    # API layer, mirroring app.main's own lazy detector construction.
    from app.vision.reference_calibration import (
        build_mm_to_px,
        validate_corners,
        write_calibration,
    )

    state = request.app.state
    config = state.config
    board_id = config.board

    # The corner quad was drawn by the frontend against a known video size;
    # prefer the actual size the vision worker has last seen (device cameras
    # may differ from the configured size), same fallback ws.py uses.
    detection_state = getattr(state, "detection_state", None)
    video_size = detection_state.get_video_size() if detection_state is not None else None
    if video_size is None:
        video_size = (config.camera.width, config.camera.height)
    frame_shape = (video_size[1], video_size[0])

    error = validate_corners(body.corners_px, frame_shape)
    if error:
        return JSONResponse(status_code=200, content=_fail(error))

    slot = state.frame_bus.get_latest(timeout=_FRAME_TIMEOUT_S)
    if slot is None:
        return JSONResponse(status_code=200, content=_fail("no_frame"))

    store = state.profile_store
    try:
        profile = store.profile(board_id)
    except ProfileError:
        return JSONResponse(status_code=200, content=_fail("board_not_found"))
    profile_dir = store.board_dir(board_id)

    mm_to_px = build_mm_to_px(body.corners_px, profile.board.outline_mm)
    pin_geometry = [
        (pin.header, pin.index, pin.pos_mm[0], pin.pos_mm[1])
        for pin in profile.pins
    ]
    result = write_calibration(
        profile_dir,
        slot.frame,
        mm_to_px,
        tuple(profile.board.outline_mm),
        pin_geometry=pin_geometry,
    )
    if not result["ok"]:
        error_code = str(result.get("error", "insufficient_features"))
        return JSONResponse(
            status_code=200,
            content=_fail(
                error_code,
                pitch_px=result.get("pitch_px"),
                px_per_mm=result.get("px_per_mm"),
                min_pitch_px=result.get("min_pitch_px"),
                min_px_per_mm=result.get("min_px_per_mm"),
            ),
        )

    try:
        reloaded_profile, _raw = store.reload(board_id)
    except ProfileError:
        log.exception("board.json failed to reload after write_calibration")
        return JSONResponse(status_code=200, content=_fail("board_not_found"))

    # Lazy import: app.vision.factory pulls in the whole CV pipeline
    # (developed in parallel) and must not be a hard import-time dependency
    # of the API layer, mirroring app.main's own lazy detector construction.
    from app.vision.factory import create_detector

    cfg = request.app.state.config
    # Calibration historically promotes mock/demo mode to the real feature
    # pipeline.  A hybrid session must remain hybrid so its freshly-written
    # profile is immediately used by both YOLO geometry and the fallback.
    detector_kind = "hybrid" if cfg.detector == "hybrid" else "pipeline"
    new_detector = create_detector(
        detector_kind, reloaded_profile, profile_dir, state.scene,
        horizontal_fov_deg=cfg.camera.horizontal_fov_deg,
        camera_calibration_path=cfg.camera.calibration_path,
        use_camera_calibration=cfg.camera.source != "xreal",
        yolo_model_path=cfg.yolo_pose.model_path_for(reloaded_profile.board.id),
        yolo_keypoint_count=cfg.yolo_pose.keypoint_count_for(
            reloaded_profile.board.id
        ),
        yolo_input_size=cfg.yolo_pose.input_size,
        yolo_confidence_threshold=cfg.yolo_pose.confidence_threshold_for(
            reloaded_profile.board.id
        ),
        yolo_keypoint_threshold=cfg.yolo_pose.keypoint_threshold,
        yolo_nms_iou_threshold=cfg.yolo_pose.nms_iou_threshold,
        yolo_max_reprojection_error_px=cfg.yolo_pose.max_reprojection_error_px,
        yolo_stability_deadband_px=cfg.yolo_pose.stability_deadband_px,
        yolo_deadband_exit_confirm_frames=cfg.yolo_pose.deadband_exit_confirm_frames,
        yolo_jump_threshold_fraction=cfg.yolo_pose.jump_threshold_fraction,
        yolo_jump_confirm_frames=cfg.yolo_pose.jump_confirm_frames,
        yolo_occlusion_hold_frames=cfg.yolo_pose.occlusion_hold_frames,
        yolo_occlusion_visibility_ratio=cfg.yolo_pose.occlusion_visibility_ratio,
        yolo_visibility_warmup_frames=cfg.yolo_pose.visibility_warmup_frames,
        yolo_runtime_backend=cfg.yolo_pose.runtime_backend,
        yolo_directml_device_id=cfg.yolo_pose.directml_device_id,
        yolo_cuda_device_id=cfg.yolo_pose.cuda_device_id,
    )
    previous_detector = state.detector
    state.vision_worker.set_detector(new_detector)
    state.detector = new_detector
    if previous_detector is not None and previous_detector is not new_detector:
        try:
            previous_detector.close()
        except Exception:
            log.exception("previous detector close failed after calibration")

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "detector": detector_kind,
            "reference_features": result["count"],
            "pitch_px": result.get("pitch_px"),
            "px_per_mm": result.get("px_per_mm"),
        },
    )
