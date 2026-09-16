from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pose_labeling import (  # noqa: E402
    PoseAnnotation,
    PoseKeypoint,
    PoseLabelDataset,
    annotations_from_ultralytics_pose_result,
    box_from_keypoints,
    load_pose_annotations,
    pose_geometry_issues,
    save_pose_annotations,
)
from audit_yolo_pose_dataset import audit as audit_pose_dataset  # noqa: E402
from derive_component_corner_pose_dataset import derive as derive_corner_pose  # noqa: E402


def _annotation(count: int = 4) -> PoseAnnotation:
    base = [(0.2, 0.2), (0.8, 0.2), (0.8, 0.7), (0.2, 0.7)]
    extra = [(0.72, 0.24), (0.76, 0.24), (0.76, 0.66), (0.72, 0.66)]
    points = [PoseKeypoint(x, y, 2) for x, y in (base + extra)[:count]]
    return PoseAnnotation(0, box_from_keypoints(points), points)


def _dataset(tmp_path: Path, *, keypoint_count: int = 4) -> Path:
    root = tmp_path / "pose-data"
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    payload = {
        "path": str(root),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "kpt_shape": [keypoint_count, 3],
        "names": {0: "raspberry-pi-5"},
        "kpt_names": {0: [f"point_{index + 1}" for index in range(keypoint_count)]},
    }
    data = tmp_path / "pose.yaml"
    data.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return data


def test_four_point_pose_round_trip_and_first_edit_backup(tmp_path: Path):
    label = tmp_path / "labels" / "board.txt"
    backup = tmp_path / "backup" / "board.txt"
    label.parent.mkdir(parents=True)
    original = (
        "0 0.5 0.45 0.6 0.5 "
        "0.2 0.2 2 0.8 0.2 2 0.8 0.7 2 0.2 0.7 2\n"
    )
    label.write_text(original, encoding="utf-8")

    loaded = load_pose_annotations(label, class_count=1, keypoint_count=4)
    assert len(loaded) == 1
    assert [point.visibility for point in loaded[0].keypoints] == [2, 2, 2, 2]

    changed = _annotation()
    changed.keypoints[0].x = 0.15
    save_pose_annotations(label, [changed], keypoint_count=4, backup_path=backup)
    reloaded = load_pose_annotations(label, class_count=1, keypoint_count=4)[0]
    assert reloaded.keypoints[0].x == pytest.approx(0.15)
    assert backup.read_text(encoding="utf-8") == original

    changed.keypoints[0].x = 0.12
    save_pose_annotations(label, [changed], keypoint_count=4, backup_path=backup)
    assert backup.read_text(encoding="utf-8") == original


def test_eight_point_pose_preserves_occluded_and_missing_visibility(tmp_path: Path):
    annotation = _annotation(8)
    annotation.keypoints[5].visibility = 1
    annotation.keypoints[7] = PoseKeypoint(0.0, 0.0, 0)
    label = tmp_path / "eight.txt"

    save_pose_annotations(label, [annotation], keypoint_count=8)
    loaded = load_pose_annotations(label, class_count=1, keypoint_count=8)[0]

    assert len(loaded.keypoints) == 8
    assert loaded.keypoints[5].visibility == 1
    assert loaded.keypoints[7].visibility == 0
    assert (loaded.keypoints[7].x, loaded.keypoints[7].y) == (0.0, 0.0)


def test_pose_dataset_reads_keypoint_contract_and_tracks_review(tmp_path: Path):
    data = _dataset(tmp_path)
    root = tmp_path / "pose-data"
    first = root / "images" / "train" / "first.jpg"
    second = root / "images" / "train" / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    dataset = PoseLabelDataset(data)

    assert dataset.dataset_root == root
    assert dataset.keypoint_count == 4
    assert dataset.keypoint_names == ["point_1", "point_2", "point_3", "point_4"]
    assert dataset.progress("train")["unlabeled"] == 2

    dataset.save(first, "train", [_annotation()], status="auto_pending", model="best.pt")
    assert dataset.progress("train")["auto_pending"] == 1
    assert dataset.progress("train")["labeled"] == 1

    dataset.save(first, "train", [_annotation()], status="reviewed")
    progress = dataset.progress("train")
    assert progress["reviewed"] == 1
    assert progress["auto_pending"] == 0
    assert dataset.review.records["train/first.jpg"]["status"] == "reviewed"


