"""Isolated POC integration: synthetic originals/fake cloud, no camera or GPIO."""
from copy import deepcopy
import hashlib
import io
import json

from PIL import Image, ImageDraw, JpegImagePlugin
import pytest

from app import wiring_photo_pipeline as pipeline
from app.guided_wiring_review import _canonical_candidates, compare_candidates

PINS = {"GPIO17": {"index": 11}}
WIRE = dict(id="wire", boardPin="GPIO17", componentId="hc-sr04", componentPin="TRIG", connectionKind="direct")


def fixture_inputs():
    review = dict(component_id="hc-sr04", round=1, slots={})
    originals = {}
    for role in pipeline.ROLES:
        image = Image.new("RGB", (200, 100), "blue")
        buffer = io.BytesIO(); image.save(buffer, "PNG")
        raw = buffer.getvalue(); originals[role] = raw
        review["slots"][role] = dict(capture_id=role, size=[200, 100], sha256=hashlib.sha256(raw).hexdigest(), crop=None)
    selection = dict(model="fixture", effort="low", response_mode="fast", binding={"wiring_hash": "wiring"})
    return review, selection, originals


def inventory(roles, marker_id="c1"):
    return dict(images=[dict(image_id=r, markers=[dict(id=marker_id, x_normalized=500, y_normalized=500,
        wire_color="red", visibility="clear", wire_roi=None, evidence="Visible red insulation at the housing exit")],
        limitations="Insertion may be hidden") for r in roles], limitations="Appearance only")


def opinion(roles):
    return dict(views=[dict(role=r, connectors=[dict(id="c1", position="Visible housing", contact="covers_pin",
        wire_color=dict(name="blue", visibility="clear", evidence="Second turn changes colour"), evidence="Visible attachment",
        breadboard=None, pin_id="TRIG" if r == "component_header" else "GPIO17", pin_evidence="Visible orientation/insertion", box=None)],
        limitations="Appearance only") for r in roles], wire_paths=[])


def run(tmp_path, review=None, selection=None, originals=None, *, callback=None, remember=lambda *_: None, clock=None):
    r, s, o = fixture_inputs()
    review, selection, originals = review or r, selection or s, originals or o
    calls = []
    def generate(prompt, schema, paths, remaining):
        calls.append(dict(prompt=prompt, paths=paths, pixels=[p.read_bytes() for p in paths], timeout=remaining))
        if callback:
            raw = callback(prompt, schema)
        elif "POC EXIT INVENTORY:" in prompt:
            rows = json.loads(prompt.split("Images are attached in this order:\n")[-1])
            raw = inventory(dict.fromkeys(row["image_id"] for row in rows))
        else:
            roles = json.loads(prompt.split("Board pin references are naming references only: ")[-1])["requested_roles"]
            raw = opinion(roles)
        if "POC EXIT INVENTORY:" not in prompt:
            properties = schema["$defs"]["ReviewConnector"]["properties"]
            assert not {"wire_color", "position", "evidence"} & properties.keys()
            raw = deepcopy(raw)
            for view in raw["views"]:
                for connector in view["connectors"]:
                    for field in ("wire_color", "position", "evidence"):
                        connector.pop(field, None)
        return raw, dict(model="fixture", elapsed_ms=1)
    options = {"clock": clock, "timeout_s": 10} if clock else {}
    result = pipeline.inspect_wiring_photos(review, selection, originals, PINS, {"TRIG"}, [WIRE], tmp_path,
        generate=generate, remember_exits=remember, **options)
    return result, calls


def save_result(review, result):
    review.update({k: deepcopy(result[k]) for k in ("exit_inventory", "exit_evidence", "exit_input_keys", "role_input_keys")})
    review["last_opinion"] = result["opinion"].model_dump()


def test_real_two_stage_call_order_native_pixels_and_no_expected_wiring_in_inventory(tmp_path):
    result, calls = run(tmp_path)
    assert len(calls) == 2
    assert "expected_wires" not in calls[0]["prompt"] and "GPIO17" not in calls[0]["prompt"]
    assert "exit_inventory" in calls[1]["prompt"] and "GPIO17" in calls[1]["prompt"]
    assert [s["stage"] for s in result["stages"]] == ["exit_inventory", "pin_review"]
    for record, raw in zip(result["image_inputs"], calls[0]["pixels"]):
        image = Image.open(io.BytesIO(raw))
        assert image.size == (200, 100) and not record["resized"] and record["original_pixels"]
        assert image.getpixel((99, 49)) == (0, 0, 255)
        assert record["supplied_sha256"] == hashlib.sha256(raw).hexdigest()


