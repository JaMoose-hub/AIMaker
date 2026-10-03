"""Application lifecycle and complete photo/chat APIs with no webcam frames.

This uses injected YOLO/geometry/AI fakes, not physical recognition evidence.
"""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import time

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from app.assistant import AssistantService
from app.main import build_app
from app.mobile import MobileService
from app.mobile_photo import MobilePhotoAnalyzer
from app.vision.yolo_pose import BoardPoseObservation
from test_backend_core import make_config, StubDetector, StubFrameSource
from test_mobile import Clock, RTC, preview
from test_photo_wiring import Geometry


def test_phone_capture_and_shared_ai_without_webcam_frames(tmp_path):
    class AbsentWebcam(StubFrameSource):
        def read(self):
            return None

    source = AbsentWebcam()
    app = build_app(make_config(), detector=StubDetector(), source=source)
    app.state.assistant = AssistantService(app.state, tmp_path / "assistant")
    corners = np.float32([[5,5], [75,5], [75,55], [5,55]])
    locator = SimpleNamespace(locate=Mock(return_value=BoardPoseObservation(corners,.9,np.ones(4),(5,5,75,55))))
    app.state.mobile_photo = MobilePhotoAnalyzer(app.state,
        contexts={"raspberry-pi-5": SimpleNamespace(_locator=locator)}, geometry_factory=Geometry)
    clock = Clock()
    app.state.mobile_service = MobileService(app.state, tmp_path / "mobile", clock=clock, wall=time.time, rtc_factory=RTC)
    generate = Mock(return_value={"answer": "Saved photo received."})
    app.state.design_service.bridge = SimpleNamespace(generate=generate, close=lambda: None)
    original_camera = app.state.config.camera.model_dump()
    with TestClient(app, client=("127.0.0.1", 5000)) as client:
        app.state.assistant.create("phone-project")
        context = dict(conversation_id="phone-project", title="Phone project", stage="guide", target="auto", round=0,
            design=dict(prompt="Inspect photograph", component_ids=["hc-sr04"], locale="en", model="fake", effort="low"), context={})
        assert client.post("/api/mobile/context", json=context).status_code == 200
        pair = client.post("/api/mobile/pairings", json=dict(conversation_id="phone-project", base_url="http://192.168.1.5:8100")).json()
        phone = client.post("/api/mobile/pair", json=dict(code=pair["code"])).json()
        headers = {"Authorization": "Bearer "+phone["token"]}
        generation = client.post("/api/mobile/stream", headers=headers).json()["generation"]
        for seq, stamp in enumerate((100.,100.5,101.1),1):
            clock.now = stamp
            app.state.mobile_service.accept_preview(phone["session_id"],generation,seq,stamp,preview(),(100,100),phone["context_id"])
        ticket = client.post("/api/mobile/capture-ticket", headers=headers).json()
        assert "ticket_id" in ticket
        assert client.delete("/api/mobile/stream", headers=headers).status_code == 200
        image = BytesIO()
        Image.new("RGB",(80,60),(20,100,140)).save(image,"JPEG")
        asset = client.post("/api/mobile/assets", headers=headers, data={"upload_id":"fresh"},
            files={"file":("fresh.jpg",image.getvalue(),"image/jpeg")}).json()
        response = client.post("/api/mobile/captures",headers=headers,
            json=dict(ticket_id=ticket["ticket_id"],asset_id=asset["id"],request_id="photo"))
        assert response.status_code == 200, response.text
        capture = response.json()
        assert capture["video_size"] == [80,60] and capture["conversation_id"] == "phone-project"
        assert app.state.assistant.read("phone-project")["active_media"]["capture_id"] == capture["capture_id"]
        assert client.get(capture["image_url"],headers=headers).status_code == 200
        wire = capture["wires"][0]["wire_id"]
        assert client.put("/api/mobile/view",headers=headers,json=dict(capture_id=capture["capture_id"],wire_id=wire)).status_code == 200
        # Plain text after a new capture must reference this photograph automatically.
        message = dict(request_id="question", text="Inspect this photo", context_id=phone["context_id"])
        assert client.post("/api/mobile/messages",headers=headers,json=message).status_code == 202
        deadline = time.monotonic()+3
        while time.monotonic() < deadline:
            history = client.get("/api/mobile/conversation",headers=headers).json()
            if history["jobs"] and history["jobs"][-1]["status"] != "running":
                break
            time.sleep(.01)
        assert history["jobs"][-1]["status"] == "completed", history
        assert history["messages"][-1]["text"] == "Saved photo received."
        assert client.post("/api/mobile/messages",headers=headers,json=message).status_code == 202
        assert generate.call_count == 1 and locator.locate.call_count == 1
        assert app.state.frame_bus.latest_seq == 0
        assert app.state.config.camera.model_dump() == original_camera
    assert source.closed
