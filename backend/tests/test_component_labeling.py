from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from component_labeling import (  # noqa: E402
    Annotation,
    ComponentLabelDataset,
    annotations_from_ultralytics_result,
    create_component_dataset,
    import_images,
    load_yolo_annotations,
    save_yolo_annotations,
)


def _image(path: Path, color: tuple[int, int, int] = (20, 80, 140)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(color) * 16)
    return path


def test_segment_annotations_round_trip_and_preserve_first_backup(tmp_path: Path):
    label = tmp_path / "labels" / "sample.txt"
    backup = tmp_path / "backup" / "sample.txt"
    original = "0 0.1 0.1 0.8 0.1 0.7 0.9\n"
    label.parent.mkdir(parents=True)
    label.write_text(original, encoding="utf-8")

    first = [Annotation(1, [(0.2, 0.2), (0.9, 0.2), (0.8, 0.8)])]
    save_yolo_annotations(label, first, task="segment", backup_path=backup)
    loaded = load_yolo_annotations(label, task="segment", class_count=2)

    assert loaded[0].class_id == 1
    assert loaded[0].points == pytest.approx(first[0].points)
    assert backup.read_text(encoding="utf-8") == original

    save_yolo_annotations(
        label,
        [Annotation(0, [(0.3, 0.3), (0.6, 0.3), (0.6, 0.6)])],
        task="segment",
        backup_path=backup,
    )
    assert backup.read_text(encoding="utf-8") == original


def test_detection_annotations_round_trip_as_rectangles(tmp_path: Path):
    label = tmp_path / "sample.txt"
    annotation = Annotation(0, [(0.1, 0.2), (0.7, 0.2), (0.7, 0.8), (0.1, 0.8)])

    save_yolo_annotations(label, [annotation], task="detect")
    loaded = load_yolo_annotations(label, task="detect", class_count=1)

    assert np.allclose(loaded[0].points, annotation.points)
    assert len(label.read_text(encoding="utf-8").split()) == 5


def test_dataset_tracks_unlabeled_auto_pending_and_reviewed(tmp_path: Path):
    data = create_component_dataset(tmp_path / "dataset", ["GPIO", "USB-C"])
    image_root = tmp_path / "dataset" / "images" / "train"
    first = _image(image_root / "first.jpg")
    _image(image_root / "second.jpg", (80, 20, 140))
    dataset = ComponentLabelDataset(data)

    assert dataset.task == "segment"
    assert dataset.progress("train") == {
        "total": 2,
        "labeled": 0,
        "reviewed": 0,
        "auto_pending": 0,
        "unlabeled": 2,
    }

    annotation = Annotation(0, [(0.1, 0.1), (0.8, 0.1), (0.8, 0.8)])
    dataset.save(first, "train", [annotation], status="auto_pending", model="model.pt")
    assert dataset.progress("train")["auto_pending"] == 1
    assert dataset.progress("train")["labeled"] == 1

    dataset.save(first, "train", [annotation], status="reviewed")
    progress = dataset.progress("train")
    assert progress["reviewed"] == 1
    assert progress["auto_pending"] == 0
    assert dataset.review.records["train/first.jpg"]["status"] == "reviewed"


def test_import_images_uses_unique_names_without_modifying_sources(tmp_path: Path):
    source = _image(tmp_path / "source" / "part.jpg")
    destination = tmp_path / "dataset" / "images" / "train"

    copied = import_images([source, source], destination)

    assert [path.name for path in copied] == ["part.jpg", "part-0001.jpg"]
    assert source.is_file()
    assert copied[0].read_bytes() == source.read_bytes()


class _Tensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values


def test_ultralytics_predictions_map_by_class_name_and_skip_unknown_classes():
    boxes = SimpleNamespace(
        cls=_Tensor([0, 1]),
        conf=_Tensor([0.91, 0.72]),
        xywhn=_Tensor([[0.5, 0.5, 0.4, 0.2], [0.3, 0.3, 0.1, 0.1]]),
    )
    masks = SimpleNamespace(
        xyn=[
            np.asarray([[0.1, 0.2], [0.8, 0.2], [0.7, 0.9]], dtype=np.float32),
            np.asarray([[0.2, 0.2], [0.4, 0.2], [0.3, 0.4]], dtype=np.float32),
        ]
    )
    result = SimpleNamespace(
        names={0: "GPIO", 1: "ModelOnlyClass"},
        boxes=boxes,
        masks=masks,
    )

    annotations, skipped = annotations_from_ultralytics_result(
        result, ["CPU", "gpio"], task="segment"
    )

    assert len(annotations) == 1
    assert annotations[0].class_id == 1
    assert annotations[0].confidence == pytest.approx(0.91)
    assert np.allclose(annotations[0].points, [(0.1, 0.2), (0.8, 0.2), (0.7, 0.9)])
    assert skipped == ["ModelOnlyClass"]


def test_created_detection_dataset_reopens_with_declared_task(tmp_path: Path):
    data = create_component_dataset(tmp_path / "detect", ["GPIO"], task="detect")

    dataset = ComponentLabelDataset(data)

    assert dataset.task == "detect"
    assert dataset.image_roots["train"] == tmp_path / "detect" / "images" / "train"
