"""Deterministic retirement migration. No AI, deployment, or disk writes."""
import copy
import re

from app.components.availability import RETIRED_COMPONENT_IDS
from app.designs import CATALOG, MODULES, DesignProposal, compile_design, demo_design


def _text(value):
    if not isinstance(value, str):
        return value
    return (re.sub(r"HW[-_ ]?123(?:\s*[、與和＋+]\s*)?", "", value, flags=re.I)
            .replace("超音波、陀螺儀和螢幕", "超音波和螢幕")
            .replace("距離與傾斜", "距離與顯示").replace("距離、姿態與顯示", "距離與顯示")
            .replace("螢幕與姿態功能", "螢幕功能"))


def _clean(value):
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


def migrate_design(design):
    if not design:
        return design
    ids = design.get("component_ids", [])
    if not RETIRED_COMPONENT_IDS.intersection(ids):
        return design
    if design.get("catalog_version") != CATALOG["version"] or set(ids) - set(MODULES) - RETIRED_COMPONENT_IDS:
        raise ValueError("Unrecognized legacy project; original draft has been preserved.")
    remaining = [cid for cid in ids if cid not in RETIRED_COMPONENT_IDS]
    if not remaining:
        return None
    defaults = demo_design(remaining)
    fields = {key: _clean(design.get(key, defaults.get(key))) for key in DesignProposal.model_fields}
    fields["component_ids"] = remaining
    # Remove whole HW-only steps/findings, not just their label. Mixed generic
    # titles are cleaned, while wiring/BOM/code/dependencies are rebuilt below.
    for key in ("features", "instructions", "tests"):
        fields[key] = [_text(item) for item in design.get(key, [])
                       if not re.search(r"HW[-_ ]?123|陀螺儀|六軸|傾斜|姿態", item, re.I)] or defaults[key]
    if re.search(r"hw[-_ ]?123|陀螺儀|傾斜|姿態", design.get("logic", ""), re.I):
        fields["logic"] = defaults["logic"]
    result = compile_design(DesignProposal.model_validate(fields), _text(design.get("prompt", "")),
                            source=design.get("source", "demo"), current=design)
    # An old assembly image still depicts the retired part. Never silently
    # relabel that image or send a paid image-generation request during migration.
    if design.get("image") or design.get("image_required"):
        result.update(image_required=True, image_error="零件清單已更新；請重新產生組裝圖片。")
    return result


def migrate_maker_state(state):
    result = copy.deepcopy(state)
    old = state.get("design")
    result["design"] = migrate_design(old)
    result["candidate"] = migrate_design(state.get("candidate"))
    if result["design"] != old:
        result["code"] = result["design"]["code"] if result["design"] else ""
        result["hardware"] = {}
        guide = result.setdefault("guide", {})
        old_ids = old.get("component_ids", [])
        index = guide.get("componentIndex", 0)
        current_id = old_ids[index] if isinstance(index, int) and 0 <= index < len(old_ids) else None
        ids = result["design"]["component_ids"] if result["design"] else []
        guide["componentIndex"] = ids.index(current_id) if current_id in ids else 0
        allowed = {wire["id"] for wire in (result["design"] or {}).get("wiring", [])}
        guide["confirmed"] = {key: value for key, value in guide.get("confirmed", {}).items() if key in allowed}
        guide.update(index=0, phase="prepare", checks=[])
        if not result["design"]:
            result["stage"] = "design"
    result["selected"] = [cid for cid in state.get("selected", []) if cid in MODULES] or list(MODULES)
    result["prompt"] = _text(state.get("prompt", ""))
    result["aiJobId"] = None  # A pre-removal job must not restore the retired design.
    return result