def test_pixel_disagreement_does_not_replace_semantic_colour_or_confirm_a_wire(tmp_path):
    result, _ = run(tmp_path)
    review, _, _ = fixture_inputs(); save_result(review, result)
    candidates = _canonical_candidates(result["opinion"], review, PINS, {"TRIG"})
    assert all(c["color"] == "red" and c["local_color"]["name"] == "blue" for c in candidates)
    assert all(c["color_agreement"] == "different" and c["wire_exit"] == [.5, .5] for c in candidates)
    assert candidates[0]["wire_exit_px"] == [99.5, 49.5]
    row = compare_candidates(candidates, [WIRE], PINS)[0]
    assert row["same_wire"] == "uncertain" and row["diagnosis"]["status"] == "uncertain"


def test_unknown_pin_or_missing_pin_stage_candidate_retains_poc_colour_and_exit(tmp_path):
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        return dict(views=[dict(role=r, connectors=[], limitations="Pin hidden") for r in pipeline.ROLES], wire_paths=[])
    result, _ = run(tmp_path, callback=answer)
    assert all(len(v.connectors) == 1 and v.connectors[0].pin_id is None
               and v.connectors[0].wire_color.name == "red" for v in result["opinion"].views)


def test_uncovered_header_survives_empty_connector_inventory_without_extra_call(tmp_path):
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            raw = inventory(pipeline.ROLES)
            raw["images"][-1]["markers"] = []
            raw["images"][-1]["limitations"] = "Only four uncovered module pins are visible."
            return raw
        assert "header_observation" in schema["$defs"]["ViewInventory"]["properties"]
        assert "empty inventory" in prompt and "bare shank" in prompt
        raw = opinion(pipeline.ROLES)
        raw["views"][-1].update(connectors=[], header_observation=dict(state="uncovered_pins",
            evidence="The complete tips of four module pins are visible without housings."))
        return raw
    result, calls = run(tmp_path, callback=answer)
    module = next(view for view in result["opinion"].views if view.role == "component_header")
    assert module.connectors == [] and module.header_observation.state == "uncovered_pins"
    assert "four" in module.header_observation.evidence and len(calls) == 2
    review, _, _ = fixture_inputs(); save_result(review, result)
    candidates = _canonical_candidates(result["opinion"], review, PINS, {"TRIG"})
    assert not any(candidate["role"] == "component_header" for candidate in candidates)
    assert compare_candidates(candidates, [WIRE], PINS)[0]["diagnosis"]["status"] == "uncertain"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 1001])
def test_invalid_poc_point_rejects_before_pin_turn(tmp_path, value):
    def answer(prompt, schema):
        result = inventory(pipeline.ROLES); result["images"][0]["markers"][0]["x_normalized"] = value
        return result
    with pytest.raises(ValueError):
        run(tmp_path, callback=answer)


@pytest.mark.parametrize("fault", ["duplicate_role", "foreign_role", "duplicate_marker", "reversed_roi"])
def test_invalid_inventory_identity_and_roi_cannot_become_pin_evidence(tmp_path, fault):
    def answer(prompt, schema):
        result = inventory(pipeline.ROLES)
        if fault == "duplicate_role": result["images"][1]["image_id"] = "pi_side_a"
        if fault == "foreign_role": result["images"][1]["image_id"] = "other"
        if fault == "duplicate_marker": result["images"][0]["markers"] *= 2
        if fault == "reversed_roi": result["images"][0]["markers"][0]["wire_roi"] = dict(x_min=200, y_min=100, x_max=100, y_max=200)
        return result
    with pytest.raises(ValueError):
        run(tmp_path, callback=answer)


def test_successful_inventory_is_reused_after_pin_turn_failure(tmp_path):
    review, selection, originals = fixture_inputs()
    def remember(exits, keys, evidence, stages):
        review.update(exit_inventory=deepcopy(exits), exit_input_keys=deepcopy(keys), exit_evidence=deepcopy(evidence))
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt: return inventory(pipeline.ROLES)
        raise TimeoutError("pin turn stalled")
    with pytest.raises(TimeoutError):
        run(tmp_path, review, selection, originals, callback=answer, remember=remember)
    assert pipeline.model_calls_needed(review, selection) == 1
    result, calls = run(tmp_path, review, selection, originals)
    assert len(calls) == 1 and result["stages"][0]["cached"]
    assert all(c.wire_color.name == "red" for v in result["opinion"].views for c in v.connectors)


