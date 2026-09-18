import ast
import itertools
import sys
import threading
import time
from types import SimpleNamespace, ModuleType

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.design import DesignService, router
from app.api.pi import router as pi_router
from app.designs import CATALOG, MODULES, DesignProposal, GenerateRequest, compile_design, demo_design, proposal_schema, validate_logic, wiring_for


def proposal(ids=None):
    demo = demo_design(ids or ["hc-sr04"])
    return {k: demo[k] for k in DesignProposal.model_fields}


class Bridge:
    def __init__(self, error=None, gate=None):
        self.error, self.gate, self.prompt = error, gate, ""

    def generate(self, prompt, schema, *, model=None, effort=None):
        self.prompt = prompt
        self.selection = (model, effort)
        if self.gate:
            self.gate.wait(2)
        if self.error:
            raise self.error
        return proposal()

    def status(self):
        return {"available": True, "logged_in": True, "busy": False, "error": None}

    def login(self):
        return {"auth_url": "https://auth.openai.com/example"}

    def models(self, refresh=False):
        return {"models": [{"id": "gpt-5.6-luna", "name": "Luna", "efforts": ["low", "medium", "high"], "default_effort": "medium"},
                            {"id": "gpt-5.3-codex-spark", "name": "Spark", "efforts": ["low", "high"], "default_effort": "high"}],
                "default_model": "gpt-5.6-luna", "billing_mode": "chatgpt"}


def client(bridge=None):
    app = FastAPI()
    app.state.design_service = DesignService(bridge or Bridge())
    app.state.pi_deployer = SimpleNamespace(snapshot=lambda: {"connected": True}, deploy=lambda code: {"ok": True})
    app.include_router(router)
    app.include_router(pi_router)
    return TestClient(app), app


