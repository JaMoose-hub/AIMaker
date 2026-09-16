"""Deterministic pipeline tests; synthetic pixels are not recognition accuracy tests."""
import copy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from app.cloud_connector_inspection import (EndpointInspection, RouteInspection, contact_views, endpoint_consistency,
    endpoint_image_names, endpoint_prompt, pin_reference, run_inspection)
from app.cloud_wiring import CloudWiringOpinion, capture_images, inspection_views
from test_cloud_wiring import setup, request, opinion, finished


def assert_codex_refs_have_no_siblings(schema, path=()):
    """Regression for the real provider's invalid_json_schema rejection.

    Local Pydantic validation and mocked replies do not validate the provider's
    supported schema subset. Check emitted references, including nested defs.
    """
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            assert set(schema.get("required", [])) == set(schema["properties"]), f"{path}: provider requires all keys"
        assert "default" not in schema, f"{path}: output schema must not rely on omitted defaults"
        if "$ref" in schema:
            assert set(schema) == {"$ref"}, f"{path}: unsupported $ref siblings {set(schema) - {'$ref'}}"
        for key, value in schema.items():
            assert_codex_refs_have_no_siblings(value, (*path, key))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            assert_codex_refs_have_no_siblings(value, (*path, index))


@pytest.mark.parametrize("model", [EndpointInspection, RouteInspection, CloudWiringOpinion])
def test_cloud_output_schemas_do_not_attach_keywords_to_refs(model):
    assert_codex_refs_have_no_siblings(model.model_json_schema())


def endpoint(side, *, state="target", contact="covers_pin"):
    old = opinion()
    pin = "TRIG" if side == "component" else "GPIO17"
    obs = old["visual_observations"][side]
    obs["connectors"][0]["contact"] = contact
    appearance = "housing"
    if state == "empty":
        obs.update(target_pin_tip="bare", target_connector_id=None)
        appearance = "bare_tip"
    elif state == "uncertain":
        obs.update(target_identity="uncertain", target_connector_id=None)
    return {"pin_contacts": [{"position": "fixture position", "pin_id": pin if state != "uncertain" else None,
        "appearance": appearance, "connector_id": "c1" if appearance == "housing" else None}],
        "observation": obs, "endpoint": {"state": state, "observed_pin": pin if state != "uncertain" else None,
        "evidence": "fixture: independently observed endpoint"}}


def route():
    return {"wire_path": {"visibility": "traceable", "evidence": "fixture: continuous route"},
            "same_wire": "consistent", "evidence": "fixture: route not merely matching colors"}


def test_real_service_uses_isolated_turns_and_reports_stages_without_hardware_mutation():
    body, _, state, client, bridge = setup(staged=True)
    state.pi_deployer, state.verification_state = Mock(), Mock()
    bridge.generate.side_effect = [endpoint("component"), endpoint("board"), route()]
    job_id = client.post("/api/guidance/cloud-checks", json=body.model_dump()).json()["job_id"]
    job = finished(state.cloud_wiring_service, job_id)
    assert job["status"] == "completed", job["error"]
    assert job["result"]["verdict"] == "looks_matched" and not job["result"]["electrical_verified"]
    assert job["result"]["pin_contacts"]["component"][0]["pin_id"] == "TRIG"
    assert job["inspection"]["phase"] == "completed" and job["inspection"]["effort"] == body.effort
    assert [s["stage"] for s in job["inspection"]["stages"]] == ["component", "board", "route"]
    calls = bridge.generate.call_args_list
    assert len(calls) == 3
    assert [p.stem for p in calls[0].kwargs["image_paths"]] == ["component_reading", "component_contact", "pi_overview"]
    assert [p.stem for p in calls[1].kwargs["image_paths"]] == ["pi_reading", "pi_contact", "pi_overview"]
    assert "observation" not in calls[2].args[1]["properties"]  # route cannot rewrite an endpoint
    assert '"same_frame": true' in calls[2].args[0] and '"frame_id": 23' in calls[2].args[0]
    for call in calls:
        assert_codex_refs_have_no_siblings(call.args[1])
        assert call.kwargs["model"] == body.model and call.kwargs["effort"] == body.effort
        assert 0 < call.kwargs["timeout_s"] <= 90 and call.kwargs["fail_if_busy"]
        assert all(not p.exists() for p in call.kwargs["image_paths"])
    assert not state.pi_deployer.mock_calls and not state.verification_state.mock_calls
    assert not state.design_service.busy and not state.cloud_wiring_service.busy
    for view in job["images"]:
        response = client.get(view["url"])
        assert response.status_code == 200
        assert response.headers["content-type"] == ("image/png" if view["name"].endswith(("_pins", "_reading", "_contact")) else "image/jpeg")


