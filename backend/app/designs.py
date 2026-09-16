"""Validated maker projects. Wiring, dependencies and hardware access are not LLM output."""
from __future__ import annotations

import ast
import copy
import json
import hashlib
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.components.models import ComponentSpec
from app.components.resolver import _pin_matches_role
from app.profiles.models import BoardProfile

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "profiles/component-catalog.json").read_text(encoding="utf-8"))
MODULES = {item["id"]: item for item in CATALOG["modules"]}
ComponentId = Literal["hc-sr04", "mrd-tf240-8p-cs"]


class Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    distance_cm: float = Field(default=20, ge=1, le=400)
    sample_ms: int = Field(default=200, ge=100, le=5000)


class ConceptPreview(BaseModel):
    """Declarative presentation only: never executable HTML, SVG or live readings."""
    model_config = ConfigDict(extra="forbid")
    scene: str = Field(min_length=1, max_length=180)
    interaction: str = Field(min_length=1, max_length=180)
    screen_title: str = Field(min_length=1, max_length=40)
    screen_lines: list[str] = Field(min_length=1, max_length=3)
    accent: Literal["teal", "blue", "amber"] = "teal"
    layout: Literal["console", "tower", "flat"] = "console"


class StructuralPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["wheel", "axle", "standoff", "acrylic-panel", "bracket", "screw"]
    quantity: int = Field(ge=1, le=32)
    purpose: str = Field(min_length=1, max_length=180)


class AssemblyConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=1200)
    parts: list[StructuralPart] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def unique_parts(self):
        if len({p.kind for p in self.parts}) != len(self.parts):
            raise ValueError("Duplicate structural part")
        return self


class DesignProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    summary: str = Field(min_length=1, max_length=2000)
    features: list[str] = Field(min_length=1, max_length=12)
    component_ids: list[ComponentId] = Field(min_length=1, max_length=2)
    parameters: Parameters
    instructions: list[str] = Field(min_length=1, max_length=15)
    tests: list[str] = Field(min_length=1, max_length=15)
    logic: str = Field(min_length=1, max_length=12000)
    preview: ConceptPreview | None = None
    assembly: AssemblyConcept | None = None

    @model_validator(mode="after")
    def unique_modules(self):
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ValueError("Each module may appear only once")
        validate_logic(self.logic)
        return self


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class WorkflowContext(BaseModel):
    stage: Literal["design", "blueprint", "guide", "deploy"] = "design"
    active_wire: str | None = Field(default=None, max_length=150)
    manual_confirmations: int = Field(default=0, ge=0, le=100)
    code_draft: str = Field(default="", max_length=16000)


class AssistantReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=4000)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    component_ids: list[ComponentId] = Field(min_length=1, max_length=2)
    current: dict | None = None
    locale: Literal["zh-TW", "en"] = "zh-TW"
    model: str | None = Field(default=None, min_length=1, max_length=150)
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    expected_output_tokens: int | None = Field(default=None, ge=256, le=128000)
    intent: Literal["design", "ask"] = "design"
    design_mode: Literal["fixed", "free"] = "free"
    conversation: list[ConversationMessage] = Field(default_factory=list, max_length=20)
    workflow: WorkflowContext = Field(default_factory=WorkflowContext)
    generate_image: bool = False  # Legacy API callers can still request text-only proposals.


def proposal_schema(intent="design"):
    schema = (AssistantReply if intent == "ask" else DesignProposal).model_json_schema()
    def strict(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)
    strict(schema)
    return schema


def validate_logic(source: str):
    """Pure formatting/decision function: no independent GPIO or package access."""
    tree = ast.parse(source)
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("logic must contain only def on_sample(readings, settings)")
    fn = tree.body[0]
    if (fn.name != "on_sample" or [a.arg for a in fn.args.args] != ["readings", "settings"]
            or fn.decorator_list or fn.args.defaults or fn.args.posonlyargs or fn.args.kwonlyargs
            or fn.args.vararg or fn.args.kwarg or fn.returns or any(a.annotation for a in fn.args.args)):
        raise ValueError("Expected on_sample(readings, settings) without decorators/defaults")
    forbidden = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef,
                 ast.While, ast.For, ast.With, ast.Lambda, ast.ListComp, ast.DictComp, ast.SetComp,
                 ast.GeneratorExp, ast.Yield, ast.YieldFrom)
    for node in ast.walk(tree):
        if isinstance(node, forbidden):
            raise ValueError("logic must be a pure, non-looping sample formatter")
        if isinstance(node, ast.Name) and (node.id.startswith("_") or node.id in {"open", "exec", "eval", "compile", "globals", "locals", "getattr", "setattr", "PINS", "sensor"}):
            raise ValueError("logic cannot access files, execution tools or hardware")
        if isinstance(node, ast.Attribute) and node.attr not in {"get", "format", "join", "upper", "lower"}:
            raise ValueError("Unsupported attribute in sample formatter")
        if isinstance(node, ast.FunctionDef) and node is not fn:
            raise ValueError("Nested functions are not supported")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in
                {"str", "round", "int", "float", "abs", "min", "max", "bool", "len"}
                or isinstance(node.func, ast.Attribute) and node.func.attr in {"get", "format", "join", "upper", "lower"}):
            raise ValueError("Unsupported function call in sample formatter")


