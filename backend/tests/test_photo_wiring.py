"""Fixed-photo POC contracts with fake models/bridge; no camera, AI or GPIO I/O."""
import copy
import hashlib
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.photo_wiring import router
from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPinPosition, ComponentPoseResult
from app.photo_wiring import (PhotoCaptureRequest, PhotoCheckRequest, PhotoOpinion,
    PhotoWiringService, canonical_plan, context_mutation, reconcile_results, validate_plan)
from app.vision.interface import DetectionResult, PinDetection


class Clock:
    value = 100.
    def __call__(self):
        return self.value


class Worker:
    def __init__(self, running=True, fail=False):
        self.running, self.fail = running, fail
        self.starts = self.stops = 0
        self.close_models = []
        self._stop = threading.Event()
        self._thread = NS(is_alive=lambda: self.running) if running else None

    def start(self):
        self.starts += 1
        self.running = True
        self._stop.clear()
        self._thread = NS(is_alive=lambda: self.running)

    def stop(self, **kwargs):
        self.stops += 1
        self.close_models.append(kwargs.get("close_models"))
        self._stop.set()
        self.running = False
        self._thread = None
        if self.fail:
            raise RuntimeError("stop failed")


class Component(Worker):
    def __init__(self, component_id, *, mismatch=False):
        super().__init__()
        self._profile = NS(component_id=component_id)
        self.detect_calls, self.reset_calls = [], 0
        self.mismatch = mismatch

    def reset_tracking(self):
        assert not self.running
        self.reset_calls += 1

    def detect_yolo_frame(self, slot):
        assert not self.running
        self.detect_calls.append((slot.frame_id, slot.ts_ms, slot.frame.copy()))
        return ComponentPoseResult(self._profile.component_id, slot.frame_id+int(self.mismatch), slot.ts_ms,
            "locked", .9, (slot.frame.shape[1], slot.frame.shape[0]), np.array([[10,10],[80,10],[80,80],[10,80]]),
            (ComponentPinPosition("VCC", 30., 40., .9),), "yolo_direct")


class Detector:
    def __init__(self, mismatch=False):
        self.mismatch, self.calls, self.yolo_only, self.closed = mismatch, [], False, False
        self.configure_calls = []

    def set_yolo_only(self, enabled):
        self.yolo_only = enabled
        self.configure_calls.append(enabled)

    def detect(self, frame, frame_id, ts_ms):
        assert self.yolo_only
        self.calls.append((frame_id, ts_ms, frame.copy()))
        return DetectionResult("raspberry-pi-5", frame_id+int(self.mismatch), ts_ms, "locked", .95,
            [PinDetection("GPIO17", 30., 40., .9)], [(0,0),(159,0),(159,99),(0,99)])

    def close(self):
        self.closed = True


class Bus:
    def __init__(self, clock):
        self.clock, self.latest_seq, self.calls = clock, 0, []
        self.frame = np.zeros((100, 160, 3), np.uint8)
        self.frame[:, 20:40] = (70, 180, 230)

    def get_latest(self, **kwargs):
        self.calls.append(kwargs)
        self.latest_seq += 1
        self.clock.value += .01
        return FrameSlot(self.frame, self.latest_seq+40, self.clock()*1000, self.latest_seq)


class Geometry:
    """Inject supported measurements to isolate service lifecycle/model calls."""
    @staticmethod
    def entry(object_id, outline):
        return dict(object_id=object_id,status="located",method="fake_current_photo",reason="supported",
            raw_outline_px=np.asarray(outline).tolist(),corrected_outline_px=np.asarray(outline).tolist(),
            evidence=dict(model_confidence=.9,pin_geometry_verified=True,board_geometry_verified=True),candidate_pins=[])
    def board(self,frame,result,detector):
        return result,self.entry(result.board_id,result.outline_px)
    def component(self,frame,result,worker):
        return result,self.entry(result.component_id,result.outline_px)


def body(component_ids=("hc-sr04", "mrd-tf240-8p-cs")):
    plan = canonical_plan()
    return PhotoCaptureRequest(project_id="photo-wiring-poc", project_revision=1,
        catalog_version=plan["catalog_version"], profile_versions=plan["profile_versions"],
        wires=[w for w in plan["wires"] if w["component_id"] in component_ids])


