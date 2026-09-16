from types import SimpleNamespace
import base64
import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.tracking import router
from app.component_worker import ComponentPoseResult

def test_model_source_endpoint_is_lossless_and_paired():
    image = np.random.default_rng(2).integers(0,256,(48,64,3),dtype=np.uint8)
    slot = SimpleNamespace(frame_id=7,frame=image)
    result = ComponentPoseResult('hc-sr04',7,100.,'searching',0.,(64,48),None,(),
        'occlusion_hold',tracking_reason='pin_orientation_unverified',
        orientation_input={'corners': [[1,1],[20,1],[20,30],[1,30]]})
    app = FastAPI()
    app.include_router(router)
    app.state.component_pose_state = SimpleNamespace(get_synchronized=lambda _: (slot,result))
    with TestClient(app) as client:
        response = client.get('/api/tracking/component-source')
        assert response.status_code == 200
        data = response.json()
        assert data['frame_id'] == data['component_pose']['frame_id'] == 7
        decoded = cv2.imdecode(np.frombuffer(base64.b64decode(data['image'].split(',')[1]),np.uint8),cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(decoded,image)
        assert data['component_pose']['pose_quality']['orientation_input'] == result.orientation_input
        assert client.get('/api/tracking/component-source?after=7').status_code == 204
        assert client.get('/api/tracking/component-source?component_id=unknown').status_code == 404
