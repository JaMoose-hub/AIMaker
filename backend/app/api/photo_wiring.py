"""Single-photo GPIO guidance endpoints; no automatic hardware actions."""
from fastapi import APIRouter, Request, Response
from app.photo_wiring import PhotoCaptureRequest, PhotoCheckRequest, canonical_plan

router = APIRouter(prefix="/api/photo-wiring", tags=["photo-wiring"])


@router.get("/plan")
def plan():
    return canonical_plan()


@router.post("/sessions")
def start(request: Request):
    return request.app.state.photo_wiring_service.start()


@router.post("/sessions/{session_id}/heartbeat")
def heartbeat(session_id: str, request: Request):
    return request.app.state.photo_wiring_service.heartbeat(session_id)


@router.delete("/sessions/{session_id}")
def finish(session_id: str, request: Request):
    return request.app.state.photo_wiring_service.finish(session_id)


@router.post("/sessions/{session_id}/captures")
def capture(session_id: str, body: PhotoCaptureRequest, request: Request):
    return request.app.state.photo_wiring_service.capture(session_id, body)


@router.get("/captures/{capture_id}")
def get_capture(capture_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.photo_wiring_service.get_capture(capture_id)


@router.get("/captures/{capture_id}/image")
def image(capture_id: str, request: Request):
    return Response(request.app.state.photo_wiring_service.image(capture_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/captures/{capture_id}/checks", status_code=202)
def check(capture_id: str, body: PhotoCheckRequest, request: Request):
    return request.app.state.photo_wiring_service.submit_check(capture_id, body)


@router.get("/checks/{job_id}")
def get_check(job_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.photo_wiring_service.get_check(job_id)
