import base64
import copy
import json
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import Mock

import cv2
import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.cloud_wiring import router
from app.api.design import DesignService
from app.cloud_wiring import (CloudWiringOpinion, CloudWiringRequest, CloudWiringService,
    capture_images, cloud_prompt, inspection_views, opinion_verdict, reconcile_opinion, resolve_wire)
from app.codex_bridge import CodexBridge
from app.designs import demo_design
from app.capture.bus import FrameSlot
from app.component_worker import ComponentPoseResult, ComponentPinPosition
from app.vision.interface import DetectionResult, PinDetection


def request(cid="hc-sr04", index=1):
    d = demo_design([cid])
    w = d["wiring"][index]
    return CloudWiringRequest(project_id=d["id"], project_revision=d["revision"], catalog_version=d["catalog_version"],
        profile_versions=d["profile_versions"], wire_id=w["id"], component_id=cid, board_pin=w["boardPin"],
        component_pin=w["componentPin"], connection_kind=w["connectionKind"], model="test-vision", effort="low")


def opinion(**changes):
    def observation():
        return {"connectors": [{"id": "c1", "position": "At header", "contact": "covers_pin",
                "wire_color": {"name": "yellow", "visibility": "clear", "evidence": "Yellow insulation at rear exit"},
                "evidence": "Housing covers one tip; adjacent shank is visible", "breadboard": None}],
            "target_identity": "identified", "target_pin_tip": "covered", "target_connector_id": "c1",
            "evidence": "Target label and covered tip are visible"}
    return {"visual_observations": {"board": observation(), "component": observation()},
        "authority": "visual_advisory", "board_endpoint": {"state": "target", "observed_pin": "GPIO17", "evidence": "Visible base"},
        "component_endpoint": {"state": "target", "observed_pin": "TRIG", "evidence": "Visible base"},
        "wire_colors": {"board": {"name": "yellow", "visibility": "clear", "evidence": "Yellow insulation at Pi connector"},
            "component": {"name": "yellow", "visibility": "clear", "evidence": "Yellow insulation at module connector"},
            "comparison": "similar", "evidence": "Both ends have yellow insulation"},
        "wire_path": {"visibility": "traceable", "evidence": "The wire can be followed in pi_overview"},
        "same_wire": "consistent", "summary": "Photo looks matched", "limitations": "Visual only", **changes}


def setup(body=None, reply=None, staged=False):
    body = body or request()
    frame = np.zeros((600, 1000, 3), np.uint8)
    frame[:, :500] = (20, 30, 200)
    frame[:, 500:] = (190, 60, 20)
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    def pose(target, x):
        return {"frame_id": 23, "tracking": "locked", "video_size": [1000, 600],
            "pose_quality": {"stability": "optical_flow"},
            "pins": [{"id": target, "x": x, "y": 300, "v": True}, {"id": "neighbor", "x": x, "y": 325, "v": True}]}
    packet = {"frame_id": 23, "ts_ms": time.monotonic()*1000, "runtime_revision": 7, "board_id": "raspberry-pi-5",
        "image": "data:image/jpeg;base64,"+base64.b64encode(encoded).decode(),
        "detection": pose(body.board_pin, 240), "components": [{**pose(body.component_pin, 760), "component_id": body.component_id}]}
    bridge = NS(generate=Mock(return_value=reply or opinion()))
    # Lifecycle/contract tests inject one deterministic inspection. The real
    # multi-turn inspector is exercised separately in test_cloud_connectors.py.
    def fixture_inspector(bridge, body, paths, progress, capture):
        progress("component", [])
        raw = bridge.generate(cloud_prompt(body, resolve_wire(body), {"mode": "overview", "views": [],
            "same_frame": True, "capture_skew_ms": 0, "coordinates_are_hints_only": True}),
            CloudWiringOpinion.model_json_schema(), model=body.model, effort=body.effort,
            image_paths=list(paths.values()), timeout_s=120, fail_if_busy=True)
        checked, issues = reconcile_opinion(CloudWiringOpinion.model_validate(raw), body)
        return checked, issues, []
    state = NS(config=NS(realtime_tracking=True, camera=NS(source=0)),
        runtime_manager=NS(snapshot=lambda: NS(board_id="raspberry-pi-5", runtime_revision=7)),
        detection_state=NS(get_synchronized=lambda: None),
        component_pose_state=NS(get_synchronized=lambda cid: None),
        motion_frame_state=NS(get=lambda **kw: packet), design_service=DesignService(bridge), cloud_wiring_service=CloudWiringService(inspector=None if staged else fixture_inspector, burst_seconds=0),
        frame_bus=NS(get_latest=Mock(side_effect=lambda **kw: FrameSlot(frame, 24, time.monotonic()*1000, 24))))
    app = FastAPI()
    app.state._state.update(state.__dict__)
    app.include_router(router)
    return body, packet, state, TestClient(app), bridge


