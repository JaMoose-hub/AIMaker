"""Create and install component-model ONNX + JSON sidecar packages."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any


def manifest_path_for(model_path: Path | str) -> Path:
    return Path(model_path).with_suffix(".json")


def write_model_manifest(model_path: Path | str, payload: dict[str, Any]) -> Path:
    path = manifest_path_for(model_path)
    content = dict(payload)
    content.setdefault("schema_version", 1)
    content.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    content["model_file"] = Path(model_path).name
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def load_model_manifest(model_path: Path | str) -> dict[str, Any]:
    path = manifest_path_for(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"component model manifest not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("task") != "segment":
        raise ValueError("Board Vision component runtime currently accepts segment models only")
    names = payload.get("class_names")
    if not isinstance(names, list) or not names or any(not str(name).strip() for name in names):
        raise ValueError("component model manifest has invalid class_names")
    return payload


def install_runtime_package(
    source_model: Path | str,
    target_model: Path | str,
) -> dict[str, Any]:
    source = Path(source_model).resolve()
    target = Path(target_model).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"trained ONNX model not found: {source}")
    manifest = load_model_manifest(source)
    source_manifest = manifest_path_for(source)
    target_manifest = manifest_path_for(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    backup_dir = None
    if target.exists() or target_manifest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = target.parent / "backups" / "component-segmentation" / stamp
        backup_dir.mkdir(parents=True, exist_ok=False)
        if target.exists():
            shutil.copy2(target, backup_dir / target.name)
        if target_manifest.exists():
            shutil.copy2(target_manifest, backup_dir / target_manifest.name)

    temporary_model = target.with_suffix(target.suffix + ".tmp")
    temporary_manifest = target_manifest.with_suffix(target_manifest.suffix + ".tmp")
    shutil.copy2(source, temporary_model)
    shutil.copy2(source_manifest, temporary_manifest)
    temporary_model.replace(target)
    temporary_manifest.replace(target_manifest)
    return {
        "installed_model": str(target),
        "installed_manifest": str(target_manifest),
        "backup_dir": None if backup_dir is None else str(backup_dir),
        "class_names": manifest["class_names"],
    }

