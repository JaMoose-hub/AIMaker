"""Project-specific snapshot checks, separate from legacy local verification."""
from fastapi import APIRouter, Request, Response
from app.cloud_wiring import CloudWiringRequest

router = APIRouter(prefix="/api/guidance/cloud-checks", tags=["cloud-wiring"])


@router.post("", status_code=202)
def check(body: CloudWiringRequest, request: Request):
    return request.app.state.cloud_wiring_service.submit(body, request.app.state)


@router.get("/{job_id}")
def status(job_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return request.app.state.cloud_wiring_service.get(job_id, request.app.state)


@router.get("/{job_id}/images/{name}")
def image(job_id: str, name: str, request: Request):
    content = request.app.state.cloud_wiring_service.image(job_id, name)
    return Response(content, media_type="image/png" if content.startswith(bytes.fromhex('89504e47')) else "image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
