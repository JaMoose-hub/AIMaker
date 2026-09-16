from __future__ import annotations

import json
from pathlib import Path

from app.components.models import ComponentSpec
from app.components.availability import RETIRED_COMPONENT_IDS


class ComponentNotFoundError(KeyError):
    pass


class ComponentStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._cache: dict[str, ComponentSpec] = {}

    def _path(self, component_id: str) -> Path:
        if component_id in RETIRED_COMPONENT_IDS:
            raise ComponentNotFoundError(component_id)
        return self.root / component_id / "component.json"

    def list(self) -> list[ComponentSpec]:
        if not self.root.is_dir():
            return []
        specs: list[ComponentSpec] = []
        for path in sorted(self.root.glob("*/component.json")):
            try:
                specs.append(self.get(path.parent.name))
            except Exception:
                # A malformed optional spec must not take down board vision;
                # the individual lookup still raises a useful error.
                continue
        return specs

    def get(self, component_id: str) -> ComponentSpec:
        path = self._path(component_id)
        if component_id in self._cache:
            return self._cache[component_id]
        if not path.is_file():
            raise ComponentNotFoundError(component_id)
        spec = ComponentSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if spec.id != component_id:
            raise ValueError(f"component id mismatch: directory={component_id!r} file={spec.id!r}")
        self._cache[component_id] = spec
        return spec

    def raw(self, component_id: str) -> dict:
        path = self._path(component_id)
        if not path.is_file():
            raise ComponentNotFoundError(component_id)
        return json.loads(path.read_text(encoding="utf-8"))