def setup(*, mismatch=False, check_launcher=None):
    clock = Clock()
    detector = Detector(mismatch)
    components = [Component("hc-sr04"), Component("mrd-tf240-8p-cs")]
    camera = NS(source="device", width=160, height=100, fps=30)
    state = NS(config=NS(camera=camera), source=NS(device_name="test-webcam"),
        runtime_manager=NS(snapshot=lambda: NS(board_id="raspberry-pi-5", runtime_revision=7)),
        frame_bus=Bus(clock), vision_worker=Worker(), body_worker=Worker(), motion_worker=Worker(),
        wire_worker=Worker(), component_segmentation_worker=Worker(), component_workers=components,
        component_worker=None, camera_control_lock=threading.Lock(),
        camera_tuner=NS(snapshot=lambda: {"busy": False}), glasses_stream=NS(snapshot=lambda: {"active":False, "state":"stopped"}),
        detection_state=NS(clear=Mock()), component_pose_state=NS(clear=Mock()),
        motion_frame_state=NS(clear=Mock()), wire_state=NS(clear=Mock()),
        verification_state=NS(clear=Mock(), set_manual=Mock()),
        design_service=NS(lock=threading.Lock(), busy=False, bridge=NS(generate=Mock())))
    service = PhotoWiringService(state, detector_factory=lambda: detector, clock=clock,
        watchdog=False, check_launcher=check_launcher or (lambda f:f()),geometry=Geometry())
    return service, state, clock, detector


def opinion(wires, **changes):
    result = []
    for wire in wires:
        item = dict(wire_id=wire["wire_id"], board_observation=dict(state="target", observed_pin=wire["board_pin"], evidence="Visible label and inserted housing"),
            component_observation=dict(state="target", observed_pin=wire["component_pin"], evidence="Visible label and inserted housing"),
            wire_observation=dict(same_wire="consistent", visibility="traceable", evidence="Visible entire strand"), note="Photo appearance matches")
        item.update(copy.deepcopy(changes))
        result.append(item)
    return {"results":result, "summary":"Fixed photo review"}


def test_canonical_plan_uses_supported_shared_profiles_and_rejects_identity_changes():
    request = body()
    assert validate_plan(request) == ["hc-sr04", "mrd-tf240-8p-cs"]
    request.wires[0].board_pin = "GPIO999"
    with pytest.raises(HTTPException) as err:
        validate_plan(request)
    assert err.value.status_code == 422
    duplicate = body()
    duplicate.wires.append(duplicate.wires[0])
    with pytest.raises(HTTPException, match="duplicate_wire_id"):
        validate_plan(duplicate)
    outdated = body()
    outdated.profile_versions["hc-sr04"]["sha256"] = "bad"
    with pytest.raises(HTTPException) as err:
        validate_plan(outdated)
    assert err.value.status_code == 409


def test_pause_capture_once_same_frame_copy_and_resume_only_previous_running_workers():
    service, state, _, detector = setup()
    dormant = Worker(running=False)
    state.insertion_vlm_worker = dormant
    token = service.start()["session_id"]
    assert state.camera_control_lock.locked()
    assert all(not worker.running for worker, _ in service._workers())
    assert state.body_worker.close_models == [False]
    assert all(c.close_models == [False] for c in state.component_workers)
    packet = service.capture(token, body())
    assert state.frame_bus.calls == [{"timeout":2, "newer_than":0}]
    assert len(detector.calls) == 1
    assert all(len(c.detect_calls) == 1 and c.reset_calls == 1 for c in state.component_workers)
    for component in packet["components"]:
        assert component["frame_id"] == packet["detection"]["frame_id"] == packet["frame_id"]
        assert component["ts_ms"] == packet["capture_ts_ms"]
        assert component["runtime_revision"] == packet["runtime_revision"] == 7
        assert component["video_size"] == packet["video_size"] == [160,100]
    image = service.image(packet["capture_id"])
    assert hashlib.sha256(image).hexdigest() == packet["image_sha256"]
    state.frame_bus.frame[:] = 255
    assert np.mean(detector.calls[0][2]) < 50
    assert all(np.mean(c.detect_calls[0][2]) < 50 for c in state.component_workers)
    assert service.image(packet["capture_id"]) == image
    service.finish(token)
    assert all(worker.running for worker,_ in service._workers() if worker is not dormant)
    assert not dormant.running and dormant.starts == 0
    assert not state.camera_control_lock.locked()
    state.verification_state.clear.assert_not_called()
    state.verification_state.set_manual.assert_not_called()


