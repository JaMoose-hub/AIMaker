"""Contract/geometry regression, not a camera recognition benchmark."""
import copy
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.cloud_endpoint_crops import EndpointRegions, crop_regions, missing_detail_sides
from app.cloud_connector_inspection import EndpointInspection, endpoint_consistency, assemble_opinion, RouteInspection
from app.cloud_wiring import capture_images
from test_cloud_connectors import endpoint, route, assert_codex_refs_have_no_siblings
from test_cloud_wiring import setup, finished, request


def region(**kw):
    return {"source_view": "pi_overview", "x0": 550, "y0": 200, "x1": 850, "y1": 600,
            "evidence": "fixture module and adjacent breadboard", **kw}


def overview(tmp_path):
    body, packet, state, _, _ = setup()
    packet["detection"]["pins"] = []
    images, capture = capture_images(state, body)
    paths = {}
    for name, data in images.items():
        paths[name] = tmp_path / f"{name}.jpg"
        paths[name].write_bytes(data)
    return paths, capture


@pytest.mark.parametrize("bad", [None, region(x0=900, x1=800), region(x0=-1), region(x1=float("nan")),
                                 region(source_view="invented"), region(x0=550, x1=551)])
def test_independent_rois_preserve_source_pixels_and_metadata(tmp_path, bad):
    paths, capture = overview(tmp_path)
    source_bytes = paths["pi_overview"].read_bytes()
    result = crop_regions(paths, capture, {"pi": bad, "component": region()})
    assert result["component"] == "cropped" and result["pi"] != "cropped"
    assert missing_detail_sides(paths) == ["pi"]
    assert paths["pi_overview"].read_bytes() == source_bytes
    view = next(v for v in capture["views"] if v["name"] == "component_pins")
    source = cv2.imdecode(np.frombuffer(source_bytes, np.uint8), 1)
    x0, y0, x1, y1 = view["crop"]
    actual = cv2.imread(str(paths["component_pins"]))
    assert np.array_equal(actual, source[y0:y1, x0:x1])
    assert capture["mode"] == "context_crops" and view["pin_hints"] == []
    assert view["frame_id"] == capture["views"][0]["frame_id"]
    assert next(v for v in capture["views"] if v["name"] == "component_reading")["rotation_ccw_quarter_turns"] == 0


def test_existing_detail_is_not_replaced_when_other_side_needs_roi(tmp_path):
    paths, capture = overview(tmp_path)
    crop_regions(paths, capture, {"pi": region(x0=100, x1=350), "component": None})
    original, views = paths["pi_pins"].read_bytes(), copy.deepcopy(capture["views"])
    crop_regions(paths, capture, {"pi": region(), "component": region()})
    assert paths["pi_pins"].read_bytes() == original
    assert all(v in capture["views"] for v in views)
    assert len({v["name"] for v in capture["views"]}) == len(capture["views"])


def test_roi_uses_its_named_source_and_rejects_wrong_size(tmp_path):
    paths, capture = overview(tmp_path)
    frame = np.full((480, 640, 3), 97, dtype=np.uint8)
    paths["component_overview"] = tmp_path / "component_overview.png"
    cv2.imwrite(str(paths["component_overview"]), frame)
    capture["views"].append({"name": "component_overview", "size": [640, 480], "frame_id": 99, "ts_ms": 900})
    capture["views"][0]["size"] = [1, 1]
    result = crop_regions(paths, capture, {"pi": region(), "component": region(source_view="component_overview")})
    assert result["pi"].startswith("rejected") and result["component"] == "cropped"
    view = next(v for v in capture["views"] if v["name"] == "component_pins")
    assert view["frame_id"] == 99 and view["ts_ms"] == 900
    assert np.all(cv2.imread(str(paths["component_pins"])) == 97)


def test_localization_error_stops_without_retry_and_preserves_overview():
    body, packet, state, _, bridge = setup(staged=True)
    packet["detection"]["pins"] = []
    bridge.generate.side_effect = RuntimeError("fixture localization failure")
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"])
    assert job["status"] == "failed" and bridge.generate.call_count == 1
    assert len(job["images"]) == 1 and job["result"] is None
    assert not state.design_service.busy and not state.cloud_wiring_service.busy


def test_service_publishes_localized_images_without_pose_or_hardware_mutation():
    body, packet, state, client, bridge = setup(staged=True)
    packet["detection"]["pins"] = []
    bridge.generate.side_effect = [{"pi": region(x0=100, x1=350), "component": region()},
                                  endpoint("component"), endpoint("board"), route()]
    job = finished(state.cloud_wiring_service, state.cloud_wiring_service.submit(body, state)["job_id"], state)
    assert job["status"] == "completed", job["error"]
    assert not job["stale"] and job["capture"]["mode"] == "context_crops"
    assert len(job["images"]) == 5 and bridge.generate.call_count == 4
    assert len(job["inspection"]["stages"]) == 4
    assert [p.stem for p in bridge.generate.call_args_list[1].kwargs["image_paths"]] == ["component_reading", "pi_overview"]
    for view in job["images"]:
        assert client.get(view["url"]).status_code == 200
    assert_codex_refs_have_no_siblings(EndpointRegions.model_json_schema())


def breadboard_endpoint():
    raw = endpoint("component", contact="breadboard_link")
    raw["pin_contacts"][0]["appearance"] = "breadboard"
    raw["observation"]["target_pin_tip"] = "not_visible"
    raw["observation"]["connectors"][0]["breadboard"] = {
        "pin_hole": {"row": 12, "column": "B", "insertion_visible": True},
        "wire_hole": {"row": 12, "column": "E", "insertion_visible": True},
        "same_board_and_numbering_confirmed": True, "topology": "standard_terminal_strip",
        "evidence": "fixture: both insertions on terminal strip B12-E12"}
    return raw


@pytest.mark.parametrize("bad", [None, "row", "gap", "same_hole", "hidden", "topology", "numbering", "missing"])
def test_breadboard_requires_visible_distinct_holes_on_same_strip(bad):
    raw = breadboard_endpoint()
    link = raw["observation"]["connectors"][0]["breadboard"]
    if bad == "row": link["wire_hole"]["row"] = 13
    if bad == "gap": link["wire_hole"]["column"] = "F"
    if bad == "same_hole": link["wire_hole"]["column"] = "B"
    if bad == "hidden": link["pin_hole"]["insertion_visible"] = False
    if bad == "topology": link["topology"] = "uncertain"
    if bad == "numbering": link["same_board_and_numbering_confirmed"] = False
    if bad == "missing": raw["observation"]["connectors"][0]["breadboard"] = None
    checked, conflict = endpoint_consistency(EndpointInspection.model_validate(raw), "TRIG")
    assert conflict == (bad is not None)
    assert checked.endpoint.state == ("uncertain" if bad else "target")
    opinion, _ = assemble_opinion(request(), {"component": checked, "board": EndpointInspection.model_validate(endpoint("board"))}, RouteInspection.model_validate(route()))
    assert opinion.component_endpoint.state == ("uncertain" if bad else "target")
