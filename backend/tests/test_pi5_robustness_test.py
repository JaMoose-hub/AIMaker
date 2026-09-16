from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from pi5_robustness_test import (  # noqa: E402
    BACKGROUND_KINDS,
    apply_photometric_stress,
    composite_foreground,
    foreground_mask,
    generate_stress_set,
    metric_summary,
    procedural_background,
    read_pose_label,
)


def _write_pose_fixture(root: Path) -> tuple[Path, bytes]:
    image_dir = root / "images" / "val"
    label_dir = root / "labels" / "val"
    image_dir.mkdir(parents=True)
    label_dir.mkdir(parents=True)
    image = np.full((96, 128, 3), 220, dtype=np.uint8)
    cv2.rectangle(image, (36, 26), (94, 72), (42, 70, 55), -1)
    cv2.line(image, (65, 26), (65, 4), (35, 45, 155), 3, cv2.LINE_AA)
    assert cv2.imwrite(str(image_dir / "board.jpg"), image)
    raw = b"0 0.5078125 0.5104167 0.453125 0.4791667 0.28125 0.2708333 2 0.734375 0.2708333 2 0.734375 0.75 2 0.28125 0.75 2\n"
    (label_dir / "board.txt").write_bytes(raw)
    return root, raw


def test_procedural_backgrounds_are_deterministic_and_distinct():
    images = []
    for kind in BACKGROUND_KINDS:
        first = procedural_background(kind, 90, 120, np.random.default_rng(17))
        second = procedural_background(kind, 90, 120, np.random.default_rng(17))
        assert first.shape == (90, 120, 3)
        assert first.dtype == np.uint8
        assert np.array_equal(first, second)
        images.append(first)

    means = {tuple(np.rint(image.mean(axis=(0, 1))).astype(int)) for image in images}
    assert len(means) == len(BACKGROUND_KINDS)


def test_composite_adds_feathered_directional_shadow_without_moving_foreground():
    foreground = np.full((80, 100, 3), 210, dtype=np.uint8)
    foreground[25:60, 30:72] = (25, 70, 35)
    mask = np.zeros((80, 100), dtype=np.uint8)
    mask[25:60, 30:72] = 255
    background = np.full_like(foreground, (40, 45, 50))

    result, params = composite_foreground(
        foreground, mask, background, np.random.default_rng(4)
    )

    assert np.linalg.norm(result[40, 50].astype(float) - foreground[40, 50]) < 2
    assert np.linalg.norm(result[0, 0].astype(float) - background[0, 0]) < 2
    assert params["shadow_dx"] != 0 or params["shadow_dy"] != 0
    assert 0.8 <= params["edge_feather_sigma"] <= 2.2


def test_auto_mask_keeps_the_inside_of_a_hand_touching_the_board(tmp_path):
    image = np.full((120, 160, 3), (150, 155, 158), dtype=np.uint8)
    cv2.rectangle(image, (55, 38), (112, 88), (35, 85, 52), -1)
    hand = np.array([[5, 45], [62, 47], [72, 62], [59, 85], [3, 103]], np.int32)
    cv2.fillPoly(image, [hand], (145, 178, 224), cv2.LINE_AA)
    label_path = tmp_path / "pose.txt"
    label_path.write_text(
        "0 0.521875 0.525 0.35625 0.416667 "
        "0.34375 0.316667 2 0.7 0.316667 2 "
        "0.7 0.733333 2 0.34375 0.733333 2\n",
        encoding="utf-8",
    )
    label = read_pose_label(label_path)
    assert label is not None

    mask, report = foreground_mask(image, label, mode="auto")

    assert mask[68, 30] == 255
    assert report["board_coverage"] >= 0.98


def test_auto_mask_excludes_a_distant_non_skin_object(tmp_path):
    image = np.full((160, 240, 3), (150, 155, 158), dtype=np.uint8)
    cv2.rectangle(image, (90, 70), (150, 120), (35, 85, 52), -1)
    cv2.rectangle(image, (0, 0), (239, 24), (10, 10, 10), -1)
    label_path = tmp_path / "pose.txt"
    label_path.write_text(
        "0 0.5 0.59375 0.25 0.3125 "
        "0.375 0.4375 2 0.625 0.4375 2 "
        "0.625 0.75 2 0.375 0.75 2\n",
        encoding="utf-8",
    )
    label = read_pose_label(label_path)
    assert label is not None

    mask, report = foreground_mask(image, label, mode="auto")

    assert mask[95, 120] == 255
    assert mask[10, 120] == 0
    assert report["board_coverage"] >= 0.98