def test_photo_mode_zero_live_inference_while_raw_preview_bus_continues():
    service, state, _, _ = setup()
    class LiveWorker:
        def __init__(self, bus):
            self.bus, self.calls, self._stop, self._thread = bus, 0, threading.Event(), None
        def start(self):
            self._stop.clear()
            self._thread = threading.Thread(target=self.run)
            self._thread.start()
        def run(self):
            seq = -1
            while not self._stop.is_set():
                slot = self.bus.get_latest(timeout=.01, newer_than=seq)
                if slot is not None:
                    seq = slot.seq
                    self.calls += 1
        def stop(self):
            self._stop.set()
            self._thread.join(1)
            self._thread = None
    bus = FrameBus()
    worker = LiveWorker(bus)
    state.vision_worker, state.frame_bus = worker, bus
    worker.start()
    bus.put(np.zeros((20,20,3), np.uint8), 1, time.monotonic()*1000)
    deadline = time.monotonic()+1
    while not worker.calls and time.monotonic()<deadline:
        time.sleep(.005)
    assert worker.calls
    token = service.start()["session_id"]
    count = worker.calls
    for frame_id in range(2,8):
        bus.put(np.zeros((20,20,3), np.uint8), frame_id, time.monotonic()*1000)
    assert bus.latest_seq == 7
    time.sleep(.025)
    assert worker.calls == count and worker._thread is None
    service.finish(token)
    worker.stop()


def test_each_retaken_photo_resets_direct_search_without_warming_up_an_old_frame():
    service,state,_,detector=setup()
    token=service.start()["session_id"]
    first=service.capture(token,body())
    count=len(detector.configure_calls)
    second=service.capture(token,body())
    assert len(detector.configure_calls)==count+1
    assert [call[0] for call in detector.calls]==[first["frame_id"],second["frame_id"]]
    assert first["capture_id"] != second["capture_id"]
    assert all([call[0] for call in c.detect_calls]==[first["frame_id"],second["frame_id"]]
        for c in state.component_workers)


def test_slow_first_model_load_and_inference_renew_lease_when_photo_finishes():
    service,state,clock,detector=setup()
    token=service.start()["session_id"]
    original=detector.detect
    def slow_inference(*args):
        clock.value += 70
        return original(*args)
    detector.detect=slow_inference
    packet=service.capture(token,body())
    service.expire_lease()
    assert service.active and service.get_capture(packet["capture_id"])["frame_id"]==packet["frame_id"]
    assert service.heartbeat(token)["continuous_inference"] is False


@pytest.mark.parametrize("failure", ["old_seq", "old_time", "none", "future", "invalid_pixels"])
def test_capture_rejects_unrelated_or_pre_request_frames_without_any_inference(failure):
    service,state,clock,detector = setup()
    token = service.start()["session_id"]
    good = FrameSlot(state.frame_bus.frame, 41, clock()*1000, 1)
    slot = {"old_seq":FrameSlot(good.frame,41,good.ts_ms,0), "old_time":FrameSlot(good.frame,41,good.ts_ms-1,1),
        "none":None, "future":FrameSlot(good.frame,41,good.ts_ms+10000,1),
        "invalid_pixels":FrameSlot(np.zeros((2,2),np.uint8),41,good.ts_ms,1)}[failure]
    state.frame_bus.get_latest = Mock(return_value=slot)
    with pytest.raises(HTTPException):
        service.capture(token, body())
    assert detector.calls == []


@pytest.mark.parametrize("side", ["board", "component"])
def test_capture_rejects_result_with_different_source_frame(side):
    service,state,_,detector = setup(mismatch=side=="board")
    state.component_workers[0].mismatch = side=="component"
    token = service.start()["session_id"]
    with pytest.raises(HTTPException, match="frame_mismatch"):
        service.capture(token, body())
    assert not service.captures


