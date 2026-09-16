from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import yaml


TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from capture_yolo_board_pose import _label  # noqa: E402
from gen_rpi5_pin_table import build as build_rpi5_profile  # noqa: E402
from label_live_board_pose_captures import (  # noqa: E402
    _proposal_geometry_ok,
    _select_evenly,
)
from rpi_40pin_geometry import pin_xy_mm, profile_pin_xy_mm  # noqa: E402
from train_yolo_board_pose import _resolved_data_yaml  # noqa: E402


def test_pose_label_has_one_class_box_and_four_visible_keypoints():
    text = _label(
        [(100.0, 100.0), (500.0, 120.0), (480.0, 400.0), (90.0, 380.0)],
        (640, 480),
    )
    tokens = text.split()
    assert tokens[0] == "0"
    assert len(tokens) == 1 + 4 + 4 * 3
    values = [float(value) for value in tokens[1:]]
    assert all(0.0 <= value <= 1.0 for value in values[:4])
    assert values[4 + 2] == 2.0
    assert values[4 + 5] == 2.0
    assert values[4 + 8] == 2.0
    assert values[4 + 11] == 2.0


def test_training_yaml_resolves_dataset_root_relative_to_source(tmp_path):
    dataset_root = tmp_path / "datasets" / "board-pose"
    source_dir = tmp_path / "training"
    source_dir.mkdir()
    source = source_dir / "board-pose.yaml"
    source.write_text(
        "path: ../datasets/board-pose\ntrain: images/train\nval: images/val\n"
        "kpt_shape: [4, 3]\nnames: {0: arduino-uno-q}\n",
        encoding="utf-8",
    )
    destination = tmp_path / "resolved.yaml"

    _resolved_data_yaml(source, destination)

    payload = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert Path(payload["path"]) == dataset_root.resolve()
    assert payload["kpt_shape"] == [4, 3]


def test_board_video_frame_selector_keeps_first_middle_and_last():
    paths = [Path(f"frame_{index:03d}.jpg") for index in range(9)]

    assert _select_evenly(paths, 3) == [paths[0], paths[4], paths[8]]
    assert _select_evenly(paths, 0) == paths


def test_board_video_prelabel_rejects_inner_collapsed_quad():
    box = (100.0, 100.0, 500.0, 400.0)
    full_board = SimpleNamespace(
        corners_px=np.array(
            [[110.0, 110.0], [490.0, 110.0], [490.0, 390.0], [110.0, 390.0]]
        ),
        box_xyxy=box,
    )
    inner_component = SimpleNamespace(
        corners_px=np.array(
            [[270.0, 220.0], [330.0, 220.0], [330.0, 280.0], [270.0, 280.0]]
        ),
        box_xyxy=box,
    )

    assert _proposal_geometry_ok(full_board, (720, 1280, 3))
    assert not _proposal_geometry_ok(inner_component, (720, 1280, 3))


def test_pi5_generated_profile_keeps_pose_geometry_and_physical_pin_ids_together():
    profile = build_rpi5_profile()

    assert profile["headers"][0]["side"] == "bottom"
    assert len(profile["pins"]) == 40
    for pin in profile["pins"]:
        physical = int(pin["index"])
        expected_x, expected_y = profile_pin_xy_mm(physical)
        assert pin["silkscreen"] == str(physical)
        assert pin["pos_mm"][:2] == [round(expected_x, 3), round(expected_y, 3)]


def test_pi5_physical_pin_one_is_inboard_and_pin_two_is_near_board_edge():
    # Canonical frame: J8 is along the top edge, so smaller y is nearer edge.
    pin1_x, pin1_y = pin_xy_mm(1)
    pin2_x, pin2_y = pin_xy_mm(2)

    assert pin1_x == pin2_x
    assert pin1_y > pin2_y


def test_pi5_profile_keeps_every_odd_pin_inboard_of_its_even_partner():
    # Runtime profile is rotated 180 degrees, putting J8 at the bottom edge;
    # larger y is therefore nearer the edge in this frame.
    for odd_pin in range(1, 40, 2):
        even_pin = odd_pin + 1
        odd_x, odd_y = profile_pin_xy_mm(odd_pin)
        even_x, even_y = profile_pin_xy_mm(even_pin)

        assert odd_x == even_x
        assert odd_y < even_y


def test_pi5_generated_profile_assigns_pin_one_and_two_to_correct_rows():
    profile = build_rpi5_profile()
    pins = {int(pin["index"]): pin for pin in profile["pins"]}

    assert pins[1]["id"] == "3V3_P1"
    assert pins[2]["id"] == "5V_P2"
    assert pins[1]["pos_mm"][0] == pins[2]["pos_mm"][0]
    assert pins[1]["pos_mm"][1] < pins[2]["pos_mm"][1]