def finished(service, job_id, state=None):
    deadline = time.monotonic()+4
    while time.monotonic() < deadline:
        job = service.get(job_id, state)
        if job["status"] in {"completed", "failed"}: return job
        time.sleep(.01)
    pytest.fail("Cloud check did not finish")


def test_crops_are_exact_source_location_with_context_neighbors_and_no_overlay():
    body, packet, state, _, _ = setup()
    images, capture = capture_images(state, body)
    assert list(images) == ["pi_overview", "pi_pins", "component_pins"]
    assert capture["same_frame"] and capture["coordinates_are_hints_only"]
    left = cv2.imdecode(np.frombuffer(images["pi_pins"], np.uint8), 1)
    right = cv2.imdecode(np.frombuffer(images["component_pins"], np.uint8), 1)
    assert np.mean(left[:, :, 2]) > 180 and np.mean(right[:, :, 0]) > 170
    assert capture["views"][1]["target_hint"] == {"x": 175, "y": 175}
    assert len(capture["views"][1]["pin_hints"]) == 2
    prompt = cloud_prompt(body, resolve_wire(body), capture)
    assert "NOT observations" in prompt and "continuity" in prompt
    assert "Pi 5" in prompt and "GPIO17" in prompt and "TRIG" in prompt
    assert "password" not in prompt and "192.168.50.174" not in prompt


@pytest.mark.parametrize("cid,order", [("hc-sr04", ["VCC", "GND"]), ("hw-123", ["VCC", "INT"]), ("mrd-tf240-8p-cs", ["GND", "BLK"])])
@pytest.mark.parametrize("turns,delta", [(0, (20, 0)), (1, (0, 20)), (2, (-20, 0)), (3, (0, -20))])
def test_reading_copies_are_lossless_rotations_of_original_pixels_using_shared_profiles(cid, order, turns, delta):
    # Pixel pattern, not a synthetic wiring verdict.
    frame = np.arange(321*321*3, dtype=np.uint32).reshape((321, 321, 3)).astype(np.uint8)
    ok, jpeg = cv2.imencode('.jpg', frame)
    assert ok
    originals = {"component_pins": jpeg.tobytes()}
    capture = {"views": [{"name": "component_pins", "frame_id": 17, "ts_ms": 12,
        "size": [321, 321], "pin_hints": [{"id": order[0], "x": 160, "y": 160},
            {"id": order[1], "x": 160+delta[0], "y": 160+delta[1]}]}]}
    before = copy.deepcopy(capture)
    images, meta = inspection_views(originals, capture, cid)
    assert images["component_pins"] == originals["component_pins"] and capture == before
    view = meta["views"][-1]
    assert view["source_view"] == "component_pins" and view["rotation_ccw_quarter_turns"] == turns
    assert view["size"] == [963, 963] and view["adds_no_detail"]
    assert "pin_hints" not in view and "target_hint" not in view
    original = cv2.imdecode(np.frombuffer(originals["component_pins"], np.uint8), 1)
    reading = cv2.imdecode(np.frombuffer(images["component_reading"], np.uint8), 1)
    np.testing.assert_array_equal(reading, np.repeat(np.repeat(np.rot90(original, turns), 3, axis=0), 3, axis=1))


def test_reading_helpers_do_not_invent_orientation_or_create_crops_in_overview_mode():
    images = {"pi_overview": b"original"}
    capture = {"mode": "overview", "views": [{"name": "pi_overview"}]}
    assert inspection_views(images, capture, "hc-sr04") == (images, capture)