def test_model_or_capture_changes_invalidate_inventory_cache(tmp_path):
    review, selection, originals = fixture_inputs()
    result, _ = run(tmp_path, review, selection, originals); save_result(review, result)
    selection["model"] = "other-model"
    assert pipeline.model_calls_needed(review, selection) == 2
    selection["model"] = "fixture"
    review["slots"]["pi_side_a"]["capture_id"] = "retaken-same-pixels"
    assert pipeline.model_calls_needed(review, selection) == 2


def test_partial_retake_replaces_old_exit_ids_and_discards_routes(tmp_path):
    review, selection, originals = fixture_inputs()
    result, _ = run(tmp_path, review, selection, originals); save_result(review, result)
    review["slots"]["pi_side_a"]["capture_id"] = "new-photo"
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt: return inventory(["pi_side_a"], marker_id="new1")
        result = opinion(["pi_side_a"])
        result["views"][0]["connectors"][0]["id"] = "new1"
        result["wire_paths"] = [dict(wire_id="wire", board_connector_id="pi_side_a:new1",
            component_connector_id="component_header:c1", visibility="traceable", evidence="Fabricated old route")]
        return result
    updated, calls = run(tmp_path, review, selection, originals, callback=answer)
    assert [len(c["paths"]) for c in calls] == [1, 1]
    assert updated["opinion"].wire_paths == []
    assert "pi_side_a:c1" not in updated["exit_evidence"]
    assert updated["exit_evidence"]["pi_side_a:new1"]["capture_id"] == "new-photo"


def test_source_hash_mismatch_fails_before_any_cloud_call(tmp_path):
    review, selection, originals = fixture_inputs(); originals["pi_side_a"] += b"changed"
    with pytest.raises(ValueError, match="photos_expired"):
        run(tmp_path, review, selection, originals)


def test_whole_pipeline_deadline_prevents_a_second_turn_after_expiry(tmp_path):
    now = [0]
    def answer(prompt, schema):
        now[0] = 11
        assert "POC EXIT INVENTORY:" in prompt
        return inventory(pipeline.ROLES)
    with pytest.raises(TimeoutError, match="analysis_timeout"):
        run(tmp_path, callback=answer, clock=lambda: now[0])


def test_original_pixel_budget_rejects_without_downscaling_or_cloud(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "MAX_ANALYSIS_PIXELS", 100)
    with pytest.raises(ValueError, match="image_budget_exceeded"):
        run(tmp_path)


def test_both_cloud_schemas_are_strict_provider_supported_arrays():
    for schema in (pipeline.ExitInventory.model_json_schema(), pipeline.pin_review_schema()):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    assert set(node.get("required", [])) == set(node.get("properties", {}))
                    assert node.get("additionalProperties") is False
                if node.get("type") == "array":
                    assert isinstance(node.get("items"), dict) and "prefixItems" not in node
                for value in node.values(): walk(value)
            elif isinstance(node, list):
                for value in node: walk(value)
        walk(schema)
    connector = pipeline.pin_review_schema()["$defs"]["ReviewConnector"]
    assert not {"wire_color", "position", "evidence"} & connector["properties"].keys()
    assert {"id", "contact", "pin_id", "pin_evidence", "box"} <= connector["properties"].keys()


def test_boolean_coordinate_is_not_coerced_to_a_one_pixel_exit():
    marker = inventory(["pi_side_a"])["images"][0]["markers"][0]
    marker["x_normalized"] = True
    with pytest.raises(ValueError):
        pipeline.ExitMarker.model_validate(marker)


def test_actual_effort_bookkeeping_does_not_invalidate_requested_policy_cache():
    review, selection, _ = fixture_inputs()
    selection.update(requested_effort="high", effort="low")
    before = pipeline.role_input_keys(review, selection)
    selection["effort"] = "medium"
    assert pipeline.role_input_keys(review, selection) == before
    selection["requested_effort"] = "low"
    assert pipeline.role_input_keys(review, selection) != before


def test_mobile_normalization_uses_shared_icc_and_orientation_without_overwriting_source(tmp_path, monkeypatch):
    from PIL import ImageCms
    from app.mobile import MobileAssets
    from app import photo_observations
    source, destination = tmp_path / "source.png", tmp_path / "normalized.jpg"
    exif = Image.Exif(); exif[274] = 6
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.new("RGB", (80, 50), "red").save(source, icc_profile=profile, exif=exif)
    before = source.read_bytes(); conversions = []
    convert = photo_observations.ImageCms.profileToProfile
    def tracked(*args, **kwargs):
        conversions.append(True); return convert(*args, **kwargs)
    monkeypatch.setattr(photo_observations.ImageCms, "profileToProfile", tracked)
    size, original_size = MobileAssets._normalize(source, destination)
    assert size == original_size == (50, 80) and conversions == [True]
    assert source.read_bytes() == before
    with Image.open(destination) as image:
        assert image.size == size and "icc_profile" not in image.info