def test_board_hand_mask_keeps_board_and_touching_hand_but_not_distant_object(tmp_path):
    image = np.full((160, 240, 3), (150, 155, 158), dtype=np.uint8)
    cv2.rectangle(image, (90, 70), (150, 120), (35, 85, 52), -1)
    hand = np.array([[25, 72], [94, 75], [110, 95], [92, 125], [20, 135]], np.int32)
    cv2.fillPoly(image, [hand], (145, 178, 224), cv2.LINE_AA)
    cv2.rectangle(image, (0, 0), (239, 24), (10, 10, 10), -1)
    label_path = tmp_path / "pose.txt"
    label_path.write_text(
        "0 0.5 0.59375 0.25 0.3125 "
        "0.375 0.4375 2 0.625 0.4375 2 "
        "0.625 0.75 2 0.375 0.75 2\n",
        encoding="utf-8",
    )
    label = read_pose_label(label_path)
    assert label is not None

    mask, report = foreground_mask(image, label, mode="board-hand")

    assert mask[95, 120] == 255
    assert mask[100, 50] == 255
    assert mask[10, 120] == 0
    assert report["source"] == "board_polygon_plus_touching_skin"


def test_pose_only_mask_uses_reviewed_board_and_j8_points(tmp_path):
    image = np.full((160, 240, 3), (150, 155, 158), dtype=np.uint8)
    label_path = tmp_path / "pose.txt"
    label_path.write_text(
        "0 0.5 0.59375 0.25 0.3125 "
        "0.375 0.4375 2 0.625 0.4375 2 "
        "0.625 0.75 2 0.375 0.75 2 "
        "0.42 0.72 2 0.45 0.72 2 0.55 0.72 2 0.58 0.72 2\n",
        encoding="utf-8",
    )
    label = read_pose_label(label_path)
    assert label is not None

    mask, report = foreground_mask(image, label, mode="pose-only")

    assert mask[95, 120] == 255
    assert mask[10, 120] == 0
    assert mask[145, 20] == 0
    assert report["source"] == "reviewed_board_and_j8_pose_polygon"


def test_photometric_stress_is_reproducible_and_within_requested_ranges():
    image = np.full((72, 96, 3), 130, dtype=np.uint8)
    first_bytes, first = apply_photometric_stress(image, np.random.default_rng(9))
    second_bytes, second = apply_photometric_stress(image, np.random.default_rng(9))

    assert first_bytes == second_bytes
    assert first == second
    assert 0.65 <= first["gamma"] <= 1.45
    assert 0.70 <= first["exposure"] <= 1.30
    assert 58 <= first["jpeg_quality"] <= 95
    assert first["local_shadow"]["shape"] == "soft_hand"
    assert 3 <= first["local_shadow"]["finger_count"] <= 5
    decoded = cv2.imdecode(np.frombuffer(first_bytes, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == image.shape


def test_photometric_stress_can_balance_a_requested_color_cast():
    image = np.full((72, 96, 3), 130, dtype=np.uint8)

    _, warm = apply_photometric_stress(
        image, np.random.default_rng(4), color_cast_override="warm"
    )
    _, cool = apply_photometric_stress(
        image, np.random.default_rng(4), color_cast_override="cool"
    )

    assert warm["color_cast"] == "warm"
    assert warm["bgr_gains"][2] > warm["bgr_gains"][0]
    assert cool["color_cast"] == "cool"
    assert cool["bgr_gains"][0] > cool["bgr_gains"][2]


def test_generation_copies_pose_labels_and_writes_reviewable_masks(tmp_path):
    dataset, raw_label = _write_pose_fixture(tmp_path / "dataset")
    output = tmp_path / "stress"

    manifest = generate_stress_set(
        dataset=dataset,
        split="val",
        output=output,
        variants=2,
        seed=22,
        foreground_mode="auto",
    )

    assert len(manifest) == 2
    assert (output / "manifest.jsonl").read_text(encoding="utf-8").count("\n") == 2
    for item in manifest:
        assert Path(item["generated_image"]).is_file()
        assert Path(item["generated_label"]).read_bytes() == raw_label
        assert Path(item["generated_mask"]).is_file()
        assert item["mask"]["board_coverage"] >= 0.98
        assert item["mask"]["warnings"] == ["auto_mask_requires_visual_review"]


def test_metric_summary_keeps_detection_and_keypoint_error_separate():
    summary = metric_summary(
        [
            {
                "positive": True,
                "detected": True,
                "errors_px": [2.0, 4.0],
                "errors_diagonal": [0.02, 0.04],
            },
            {"positive": True, "detected": False},
            {"positive": False, "detected": True},
        ]
    )

    assert summary["detection_rate"] == 0.5
    assert summary["false_positive_rate"] == 1.0
    assert summary["keypoint_error_px"]["median"] == 3.0
    assert summary["keypoint_error_board_diagonal"]["p95"] > 0.03