@pytest.mark.parametrize("change", ["stale", "mismatched_frame", "hidden_pin", "wrong_module", "wrong_size", "expired", "held", "runtime", "outline_only", "no_pins", "bad_image"])
def test_unusable_local_pose_sends_fresh_overview_without_old_pin_hints(change):
    body, packet, state, c, bridge = setup()
    if change == "stale": packet["components"][0]["tracking"] = "stale"
    if change == "mismatched_frame": packet["detection"]["frame_id"] = 22
    if change == "hidden_pin": packet["detection"]["pins"][0]["v"] = False
    if change == "wrong_module": packet["components"][0]["component_id"] = "hw-123"
    if change == "wrong_size": packet["detection"]["video_size"] = [100, 100]
    if change == "expired": packet["ts_ms"] -= 2000
    if change == "held": packet["detection"]["pose_quality"]["stability"] = "occlusion_hold"
    if change == "runtime": packet["runtime_revision"] = 99
    if change == "outline_only": packet["detection"]["pose_quality"]["outline_only"] = True
    if change == "no_pins": packet["detection"]["pins"] = []
    if change == "bad_image": packet["image"] = "data:image/jpeg;base64,garbage"
    r = c.post("/api/guidance/cloud-checks", json=body.model_dump())
    assert r.status_code == 202
    job = finished(state.cloud_wiring_service, r.json()["job_id"])
    assert job["status"] == "completed" and job["error"] is None
    assert [i["name"] for i in job["images"]] == ["pi_overview"]
    assert job["capture"]["mode"] == "overview" and job["capture"]["anchors"] == {}
    assert job["capture"]["views"][0]["frame_id"] == 24
    prompt = bridge.generate.call_args.args[0]
    assert '"mode": "overview"' in prompt and '"target_hint"' not in prompt and '"pin_hints"' not in prompt
    bridge.generate.assert_called_once()
    assert not state.design_service.busy and not state.cloud_wiring_service.busy


@pytest.mark.parametrize("cid", ["hc-sr04", "hw-123", "mrd-tf240-8p-cs"])
def test_supported_module_names_are_not_confused_by_same_pin_name(cid):
    body = request(cid, 0)
    body, packet, state, _, _ = setup(body)
    assert resolve_wire(body)["componentId"] == cid
    images, _ = capture_images(state, body)
    assert "component_pins" in images
    packet["components"][0]["component_id"] = "not-the-target"
    images, capture = capture_images(state, body)
    assert list(images) == ["pi_overview"] and capture["anchors"] == {}


@pytest.mark.parametrize("field,value", [("board_pin", "GPIO18"), ("component_pin", "GND"), ("connection_kind", "divider"),
    ("catalog_version", "stale"), ("profile_versions", {}), ("wire_id", "hw-123:gnd")])
def test_target_and_profile_validation_before_capture(field, value):
    body, _, state, c, bridge = setup()
    response = c.post("/api/guidance/cloud-checks", json={**body.model_dump(), field: value})
    assert response.status_code in {409, 422}
    assert not state.cloud_wiring_service.jobs
    bridge.generate.assert_not_called()


def test_cloud_job_addressable_photos_and_advisory_result_no_manual_or_deploy_mutation():
    body, _, state, c, bridge = setup()
    state.verification_state = Mock()
    state.pi_deployer = Mock()
    r = c.post("/api/guidance/cloud-checks", json=body.model_dump())
    job = finished(state.cloud_wiring_service, r.json()["job_id"])
    assert job["result"]["verdict"] == "looks_matched" and job["result"]["electrical_verified"] is False
    assert bridge.generate.call_count == 1
    kwargs = bridge.generate.call_args.kwargs
    assert kwargs["model"] == "test-vision" and kwargs["timeout_s"] == 120 and kwargs["fail_if_busy"]
    assert all(not path.exists() for path in kwargs["image_paths"])
    for image in job["images"]:
        response = c.get(image["url"])
        assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
        assert response.headers["content-type"] == ("image/png" if image["name"].endswith(("_pins", "_reading", "_contact")) else "image/jpeg")
    assert len(job["images"]) == 7
    assert not state.verification_state.mock_calls and not state.pi_deployer.mock_calls
    assert c.get("/api/guidance/cloud-checks/missing").status_code == 404