def wiring_for(ids: list[str]) -> list[dict]:
    board = json.loads((ROOT / "profiles/boards/raspberry-pi-5/board.json").read_text(encoding="utf-8"))
    board_model = BoardProfile.model_validate(board)
    pins = {p.id: p for p in board_model.pins}
    occupied = set()
    wiring = []
    for cid in ids:
        module = MODULES[cid]
        component = json.loads((ROOT / f"profiles/components/{cid}/component.json").read_text(encoding="utf-8"))
        spec = ComponentSpec.model_validate(component)
        component_pins = {p.id: p for p in spec.pins}
        for original in module["steps"]:
            step = copy.deepcopy(original)
            pin = step["boardPin"]
            if pin not in pins or step["componentPin"] not in component_pins:
                raise ValueError("Catalog references an unknown pin")
            component_pin = component_pins[step["componentPin"]]
            if step["connectionKind"] == "divider":
                if cid != "hc-sr04" or component_pin.id != "ECHO":
                    raise ValueError("Unsupported divider circuit")
                # This supported topology is shown in both existing guidance and SVG.
                component_pin = component_pin.model_copy(update={"signal_voltage": 5 * 470 / (330 + 470)})
            compatible, reason = _pin_matches_role(component_pin, pins[pin])
            if not compatible:
                raise ValueError(f"{cid}:{component_pin.id} -> {pin}: {reason}")
            spi_role = {"spi_clock": "SCLK", "spi_mosi": "MOSI", "spi_chip_select": "CE0"}.get(component_pin.role)
            if spi_role and not any(cap.type == "spi" and cap.role == spi_role for cap in pins[pin].capabilities):
                raise ValueError(f"{cid}:{component_pin.id} requires SPI role {spi_role}")
            if pin.startswith("GPIO") and pin in occupied:
                raise ValueError(f"Pin conflict: {pin}")
            occupied.add(pin)
            step.update(id=f"{cid}:{step['id']}", componentId=cid)
            wiring.append(step)
    return wiring


def profile_versions(ids):
    paths = {"raspberry-pi-5": ROOT / "profiles/boards/raspberry-pi-5/board.json"}
    paths.update({cid: ROOT / f"profiles/components/{cid}/component.json" for cid in ids})
    result = {}
    for cid, path in paths.items():
        contents = path.read_bytes()
        data = json.loads(contents)
        result[cid] = {"version": data.get("version", data["schema_version"]), "sha256": hashlib.sha256(contents).hexdigest()}
    return result


def render_code(wiring: list[dict], params: dict, logic: str, unresolved: list[str]) -> str:
    pins = {cid: {s["componentPin"]: int(s["boardPin"][4:]) for s in wiring
                  if s["componentId"] == cid and s["boardPin"].startswith("GPIO")}
            for cid in dict.fromkeys(s["componentId"] for s in wiring)}
    preamble = "# Generated by BoardVision. Wiring comes from the shared component catalog.\n"
    preamble += f"PINS = {pins!r}\nSETTINGS = {params!r}\n"
    if unresolved:
        return preamble + "# Preview only. No GPIO is initialized for unresolved hardware.\n" + f"raise RuntimeError({'; '.join(unresolved)!r})\n"
    return preamble + f'''from time import sleep, monotonic
from gpiozero import DistanceSensor
from gpiozero.pins.lgpio import LGPIOFactory

# Keep an invalid/missing echo explicit instead of reprinting a cached average.
class FreshDistanceSensor(DistanceSensor):
    def __init__(self, **kwargs):
        self.latest = None
        super().__init__(**kwargs)

    def _read(self):
        value = super()._read()
        self.latest = (monotonic(), value)
        return value

# The AI function has no GPIO, imports, files or execution tools in its namespace.
namespace = {{"__builtins__": {{"str": str, "round": round, "int": int, "float": float,
    "abs": abs, "min": min, "max": max, "bool": bool, "len": len}}}}
exec({logic!r}, namespace)
with FreshDistanceSensor(echo=PINS["hc-sr04"]["ECHO"], trigger=PINS["hc-sr04"]["TRIG"],
                         queue_len=1, partial=True, max_distance=4, pin_factory=LGPIOFactory()) as sensor:
    while True:
        sample = sensor.latest
        if sample is None or monotonic() - sample[0] > 1 or sample[1] is None or not 0 < sample[1] < 1:
            print("distance_cm=UNAVAILABLE (no fresh echo / out of range)", flush=True)
        else:
            readings = {{"distance_cm": round(sample[1] * sensor.max_distance * 100, 1)}}
            print(namespace["on_sample"](readings, SETTINGS), flush=True)
        sleep(SETTINGS["sample_ms"] / 1000)
'''


