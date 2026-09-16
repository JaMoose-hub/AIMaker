import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.vlm.service import VlmService


def _payload() -> dict:
    return {
        "schema_version": "1.0",
        "authority": "advisory_only",
        "board": {"type": "arduino-uno-q", "confidence": 0.98},
        "modules": [{
            "id": "servo-1",
            "type": "servo",
            "confidence": 0.8,
            "bbox_norm": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2},
            "pins": ["VCC", "GND", "SIGNAL"],
        }],
        "connections": [{
            "from_device": "arduino-uno-q",
            "from_pin": "D9",
            "to_device": "servo-1",
            "to_pin": None,
            "status": "candidate",
            "confidence": 0.7,
        }],
        "issues": [],
        "uncertain_items": [],
        "overall_confidence": 0.7,
    }


def test_validate_accepts_fixed_schema_and_fenced_json():
    raw = "```json\n" + json.dumps(_payload()) + "\n```"
    result = VlmService().validate(raw)
    assert result.ok is True
    assert result.data is not None
    assert result.data.authority == "advisory_only"
    assert result.raw_response == raw


def test_checked_in_json_schema_accepts_the_same_payload_as_the_service():
    schema_path = Path(__file__).resolve().parents[2] / "schemas" / "scene-understanding.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(_payload())


def test_validate_rejects_extra_fields_and_bad_confidence():
    payload = _payload()
    payload["unexpected"] = True
    payload["board"]["confidence"] = 1.5
    result = VlmService().validate(json.dumps(payload))
    assert result.ok is False
    assert result.data is None
    assert result.raw_response is not None
    assert "invalid_scene_json" in (result.error or "")


class SequenceProvider:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts = []

    def complete(self, prompt, image_b64, timeout_s):
        self.calls += 1
        self.prompts.append(prompt)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


def test_ask_retries_malformed_output_and_keeps_last_valid_result():
    provider = SequenceProvider(["not json", json.dumps(_payload())])
    result = VlmService(provider, retries=1).ask("identify the scene")
    assert result.ok is True
    assert result.attempts == 2
    assert provider.calls == 2


def test_ask_sends_image_and_structured_cv_ocr_context_to_provider():
    provider = SequenceProvider([json.dumps(_payload())])
    result = VlmService(provider).ask(
        "identify fixed MVP modules",
        image_b64="abc123",
        cv={"board_id": "arduino-uno-q", "pins": [{"id": "D9"}]},
        ocr=[{"text": "SIG", "confidence": 0.9}],
        board_profile={"id": "arduino-uno-q"},
    )
    assert result.ok is True
    assert "arduino-uno-q" in provider.prompts[0]
    assert '"ocr"' in provider.prompts[0]


def test_ask_is_safe_when_not_configured():
    result = VlmService().ask("identify the scene")
    assert result.as_dict() == {
        "ok": False,
        "authority": "advisory_only",
        "data": None,
        "raw_response": None,
        "error": "vlm_not_configured",
        "attempts": 0,
    }


def _insertion_payload() -> dict:
    return {
        "schema_version": "1.0",
        "authority": "visual_advisory",
        "board_endpoint": {
            "state": "inserted_target",
            "confidence": 0.91,
            "evidence": "connector centered over the target header opening",
        },
        "component_endpoint": {
            "state": "inserted_target",
            "confidence": 0.87,
            "evidence": "female housing visibly surrounds the sensor pin",
        },
        "same_wire": "likely",
        "same_wire_confidence": 0.82,
        "note": "visual only",
    }


def test_validate_insertion_accepts_only_the_narrow_visual_contract():
    result = VlmService().validate_insertion(json.dumps(_insertion_payload()))
    assert result.ok is True
    assert result.data is not None
    assert result.data.authority == "visual_advisory"


def test_validate_insertion_rejects_electrical_claim_fields():
    payload = _insertion_payload()
    payload["continuity"] = True
    result = VlmService().validate_insertion(json.dumps(payload))
    assert result.ok is False
    assert "invalid_insertion_json" in (result.error or "")


def test_ask_insertion_uses_existing_provider_protocol_and_retries():
    provider = SequenceProvider(["bad", json.dumps(_insertion_payload())])
    result = VlmService(provider, retries=1).ask_insertion(
        image_b64="abc", board_pin="A0", component_pin="AO"
    )
    assert result.ok is True
    assert result.attempts == 2
    assert provider.calls == 2


class SchemaProvider:
    def __init__(self):
        self.calls = []

    def complete_schema(self, system, prompt, image_b64, timeout_s, schema):
        self.calls.append({
            "system": system,
            "prompt": prompt,
            "image_b64": image_b64,
            "timeout_s": timeout_s,
            "schema": schema,
        })
        return json.dumps(_insertion_payload())


def test_ask_insertion_prefers_provider_json_schema_output():
    provider = SchemaProvider()
    result = VlmService(provider).ask_insertion(
        image_b64="abc", board_pin="A0", component_pin="AO"
    )

    assert result.ok is True
    assert len(provider.calls) == 1
    call = provider.calls[0]
    assert call["schema"]["additionalProperties"] is False
    assert call["schema"]["properties"]["same_wire_confidence"]["maximum"] == 1.0
    assert call["image_b64"] == "abc"