def test_heartbeat_lease_expiry_rollback_shutdown_and_busy_source_guards():
    service,state,clock,detector = setup()
    token = service.start()["session_id"]
    clock.value += 40
    assert service.heartbeat(token)["continuous_inference"] is False
    clock.value += service.lease_s-1
    service.expire_lease()
    assert service.active
    clock.value += 2
    service.expire_lease()
    assert not service.active and state.vision_worker.running and not state.camera_control_lock.locked()
    with pytest.raises(HTTPException, match="photo_session_expired"):
        service.heartbeat(token)
    state.vision_worker.fail = True
    with pytest.raises(HTTPException, match="photo_pause_failed"):
        service.start()
    assert state.motion_worker.running and state.vision_worker.running and not service.active
    assert not state.camera_control_lock.locked()
    state.vision_worker.fail = False
    token = service.start()["session_id"]
    service.capture(token, body())
    starts = state.vision_worker.starts
    service.close()
    assert not state.vision_worker.running and state.vision_worker.starts == starts
    assert detector.closed and not state.camera_control_lock.locked()
    other,state,_,_=setup()
    state.camera_tuner.snapshot = lambda:{"busy":True}
    with pytest.raises(HTTPException, match="camera_adjustment_busy"):
        other.start()
    state.camera_tuner.snapshot = lambda:{"busy":False}
    state.glasses_stream.snapshot = lambda:{"active":False,"state":"switching"}
    with pytest.raises(HTTPException, match="camera_source_switch_busy"):
        other.start()


def test_fixed_photo_check_uses_one_cloud_call_same_hash_and_no_manual_or_hardware_changes():
    service,state,clock,_=setup()
    token=service.start()["session_id"]
    packet=service.capture(token,body())
    state.design_service.bridge.generate.return_value=opinion(packet["wires"])
    reply=service.submit_check(packet["capture_id"],PhotoCheckRequest(model="selected",effort="low"))
    job=service.get_check(reply["job_id"])
    assert job["status"]=="completed" and not job["electrical_verified"]
    assert job["frame_id"]==packet["frame_id"] and job["image_sha256"]==packet["image_sha256"]
    assert all(r["verdict"]==("uncertain" if w["connection_kind"]=="divider" else "matched")
        for r,w in zip(job["results"],packet["wires"]))
    state.design_service.bridge.generate.assert_called_once()
    args,kwargs=state.design_service.bridge.generate.call_args
    assert kwargs["model"]=="selected" and kwargs["effort"]=="low" and kwargs["fail_if_busy"] and kwargs["restricted_tools"]
    assert "NOT observations" in args[0] and "No tools" in args[0] and packet["image_sha256"] in args[0]
    assert not service.busy and not state.design_service.busy
    clock.value += 60
    state.runtime_manager.snapshot=lambda:NS(board_id="raspberry-pi-5",runtime_revision=8)
    historical = service.get_check(reply["job_id"])
    assert historical["results"]==job["results"] and historical["stale"]
    assert service.get_capture(packet["capture_id"])["stale"]
    with pytest.raises(HTTPException,match="photo_context_changed"):
        service.submit_check(packet["capture_id"],PhotoCheckRequest(model="selected"))
    state.verification_state.set_manual.assert_not_called()


@pytest.mark.parametrize("change, verdict", [
    ({"board_observation":{"state":"empty","observed_pin":"GPIO17","evidence":"Bare target tip"}},"suspected"),
    ({"board_observation":{"state":"other","observed_pin":"GPIO18","evidence":"Inserted into GPIO18"}},"suspected"),
    ({"board_observation":{"state":"target","observed_pin":"GPIO18","evidence":"Contradictory pin"}},"uncertain"),
    ({"wire_observation":{"same_wire":"different","visibility":"traceable","evidence":"Different strands"}},"suspected"),
    ({"wire_observation":{"same_wire":"consistent","visibility":"partially_visible","evidence":"Hidden crossing"}},"uncertain"),
])
def test_conservative_three_states(change,verdict):
    wire=next(w for w in canonical_plan()["wires"] if w["board_pin"]=="GPIO17")
    result=reconcile_results(PhotoOpinion.model_validate(opinion([wire],**change)),[wire])
    assert result[0]["verdict"]==verdict