def test_empty_target_skips_route_and_does_not_erase_other_endpoint():
    body, _, state, _, bridge = setup(staged=True)
    bridge.generate.side_effect = [endpoint("component"), endpoint("board", state="empty")]
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert bridge.generate.call_count == 2
    assert job["result"]["verdict"] == "suspected_issue"
    assert job["result"]["component_endpoint"]["state"] == "target"
    assert job["result"]["wire_colors"]["component"]["name"] == "yellow"


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_stage_failure_preserves_completed_evidence_releases_busy_and_never_retries(stage):
    body, _, state, _, bridge = setup(staged=True)
    replies = [endpoint("component"), endpoint("board"), route()]
    replies[stage] = RuntimeError("fixture cloud timeout")
    bridge.generate.side_effect = replies
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["status"] == "failed" and job["result"] is None and "timeout" in job["error"]
    assert bridge.generate.call_count == stage+1 and len(job["inspection"]["stages"]) == stage
    assert not state.design_service.busy and not state.cloud_wiring_service.busy


def test_invalid_new_schema_fails_not_legacy_fallback():
    body, _, state, _, bridge = setup(staged=True)
    bridge.generate.return_value = opinion()
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["status"] == "failed" and job["result"] is None
    assert bridge.generate.call_count == 1


@pytest.mark.parametrize("mode", ["target", "empty", "detached", "missing", "duplicate"])
def test_pin_inventory_contradictions_can_only_demote(mode):
    raw = endpoint("component", state="empty" if mode == "empty" else "target")
    if mode in {"target", "empty"}:
        raw["pin_contacts"][0]["appearance"] = "uncertain"
    if mode == "detached": raw["observation"]["connectors"][0]["contact"] = "detached"
    if mode == "missing": raw["pin_contacts"][0]["connector_id"] = "not-a-candidate"
    if mode == "duplicate": raw["pin_contacts"].append(copy.deepcopy(raw["pin_contacts"][0]))
    original = EndpointInspection.model_validate(raw)
    checked, conflict = endpoint_consistency(original, "TRIG")
    assert conflict and checked.endpoint.state == "uncertain"
    assert original.model_dump() == raw and checked.observation.connectors[0].wire_color.name == "yellow"


def test_unknown_exact_pin_preserves_housing_without_turning_trace_into_pass():
    body, _, state, _, bridge = setup(staged=True)
    bridge.generate.side_effect = [endpoint("component"), endpoint("board", state="uncertain"), route()]
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    result = job["result"]
    assert result["verdict"] == "uncertain" and result["same_wire"] == "uncertain"
    assert result["wire_path"]["visibility"] == "not_visible"
    assert bridge.generate.call_count == 2  # no route call while an endpoint is unresolved
    assert result["visual_observations"]["board"]["connectors"][0]["contact"] == "covers_pin"


