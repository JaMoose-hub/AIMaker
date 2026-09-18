"""Deterministic catalog migrations. No AI, deployment, or disk writes."""
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
    retired = bool(RETIRED_COMPONENT_IDS.intersection(ids))
    voltage_update = design.get("catalog_version") == "1"
    display_update = design.get("catalog_version") in {"1", "2"} and "mrd-tf240-8p-cs" in ids
    if not retired and design.get("catalog_version") == CATALOG["version"]:
        return design
    if (design.get("catalog_version") not in {"1", "2", CATALOG["version"]}
            or set(ids) - set(MODULES) - RETIRED_COMPONENT_IDS):
        raise ValueError("Unrecognized legacy project; original draft has been preserved.")
    remaining = [cid for cid in ids if cid not in RETIRED_COMPONENT_IDS]
    if not remaining:
        return None
    defaults = demo_design(remaining)
    clean = _clean if retired else copy.deepcopy
    fields = {key: clean(design.get(key, defaults.get(key))) for key in DesignProposal.model_fields}
    fields["component_ids"] = remaining
    # Remove whole HW-only steps/findings, not just their label. Mixed generic
    # titles are cleaned, while wiring/BOM/code/dependencies are rebuilt below.
    for key in (("features", "instructions", "tests") if retired else ()):
        fields[key] = [_text(item) for item in design.get(key, [])
                       if not re.search(r"HW[-_ ]?123|陀螺儀|六軸|傾斜|姿態", item, re.I)] or defaults[key]
    if retired and re.search(r"hw[-_ ]?123|陀螺儀|傾斜|姿態", design.get("logic", ""), re.I):
        fields["logic"] = defaults["logic"]
    if voltage_update and "hc-sr04" in remaining:
        # Old free-form assembly steps may still mandate 5V or a divider.
        # Rebuild instructions from the selected variant, retaining the original
        # complete project in the browser's pre-migration backup.
        fields["instructions"] = defaults["instructions"]
        for key in ("summary", "features", "tests"):
            def update_text(text):
                if re.search(r"330\s*[ΩΩ]|470\s*[ΩΩ]|分壓|voltage divider|5\s*V", text, re.I):
                    return MODULES["hc-sr04"]["safety"]["zh-TW"]
                return re.sub(r"HC-SR04(?!\+)", "HC-SR04+", text, flags=re.I)
            fields[key] = ([update_text(t) for t in fields[key]] if isinstance(fields[key], list)
                           else update_text(fields[key]))
    if display_update:
        fields["instructions"] = defaults["instructions"]
        # Replace obsolete preview-only claims, not custom titles/thresholds or
        # independent project features. The complete original is backed up.
        stale = r"(?:TFT|螢幕|供電|背光|驅動|未知規格).*(?:未核實|未確認|待確認|須先確認|禁止上電|不會上電)"
        if re.search(stale, fields["summary"]):
            fields["summary"] = defaults["summary"]
        fields["features"] = [item for item in fields["features"] if not re.search(stale, item)]
        fields["features"] = list(dict.fromkeys(fields["features"] + ["ILI9341 RGB 色塊與文字測試"]))[:12]
        fields["tests"] = list(dict.fromkeys(
            [item for item in fields["tests"] if not re.search(stale, item)] + defaults["tests"]))[:15]
    result = compile_design(DesignProposal.model_validate(fields), clean(design.get("prompt", "")),
                            source=design.get("source", "demo"), current=design)
    # An old assembly image still depicts the retired part. Never silently
    # relabel that image or send a paid image-generation request during migration.
    if retired and (design.get("image") or design.get("image_required")):
        result.update(image_required=True, image_error="零件清單已更新；請重新產生組裝圖片。")
    elif not retired:
        for key in ("image", "image_required", "image_error", "generation"):
            if key in design:
                result[key] = copy.deepcopy(design[key])
    return result


def migrate_maker_state(state):
    result = copy.deepcopy(state)
    old = state.get("design")
    result["design"] = migrate_design(old)
    result["candidate"] = migrate_design(state.get("candidate"))
    if result["design"] != old:
        user_edited = state.get("code", "") != old.get("code", "")
        retired = bool(RETIRED_COMPONENT_IDS.intersection(old.get("component_ids", [])))
        if not user_edited or retired:
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
        if old.get("catalog_version") != CATALOG["version"]:
            def signature(wire):
                return "|".join(wire.get(key, "") for key in ("componentId", "componentPin", "boardPin", "connectionKind"))
            old_wires = {wire["id"]: signature(wire) for wire in old.get("wiring", [])}
            new_wires = {wire["id"]: signature(wire) for wire in (result["design"] or {}).get("wiring", [])}
            guide["confirmed"] = {key: record for key, record in guide["confirmed"].items()
                                  if old_wires.get(key) == new_wires.get(key)
                                  and record.get("signature") == new_wires.get(key)}
        guide.update(index=0, phase="prepare", checks=[])
        if not result["design"]:
            result["stage"] = "design"
    result["selected"] = [cid for cid in state.get("selected", []) if cid in MODULES] or list(MODULES)
    if RETIRED_COMPONENT_IDS.intersection(state.get("selected", [])):
        result["prompt"] = _text(state.get("prompt", ""))
    result["aiJobId"] = None  # A pre-removal job must not restore the retired design.
    return result