def compile_design(proposal: DesignProposal, prompt: str, *, source="ai", current: dict | None = None) -> dict:
    ids = list(proposal.component_ids)
    wiring = wiring_for(ids)
    unresolved = [MODULES[cid]["runtime"]["reason"] for cid in ids if not MODULES[cid]["runtime"]["supported"]]
    params = proposal.parameters.model_dump()
    bom = [{"id": "raspberry-pi-5", "name": "Raspberry Pi 5", "quantity": 1, "price": 2500, "purpose": "控制與執行 / Controller"}]
    bom += [{"id": cid, "name": MODULES[cid]["name"]["zh-TW"], "quantity": 1,
             "price": MODULES[cid]["price"], "purpose": MODULES[cid]["name"]["en"]} for cid in ids]
    bom += [{"id": "breadboard", "name": "麵包板 / Breadboard", "quantity": 1, "price": 50, "purpose": "共地與接線 / Wiring"},
            {"id": "jumper-wires", "name": "杜邦線 / Jumper wires", "quantity": len(wiring) + 3, "price": 2, "purpose": "模組連接 / Connections"}]
    if "hc-sr04" in ids:
        bom += [{"id": f"resistor-{ohms}", "name": f"{ohms}Ω 電阻 / resistor", "quantity": 1, "price": 1, "purpose": "ECHO 分壓保護 / Voltage divider"} for ohms in (330, 470)]
    code = render_code(wiring, params, proposal.logic, unresolved)
    compile(code, "main.py", "exec")
    return {
        "id": str((current or {}).get("id") or uuid4()),
        "revision": int((current or {}).get("revision", 0)) + 1,
        "source": source, "prompt": prompt, "catalog_version": CATALOG["version"],
        "profile_versions": profile_versions(ids),
        **proposal.model_dump(exclude={"logic", "parameters"}), "parameters": params,
        "wiring": wiring, "bom": bom, "code": code, "logic": proposal.logic,
        "unresolved": unresolved,
        "requirements": {"imports": sorted({i for cid in ids for i in MODULES[cid]["runtime"]["imports"]}),
                         "devices": sorted({d for cid in ids for d in MODULES[cid]["runtime"]["devices"]})},
    }


def demo_design(ids=None):
    sensor_only = ids == ["hc-sr04"]
    return compile_design(DesignProposal(
        title="桌上型距離警告器" if sensor_only else "桌上型距離與顯示監測器",
        summary="示範子作品：以 Pi 5 與 HC-SR04 讀取真實距離，每 200 毫秒輸出，低於 20 公分時警告。" if sensor_only else "示範作品：整合距離與顯示。未知規格的模組僅提供設計與接線預覽，不會上電。",
        features=["距離低於門檻時輸出警告", "依模組提供逐腳接線引導"] + ([] if sensor_only else ["螢幕功能須先確認規格"]),
        component_ids=ids or list(MODULES), parameters=Parameters(),
        instructions=["備齊材料並關閉所有電源。", "依 Pin 引導逐線接好，確認共地與分壓。", "檢查執行環境，部署後依測試步驟觀察。"],
        tests=["移動物體，觀察距離是否隨之變化；沒有有效讀值不能算通過。", "將物體移至 20 公分內，確認輸出 WARNING；移遠後確認恢復 OK。" if sensor_only else "TFT 規格未核實時，該功能保持待確認。"],
        logic='def on_sample(readings, settings):\n    distance = readings["distance_cm"]\n    state = "WARNING" if distance < settings["distance_cm"] else "OK"\n    return f"distance_cm={distance} {state}"',
    ), "內建示範作品（非 AI 生成）", source="demo")