def completed(service, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = service.get(job_id)
        if result["status"] != "generating":
            return result
        time.sleep(0.01)
    pytest.fail("job did not finish")


@pytest.mark.parametrize("ids", [list(s) for n in (1, 2, 3) for s in itertools.combinations(MODULES, n)])
def test_all_combinations_share_profiles_and_never_enable_unknown_hardware(ids):
    design = demo_design(ids)
    assert len(design["wiring"]) == sum(len(MODULES[c]["steps"]) for c in ids)
    ast.parse(design["code"])
    for cid in ids:
        for step in MODULES[cid]["steps"]:
            wire = next(w for w in design["wiring"] if w["id"] == f"{cid}:{step['id']}")
            assert wire["boardPin"] == step["boardPin"]
    assert not design["unresolved"]
    if "mrd-tf240-8p-cs" in ids:
        assert "WiringDisplay" in design["code"]
        assert "backlight=lambda enabled: None" in design["code"]
    if ids == ["hc-sr04"]:
        assert "'TRIG': 17" in design["code"] and "'ECHO': 18" in design["code"]
        assert not {"resistor-330", "resistor-470", "breadboard"}.intersection(i["id"] for i in design["bom"])
        assert next(i for i in design["bom"] if i["id"] == "jumper-wires")["quantity"] == 4
        assert next(w for w in design["wiring"] if w["componentPin"] == "VCC")["boardPin"] == "3V3_P1"
        assert next(w for w in design["wiring"] if w["componentPin"] == "ECHO")["connectionKind"] == "direct"


def test_revisions_keep_identity_and_regenerate_from_profile_not_client_wires():
    old = demo_design(["hc-sr04"])
    old["wiring"][0]["boardPin"] = "GPIO99"
    p = DesignProposal.model_validate({**proposal(), "parameters": {"distance_cm": 10, "sample_ms": 300}})
    result = compile_design(p, "change threshold", current=old)
    assert result["id"] == old["id"] and result["revision"] == 2
    assert result["wiring"][0]["boardPin"] == "GND_P6"
    assert "'distance_cm': 10.0" in result["code"]


def test_strict_output_schema_requires_defaulted_nested_fields():
    schema = proposal_schema()
    params = schema["$defs"]["Parameters"]
    assert set(params["required"]) == set(params["properties"])
    assert params["additionalProperties"] is False


@pytest.mark.parametrize("source", ["import os", "def on_sample(readings, settings):\n    import gpiozero", "def on_sample(readings, settings):\n    return open('x')", "def on_sample(readings, settings):\n    while True: pass", "def on_sample(readings, settings):\n    return readings.__class__", "def other():\n    return 1"])
def test_unsafe_or_independent_hardware_logic_rejected(source):
    with pytest.raises(ValueError):
        validate_logic(source)


def test_generation_routes_and_private_config_not_forwarded():
    b = Bridge()
    c, app = client(b)
    assert c.get("/api/ai/status").json()["logged_in"]
    assert c.post("/api/ai/login").json()["auth_url"].startswith("https://")
    result = c.post("/api/design/generate", json={"prompt": "distance", "component_ids": ["hc-sr04"], "current": {"password": "SECRET", "host": "PRIVATE"}})
    assert result.status_code == 202
    job = completed(app.state.design_service, result.json()["job_id"])
    assert job["status"] == "completed" and job["design"]["source"] == "ai"
    assert "SECRET" not in b.prompt and "PRIVATE" not in b.prompt
    assert c.get("/api/design/jobs/absent").status_code == 404
    assert c.post("/api/design/generate", json={"prompt": "", "component_ids": []}).status_code == 422
    assert c.post("/api/design/generate", json={"prompt": "x", "component_ids": ["unknown"]}).status_code == 422
    assert c.get("/api/design/demo").json()["source"] == "demo"
    assert c.get("/api/design/catalog").json()["version"] == CATALOG["version"]


def test_busy_and_failure_are_explicit_not_demo_fallback():
    gate = threading.Event()
    c, app = client(Bridge(TimeoutError("AI timeout"), gate))
    job = c.post("/api/design/generate", json={"prompt": "distance", "component_ids": ["hc-sr04"]}).json()
    assert c.post("/api/design/generate", json={"prompt": "second", "component_ids": ["hc-sr04"]}).status_code == 409
    gate.set()
    result = completed(app.state.design_service, job["job_id"])
    assert result["status"] == "failed" and result["design"] is None
    assert result["error"] == "AI timeout"


def test_unsupported_hardware_deploy_is_blocked_on_server_legacy_unchanged():
    c, _ = client()
    assert c.post("/api/pi/deploy", json={"code": "print('x')", "project": {"component_ids": ["hw-123"], "catalog_version": "1"}}).status_code == 422
    for cid in ("mrd-tf240-8p-cs",):
        result = c.post("/api/pi/deploy", json={"code": "print('x')", "project": {"component_ids": [cid], "catalog_version": "1"}}).json()
        assert result["ok"] is False and result["error"]
    assert c.post("/api/pi/deploy", json={"code": "print('legacy')"}).json()["ok"]
    assert not c.post("/api/pi/deploy", json={"code": "print('x')", "project": {"component_ids": ["hc-sr04"], "catalog_version": "0"}}).json()["ok"]


def test_model_cannot_add_modules_outside_available_parts():
    c, app = client()
    result = c.post("/api/design/generate", json={"prompt": "display", "component_ids": ["mrd-tf240-8p-cs"]})
    job = completed(app.state.design_service, result.json()["job_id"])
    assert job["status"] == "failed"


@pytest.mark.parametrize("cid,index,field,value", [
    ("hc-sr04", 3, "boardPin", "5V_P2"),
    ("mrd-tf240-8p-cs", 1, "boardPin", "GPIO10"),
    ("hc-sr04", 3, "boardPin", "GND_P9"),
])
def test_catalog_validation_rejects_unsafe_rails_swapped_bus_and_missing_protection(monkeypatch, cid, index, field, value):
    monkeypatch.setitem(MODULES[cid]["steps"][index], field, value)
    with pytest.raises(ValueError):
        wiring_for([cid])


def test_profile_revision_mismatch_requires_new_design():
    c, _ = client()
    result = c.post("/api/pi/deploy", json={"code": "print('x')", "project": {
        "component_ids": ["hc-sr04"], "catalog_version": CATALOG["version"], "profile_versions": {"old": {"version": "0"}}}}).json()
    assert not result["ok"] and "Profile" in result["error"]


@pytest.mark.parametrize("source", [
    "def on_sample(readings, settings):\n    return on_sample(readings, settings)",
    "def on_sample(readings, settings):\n    return [str(x) for x in readings]",
    "def on_sample(readings, settings):\n    return unknown(readings)",
])
def test_formatter_cannot_recurse_loop_or_call_unknown_function(source):
    with pytest.raises(ValueError):
        validate_logic(source)


@pytest.mark.parametrize("raw,age,expected", [(.04, 0, "distance_cm=16.0 WARNING"), (None, 0, "UNAVAILABLE"), (.04, 2, "UNAVAILABLE"), (1, 0, "UNAVAILABLE")])
def test_generated_runtime_marks_missing_stale_and_clipped_echo_unavailable(monkeypatch, capsys, raw, age, expected):
    """Synthetic runtime contract test, not a hardware distance measurement."""
    class StopSample(Exception):
        pass
    class Sensor:
        def __init__(self, **kwargs):
            self.max_distance = kwargs["max_distance"]
        def _read(self):
            return raw
        def __enter__(self):
            self._read()
            return self
        def __exit__(self, *args):
            return False
    def stop(_):
        raise StopSample()
    ticks = iter([10, 10 + age])
    for name, values in {
        "time": {"sleep": stop, "monotonic": lambda: next(ticks)},
        "gpiozero": {"DistanceSensor": Sensor},
        "gpiozero.pins": {},
        "gpiozero.pins.lgpio": {"LGPIOFactory": lambda: None},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    with pytest.raises(StopSample):
        exec(demo_design(["hc-sr04"])["code"], {})
    assert expected in capsys.readouterr().out
