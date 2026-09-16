"""Retired parts stay on disk for historical replay, never in the live runtime."""
import json
from pathlib import Path

_CATALOG = Path(__file__).resolve().parents[3] / "profiles/component-catalog.json"
RETIRED_COMPONENT_IDS = frozenset(json.loads(_CATALOG.read_text(encoding="utf-8"))["retired_module_ids"])


def retired_target(component_id: str, profile_path: Path) -> bool:
    if component_id in RETIRED_COMPONENT_IDS or profile_path.parent.name in RETIRED_COMPONENT_IDS:
        return True
    # Old single-target configs can label a retired profile as "legacy".
    try:
        return json.loads(profile_path.read_text(encoding="utf-8")).get("component_id") in RETIRED_COMPONENT_IDS
    except (OSError, ValueError):
        return False  # Keep existing missing-profile diagnostics for active parts.
