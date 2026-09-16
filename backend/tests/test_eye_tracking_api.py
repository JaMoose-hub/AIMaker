from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.tracking import router


@pytest.mark.parametrize('board', ['raspberry-pi-5', 'arduino-uno-q'])
def test_eye_direct_yolo_packet_does_not_depend_on_normal_tracking_switch(board):
    app = FastAPI()
    app.include_router(router)
    runtime = SimpleNamespace(board_id=board, runtime_revision=7)
    packet = {'board_id': board, 'runtime_revision': 7, 'mode': 'yolo_only', 'seq': 123}
    app.state.config = SimpleNamespace(realtime_tracking=False)
    app.state.runtime_manager = SimpleNamespace(snapshot=lambda: runtime)
    app.state.motion_frame_state = SimpleNamespace(get=lambda after: packet)
    app.state.glasses_stream = SimpleNamespace(snapshot=lambda: {'active': True})
    with TestClient(app) as client:
        response = client.get('/api/tracking/frame')
        assert response.status_code == 200 and response.json() == packet
        app.state.glasses_stream = SimpleNamespace(snapshot=lambda: {'active': False})
        assert client.get('/api/tracking/frame').status_code == 404
