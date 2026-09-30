"""Validated, immutable diagram data for historical debug conversation cards."""
from copy import deepcopy
import hashlib
import json
import time
import uuid

from app.debug_support import validate_project
from app.designs import MODULES, ROOT, component_spec_path, wiring_for


def resolve_wiring_target(project, target):
    """Resolve only a selected project's canonical wire; never accept model pin IDs."""
    validate_project(project)
    if not isinstance(target, dict) or set(target) - {"component_id", "wire_id"}:
        raise ValueError("invalid_wiring_target")
    cid, wire_id = target.get("component_id"), target.get("wire_id")
    if cid not in project["component_ids"] or not isinstance(wire_id, str):
        raise ValueError("invalid_wiring_target")
    wire = next((w for w in wiring_for(project["component_ids"])
                 if w["componentId"] == cid and w["id"] == wire_id), None)
    selected = next((w for w in project["wiring"] if w["id"] == wire_id and w["componentId"] == cid), None)
    if wire is None or selected is None:
        raise ValueError("invalid_wiring_target")
    return deepcopy(dict(project_id=project["id"], project_revision=project["revision"],
                         catalog_version=project["catalog_version"], profile_versions=project["profile_versions"],
                         component_id=cid, wire_id=wire_id, board_pin=wire["boardPin"],
                         component_pin=wire["componentPin"], connection_kind=wire["connectionKind"]))


def build_diagram_snapshot(project, wiring_target=None):
    """Snapshot all render inputs. Reading a saved result needs no current catalog."""
    validate_project(project)
    resolved = None
    if wiring_target is not None:
        if not isinstance(wiring_target, dict):
            raise ValueError("invalid_wiring_target")
        resolved = resolve_wiring_target(project, {key: wiring_target.get(key) for key in ("component_id", "wire_id")})
        if any(key not in resolved or resolved[key] != value for key, value in wiring_target.items()):
            raise ValueError("invalid_wiring_target")
    board = json.loads((ROOT / "profiles/boards/raspberry-pi-5/board.json").read_text(encoding="utf-8"))
    modules = []
    for cid in project["component_ids"]:
        guide = MODULES[cid]
        raw = (ROOT / "profiles/components" / cid / "vision_profile.json").read_bytes()
        vision = json.loads(raw)
        pins = sorted(vision["pins"], key=lambda pin: pin["x_norm"])
        electrical = json.loads(component_spec_path(cid).read_text(encoding="utf-8"))
        modules.append(dict(id=cid, name=deepcopy(guide["name"]), safety=deepcopy(guide["safety"]),
                            unresolved=deepcopy(guide["unresolved"]), pins=deepcopy(pins),
                            pin_order=[pin["id"] for pin in pins],
                            header_at_top=sum(pin["y_norm"] for pin in pins) / len(pins) < .5,
                            canonical_orientation=vision.get("canonical_orientation", ""),
                            vision_profile_sha256=hashlib.sha256(raw).hexdigest(),
                            variant=guide.get("variant"), electrical_profile=electrical))
    # Board profile carries actual J8 rows and physical numbering, not a separate
    # manually maintained GPIO table. Preserve it even if the renderer changes.
    render = dict(board=dict(id=board["board"]["id"], name=deepcopy(board["board"]["name"]),
                             pins=deepcopy(board["pins"]), numbering="physical",
                             orientation=dict(headers=deepcopy(board.get("headers", [])),
                                              landmarks=deepcopy(board.get("landmarks", [])),
                                              reference=deepcopy(board.get("reference", {})))),
                  modules=modules, catalog_version=project["catalog_version"],
                  profile_versions=deepcopy(project["profile_versions"]))
    design = deepcopy(project)
    # Labels, instructions and connection type come from the validated catalog,
    # never arbitrary strings submitted in a client/model project object.
    design["wiring"] = wiring_for(project["component_ids"])
    return dict(id=uuid.uuid4().hex, created_at=time.time(), schema_version="debug-diagram-v1",
                project_id=project["id"], project_revision=project["revision"],
                target={key: resolved[key] for key in ("component_id", "wire_id")} if resolved else None,
                design=design, render_snapshot=render)