def test_demo_large_photos_shrink_for_cloud_but_poc_votes_use_original_pixels(tmp_path):
    review, selection, originals = fixture_inputs()
    source = Image.new("RGB", (4000, 3000), "red")
    ImageDraw.Draw(source).rectangle((1990, 1490, 2010, 1510), fill="blue")
    buffer = io.BytesIO(); source.save(buffer, "PNG")
    originals["pi_side_a"] = buffer.getvalue()
    review["slots"]["pi_side_a"].update(size=[4000, 3000], sha256=hashlib.sha256(buffer.getvalue()).hexdigest())
    before = deepcopy(originals)
    result, calls = run(tmp_path, review, selection, originals)
    record = result["image_inputs"][0]
    with Image.open(io.BytesIO(calls[0]["pixels"][0])) as supplied:
        assert supplied.format == "JPEG" and supplied.size == (2048, 1536)
        assert JpegImagePlugin.get_sampling(supplied) == 0
    assert record["size"] == [2048, 1536] and record["source_size"] == [4000, 3000]
    assert record["resized"] and not record["original_pixels"]
    assert record["encoding"].lower() == "jpeg" and record["jpeg_quality"] == 92 and record["subsampling"] == 0
    assert record["source_sha256"] == hashlib.sha256(before["pi_side_a"]).hexdigest()
    assert record["supplied_sha256"] == hashlib.sha256(calls[0]["pixels"][0]).hexdigest()
    assert originals == before
    audit = result["exit_evidence"]["pi_side_a:c1"]
    assert audit["source_size"] == [4000, 3000] and audit["wire_exit_px"] == [1999.5, 1499.5]
    assert audit["local_color"]["name"] == "blue" and audit["local_color"]["method"] == "local_hsv_vote"


def test_demo_crops_preserve_source_coordinates_and_small_native_pixels(tmp_path):
    review, _, originals = fixture_inputs()
    source = Image.new("RGB", (4000, 3000), "red")
    ImageDraw.Draw(source).rectangle((1600, 1200, 2400, 1800), fill="blue")
    buffer = io.BytesIO(); source.save(buffer, "PNG")
    raw = buffer.getvalue()
    for role in ("pi_side_a", "pi_side_b"):
        originals[role] = raw
        review["slots"][role].update(size=[4000, 3000], sha256=hashlib.sha256(raw).hexdigest())
    review["slots"]["pi_side_a"]["crop"] = [.4, .4, .6, .6]
    review["slots"]["pi_side_b"]["crop"] = [.1, .1, .9, .9]
    photos, paths, manifest = pipeline._prepare(review, originals, ["pi_side_a", "pi_side_b"], tmp_path)
    details = {row["role"]: (path, row) for path, row in zip(paths, manifest) if row["view"] == "detail"}
    path, small = details["pi_side_a"]
    with Image.open(path) as pixels:
        assert pixels.format == "PNG" and pixels.size == (800, 600)
        assert pixels.tobytes() == source.crop((1600, 1200, 2400, 1800)).tobytes()
    assert small["crop"] == [1600, 1200, 2400, 1800]
    assert small["original_pixels"] and not small["resized"]
    path, large = details["pi_side_b"]
    with Image.open(path) as pixels:
        assert pixels.format == "JPEG" and pixels.size == (2048, 1536)
    assert large["crop"] == [400, 300, 3600, 2700] and large["source_size"] == [4000, 3000]
    assert large["resized"] and not large["original_pixels"]
    assert all(photo.size == source.size and photo.tobytes() == source.tobytes() for photo in photos.values())
    assert originals["pi_side_a"] == originals["pi_side_b"] == raw


def test_compact_pin_reply_cannot_inherit_exit_evidence_for_unknown_connector(tmp_path):
    def answer(prompt, schema):
        if "POC EXIT INVENTORY:" in prompt:
            return inventory(pipeline.ROLES)
        result = opinion(pipeline.ROLES)
        for view in result["views"]:
            view["connectors"][0]["id"] = "not-in-inventory"
        return result
    result, _ = run(tmp_path, callback=answer)
    for view in result["opinion"].views:
        connectors = {connector.id: connector for connector in view.connectors}
        assert connectors["not-in-inventory"].wire_color.name == "unknown"
        assert connectors["not-in-inventory"].wire_color.visibility == "not_visible"
        assert connectors["c1"].wire_color.name == "red" and connectors["c1"].pin_id is None
    assert all(not key.endswith(":not-in-inventory") for key in result["exit_evidence"])