def test_single_flight_and_no_automatic_retries_on_cloud_error():
    body, _, state, c, bridge = setup()
    gate = threading.Event()
    def generate(*a, **kw):
        assert gate.wait(3)
        raise RuntimeError("Cloud quota unavailable")
    bridge.generate.side_effect = generate
    first = c.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    assert c.post("/api/guidance/cloud-checks", json=body.model_dump()).status_code == 409
    gate.set()
    result = finished(state.cloud_wiring_service, first)
    assert result["status"] == "failed" and "quota" in result["error"]
    assert bridge.generate.call_count == 1
    state.design_service.busy = True
    assert c.post("/api/guidance/cloud-checks", json=body.model_dump()).status_code == 409


@pytest.mark.parametrize("changes,expected", [({}, "looks_matched"), ({"same_wire": "uncertain"}, "uncertain"),
    ({"same_wire": "different"}, "suspected_issue"),
    ({"board_endpoint": {"state": "occluded", "observed_pin": None, "evidence": "hidden"}}, "uncertain"),
    ({"board_endpoint": {"state": "other", "observed_pin": "GPIO18", "evidence": "adjacent"}}, "suspected_issue")])
def test_verdict_is_cloud_visual_advice_and_unknown_does_not_pass(changes, expected):
    assert opinion_verdict(CloudWiringOpinion.model_validate(opinion(**changes)), request()) == expected
    # The selected HC-SR04+ now has a direct 3.3V ECHO wire.
    assert opinion_verdict(CloudWiringOpinion.model_validate(opinion()), request(index=2)) == "looks_matched"
    divider = request(index=2).model_copy(update={"connection_kind": "divider"})
    assert opinion_verdict(CloudWiringOpinion.model_validate(opinion()), divider) == "needs_review"


def test_model_format_errors_do_not_become_success():
    body, _, state, c, _ = setup(reply={"authority": "electrical_verified"})
    job_id = c.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    job = finished(state.cloud_wiring_service, job_id)
    assert job["status"] == "failed" and job["result"] is None


@pytest.mark.parametrize("path", ["partially_visible", "not_visible"])
def test_matching_colors_and_endpoints_do_not_pass_an_untraceable_path(path):
    result = CloudWiringOpinion.model_validate(opinion(wire_path={"visibility": path, "evidence": "Path hidden"}))
    assert result.wire_colors.comparison == "similar"
    assert opinion_verdict(result, request()) == "uncertain"


def test_readable_colors_are_preserved_when_exact_pin_or_wire_identity_is_uncertain():
    reply = opinion(board_endpoint={"state": "uncertain", "observed_pin": None, "evidence": "Adjacent pin unclear"},
                    same_wire="uncertain", wire_path={"visibility": "partially_visible", "evidence": "Crossing is obscured"})
    body, _, state, client, bridge = setup(reply=reply)
    job_id = client.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    result = finished(state.cloud_wiring_service, job_id)["result"]
    assert result["verdict"] == "uncertain" and not result["electrical_verified"]
    assert result["wire_colors"]["board"]["name"] == "yellow"
    assert result["wire_colors"]["component"]["name"] == "yellow"
    assert result["wire_path"]["evidence"] == "Crossing is obscured"
    bridge.generate.assert_called_once()


def test_unknown_colors_do_not_erase_an_independently_traceable_wire():
    colors = {"board": {"name": "unknown", "visibility": "partial", "evidence": "Ambiguous color cast"},
              "component": {"name": "unknown", "visibility": "partial", "evidence": "Ambiguous color cast"},
              "comparison": "uncertain", "evidence": "Color cannot be named reliably"}
    result = CloudWiringOpinion.model_validate(opinion(wire_colors=colors))
    assert opinion_verdict(result, request()) == "looks_matched"


def test_color_difference_alone_is_not_a_wrong_connection_verdict():
    reply = opinion(same_wire="uncertain", wire_path={"visibility": "partially_visible", "evidence": "Hidden middle"})
    reply["wire_colors"]["board"]["name"] = "orange"
    reply["wire_colors"]["component"]["name"] = "brown"
    reply["wire_colors"]["comparison"] = "different"
    assert opinion_verdict(CloudWiringOpinion.model_validate(reply), request()) == "uncertain"


@pytest.mark.parametrize("problem", ["missing_colors", "missing_path", "invalid_color", "invalid_visibility"])
def test_new_cloud_observations_are_required_and_schema_validated(problem):
    reply = opinion()
    if problem == "missing_colors": del reply["wire_colors"]
    if problem == "missing_path": del reply["wire_path"]
    if problem == "invalid_color": reply["wire_colors"]["board"]["name"] = "GPIO17"
    if problem == "invalid_visibility": reply["wire_path"]["visibility"] = "electrically_verified"
    body, _, state, _, _ = setup(reply=reply)
    job_id = state.cloud_wiring_service.submit(body, state)["job_id"]
    job = finished(state.cloud_wiring_service, job_id)
    assert job["status"] == "failed" and job["result"] is None


