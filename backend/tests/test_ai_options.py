import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.ai_costs import PRICING, estimate_cost, resolve_selection
from app.codex_bridge import CodexBridge
from app.design_prompt import build_design_prompt
from app.designs import GenerateRequest, proposal_schema
from test_maker import Bridge, client, completed, proposal

BODY = {"prompt": "distance warning below 20 cm", "component_ids": ["hc-sr04"], "model": "gpt-5.6-luna", "effort": "high"}


def test_estimate_is_local_does_not_generate_or_create_job_and_matches_payload():
    bridge = Bridge()
    bridge.generate = Mock(side_effect=AssertionError("estimation cannot generate"))
    c, app = client(bridge)
    assert c.get("/api/ai/models").json()["models"][0]["id"] == BODY["model"]
    response = c.post("/api/ai/estimate", json=BODY)
    assert response.status_code == 200
    estimate = response.json()
    assert estimate["model"] == BODY["model"] and estimate["effort"] == "high"
    assert estimate["actual_charge_usd"] is None and estimate["billing_mode"] == "chatgpt"
    assert estimate["api_equivalent_usd"]["min"] > 0
    text = build_design_prompt(GenerateRequest(**BODY))
    assert estimate["payload_bytes"] == len((text + json.dumps(proposal_schema(), ensure_ascii=False)).encode())
    assert not app.state.design_service.jobs
    bridge.generate.assert_not_called()


def test_job_passes_model_and_effort_and_records_estimate_without_mutating_design_draft():
    bridge = Bridge()
    c, app = client(bridge)
    job_id = c.post("/api/design/generate", json=BODY).json()["job_id"]
    job = completed(app.state.design_service, job_id)
    assert bridge.selection == (BODY["model"], "high")
    assert job["estimate"]["model"] == job["model"] == BODY["model"]
    assert job["design"]["generation"] == {"model": BODY["model"], "effort": "high", "design_mode": "free"}


@pytest.mark.parametrize("changes", [{"model": "invented"}, {"effort": "max"}, {"effort": "ultra"}, {"expected_output_tokens": 0}, {"expected_output_tokens": 200000}])
def test_invalid_selection_cannot_estimate_or_start_billable_job(changes):
    c, app = client()
    for path in ("estimate",):
        assert c.post(f"/api/ai/{path}", json={**BODY, **changes}).status_code == 422
    assert c.post("/api/design/generate", json={**BODY, **changes}).status_code == 422
    assert not app.state.design_service.jobs


def test_defaults_and_unknown_price_are_explicit_not_zero():
    model, effort = resolve_selection(Bridge().models())
    assert (model, effort) == ("gpt-5.6-luna", "low")
    unknown = estimate_cost("x", {}, "gpt-5.3-codex-spark", "low")
    assert unknown["api_equivalent_usd"] is None and unknown["reference_credits"] is None
    assert unknown["unavailable_reason"] == "unknown_price"
    with pytest.raises(ValueError):
        resolve_selection({**Bridge().models(), "default_model": "unavailable-environment-model"})


def test_calculation_uses_model_prices_reasoning_and_custom_output_scenario():
    low = estimate_cost("x", {}, "gpt-5.6-luna", "low")
    high = estimate_cost("x", {}, "gpt-5.6-luna", "high")
    pricey = estimate_cost("x", {}, "gpt-6-astra", "low")
    assert high["api_equivalent_usd"]["max"] > low["api_equivalent_usd"]["max"]
    assert pricey["api_equivalent_usd"]["min"] > low["api_equivalent_usd"]["min"]
    expected = round((low["input_tokens"]["min"] * .2 + low["output_tokens"]["min"] * 1.2) / 1_000_000, 6)
    assert low["api_equivalent_usd"]["min"] == expected
    custom = estimate_cost("x", {}, "gpt-6-astra", "high", 2000)
    assert custom["output_tokens"] == {"min": 1000, "max": 3000}
    assert not custom["assumptions"]["is_spend_cap"]


def test_prompt_length_context_and_schema_are_counted_but_secrets_never_forwarded():
    short = GenerateRequest(**BODY)
    longer = GenerateRequest(**{**BODY, "prompt": "中文" * 500, "current": {"title": "existing", "logic": "abc" * 50, "password": "SECRET"}})
    assert "SECRET" not in build_design_prompt(longer)
    assert estimate_cost(build_design_prompt(longer), proposal_schema(), BODY["model"], "low")["input_tokens"]["max"] > estimate_cost(build_design_prompt(short), proposal_schema(), BODY["model"], "low")["input_tokens"]["max"]


