"""Language contracts with fake AI only; no cloud calls or physical hardware."""
import re
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.debug import Context
from app.api.debug_sessions import SessionContext
from app.design_prompt import build_design_prompt
from app.designs import GenerateRequest, demo_design
from app.reply_language import reply_language_instruction, system_text
from test_maker import client
from test_unified_conversation import ChatBridge


@pytest.mark.parametrize("intent", ["ask", "auto", "design"])
@pytest.mark.parametrize("locale,language", [("en", "English"), ("zh-TW", "Traditional Chinese")])
def test_design_reply_language_overrides_message_and_history_language(intent, locale, language):
    prompt = build_design_prompt(GenerateRequest(prompt="這一步怎麼接？", intent=intent, locale=locale,
        component_ids=["hc-sr04"], conversation=[{"role": "assistant", "text": "這是旧回覆"}]))
    assert f"in {language}." in prompt and "takes precedence" in prompt
    assert "這一步怎麼接？" in prompt  # evidence/user input is not rewritten
    assert "Do not translate JSON keys" in prompt


@pytest.mark.parametrize("model", [Context, SessionContext])
def test_locale_defaults_and_validation(model):
    assert model.model_validate({}).locale == "zh-TW"
    assert model.model_validate({"locale": "en"}).locale == "en"
    with pytest.raises(ValidationError):
        model.model_validate({"locale": "fr"})


@pytest.mark.parametrize("ids", [None, ["hc-sr04"], ["mrd-tf240-8p-cs"]])
def test_demo_all_user_facing_prose_is_english_without_changing_wiring(ids):
    zh, en = demo_design(ids), demo_design(ids, locale="en")
    for field in ("title", "summary", "prompt", "features", "instructions", "tests"):
        assert not re.search(r"[\u3400-\u9fff]", str(en[field])), (field, en[field])
    for item in en["bom"]:
        assert not re.search(r"[\u3400-\u9fff]", item["name"] + item["purpose"])
    for field in ("wiring", "code", "parameters", "component_ids", "profile_versions"):
        assert zh[field] == en[field]


def test_demo_endpoint_accepts_locale_and_never_calls_ai():
    bridge = ChatBridge("answer")
    c, _ = client(bridge)
    response = c.get("/api/design/demo?locale=en")
    assert response.status_code == 200
    assert not re.search(r"[\u3400-\u9fff]", response.json()["title"])
    assert not bridge.text_calls and not bridge.image_calls
    assert c.get("/api/design/demo?locale=fr").status_code == 422


def test_fixed_status_translation_and_observed_text_exception_are_explicit():
    assert system_text("本次 AI 協作除錯已停止。", {"locale": "en"}) == "This AI debugging check has stopped."
    assert "verbatim text observed in an image" in reply_language_instruction({"locale": "en"})


def test_all_fixed_debug_instructions_have_english_translations():
    tree = ast.parse((Path(__file__).parents[1] / "app" / "debug_sessions.py").read_text(encoding="utf-8"))
    instructions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "instruction":
            instructions.append(node.value)
        elif isinstance(node, ast.Dict):
            instructions.extend(value for key, value in zip(node.keys, node.values)
                                if isinstance(key, ast.Constant) and key.value == "instruction")
    missing = []
    for node in instructions:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.search(r"[\u3400-\u9fff]", system_text(node.value, {"locale": "en"})):
                missing.append(node.value)
    assert not missing, missing