def test_prompt_requests_independent_color_observations_and_disambiguates_crossings():
    body, _, state, _, _ = setup()
    _, capture = capture_images(state, body)
    prompt = cloud_prompt(body, resolve_wire(body), capture)
    for instruction in ("INSULATION", "black plastic connector housing", "GND need not be black",
                        "orange/brown/red", "unknown ends must not count as similar",
                        "A crossing alone is NOT a reason to abstain", "wire_path.evidence",
                        "Do not equate matching colors", "pin from its neighbors"):
        assert instruction in prompt
    assert "crossing/hidden paths must be uncertain" not in prompt


def test_prompt_observes_connector_rear_insulation_before_target_matching():
    body, _, state, _, _ = setup()
    _, capture = capture_images(state, body)
    prompt = " ".join(cloud_prompt(body, resolve_wire(body), capture).split())
    assert prompt.index("1. Observe connectors") < prompt.index("2. Follow each candidate housing")
    assert prompt.index("2. Follow each candidate housing") < prompt.index("3. Match observed connectors")
    assert prompt.index("3. Match observed connectors") < prompt.index("4. Trace the candidate")
    for instruction in ("fixed black header strip", "rear wire exit", "detail crop cuts it off",
                        "Unknown target color does not erase", "independently identified target",
                        "bare adjacent pin is not evidence", "all wires are dangling",
                        "an unrelated neighboring connection alone does not establish other",
                        "bare metal SHANK", "pin TIP", "visual_observations FIRST"):
        assert instruction in prompt
    # This particular failed capture must not be hard-coded as the next answer.
    assert "d288e3703bd14e8ea863491c0a9a5bfb" not in prompt
    assert "brown wire on GND" not in prompt
    assert "c6cd4425026b425b82aec3233961207d" not in prompt


@pytest.mark.parametrize("contradiction", ["covered_but_empty", "bare_but_target", "unidentified_but_empty", "missing_connector", "detached_but_target", "duplicate_id", "wrong_pin"])
def test_inconsistent_connector_claims_never_become_a_match(contradiction):
    raw = opinion()
    view = raw["visual_observations"]["component"]
    if contradiction == "covered_but_empty": raw["component_endpoint"]["state"] = "empty"
    if contradiction == "bare_but_target": view["target_pin_tip"] = "bare"
    if contradiction == "unidentified_but_empty":
        raw["component_endpoint"]["state"] = "empty"
        view.update(target_identity="uncertain", target_pin_tip="bare", target_connector_id=None)
    if contradiction == "missing_connector": view["target_connector_id"] = "invented"
    if contradiction == "detached_but_target": view["connectors"][0]["contact"] = "detached"
    if contradiction == "duplicate_id": view["connectors"].append(copy.deepcopy(view["connectors"][0]))
    if contradiction == "wrong_pin": raw["component_endpoint"]["observed_pin"] = "ECHO"
    original = CloudWiringOpinion.model_validate(raw)
    checked, issues = reconcile_opinion(original, request())
    assert issues == ["component"] and checked.component_endpoint.state == "uncertain"
    assert opinion_verdict(checked, request()) == "uncertain"
    assert original.model_dump() == raw  # retain original evidence, no in-place mutation
    assert checked.visual_observations.component.connectors[0].wire_color.name == "yellow"


def test_bare_tip_can_be_reported_empty_but_not_as_missing_all_candidate_colors():
    raw = opinion(component_endpoint={"state": "empty", "observed_pin": "TRIG", "evidence": "Bare tip at TRIG"})
    raw["visual_observations"]["component"].update(target_connector_id=None, target_pin_tip="bare")
    checked, issues = reconcile_opinion(CloudWiringOpinion.model_validate(raw), request())
    assert not issues and checked.component_endpoint.state == "empty"
    assert checked.wire_colors.component.name == "unknown"
    assert checked.visual_observations.component.connectors[0].wire_color.name == "yellow"
    assert opinion_verdict(checked, request()) == "suspected_issue"