def test_unknown_duplicate_and_missing_cloud_wire_ids_cannot_be_promoted():
    wires=canonical_plan()["wires"][:2]
    raw=opinion(wires)
    raw["results"].pop()
    assert reconcile_results(PhotoOpinion.model_validate(raw),wires)[1]["verdict"]=="uncertain"
    raw["results"].append(copy.deepcopy(raw["results"][0]))
    with pytest.raises(ValueError,match="duplicate"):
        reconcile_results(PhotoOpinion.model_validate(raw),wires)
    raw["results"][1]["wire_id"]="unknown"
    with pytest.raises(ValueError,match="unknown"):
        reconcile_results(PhotoOpinion.model_validate(raw),wires)


@pytest.mark.parametrize("object_id",["raspberry-pi-5","hc-sr04"])
def test_unverified_geometry_cannot_ai_upgrade_target_traceable_to_matched(object_id):
    wire=next(w for w in canonical_plan()["wires"] if w["component_id"]=="hc-sr04" and w["connection_kind"]=="direct")
    localization=[Geometry.entry("raspberry-pi-5",[[0,0],[1,0],[1,1],[0,1]]),
        Geometry.entry("hc-sr04",[[0,0],[1,0],[1,1],[0,1]])]
    next(entry for entry in localization if entry["object_id"]==object_id)["status"]="uncertain"
    results=reconcile_results(PhotoOpinion.model_validate(opinion([wire])),[wire],localization)
    assert results[0]["verdict"]=="uncertain" and "幾何驗證" in results[0]["note"]
    wrong=opinion([wire],board_observation=dict(state="empty",observed_pin=wire["board_pin"],evidence="Independently visible bare target"))
    assert reconcile_results(PhotoOpinion.model_validate(wrong),[wire],localization)[0]["verdict"]=="suspected"


def test_missing_pin_geometry_evidence_cannot_match_even_when_locator_claims_located():
    wire=next(w for w in canonical_plan()["wires"] if w["connection_kind"]=="direct")
    localization=[dict(object_id="raspberry-pi-5",status="located",evidence={}),
        dict(object_id=wire["component_id"],status="located",evidence={})]
    assert reconcile_results(PhotoOpinion.model_validate(opinion([wire])),[wire],localization)[0]["verdict"]=="uncertain"
    assert reconcile_results(PhotoOpinion.model_validate(opinion([wire])),[wire])[0]["verdict"]=="uncertain"


def test_photo_check_receives_fixed_localization_and_demotes_unverified_pose_without_manual_writes():
    service,state,_,_=setup()
    session=service.start()["session_id"]
    packet=service.capture(session,body())
    original=copy.deepcopy(packet["localization"])
    stored=service.captures[packet["capture_id"]]["packet"]
    stored["localization"][0]["status"]="uncertain"
    stored["localization"][0]["evidence"]["pin_geometry_verified"]=False
    state.design_service.bridge.generate.return_value=opinion(packet["wires"])
    job=service.submit_check(packet["capture_id"],PhotoCheckRequest(model="selected"))
    result=service.get_check(job["job_id"])
    assert result["status"]=="completed" and all(w["verdict"]=="uncertain" for w in result["results"])
    prompt=state.design_service.bridge.generate.call_args.args[0]
    assert '"localization"' in prompt and "candidate_pins are diagnostics" in prompt
    assert packet["localization"]==original  # Response and stored/photo/check packets do not share mutable state.
    state.verification_state.set_manual.assert_not_called()


def test_failed_resume_retains_recovery_and_same_token_retry_without_duplicate_workers():
    service,state,clock,_=setup()
    token=service.start()["session_id"]
    original_start=state.vision_worker.start
    state.vision_worker.start=Mock(side_effect=RuntimeError("temporarily unavailable"))
    with pytest.raises(HTTPException,match="photo_resume_failed"):
        service.finish(token)
    assert service.active and state.camera_control_lock.locked()
    assert not state.vision_worker.running
    restarted_components=[c.starts for c in state.component_workers]
    with pytest.raises(HTTPException,match="photo_resume_pending"):
        service.heartbeat(token)
    state.vision_worker.start=original_start
    assert service.finish(token)["resumed"]
    assert state.vision_worker.running and not service.active
    assert not state.camera_control_lock.locked()
    assert [c.starts for c in state.component_workers]==restarted_components


