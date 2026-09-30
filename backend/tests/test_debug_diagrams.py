"""Saved diagram references preserve the exact supported wiring and render inputs."""
from copy import deepcopy
import json

import pytest

from app.debug_diagrams import build_diagram_snapshot, resolve_wiring_target
from app.designs import MODULES, demo_design


def test_snapshot_freezes_pin_order_header_labels_and_hc_plus_spec(monkeypatch):
    design = demo_design()
    target = dict(component_id="hc-sr04", wire_id="hc-sr04:echo")
    snapshot = build_diagram_snapshot(design, target)
    saved = json.loads(json.dumps(snapshot))
    hc, tft = saved["render_snapshot"]["modules"]
    assert hc["pin_order"] == ["VCC", "TRIG", "ECHO", "GND"]
    assert not hc["header_at_top"] and tft["header_at_top"]
    assert "HC-SR04+" in hc["name"]["zh-TW"] and hc["variant"] == "HC-SR04+ / 3.3V"
    echo = next(w for w in saved["design"]["wiring"] if w["id"] == target["wire_id"])
    vcc = next(w for w in saved["design"]["wiring"] if w["id"] == "hc-sr04:vcc")
    assert echo["boardPin"] == "GPIO18" and echo["connectionKind"] == "direct"
    assert vcc["boardPin"] == "3V3_P1"
    assert saved["render_snapshot"]["board"]["numbering"] == "physical"
    assert len(saved["render_snapshot"]["board"]["pins"]) == 40
    design["wiring"][0]["boardLabel"] = "modified project"
    monkeypatch.setitem(MODULES["hc-sr04"], "name", {"zh-TW": "changed catalog", "en": "changed"})
    assert snapshot == saved


def test_target_resolves_canonical_supported_project_wire_and_is_independent():
    design = demo_design(["hc-sr04"])
    resolved = resolve_wiring_target(design, dict(component_id="hc-sr04", wire_id="hc-sr04:vcc"))
    assert resolved["board_pin"] == "3V3_P1" and resolved["component_pin"] == "VCC"
    assert build_diagram_snapshot(design, resolved)["target"]["wire_id"] == "hc-sr04:vcc"
    forged = {**resolved, "board_pin": "5V_P2"}
    with pytest.raises(ValueError, match="invalid_wiring_target"):
        build_diagram_snapshot(design, forged)
    design["profile_versions"].clear()
    assert resolved["profile_versions"]


@pytest.mark.parametrize("target", [
    {"component_id": "mrd-tf240-8p-cs", "wire_id": "mrd-tf240-8p-cs:gnd"},
    {"component_id": "hc-sr04", "wire_id": "hc-sr04:made-up"},
    {"component_id": "hc-sr04", "wire_id": "hc-sr04:echo", "board_pin": "5V_P2"},
    {"component_id": "../private", "wire_id": "hc-sr04:echo"}, None,
])
def test_invalid_or_model_invented_wire_target_rejected(target):
    with pytest.raises(ValueError, match="invalid_wiring_target"):
        resolve_wiring_target(demo_design(["hc-sr04"]), target)


def test_diagram_uses_canonical_labels_and_rejects_stale_or_changed_wiring():
    design = demo_design(["hc-sr04"])
    design["wiring"][0]["boardLabel"] = "invented model label"
    snapshot = build_diagram_snapshot(design)
    assert snapshot["design"]["wiring"][0]["boardLabel"] != "invented model label"
    stale = deepcopy(design)
    stale["catalog_version"] = "old"
    with pytest.raises(ValueError, match="profile_changed"):
        build_diagram_snapshot(stale)
    design["wiring"][0]["boardPin"] = "5V_P2"
    with pytest.raises(ValueError, match="wiring_changed"):
        build_diagram_snapshot(design)