def test_candidate_colors_survive_unresolved_pin_association_without_becoming_target_colors():
    raw = opinion(component_endpoint={"state": "uncertain", "observed_pin": None, "evidence": "Pin unreadable"})
    raw["visual_observations"]["component"].update(target_connector_id=None, target_identity="uncertain", target_pin_tip="not_visible")
    raw["visual_observations"]["component"]["connectors"][0]["wire_color"]["name"] = "brown"
    checked, issues = reconcile_opinion(CloudWiringOpinion.model_validate(raw), request())
    assert not issues and checked.component_endpoint.state == "uncertain"
    assert checked.wire_colors.component.name == "unknown"
    assert checked.visual_observations.component.connectors[0].wire_color.name == "brown"
    assert opinion_verdict(checked, request()) == "uncertain"


def test_connector_inventory_is_required_for_new_jobs():
    raw = opinion()
    del raw["visual_observations"]
    body, _, state, _, _ = setup(reply=raw)
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["status"] == "failed" and job["result"] is None


@pytest.mark.parametrize("mode", ["pin_crops", "overview"])
@pytest.mark.parametrize("latency_s", [47, 119])
def test_slow_cloud_latency_does_not_expire_result_before_reading(monkeypatch, mode, latency_s):
    clock = [1000.0]
    monkeypatch.setattr("app.cloud_wiring.time.monotonic", lambda: clock[0])
    # Exercise the actual submit/run/get path without waiting or a real cloud call.
    monkeypatch.setattr("app.cloud_wiring.threading.Thread",
                        lambda **kw: NS(start=lambda: kw["target"](*kw["args"])))
    body, packet, state, _, bridge = setup()
    if mode == "overview": packet["detection"]["pins"] = []
    service = state.cloud_wiring_service
    def slow_reply(*args, **kwargs):
        job_id = next(iter(service.jobs))
        for elapsed in (15, 31, latency_s):
            clock[0] = 1000.0 + elapsed
            packet["ts_ms"] = clock[0]*1000
            pending = service.get(job_id, state)
            assert pending["status"] == "checking" and not pending["stale"]
            assert pending["completed_at"] is None
        return opinion()
    bridge.generate.side_effect = slow_reply
    job_id = service.submit(body, state)["job_id"]
    job = service.get(job_id, state)
    assert job["status"] == "completed" and not job["stale"], job["error"]
    assert job["capture"]["mode"] == mode and job["capture"]["capture_ts_ms"] == 1000000
    assert job["completed_at"] and "_completed_ts_ms" not in job
    assert job["elapsed_s"] == latency_s
    clock[0] += 30
    packet["ts_ms"] = clock[0]*1000
    assert not service.get(job_id, state)["stale"]
    clock[0] += .001
    packet["ts_ms"] = clock[0]*1000
    assert service.get(job_id, state)["stale"]
    bridge.generate.assert_called_once()


@pytest.mark.parametrize("change", ["movement", "loss", "runtime", "camera"])
def test_scene_invalidated_during_slow_call_stays_historical_after_completion(monkeypatch, change):
    clock = [1000.0]
    monkeypatch.setattr("app.cloud_wiring.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.cloud_wiring.threading.Thread",
                        lambda **kw: NS(start=lambda: kw["target"](*kw["args"])))
    body, packet, state, _, bridge = setup()
    if change == "camera": packet["detection"]["pins"] = []
    service = state.cloud_wiring_service
    def reply(*args, **kwargs):
        clock[0] += 47
        packet["ts_ms"] = clock[0]*1000
        job_id = next(iter(service.jobs))
        if change == "movement": packet["detection"]["pins"][0]["x"] += 50
        if change == "loss": packet["detection"]["tracking"] = "stale"
        if change == "runtime": packet["runtime_revision"] += 1
        if change == "camera":
            original = state.frame_bus.get_latest.side_effect
            state.frame_bus.get_latest.side_effect = lambda **kw: None
        assert service.get(job_id, state)["stale"]
        if change == "movement": packet["detection"]["pins"][0]["x"] -= 50
        if change == "loss": packet["detection"]["tracking"] = "locked"
        if change == "runtime": packet["runtime_revision"] -= 1
        if change == "camera": state.frame_bus.get_latest.side_effect = original
        return opinion()
    bridge.generate.side_effect = reply
    job_id = service.submit(body, state)["job_id"]
    job = service.get(job_id, state)
    assert job["status"] == "completed" and job["completed_at"], job["error"]
    assert job["stale"] and not job["result"]["electrical_verified"]
    bridge.generate.assert_called_once()


