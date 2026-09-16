from __future__ import annotations

import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
BACKEND = ROOT / "backend"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from component_dataset import audit_component_dataset, normalized_training_yaml  # noqa: E402
from component_model_package import (  # noqa: E402
    install_runtime_package,
    manifest_path_for,
    write_model_manifest,
)
from app.vision.yolo_segmentation import class_names_from_model_manifest  # noqa: E402


SEGMENT_ROW = "0 0.1 0.1 0.8 0.1 0.8 0.8 0.1 0.8\n"


def _dataset(tmp_path: Path, *, roboflow_parent_paths: bool = False) -> Path:
    for split, count in (("train", 20), ("valid", 5), ("test", 2)):
        image_dir = tmp_path / split / "images"
        label_dir = tmp_path / split / "labels"
        image_dir.mkdir(parents=True)
        label_dir.mkdir(parents=True)
        for index in range(count):
            stem = f"{split}-{index:03d}"
            (image_dir / f"{stem}.jpg").write_bytes(f"image-{stem}".encode())
            (label_dir / f"{stem}.txt").write_text(SEGMENT_ROW, encoding="utf-8")
    prefix = "../" if roboflow_parent_paths else ""
    payload = {
        "train": f"{prefix}train/images",
        "val": f"{prefix}valid/images",
        "test": f"{prefix}test/images",
        "names": ["GPIO"],
        "nc": 1,
    }
    data = tmp_path / "data.yaml"
    data.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return data


def test_component_dataset_audit_detects_segment_and_counts_splits(tmp_path):
    report = audit_component_dataset(_dataset(tmp_path))

    assert report["ready_to_train"]
    assert report["task"] == "segment"
    assert report["class_names"] == ["GPIO"]
    assert report["splits"]["train"]["images"] == 20
    assert report["splits"]["val"]["images"] == 5
    assert report["splits"]["test"]["images"] == 2
    assert report["cross_split_duplicate_groups"] == []


def test_component_dataset_supports_roboflow_parent_prefixed_paths(tmp_path):
    report = audit_component_dataset(_dataset(tmp_path, roboflow_parent_paths=True))

    assert report["ready_to_train"]
    assert Path(report["splits"]["train"]["image_root"]) == tmp_path / "train" / "images"


def test_component_dataset_rejects_invalid_coordinates_and_mixed_tasks(tmp_path):
    data = _dataset(tmp_path)
    first = next((tmp_path / "train" / "labels").glob("*.txt"))
    first.write_text("0 0.5 0.5 0.2 0.2\n0 1.2 0.1 0.5 0.5 0.2 0.8\n", encoding="utf-8")

    report = audit_component_dataset(data)

    assert not report["ready_to_train"]
    assert report["task"] == "mixed"
    assert any("coordinates must be" in issue for issue in report["errors"])


def test_normalized_training_yaml_uses_absolute_split_paths(tmp_path):
    report = audit_component_dataset(_dataset(tmp_path))
    destination = tmp_path / "normalized.yaml"

    normalized_training_yaml(report, destination)

    payload = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert Path(payload["train"]).is_absolute()
    assert payload["names"] == {0: "GPIO"}


def test_component_package_install_backs_up_previous_runtime(tmp_path):
    source = tmp_path / "trained.onnx"
    source.write_bytes(b"new-model")
    write_model_manifest(
        source,
        {"task": "segment", "class_names": ["GPIO", "USB-C"], "input_size": 640},
    )
    target = tmp_path / "runtime" / "pi5-components-seg.onnx"
    target.parent.mkdir()
    target.write_bytes(b"old-model")
    manifest_path_for(target).write_text(
        json.dumps({"task": "segment", "class_names": ["old"]}), encoding="utf-8"
    )

    result = install_runtime_package(source, target)

    assert target.read_bytes() == b"new-model"
    assert class_names_from_model_manifest(target, ("fallback",)) == ("GPIO", "USB-C")
    backup_dir = Path(result["backup_dir"])
    assert (backup_dir / target.name).read_bytes() == b"old-model"


def test_component_runtime_uses_fallback_for_missing_or_invalid_manifest(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    fallback = ("CPU", "GPIO")

    assert class_names_from_model_manifest(model, fallback) == fallback
    manifest_path_for(model).write_text("{}", encoding="utf-8")
    assert class_names_from_model_manifest(model, fallback) == fallback
