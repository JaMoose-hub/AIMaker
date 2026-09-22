"""Resolution selection for the current native MJPEG webcam."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.camera_tuning import camera_mutation_guard
from app.capture.modes import change_mode, mode_info

router = APIRouter(prefix='/api/camera/modes')


class ModeRequest(BaseModel):
    device_id: str
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    fps: float = Field(gt=0, le=120)


def _info(state):
    try:
        return mode_info(state)
    except Exception:
        raise HTTPException(503, detail='camera_modes_unavailable') from None


@router.get('')
def get_modes(request: Request):
    state = request.app.state
    lock = getattr(state, 'camera_control_lock', None)
    return {**_info(state), 'busy': bool(lock and lock.locked())}


@router.post('', dependencies=[Depends(camera_mutation_guard)])
def set_mode(body: ModeRequest, request: Request):
    state = request.app.state
    info = _info(state)
    if not info['supported']:
        raise HTTPException(409, detail='camera_modes_unsupported')
    if body.device_id != info['device_id']:
        raise HTTPException(409, detail='camera_changed')
    mode = dict(width=body.width, height=body.height, fps=body.fps)
    if mode not in info['modes']:
        raise HTTPException(422, detail='camera_mode_unsupported')
    result = change_mode(state, mode)
    return {**_info(state), **result, 'busy': False}
