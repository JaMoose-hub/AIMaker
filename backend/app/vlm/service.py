"""Optional VLM adapter with strict JSON validation and safe failure modes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib import request as urllib_request

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from app.vlm.models import (
    FinalWiringUnderstanding,
    InsertionUnderstanding,
    SceneInput,
    SceneUnderstanding,
    WireColorUnderstanding,
)


class VlmProvider(Protocol):
    def complete(self, prompt: str, image_b64: str | None, timeout_s: float) -> str:
        ...


@dataclass
class VlmValidationResult:
    ok: bool
    data: SceneUnderstanding | None
    raw_response: str | None
    error: str | None
    attempts: int

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "authority": "advisory_only",
            "data": self.data.model_dump(mode="json") if self.data is not None else None,
            "raw_response": self.raw_response,
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass
class InsertionValidationResult:
    ok: bool
    data: InsertionUnderstanding | None
    raw_response: str | None
    error: str | None
    attempts: int

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "authority": "visual_advisory",
            "data": self.data.model_dump(mode="json") if self.data is not None else None,
            "raw_response": self.raw_response,
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass
class FinalWiringValidationResult:
    ok: bool
    data: FinalWiringUnderstanding | None
    raw_response: str | None
    error: str | None
    attempts: int

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "authority": "visual_advisory",
            "data": self.data.model_dump(mode="json") if self.data is not None else None,
            "raw_response": self.raw_response,
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass
class WireColorValidationResult:
    ok: bool
    data: WireColorUnderstanding | None
    raw_response: str | None
    error: str | None
    attempts: int

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "authority": "visual_advisory",
            "data": self.data.model_dump(mode="json") if self.data is not None else None,
            "raw_response": self.raw_response,
            "error": self.error,
            "attempts": self.attempts,
        }


_FENCED_JSON = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.IGNORECASE | re.DOTALL)
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "scene-understanding.schema.json"


def _scene_schema_validator() -> Draft202012Validator:
    """Load the checked-in wire contract used by the external VLM boundary.

    Pydantic gives the application typed objects, but the JSON Schema is the
    interoperability contract for providers and downstream clients. Keeping
    both checks here prevents the two definitions from silently drifting.
    """
    raw_schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(raw_schema)


def _decode_json(text: str) -> object:
    candidate = text.strip()
    fenced = _FENCED_JSON.match(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # Some local models prepend a sentence despite being instructed to
        # return JSON.  Restrict recovery to the outermost object; schema
        # validation below remains mandatory and no fields are inferred.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(candidate[start : end + 1])


class VlmService:
    def __init__(self, provider: VlmProvider | None = None,
                 *, timeout_s: float = 8.0, retries: int = 1) -> None:
        self.provider = provider
        self.timeout_s = max(float(timeout_s), 0.1)
        self.retries = max(int(retries), 0)

    def validate(self, raw_response: str) -> VlmValidationResult:
        try:
            decoded = _decode_json(raw_response)
            data = SceneUnderstanding.model_validate(decoded)
            _scene_schema_validator().validate(data.model_dump(mode="json"))
        except (json.JSONDecodeError, TypeError, ValidationError,
                JsonSchemaValidationError, SchemaError, OSError, ValueError) as exc:
            return VlmValidationResult(False, None, raw_response,
                                       f"invalid_scene_json: {exc}", 1)
        return VlmValidationResult(True, data, raw_response, None, 1)

    def ask(self, prompt: str, image_b64: str | None = None,
            cv: dict | None = None,
            ocr: list[dict] | None = None,
            board_profile: dict | None = None) -> VlmValidationResult:
        if self.provider is None:
            return VlmValidationResult(False, None, None, "vlm_not_configured", 0)
        last_raw: str | None = None
        last_error = "vlm_failed"
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                input_data = SceneInput(
                    prompt=prompt,
                    cv=cv or {},
                    ocr=ocr or [],
                    board_profile=board_profile or {},
                )
                grounded_prompt = (
                    "Use the following structured CV/OCR evidence as grounding. "
                    "Do not invent a pin or connection that is absent from it.\n"
                    + json.dumps(input_data.model_dump(mode="json"), ensure_ascii=False)
                )
                raw = self.provider.complete(grounded_prompt, image_b64, self.timeout_s)
                last_raw = raw
                checked = self.validate(raw)
                checked.attempts = attempt
                if checked.ok:
                    return checked
                last_error = checked.error or last_error
            except Exception as exc:  # provider failure is non-fatal to CV
                last_error = f"provider_error: {exc}"
        return VlmValidationResult(False, None, last_raw, last_error, attempts)

    def validate_insertion(self, raw_response: str) -> InsertionValidationResult:
        try:
            decoded = _decode_json(raw_response)
            data = InsertionUnderstanding.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            return InsertionValidationResult(
                False, None, raw_response, f"invalid_insertion_json: {exc}", 1
            )
        return InsertionValidationResult(True, data, raw_response, None, 1)

    def ask_insertion(
        self,
        *,
        image_b64: str,
        board_pin: str,
        component_pin: str,
    ) -> InsertionValidationResult:
        if self.provider is None:
            return InsertionValidationResult(
                False, None, None, "vlm_not_configured", 0
            )
        system = (
            "Return ONLY one JSON object with exactly these fields: "
            "schema_version='1.0', authority='visual_advisory', "
            "board_endpoint, component_endpoint, same_wire, "
            "same_wire_confidence, note. Each endpoint must contain state, "
            "confidence, evidence. state must be inserted_target, "
            "inserted_adjacent, empty, occluded, or uncertain. same_wire must "
            "be likely, unlikely, or uncertain. The supplied image is either a "
            "raw full-resolution camera frame or a four-panel composite ordered "
            "LEFT to RIGHT: complete view, connection context, enlarged Arduino "
            "target-header, enlarged sensor target-header. It contains no frontend "
            "UI. When enlarged panels are present, use them to judge the connector "
            "and neighboring pins. When only the raw frame is present, locate the "
            "UNO Q and sensor yourself using the expected pin names and use "
            "uncertain if their targets are too small to inspect. "
            "Judge the connector socket/base, not the "
            "direction in which the flexible wire exits it. Use inserted_adjacent "
            "only when the expected target pin itself is visibly empty and the seated "
            "connector is on a different neighboring pin. Judge visible connector "
            "seating only. "
            "Never claim electrical continuity or voltage. Use uncertain when "
            "the exact pin or insertion depth cannot be seen."
        )
        prompt = (
            f"Expected board pin: {board_pin}. Expected component pin: "
            f"{component_pin}. Decide whether each connector is visibly seated "
            "on its target and whether the multi-view evidence is "
            "consistent with the same wire."
        )
        last_raw: str | None = None
        last_error = "vlm_failed"
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                complete_structured = getattr(self.provider, "complete_structured", None)
                complete_schema = getattr(self.provider, "complete_schema", None)
                if callable(complete_schema):
                    raw = complete_schema(
                        system,
                        prompt,
                        image_b64,
                        self.timeout_s,
                        InsertionUnderstanding.model_json_schema(),
                    )
                elif callable(complete_structured):
                    raw = complete_structured(
                        system, prompt, image_b64, self.timeout_s
                    )
                else:
                    # Test/custom providers that only implement the original
                    # protocol still work; strict validation remains mandatory.
                    raw = self.provider.complete(
                        system + "\n" + prompt, image_b64, self.timeout_s
                    )
                last_raw = raw
                checked = self.validate_insertion(raw)
                checked.attempts = attempt
                if checked.ok:
                    return checked
                last_error = checked.error or last_error
            except Exception as exc:
                last_error = f"provider_error: {exc}"
        return InsertionValidationResult(
            False, None, last_raw, last_error, attempts
        )

    def validate_final_wiring(self, raw_response: str) -> FinalWiringValidationResult:
        try:
            decoded = _decode_json(raw_response)
            data = FinalWiringUnderstanding.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            return FinalWiringValidationResult(
                False, None, raw_response, f"invalid_final_wiring_json: {exc}", 1
            )
        return FinalWiringValidationResult(True, data, raw_response, None, 1)

    def ask_final_wiring(
        self,
        *,
        image_b64: str,
        expected_connections: list[dict[str, str]],
    ) -> FinalWiringValidationResult:
        """Ask once for all guided connections; visual evidence only."""
        if self.provider is None:
            return FinalWiringValidationResult(
                False, None, None, "vlm_not_configured", 0
            )
        expected_text = json.dumps(expected_connections, ensure_ascii=False)
        system = (
            "Return ONLY one JSON object with exactly these fields: "
            "schema_version='1.0', authority='visual_advisory', connections, note. "
            "Each connections item must contain board_pin, component_pin, state, "
            "confidence, evidence. state must be inserted_target, inserted_adjacent, "
            "empty, occluded, or uncertain. The image has four panels ordered "
            "LEFT to RIGHT: complete camera view, connection context, enlarged "
            "Arduino view, and enlarged sensor view. Use the full/context panels "
            "to associate each wire, and the enlarged panels to inspect the actual "
            "connector socket and neighboring pins. This is visual evidence only; "
            "never claim electrical continuity or voltage. Return one item for "
            "every expected pair, even when uncertain."
        )
        prompt = (
            "Expected wiring pairs, which must all be checked: "
            f"{expected_text}. Judge the physical connector seating for each pair."
        )
        last_raw: str | None = None
        last_error = "vlm_failed"
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                complete_structured = getattr(self.provider, "complete_structured", None)
                complete_schema = getattr(self.provider, "complete_schema", None)
                if callable(complete_schema):
                    raw = complete_schema(
                        system,
                        prompt,
                        image_b64,
                        self.timeout_s,
                        FinalWiringUnderstanding.model_json_schema(),
                    )
                elif callable(complete_structured):
                    raw = complete_structured(system, prompt, image_b64, self.timeout_s)
                else:
                    raw = self.provider.complete(
                        system + "\n" + prompt, image_b64, self.timeout_s
                    )
                last_raw = raw
                checked = self.validate_final_wiring(raw)
                checked.attempts = attempt
                if checked.ok:
                    return checked
                last_error = checked.error or last_error
            except Exception as exc:
                last_error = f"provider_error: {exc}"
        return FinalWiringValidationResult(False, None, last_raw, last_error, attempts)

    def validate_wire_color(self, raw_response: str) -> WireColorValidationResult:
        try:
            decoded = _decode_json(raw_response)
            data = WireColorUnderstanding.model_validate(decoded)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            return WireColorValidationResult(
                False, None, raw_response, f"invalid_wire_color_json: {exc}", 1
            )
        return WireColorValidationResult(True, data, raw_response, None, 1)

    def ask_wire_color(
        self,
        *,
        image_b64: str,
        board_pin: str,
        component_pin: str,
    ) -> WireColorValidationResult:
        """Ask for an explicit, manual colour opinion around one guided wire.

        The model receives the raw camera view, connection context, and tight
        crops around both expected pins.  It may abstain with ``unknown``;
        this result never changes insertion or electrical verification.
        """
        if self.provider is None:
            return WireColorValidationResult(
                False, None, None, "vlm_not_configured", 0
            )
        system = (
            "Return ONLY one JSON object with exactly these fields: "
            "schema_version='1.0', authority='visual_advisory', board_color, "
            "component_color, same_color, confidence, board_evidence, "
            "component_evidence, note. The only allowed colours are red, orange, "
            "brown, yellow, green, blue, purple, and unknown. "
            "The image contains four raw-camera panels ordered LEFT to RIGHT: "
            "the full camera frame, connection context, a tight UNO Q target crop, "
            "and a tight Sensor target crop. Inspect only coloured insulation "
            "outside the black Dupont housings. Ignore black connector plastic, "
            "PCB colour, desk surface, shadows, and frontend UI. "
            "Use unknown and same_color='unknown' when either line colour is not "
            "clear. This is visual colour evidence only: never claim the wire is "
            "connected, inserted, electrically continuous, or safe."
        )
        prompt = (
            f"Expected UNO Q pin: {board_pin}. Expected Sensor pin: {component_pin}. "
            "Identify the visible insulation colour at each endpoint, then say "
            "whether the two colours visibly match."
        )
        last_raw: str | None = None
        last_error = "vlm_failed"
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                complete_structured = getattr(self.provider, "complete_structured", None)
                complete_schema = getattr(self.provider, "complete_schema", None)
                if callable(complete_schema):
                    raw = complete_schema(
                        system,
                        prompt,
                        image_b64,
                        self.timeout_s,
                        WireColorUnderstanding.model_json_schema(),
                    )
                elif callable(complete_structured):
                    raw = complete_structured(system, prompt, image_b64, self.timeout_s)
                else:
                    raw = self.provider.complete(
                        system + "\n" + prompt, image_b64, self.timeout_s
                    )
                last_raw = raw
                checked = self.validate_wire_color(raw)
                checked.attempts = attempt
                if checked.ok:
                    return checked
                last_error = checked.error or last_error
            except Exception as exc:
                last_error = f"provider_error: {exc}"
        return WireColorValidationResult(False, None, last_raw, last_error, attempts)


class OllamaOpenAIProvider:
    """Small stdlib-only adapter for Ollama's OpenAI-compatible endpoint."""

    def __init__(self, endpoint: str, model: str) -> None:
        openai_base = endpoint.rstrip("/")
        self.endpoint = openai_base + "/chat/completions"
        native_base = openai_base[:-3] if openai_base.endswith("/v1") else openai_base
        self.native_endpoint = native_base.rstrip("/") + "/api/chat"
        self.model = model

    def complete(self, prompt: str, image_b64: str | None, timeout_s: float) -> str:
        system = (
            "Return ONLY JSON matching the Board Vision scene-understanding schema. "
            "Use null/unknown and uncertain_items when evidence is insufficient. "
            "Never claim electrical safety or override geometric detection."
        )
        return self.complete_structured(system, prompt, image_b64, timeout_s)

    def complete_structured(
        self,
        system: str,
        prompt: str,
        image_b64: str | None,
        timeout_s: float,
    ) -> str:
        user_content: object = prompt
        if image_b64:
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 300,
            # Ollama's OpenAI-compatible endpoint accepts this field for
            # thinking-capable models. Connector classification benefits from
            # bounded deterministic output, not a long reasoning trace.
            "reasoning_effort": "none",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            self.endpoint, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout_s) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        message = parsed["choices"][0]["message"]
        # Current Ollama thinking-capable VLMs may place a bounded structured
        # response in ``reasoning`` while returning an empty ``content`` even
        # with reasoning_effort="none". Both fields are provider output; the
        # strict Pydantic contract still validates every accepted byte.
        content = message.get("content") or message.get("reasoning") or ""
        return str(content)

    def complete_schema(
        self,
        system: str,
        prompt: str,
        image_b64: str | None,
        timeout_s: float,
        schema: dict,
    ) -> str:
        """Use Ollama's native structured-output path for strict VLM results.

        The native API accepts a full JSON Schema in ``format`` and base64
        images in ``messages[].images``.  This is more reliable than asking a
        vision model to imitate numeric confidence fields in plain JSON mode.
        """
        schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        user_message: dict[str, object] = {
            "role": "user",
            "content": prompt + "\nReturn JSON matching this schema exactly:\n" + schema_text,
        }
        if image_b64:
            user_message["images"] = [image_b64]
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {"temperature": 0, "num_predict": 300},
            "messages": [
                {"role": "system", "content": system},
                user_message,
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib_request.Request(
            self.native_endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=timeout_s) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        message = parsed["message"]
        content = message.get("content") or message.get("thinking") or ""
        return str(content)