def test_pose_audit_require_reviewed_rejects_drafts(tmp_path: Path):
    data = _dataset(tmp_path)
    root = tmp_path / "pose-data"
    image = root / "images" / "train" / "draft.jpg"
    image.write_bytes(b"draft-image")
    dataset = PoseLabelDataset(data)
    dataset.save(image, "train", [_annotation()], status="draft")

    report, issues = audit_pose_dataset(
        data,
        min_train=1,
        min_val=0,
        min_test=0,
        min_negative=0,
        require_reviewed=True,
    )

    assert report["splits"]["train"]["unreviewed"] == 1
    assert report["unreviewed"] == 1
    assert any("not reviewed" in issue for issue in issues)

    dataset.save(image, "train", [_annotation()], status="reviewed")
    report, issues = audit_pose_dataset(
        data,
        min_train=1,
        min_val=0,
        min_test=0,
        min_negative=0,
        require_reviewed=True,
    )
    assert report["unreviewed"] == 0
    assert issues == []


def test_corner_pose_derivation_can_exclude_empty_source_labels(tmp_path: Path):
    data = _dataset(tmp_path, keypoint_count=8)
    root = tmp_path / "pose-data"
    positive = root / "images" / "train" / "positive.jpg"
    negative = root / "images" / "train" / "false-negative.jpg"
    positive.write_bytes(b"positive")
    negative.write_bytes(b"false-negative")
    save_pose_annotations(
        root / "labels" / "train" / "positive.txt",
        [_annotation(8)],
        keypoint_count=8,
    )
    (root / "labels" / "train" / "false-negative.txt").write_text(
        "", encoding="utf-8"
    )

    destination = tmp_path / "corner-pose"
    report = derive_corner_pose(data, destination, positive_only=True)

    assert report["splits"]["train"] == 1
    assert report["skipped_empty"]["train"] == 1
    assert (destination / "images" / "train" / "positive.jpg").is_file()
    assert not (destination / "images" / "train" / "false-negative.jpg").exists()
    fields = (
        destination / "labels" / "train" / "positive.txt"
    ).read_text(encoding="utf-8").split()
    assert len(fields) == 17


def test_geometry_gate_detects_missing_and_crossed_semantic_corners():
    missing = _annotation()
    missing.keypoints[2] = PoseKeypoint(0.0, 0.0, 0)
    assert any("missing keypoints" in issue for issue in pose_geometry_issues(missing))

    crossed = _annotation()
    crossed.keypoints[1], crossed.keypoints[2] = (
        crossed.keypoints[2],
        crossed.keypoints[1],
    )
    assert any("crossed" in issue for issue in pose_geometry_issues(crossed))
    assert pose_geometry_issues(_annotation()) == []


class _Tensor:
    def __init__(self, values):
        self.values = values

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.values


def test_pose_model_predictions_map_names_points_and_low_confidence_visibility():
    result = SimpleNamespace(
        names={0: "raspberry-pi-5", 1: "unknown-board"},
        boxes=SimpleNamespace(
            cls=_Tensor([0, 1]),
            conf=_Tensor([0.93, 0.72]),
            xywhn=_Tensor([[0.5, 0.45, 0.6, 0.5], [0.5, 0.5, 0.2, 0.2]]),
        ),
        keypoints=SimpleNamespace(
            xyn=_Tensor(
                [
                    [[0.2, 0.2], [0.8, 0.2], [0.8, 0.7], [0.2, 0.7]],
                    [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]],
                ]
            ),
            conf=_Tensor([[0.9, 0.8, 0.2, 0.7], [0.8, 0.8, 0.8, 0.8]]),
        ),
    )

    annotations, skipped = annotations_from_ultralytics_pose_result(
        result,
        ["raspberry-pi-5"],
        keypoint_count=4,
        keypoint_threshold=0.25,
    )

    assert len(annotations) == 1
    assert annotations[0].confidence == pytest.approx(0.93)
    assert [point.visibility for point in annotations[0].keypoints] == [2, 2, 1, 2]
    assert skipped == ["unknown-board"]


def test_model_prediction_with_wrong_keypoint_shape_is_not_saved_as_pose():
    result = SimpleNamespace(
        names={0: "raspberry-pi-5"},
        boxes=SimpleNamespace(
            cls=_Tensor([0]), conf=_Tensor([0.9]), xywhn=_Tensor([[0.5, 0.5, 0.5, 0.5]])
        ),
        keypoints=SimpleNamespace(
            xyn=_Tensor([[[0.2, 0.2], [0.8, 0.2], [0.8, 0.8]]]),
            conf=_Tensor([[0.9, 0.9, 0.9]]),
        ),
    )

    annotations, skipped = annotations_from_ultralytics_pose_result(
        result, ["raspberry-pi-5"], keypoint_count=4
    )

    assert annotations == []
    assert skipped == ["raspberry-pi-5:keypoint-count"]
