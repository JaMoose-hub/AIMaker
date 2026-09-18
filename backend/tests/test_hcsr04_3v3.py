"""3.3V variant contract/migration tests; not physical voltage measurements."""
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.design import router
from app.design_migration import migrate_maker_state
from app.designs import CATALOG, MODULES, ROOT, component_spec_path, demo_design, wiring_for


def signature(wire):
    return "|".join(wire[k] for k in ("componentId", "componentPin", "boardPin", "connectionKind"))


def legacy_state():
    design = demo_design()
    design.update(catalog_version="1", code="# old generated code", instructions=["VCC 接 5V；ECHO 接 330Ω/470Ω 分壓。"])
    design["wiring"] = [w for w in design["wiring"] if w["id"] != "mrd-tf240-8p-cs:vcc"]
    for wire in design["wiring"]:
        if wire["id"] == "hc-sr04:vcc":
            wire.update(boardPin="5V_P2", boardLabel="Pin 2 · 5V")
        if wire["id"] == "hc-sr04:echo":
            wire["connectionKind"] = "divider"
    design["image"] = {"id": "a" * 32, "url": "/api/design/images/" + "a" * 32}
    return dict(design=design, candidate=copy.deepcopy(design), selected=design["component_ids"],
                code=design["code"], stage="blueprint", prompt="我的作品", conversation=[{"text": "5V old discussion"}],
                guide=dict(index=3, componentIndex=0, phase="active", checks=["old"],
                           confirmed={w["id"]: dict(signature=signature(w), mode="camera", at="before") for w in design["wiring"]}),
                hardware={"distance": "passed"}, aiJobId="old")


def test_variant_is_separate_from_standard_profile_and_old_echo_is_rejected(monkeypatch):
    variant = json.loads(component_spec_path("hc-sr04").read_text(encoding="utf-8"))
    standard = json.loads((ROOT / "profiles/components/hc-sr04/component.json").read_text(encoding="utf-8"))
    assert next(p for p in variant["pins"] if p["id"] == "ECHO")["signal_voltage"] == 3.3
    assert next(p for p in standard["pins"] if p["id"] == "ECHO")["signal_voltage"] == 5
    monkeypatch.setitem(MODULES["hc-sr04"], "electrical_profile", "component.json")
    with pytest.raises(ValueError, match="ECHO"):
        wiring_for(["hc-sr04"])


def test_catalog_migration_updates_all_artifacts_without_losing_identity_or_conversation():
    old = legacy_state()
    before = copy.deepcopy(old)
    new = migrate_maker_state(old)
    assert old == before
    for key in ("design", "candidate"):
        design = new[key]
        assert design["id"] == old[key]["id"]
        assert design["revision"] == old[key]["revision"] + 1
        assert design["catalog_version"] == CATALOG["version"]
        assert design["profile_versions"]["hc-sr04"]["version"] == "2.0.0"
        assert all(w["connectionKind"] == "direct" for w in design["wiring"])
        assert design["image"] == old[key]["image"]
        assert "330Ω" not in str(design["instructions"])
        assert "Pin 1（3.3V）" in str(design["instructions"])
        assert not any(i["id"].startswith("resistor-") or i["id"] == "breadboard" for i in design["bom"])
    assert new["code"] == new["design"]["code"]
    assert new["stage"] == "blueprint" and new["conversation"] == old["conversation"]
    assert new["guide"]["phase"] == "prepare" and not new["hardware"]
    assert len(new["guide"]["confirmed"]) == 8
    assert "hc-sr04:vcc" not in new["guide"]["confirmed"]
    assert "hc-sr04:echo" not in new["guide"]["confirmed"]
    assert "hc-sr04:trig" in new["guide"]["confirmed"]
    assert migrate_maker_state(new) == new


def test_user_edited_code_and_tft_only_are_not_replaced_by_hc_instructions():
    old = legacy_state()
    old["code"] = "# user's custom code"
    new = migrate_maker_state(old)
    assert new["code"] == old["code"]
    assert "HC-SR04" not in str(demo_design(["mrd-tf240-8p-cs"])["instructions"])


def test_catalog_route_rejects_unknown_versions_and_does_not_need_cloud():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        assert client.post("/api/design/migrate-catalog", json=legacy_state()).status_code == 200
        old = legacy_state()
        old["design"]["catalog_version"] = "unknown"
        assert client.post("/api/design/migrate-catalog", json=old).status_code == 422