def test_movement_loss_and_age_permanently_label_old_photo():
    body, packet, state, _, _ = setup()
    job_id = state.cloud_wiring_service.submit(body, state)["job_id"]
    job = finished(state.cloud_wiring_service, job_id)
    assert not state.cloud_wiring_service.get(job_id, state)["stale"]
    packet["detection"]["pins"][0]["x"] += 50
    assert state.cloud_wiring_service.get(job_id, state)["stale"]
    packet["detection"]["pins"][0]["x"] -= 50
    assert state.cloud_wiring_service.get(job_id, state)["stale"]
    state.cloud_wiring_service.jobs[job_id]["created"] -= 901
    with pytest.raises(HTTPException): state.cloud_wiring_service.image(job_id, "pi_pins")


def test_bridge_image_input_schema_model_and_disabled_tools(tmp_path):
    bridge = CodexBridge()
    bridge._start = Mock()
    bridge._workspace = NS(name=str(tmp_path))
    bridge._load_models = Mock(return_value={"default_model": "test-vision", "models": [
        {"id": "test-vision", "efforts": ["low"], "default_effort": "low", "input_modalities": ["text", "image"]}]})
    calls = []
    def rpc(method, params, **kwargs):
        calls.append((method, copy.deepcopy(params)))
        if method == "account/read": return {"account": {"type": "chatgpt"}}
        if method == "thread/start": return {"thread": {"id": "t"}, "model": "test-vision"}
        if method == "turn/start":
            bridge._events.extend([
                {"method": "item/completed", "params": {"threadId": "t", "item": {"type": "agentMessage", "text": json.dumps(opinion())}}},
                {"method": "turn/completed", "params": {"threadId": "t", "turn": {"status": "completed"}}}])
            return {"turn": {"id": "turn"}}
        raise AssertionError(method)
    bridge._rpc = rpc
    image_path = tmp_path / "camera.jpg"
    image_path.write_bytes(b"test fixture")
    result = bridge.generate("Inspect camera", CloudWiringOpinion.model_json_schema(), image_paths=[image_path], fail_if_busy=True)
    assert result["authority"] == "visual_advisory"
    start = next(p for m, p in calls if m == "thread/start")
    turn = next(p for m, p in calls if m == "turn/start")
    assert start["config"]["features.image_generation"] is False and start["config"]["features.shell_tool"] is False
    assert turn["input"][1] == {"type": "localImage", "path": str(image_path.resolve()), "detail": "original"}
    assert turn["outputSchema"]["properties"]["authority"]["const"] == "visual_advisory"
    bridge._load_models.return_value["models"][0]["input_modalities"] = ["text"]
    with pytest.raises(ValueError, match="圖片"):
        bridge.generate("Inspect", {}, image_paths=[image_path])
    with bridge._lock, pytest.raises(RuntimeError, match="正忙"):
        bridge.generate("Inspect", {}, image_paths=[image_path], fail_if_busy=True)


def test_tracking_off_uses_each_exact_detector_frame_not_latest_camera(monkeypatch):
    body, _, state, _, _ = setup()
    state.config.realtime_tracking = False
    ts = time.monotonic()*1000
    left_frame = np.full((600, 1000, 3), (30, 40, 190), np.uint8)
    right_frame = np.full((600, 1000, 3), (200, 50, 30), np.uint8)
    board = DetectionResult("raspberry-pi-5", 10, ts-100, "locked", .8,
        pins=[PinDetection(body.board_pin, 200, 300, .8)])
    component = ComponentPoseResult(body.component_id, 11, ts, "locked", .8, (1000, 600), None,
        (ComponentPinPosition(body.component_pin, 700, 300, .8),), "locked")
    state.detection_state = NS(get_synchronized=lambda: (FrameSlot(left_frame, 10, ts-100, 10), board))
    state.component_pose_state = NS(get_synchronized=lambda cid: (FrameSlot(right_frame, 11, ts, 11), component))
    # No wire tracing or color sampling is permitted in this cloud-only path.
    monkeypatch.setattr("app.vision.wire_tracer.trace", Mock(side_effect=AssertionError("local wire recognition")))
    monkeypatch.setattr("app.vision.endpoint_color.inspect_guided_board_endpoint_color", Mock(side_effect=AssertionError("local color recognition")))
    images, capture = capture_images(state, body)
    assert not capture["same_frame"] and capture["capture_skew_ms"] == 100
    assert list(images) == ["pi_overview", "pi_pins", "component_overview", "component_pins"]
    assert np.mean(cv2.imdecode(np.frombuffer(images["component_pins"], np.uint8), 1)[:, :, 0]) > 190
    state.detection_state = NS(get_synchronized=lambda: (FrameSlot(left_frame, 10, ts-400, 10), board))
    images, capture = capture_images(state, body)
    assert list(images) == ["pi_overview"] and capture["mode"] == "overview"