def test_stale_prices_and_long_context_do_not_get_plausible_wrong_quotes(monkeypatch):
    assert estimate_cost("x" * 600000, {}, BODY["model"], "low")["unavailable_reason"] == "long_context"
    monkeypatch.setitem(PRICING, "checked_at", "2000-01-01")
    result = estimate_cost("x", {}, BODY["model"], "low")
    assert result["unavailable_reason"] == "pricing_stale"
    assert result["api_equivalent_usd"] is None


def raw_model(model="gpt-5.6-luna", **extra):
    return {"model": model, "displayName": model, "supportedReasoningEfforts": [{"reasoningEffort": e} for e in ("low", "high", "ultra")],
            "defaultReasoningEffort": "low", "isDefault": True, **extra}


def test_model_catalog_paginates_filters_hidden_and_delegating_efforts_and_caches(monkeypatch):
    monkeypatch.delenv("BOARDVISION_CODEX_MODEL", raising=False)
    b = CodexBridge()
    b._start = Mock()
    b._rpc = Mock(side_effect=[{"data": [raw_model(), raw_model("hidden", hidden=True)], "nextCursor": "next"},
                               {"data": [raw_model("second", isDefault=False)], "nextCursor": None}])
    result = b.models()
    assert [m["id"] for m in result["models"]] == ["gpt-5.6-luna", "second"]
    assert result["models"][0]["efforts"] == ["low", "high"]
    assert result["models"][0]["excluded_efforts"] == ["ultra"]
    assert b._rpc.call_args_list[1].args[1]["cursor"] == "next"
    result["models"].clear()
    assert len(b.models()["models"]) == 2 and b._rpc.call_count == 2
    with b._lock:
        assert b.models()["models"]


def test_catalog_failure_empty_and_busy_are_not_fake_model_lists():
    b = CodexBridge()
    with b._lock, pytest.raises(RuntimeError, match="正忙"):
        b.models()
    b._start = Mock()
    b._rpc = Mock(return_value={"data": [], "nextCursor": None})
    with pytest.raises(RuntimeError, match="沒有回傳"):
        b.models()
    bridge = Bridge()
    bridge.models = Mock(side_effect=RuntimeError("CLI unavailable"))
    c, _ = client(bridge)
    assert c.get("/api/ai/models").status_code == 503
    assert c.post("/api/ai/estimate", json=BODY).status_code == 503


def test_bridge_passes_explicit_model_effort_standard_tier_to_real_rpc_shape():
    b = CodexBridge()
    b._start = Mock()
    b._workspace = SimpleNamespace(name="test-workspace")
    b._load_models = Mock(return_value=Bridge().models())
    calls = []
    def rpc(method, params, **kwargs):
        calls.append((method, copy.deepcopy(params)))
        if method == "account/read": return {"account": {"type": "chatgpt"}}
        if method == "thread/start": return {"thread": {"id": "thread"}, "model": BODY["model"]}
        if method == "turn/start":
            b._events.extend([
                {"method": "item/completed", "params": {"threadId": "thread", "item": {"type": "agentMessage", "text": json.dumps(proposal())}}},
                {"method": "turn/completed", "params": {"threadId": "thread", "turn": {"status": "completed"}}},
            ])
            return {"turn": {"id": "turn"}}
        raise AssertionError(method)
    b._rpc = rpc
    assert b.generate("prompt", {}, model=BODY["model"], effort="high")["title"]
    start = next(params for method, params in calls if method == "thread/start")
    turn = next(params for method, params in calls if method == "turn/start")
    assert start["model"] == BODY["model"] and start["serviceTier"] == "default"
    assert turn["effort"] == "high" and start["sandbox"] == "read-only"


@pytest.mark.parametrize("rerouted", [False, True])
def test_bridge_rejects_model_substitution_and_interrupts_started_turn(rerouted):
    b = CodexBridge()
    b._start = Mock()
    b._workspace = SimpleNamespace(name="test-workspace")
    b._load_models = Mock(return_value=Bridge().models())
    calls = []

    def rpc(method, params, **kwargs):
        calls.append(method)
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "thread/start":
            return {"thread": {"id": "thread"}, "model": BODY["model"] if rerouted else "different-model"}
        if method == "turn/start":
            b._events.append({"method": "model/rerouted", "params": {"threadId": "thread", "toModel": "different-model"}})
            return {"turn": {"id": "turn"}}
        if method == "turn/interrupt":
            assert params == {"threadId": "thread", "turnId": "turn"}
            return {}
        raise AssertionError(method)

    b._rpc = rpc
    with pytest.raises(RuntimeError, match="模型"):
        b.generate("prompt", {}, model=BODY["model"], effort="low")
    assert ("turn/start" in calls) == rerouted
    assert ("turn/interrupt" in calls) == rerouted
