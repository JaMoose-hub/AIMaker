"""Local, non-billable estimates. Never treat ChatGPT credits as a USD invoice."""
import json
import math
from datetime import date
from pathlib import Path

PRICING = json.loads(Path(__file__).with_name("ai_pricing.json").read_text(encoding="utf-8"))
# Product heuristics, NOT provider token guarantees or enforced output limits.
OUTPUT_SCENARIOS = {"none": 2000, "minimal": 2500, "low": 4000, "medium": 8000,
                    "high": 16000, "xhigh": 32000, "max": 64000}


def resolve_selection(options, model=None, effort=None):
    model_id = model or options["default_model"]
    selected = next((m for m in options["models"] if m["id"] == model_id), None)
    if not selected:
        raise ValueError(f"模型 {model_id!r} 不在目前 Codex 清單內；請重新選擇。")
    chosen_effort = effort or ("low" if "low" in selected["efforts"] else selected["default_effort"])
    if chosen_effort not in selected["efforts"]:
        raise ValueError(f"模型 {model_id} 不支援推理強度 {chosen_effort}。")
    return model_id, chosen_effort


def estimate_cost(prompt, schema, model, effort, expected_output_tokens=None):
    payload_bytes = len((prompt + json.dumps(schema, ensure_ascii=False)).encode("utf-8"))
    # Known prompt + output schema, plus an explicit allowance for Codex system context.
    inputs = {"min": math.ceil(payload_bytes / 4) + 1000, "max": math.ceil(payload_bytes / 2) + 6000}
    scenario = expected_output_tokens or OUTPUT_SCENARIOS[effort]
    outputs = {"min": math.ceil(scenario / 2), "max": min(128000, math.ceil(scenario * 1.5))}
    rate = PRICING["models"].get(model)
    stale = (date.today() - date.fromisoformat(PRICING["checked_at"])).days > 30
    reason = "pricing_stale" if stale else "unknown_price" if not rate else "long_context" if inputs["max"] > 272000 else None

    def cost(input_rate, output_rate):
        return {bound: round((inputs[bound] * input_rate + outputs[bound] * output_rate) / 1_000_000, 6)
                for bound in ("min", "max")}

    return {"model": model, "effort": effort, "billing_mode": "chatgpt", "currency": "USD",
            "kind": "scenario_estimate", "input_tokens": inputs, "output_tokens": outputs,
            "expected_output_tokens": scenario, "payload_bytes": payload_bytes,
            "api_equivalent_usd": cost(rate["input"], rate["output"]) if not reason else None,
            "reference_credits": cost(rate["credit_input"], rate["credit_output"]) if not reason else None,
            "actual_charge_usd": None, "unavailable_reason": reason,
            "pricing_checked_at": PRICING["checked_at"], "pricing_stale": stale,
            "api_source": (rate or {}).get("api_source", PRICING["api_source"]),
            "credits_source": PRICING["credits_source"], "rates": rate,
            "assumptions": {"tokenizer": "utf8_heuristic", "system_context_tokens": [1000, 6000],
                            "cached_input_tokens": 0, "service_tier": "standard",
                            "includes_reasoning": True, "is_spend_cap": False}}