@pytest.mark.parametrize("problem", ["no_camera", "old_camera", "future_camera", "invalid_pixels", "synthetic", "wrong_board"])
def test_no_real_fresh_photo_still_errors_without_cloud_call(problem):
    body, packet, state, client, bridge = setup()
    packet["ts_ms"] -= 2000
    frame = np.zeros((600, 1000, 3), np.uint8)
    slot = FrameSlot(frame, 31, time.monotonic()*1000, 31)
    if problem == "no_camera": slot = None
    if problem == "old_camera": slot = FrameSlot(frame, 31, time.monotonic()*1000-2000, 31)
    if problem == "future_camera": slot = FrameSlot(frame, 31, time.monotonic()*1000+10000, 31)
    if problem == "invalid_pixels": slot = FrameSlot(np.zeros((0, 0, 3), np.uint8), 31, time.monotonic()*1000, 31)
    if problem == "synthetic": state.config.camera.source = "synthetic"
    if problem == "wrong_board": state.runtime_manager.snapshot = lambda: NS(board_id="arduino-uno-q", runtime_revision=8)
    state.frame_bus.get_latest.side_effect = None
    state.frame_bus.get_latest.return_value = slot
    job_id = client.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    job = finished(state.cloud_wiring_service, job_id)
    assert job["status"] == "failed" and job["result"] is None
    bridge.generate.assert_not_called()


def test_tracking_off_without_any_model_pose_uses_camera_and_no_local_recognition(monkeypatch):
    body, packet, state, client, bridge = setup(reply=opinion(same_wire="uncertain"))
    state.config.realtime_tracking = False
    monkeypatch.setattr("app.vision.wire_tracer.trace", Mock(side_effect=AssertionError("wire trace")))
    monkeypatch.setattr("app.vision.endpoint_color.inspect_guided_board_endpoint_color", Mock(side_effect=AssertionError("color")))
    job_id = client.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    job = finished(state.cloud_wiring_service, job_id, state)
    assert job["status"] == "completed" and job["result"]["verdict"] == "uncertain", job["error"]
    assert job["capture"]["mode"] == "overview" and not job["stale"]
    assert not job["result"]["electrical_verified"]
    state.cloud_wiring_service.jobs[job_id]["_completed_ts_ms"] -= 31000
    assert state.cloud_wiring_service.get(job_id, state)["stale"]


def test_overview_remains_capture_only_and_tracks_runtime_or_camera_changes():
    body, packet, state, _, _ = setup()
    packet["detection"]["pins"] = []
    job_id = state.cloud_wiring_service.submit(body, state)["job_id"]
    finished(state.cloud_wiring_service, job_id)
    assert not state.cloud_wiring_service.get(job_id, state)["stale"]
    state.runtime_manager.snapshot = lambda: NS(board_id="raspberry-pi-5", runtime_revision=8)
    assert state.cloud_wiring_service.get(job_id, state)["stale"]


def test_old_result_cannot_follow_runtime_switch_and_unbounded_jobs_are_not_retained():
    body, packet, state, _, _ = setup()
    for _ in range(13):
        packet["ts_ms"] = time.monotonic()*1000
        job_id = state.cloud_wiring_service.submit(body, state)["job_id"]
        finished(state.cloud_wiring_service, job_id)
    assert len(state.cloud_wiring_service.jobs) == 12
    packet["runtime_revision"] += 1
    assert state.cloud_wiring_service.get(job_id, state)["stale"]
    state.cloud_wiring_service.close()
    with pytest.raises(HTTPException): state.cloud_wiring_service.submit(body, state)
