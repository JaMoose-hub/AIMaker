from __future__ import annotations

from pathlib import Path
import sys

import cv2
import numpy as np


TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from capture_pi5_occlusion_cases import CaptureSessionWriter  # noqa: E402
from pi5_occlusion_policy import hard_case_reasons, pin_motion_in_pitch  # noqa: E402


def _message(*, confidence=0.92, tracking="locked", x_offset=0.0, stability="stable"):
    return {
        "type": "detection",
        "board_id": "raspberry-pi-5",
        "runtime_revision": 1,
        "tracking": tracking,
        "confidence": confidence,
        "geometry": {"pitch_px": 10.0},
        "pose_landmarks_visible": 4,
        "pose_quality": {"stability": stability, "visible_fraction": 1.0},
        "pins": [
            {"id": f"GPIO_P{index}", "x": index * 10.0 + x_offset, "y": 20.0, "v": True}
            for index in range(1, 9)
        ],
    }


def test_occlusion_and_jump_hold_are_hard_examples():
    previous = _message()

    assert "occlusion_hold" in hard_case_reasons(
        previous, _message(stability="occlusion_hold")
    )
    assert "jump_hold" in hard_case_reasons(previous, _message(stability="jump_hold"))


def test_confidence_loss_tracking_loss_and_visibility_are_explained():
    previous = _message(confidence=0.95)
    current = _message(confidence=0.62, tracking="searching")
    current["pose_quality"]["visible_fraction"] = 0.5
    current["pose_landmarks_visible"] = 2

    reasons = hard_case_reasons(previous, current)

    assert reasons == ["tracking_lost", "confidence_drop", "visibility_drop", "landmark_drop"]


def test_low_four_point_visibility_baseline_does_not_repeat_false_trigger():
    previous = _message()
    current = _message()
    previous["pose_quality"]["visible_fraction"] = 0.39
    current["pose_quality"]["visible_fraction"] = 0.38

    assert hard_case_reasons(previous, current, min_visible_fraction=0.75) == []

    current["pose_quality"]["visible_fraction"] = 0.15
    assert "visibility_drop" in hard_case_reasons(
        previous,
        current,
        min_visible_fraction=0.75,
        visible_fraction_drop=0.18,
    )


def test_pin_motion_is_normalized_by_pitch_and_normal_pose_does_not_trigger():
    previous = _message(x_offset=0.0)
    moved = _message(x_offset=6.0)

    assert pin_motion_in_pitch(previous, moved) == 0.6
    assert "pin_motion" in hard_case_reasons(previous, moved, motion_pitch=0.45)
    assert hard_case_reasons(previous, _message(x_offset=1.0), motion_pitch=0.45) == []


def test_capture_session_stores_raw_frame_manifest_and_undo_is_recoverable(tmp_path):
    writer = CaptureSessionWriter(tmp_path, "session-one", {"created_at": "now"})
    frame = np.full((24, 32, 3), 127, dtype=np.uint8)
    telemetry = _message(stability="occlusion_hold")

    record = writer.save(
        frame,
        source_kind="manual",
        occluder_label="hand",
        reasons=["hand"],
        telemetry=telemetry,
        telemetry_age_ms=12.0,
        jpeg_quality=95,
    )

    image_path = writer.session_dir / record["image"]
    assert image_path.exists()
    assert cv2.imread(str(image_path)).shape == frame.shape
    assert "browser overlays" in record["notes"]
    assert len(writer.manifest_path.read_text(encoding="utf-8").splitlines()) == 1

    undone = writer.undo_last()

    assert undone == record
    assert not image_path.exists()
    assert any(writer.undo_dir.iterdir())
    assert writer.manifest_path.read_text(encoding="utf-8") == ""
