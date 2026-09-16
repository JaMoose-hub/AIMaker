"""Same-frame image + display poses; separate from authoritative WS results."""
import asyncio

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.get('/api/tracking/component-source')
async def component_source(request: Request, component_id: str = 'hc-sr04', after: int = -1):
    """On-demand lossless source paired with the actual model result.

    No extra image work on the live display path. No file reads or uploads.
    """
    import base64
    import cv2
    from app.component_worker import component_pose_message
    if component_id not in ('hc-sr04', 'mrd-tf240-8p-cs'):
        return Response(status_code=404)
    pair = request.app.state.component_pose_state.get_synchronized(component_id)
    if pair is None or pair[0].frame_id <= after:
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})
    slot, result = pair
    if result.frame_id != slot.frame_id:
        return Response(status_code=409)
    ok, data = await asyncio.to_thread(cv2.imencode, '.png', slot.frame)
    if not ok:
        return Response(status_code=503)
    from fastapi.responses import JSONResponse
    return JSONResponse({'frame_id': slot.frame_id, 'component_pose': component_pose_message(result),
        'image': 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')},
        headers={'Cache-Control': 'no-store'})


@router.get('/api/tracking/frame')
async def tracking_frame(request: Request, after: int = -1):
    state = request.app.state
    glasses = getattr(state, 'glasses_stream', None)
    eye_active = glasses is not None and glasses.snapshot()['active']
    if not eye_active and (not state.config.realtime_tracking
                           or state.runtime_manager.snapshot().board_id != 'raspberry-pi-5'):
        return Response(status_code=404)
    packet = await asyncio.to_thread(state.motion_frame_state.get, after)
    if packet is None:
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})
    # A runtime switch may have happened while waiting for a frame.
    runtime = state.runtime_manager.snapshot()
    if packet['runtime_revision'] != runtime.runtime_revision or packet['board_id'] != runtime.board_id:
        return Response(status_code=204, headers={'Cache-Control': 'no-store'})
    from fastapi.responses import JSONResponse
    return JSONResponse(packet, headers={'Cache-Control': 'no-store'})
