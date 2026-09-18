"""Non-blocking one-button tuning. Camera writes share one exclusive lease."""
import threading

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix='/api/camera/auto-tune')


def camera_mutation_guard(request: Request):
    state = request.app.state
    # Bare-router unit tests also get a lock; full app initializes it once.
    if not hasattr(state, 'camera_control_lock'):
        state.camera_control_lock = threading.Lock()
    lock = state.camera_control_lock
    if not lock.acquire(blocking=False):
        raise HTTPException(409, detail='camera_adjustment_busy')
    try:
        yield
    finally:
        lock.release()


@router.get('')
async def status(request: Request):
    return request.app.state.camera_tuner.snapshot()


@router.post('')
async def start(request: Request):
    return request.app.state.camera_tuner.start()


@router.delete('')
async def cancel(request: Request):
    return request.app.state.camera_tuner.cancel()


@router.post('/restore')
async def restore(request: Request):
    return request.app.state.camera_tuner.start(restore=True)
