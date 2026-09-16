import copy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.design import router
from app.components.store import ComponentStore, ComponentNotFoundError
from app.config import AppConfig, ComponentVisionConfig, ComponentVisionTargetConfig
from app.design_migration import migrate_maker_state
from app.designs import MODULES, demo_design, proposal_schema
from app.main import _component_targets
from app.motion_worker import TRACKED_COMPONENT_IDS

ROOT = Path(__file__).resolve().parents[2]


def legacy():
    design = demo_design()
    design["component_ids"].insert(1, "hw-123")
    design["title"] = "桌上型距離與傾斜監測器"
    design["wiring"].append({"id": "hw-123:gnd", "componentId": "hw-123"})
    design["profile_versions"]["hw-123"] = {"version": "1", "sha256": "old"}
    design["code"] = "PINS = {'hw-123': {'SDA': 2}}"
    design["image"] = {"id": "a" * 32}
    return {"design": design, "candidate": copy.deepcopy(design), "code": "# user edited original code",
            "selected": design["component_ids"], "stage": "guide", "prompt": "使用 Pi 5、超音波、陀螺儀和螢幕",
            "guide": {"componentIndex": 2, "phase": "active", "confirmed": {"hc-sr04:gnd": {"at": "today"}, "hw-123:gnd": {}}},
            "conversation": [{"role": "user", "text": "original request"}], "aiJobId": "old-job"}


def test_active_contract_has_only_distance_and_display_and_no_retired_model():
    assert list(MODULES) == ["hc-sr04", "mrd-tf240-8p-cs"]
    assert list(TRACKED_COMPONENT_IDS) == list(MODULES)
    assert "hw-123" not in str(proposal_schema())
    design = demo_design()
    assert len(design["wiring"]) == 10
    assert "HW-123" not in str(design) and "hw-123" not in str(design)


def test_retired_profile_files_are_preserved_but_unavailable_to_live_store():
    store = ComponentStore(ROOT / "profiles/components")
    assert (store.root / "hw-123/component.json").is_file()
    assert "hw-123" not in [component.id for component in store.list()]
    for lookup in (store.get, store.raw):
        with pytest.raises(ComponentNotFoundError):
            lookup("hw-123")


def test_legacy_config_cannot_restart_retired_model():
    old = ComponentVisionTargetConfig(id="hw-123", model_path=ROOT / "models/hw-123-pose.onnx",
        profile_path=ROOT / "profiles/components/hw-123/vision_profile.json")
    live = ComponentVisionTargetConfig(id="hc-sr04", model_path=ROOT / "models/hc-sr04-corner-pose-v3-robust.onnx",
        profile_path=ROOT / "profiles/components/hc-sr04/vision_profile.json")
    cfg = AppConfig(component_vision=ComponentVisionConfig(components=[old, live]))
    assert [item.id for item in _component_targets(cfg)] == ["hc-sr04"]
    cfg.component_vision.components = []
    cfg.component_vision.profile_path = old.profile_path
    assert _component_targets(cfg) == []


def test_migration_preserves_identity_progress_and_rebuilds_all_active_artifacts():
    state = legacy()
    before = copy.deepcopy(state)
    result = migrate_maker_state(state)
    assert state == before
    for key in ("design", "candidate"):
        design = result[key]
        assert design["id"] == state[key]["id"]
        assert design["revision"] == state[key]["revision"] + 1
        assert design["component_ids"] == list(MODULES)
        assert len(design["wiring"]) == 10
        assert "hw-123" not in str(design).lower()
        assert "image" not in design and design["image_error"]
        compile(design["code"], "migration.py", "exec")
    assert result["code"] == result["design"]["code"]
    assert result["guide"]["componentIndex"] == 1  # TFT stays selected after middle module removal.
    assert list(result["guide"]["confirmed"]) == ["hc-sr04:gnd"]
    assert result["conversation"] == state["conversation"] and result["aiJobId"] is None
    assert migrate_maker_state(result) == result


def test_retired_only_project_becomes_empty_without_substituting_a_demo():
    state = legacy()
    state["design"]["component_ids"] = ["hw-123"]
    state["candidate"] = None
    result = migrate_maker_state(state)
    assert result["design"] is None and result["code"] == ""
    assert result["stage"] == "design" and not result["guide"]["confirmed"]


def test_migration_route_is_local_deterministic_and_rejects_unknown_legacy_versions():
    app = FastAPI()
    app.include_router(router)  # No bridge/AI service is installed.
    with TestClient(app) as client:
        assert client.post("/api/design/migrate-retired", json=legacy()).status_code == 200
        state = legacy()
        state["design"]["catalog_version"] = "bad"
        assert client.post("/api/design/migrate-retired", json=state).status_code == 422
