from __future__ import annotations

import base64
import json

import cv2
import numpy as np

from app.verification.color_vlm_worker import _wire_color_views_image
from app.vlm.service import VlmService


def _payload(*, board_color: str = "orange", component_color: str = "brown", same_color: str = "mismatch") -> dict:
    return {
        "schema_version": "1.0",
        "authority": "visual_advisory",
        "board_color": board_color,
        "component_color": component_color,
        "same_color": same_color,
        "confidence": 0.78,
        "board_evidence": "orange insulation is visible outside the UNO Q housing",
        "component_evidence": "brown insulation is visible outside the Sensor housing",
        "note": "visual colour evidence only",
    }


class _Provider:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[tuple[str, str, str | None, float, dict]] = []

    def complete_schema(self, system, prompt, image_b64, timeout_s, schema):
        self.calls.append((system, prompt, image_b64, timeout_s, schema))
        return self.output


def test_wire_color_contract_allows_an_explicit_unknown_abstention() -> None:
    provider = _Provider(json.dumps(_payload(
        board_color="unknown",
        component_color="orange",
        same_color="unknown",
    )))

    result = VlmService(provider).ask_wire_color(
        image_b64="sample", board_pin="3V3", component_pin="VCC"
    )

    assert result.ok is True
    assert result.data is not None
    assert result.data.board_color == "unknown"
    assert result.data.same_color == "unknown"
    assert provider.calls[0][4]["additionalProperties"] is False


def test_wire_color_contract_rejects_an_invented_colour() -> None:
    payload = _payload(board_color="teal")

    result = VlmService().validate_wire_color(json.dumps(payload))

    assert result.ok is False
    assert "invalid_wire_color_json" in (result.error or "")


def test_wire_color_vlm_image_contains_full_context_and_two_tight_endpoint_views() -> None:
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    encoded = _wire_color_views_image(
        frame,
        (240.0, 360.0),
        (1000.0, 360.0),
        "3V3",
        "VCC",
    )

    image = cv2.imdecode(
        np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), cv2.IMREAD_COLOR
    )

    assert image is not None
    assert image.shape[:2] == (360, 1956)