def test_total_deadline_stops_before_a_new_call(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("app.cloud_connector_inspection.time.monotonic", lambda: clock[0])
    def reply(*args, **kwargs):
        clock[0] += 220
        return endpoint("component")
    bridge = NS(generate=Mock(side_effect=reply))
    with pytest.raises(TimeoutError):
        run_inspection(bridge, request(), {"pi_overview": Path("unused.jpg")})
    assert bridge.generate.call_count == 1


def test_no_locator_still_allows_cloud_to_inspect_overview():
    body, packet, state, _, bridge = setup(staged=True)
    packet["detection"]["pins"] = []
    bridge.generate.side_effect = [{"pi": None, "component": None}, endpoint("component"), endpoint("board"), route()]
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["status"] == "completed" and job["capture"]["mode"] == "overview"
    assert len(job["images"]) == 1
    assert job["inspection"]["max_calls"] == 4
    assert all([p.stem for p in c.kwargs["image_paths"]] == ["pi_overview"] for c in bridge.generate.call_args_list)


@pytest.mark.parametrize("cid", ["hc-sr04", "mrd-tf240-8p-cs"])
def test_focus_views_preserve_exact_pixels_and_metadata_for_each_module(cid):
    body, _, state, _, _ = setup(body=request(cid, 0))
    originals, capture = capture_images(state, body)
    images, capture = inspection_views(originals, capture, cid)
    before = copy.deepcopy(capture)
    output, metadata = contact_views(images, capture)
    assert capture == before and all(output[k] == v for k, v in images.items())
    for side in ("pi", "component"):
        view = next(v for v in metadata["views"] if v["name"] == f"{side}_contact")
        decoded = cv2.imdecode(np.frombuffer(images[view["source_view"]], np.uint8), 1)
        x0, y0, x1, y1 = view["crop"]
        expected = np.rot90(decoded[y0:y1, x0:x1], view["rotation_ccw_quarter_turns"])
        expected = np.repeat(np.repeat(expected, view["integer_scale"], 0), view["integer_scale"], 1)
        actual = cv2.imdecode(np.frombuffer(output[view["name"]], np.uint8), 1)
        np.testing.assert_array_equal(actual, expected)
        assert view["adds_no_detail"] and "target_hint" not in view and max(actual.shape[:2]) <= 1024


def test_prompt_profile_reference_has_no_password_or_hard_coded_case_answer():
    body = request(index=0)
    ref = pin_reference(body)
    assert ref["physical_pin"] == 6 and ref["row"] == "even" and ref["pair_counted_from_pin1_end"] == 3
    prompt = endpoint_prompt(body, "component", ["component_reading"])
    assert "VCC" in prompt and "black" in prompt and "other endpoint" in prompt
    assert "brown wire on GND" not in prompt and "192.168.50.174" not in prompt
    assert "pin_hints" not in prompt  # contact observations independent of projected target coordinates


def test_locator_reference_is_explicitly_fallible_and_uses_reading_coordinates():
    ref = pin_reference(request(), {"views": [
        {"name": "pi_pins", "size": [100, 80], "pin_hints": [{"id": "3V3_P1", "x": 10, "y": 20}]},
        {"name": "pi_reading", "rotation_ccw_quarter_turns": 1, "integer_scale": 3}]})
    assert ref["fallible_locator_hints"]["anchors"] == [{"pin_id": "3V3_P1", "x": 60, "y": 267}]
    assert "not proof" in ref["fallible_locator_hints"]["warning"]


@pytest.mark.parametrize("delta,turns", [((0, 20), 0), ((-20, 0), 1), ((0, -20), 2), ((20, 0), 3)])
def test_pi_reading_rotates_pin1_end_up_without_changing_pixels(delta, turns):
    frame = np.arange(160*160*3, dtype=np.uint32).reshape((160, 160, 3)).astype(np.uint8)
    ok, encoded = cv2.imencode('.jpg', frame)
    assert ok
    images = {"pi_pins": encoded.tobytes()}
    source = {"name": "pi_pins", "frame_id": 1, "ts_ms": 2, "size": [160, 160],
        "pin_hints": [{"id": "3V3_P1", "x": 80, "y": 80}, {"id": "GPIO2", "x": 80+delta[0], "y": 80+delta[1]}]}
    output, capture = inspection_views(images, {"views": [source]}, "hc-sr04")
    assert capture["views"][-1]["rotation_ccw_quarter_turns"] == turns
    decoded = cv2.imdecode(np.frombuffer(images["pi_pins"], np.uint8), 1)
    actual = cv2.imdecode(np.frombuffer(output["pi_reading"], np.uint8), 1)
    np.testing.assert_array_equal(actual, np.repeat(np.repeat(np.rot90(decoded, turns), 3, 0), 3, 1))
    source["pin_hints"].pop(0)
    _, capture = inspection_views(images, {"views": [source]}, "hc-sr04")
    assert capture["views"][-1]["rotation_ccw_quarter_turns"] == 0


def test_conflicting_pin_conclusion_stays_in_raw_stage_not_the_normalized_summary():
    body, _, state, _, bridge = setup(staged=True)
    bad = endpoint("board")
    bad["pin_contacts"][0].update(appearance="bare_tip", connector_id=None)
    bad["endpoint"]["evidence"] = "fixture false target claim"
    bridge.generate.side_effect = [endpoint("component"), bad, route()]
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["result"]["verdict"] == "uncertain"
    assert "fixture false target claim" not in job["result"]["summary"]
    assert job["result"]["pin_contacts"]["board"][0]["pin_id"] is None
    assert job["inspection"]["stages"][1]["raw"]["endpoint"]["evidence"] == "fixture false target claim"