def test_pause_rollback_resume_failure_is_retained_and_lease_can_recover_it():
    service,state,clock,_=setup()
    state.vision_worker.fail=True
    original_start=state.motion_worker.start
    state.motion_worker.start=Mock(side_effect=RuntimeError("restore failure"))
    with pytest.raises(HTTPException,match="resume pending"):
        service.start()
    assert service.active and state.camera_control_lock.locked()
    state.motion_worker.start=original_start
    clock.value += 6
    service.expire_lease()
    assert not service.active and state.motion_worker.running and not state.camera_control_lock.locked()


def test_single_flight_selected_wire_failure_retention_and_packet_routes():
    pending=[]
    service,state,clock,_=setup(check_launcher=pending.append)
    app=FastAPI()
    app.state.photo_wiring_service=service
    app.include_router(router)
    client=TestClient(app)
    plan=client.get("/api/photo-wiring/plan").json()
    token=client.post("/api/photo-wiring/sessions").json()["session_id"]
    payload={k:v for k,v in plan.items() if k!="component_ids"}
    payload.update(project_id="photo-wiring-poc",project_revision=1)
    packet=client.post(f"/api/photo-wiring/sessions/{token}/captures",json=payload).json()
    response=client.get(packet["image_url"])
    assert response.headers["cache-control"]=="no-store"
    assert hashlib.sha256(response.content).hexdigest()==packet["image_sha256"]
    wire=packet["wires"][0]
    reply=client.post(f"/api/photo-wiring/captures/{packet['capture_id']}/checks",json={"model":"test","wire_id":wire["wire_id"]})
    assert reply.status_code==202 and service.busy and state.design_service.busy
    assert client.post(f"/api/photo-wiring/captures/{packet['capture_id']}/checks",json={"model":"test"}).status_code==409
    state.design_service.bridge.generate.return_value=opinion([wire])
    pending.pop()()
    job=client.get(f"/api/photo-wiring/checks/{reply.json()['job_id']}").json()
    assert len(job["results"])==1 and job["capture_id"]==packet["capture_id"]
    state.design_service.bridge.generate.side_effect=RuntimeError("fake provider failure")
    failed=service.submit_check(packet["capture_id"],PhotoCheckRequest(model="test"))
    pending.pop()()
    assert service.get_check(failed["job_id"])["status"]=="failed"
    assert not service.busy and not state.design_service.busy
    for _ in range(7):
        service.capture(token,body())
    assert len(service.captures)==6
    assert client.get(packet["image_url"]).status_code==404
    last=next(iter(service.captures))
    clock.value += 901
    assert client.get(f"/api/photo-wiring/captures/{last}").status_code==404


def test_main_middleware_blocks_context_mutations_but_allows_photo_api_and_reads():
    from app.config import AppConfig
    from app.main import build_app
    root=Path(__file__).resolve().parents[2]
    config=AppConfig(board="raspberry-pi-5",profile_dir=root/"profiles",frontend_dist=root/"frontend/dist")
    app=build_app(config,source=NS())
    service,state,_,_=setup()
    app.state.photo_wiring_service=service
    client=TestClient(app)
    token=client.post("/api/photo-wiring/sessions").json()["session_id"]
    for path in ("/api/cameras/select","/api/camera/focus","/api/camera/modes","/api/camera/auto-tune",
                 "/api/controllers/select","/api/calibrate","/api/glasses/stream"):
        response=client.post(path,json={})
        assert response.status_code==409 and response.json()["detail"]=="photo_session_active"
    assert client.get("/api/photo-wiring/plan").status_code==200
    assert client.post(f"/api/photo-wiring/sessions/{token}/heartbeat").status_code==200
    assert client.delete(f"/api/photo-wiring/sessions/{token}").json()["resumed"]
    assert not context_mutation("GET","/api/camera/modes")
    assert not context_mutation("POST","/api/pi/stop")
