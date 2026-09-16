"""Small contract tests for the offline accuracy tools.

These tests do not require a camera or a checked-in dataset.  They protect
the two easy-to-miss integrity rules: recorded pose must preserve pin metadata
and aggregate recall must count every frame in its denominator.
"""
from __future__ import annotations

import sys
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(_ROOT / "tools"))

from app.vision.interface import PinDetection  # noqa: E402
from capture_groundtruth import _detection_record, _scale_report  # noqa: E402
from calibrate_reference import filter_reference_features  # noqa: E402
import replay_accuracy as replay_module  # noqa: E402
from replay_accuracy import (  # noqa: E402
    _aggregate,
    _check_baseline,
    _pins_from_pose_record,
    _replay_config,
)
from profile_preflight import _scale_status, inspect_profile  # noqa: E402
from app.vision.interface import DetectionResult  # noqa: E402
from app.vision.wire_tracer import (  # noqa: E402
    WireEndpoint,
    WireInstance,
    WireTraceResult,
)


def test_detection_record_keeps_pose_and_pin_lattice_metadata():
    result = SimpleNamespace(
        tracking="locked",
        confidence=0.91,
        rvec=[1.0, 2.0, 3.0],
        tvec=[4.0, 5.0, 6.0],
        pins=[PinDetection("D7", 10.5, 20.5, 0.8, True, "JDIGITAL", 7)],
        outline_px=[(1.0, 2.0), (3.0, 4.0)],
        wire_exclusion_px=None,
    )
    record = _detection_record(result)
    assert record["pose_mode"] == "recorded"
    assert record["rvec"] == [1.0, 2.0, 3.0]
    assert record["pins"][0]["header"] == "JDIGITAL"
    assert record["pins"][0]["index"] == 7


def test_capture_scale_report_marks_physical_gate_quality():
    assert _scale_report(15.0)["status"] == "reject"
    assert _scale_report(19.0)["status"] == "below_recommended"
    report = _scale_report(22.86)
    assert report["status"] == "ok"
    assert report["px_per_mm"] == pytest.approx(9.0, abs=0.01)


def test_cli_reference_cache_excludes_background_features():
    features = {
        "xy_mm": np.array([[-10.0, 10.0], [10.0, 10.0], [70.0, 53.0], [100.0, 100.0]]),
        "desc": np.arange(4 * 32, dtype=np.uint8).reshape(4, 32),
        "orb_pts": np.arange(8, dtype=np.float32).reshape(4, 2),
    }
    filtered, count = filter_reference_features(features, (68.58, 53.34))
    assert count == 2
    assert len(filtered["xy_mm"]) == 2
    assert len(filtered["desc"]) == 2
    assert len(filtered["orb_pts"]) == 2


def test_profile_preflight_requires_camera_and_scale_evidence():
    assert _scale_status(10.0) == "reject"
    report = inspect_profile(FIXTURES / "mini-board" / "board.json")
    assert report["scale_status"] == "ok"
    assert report["camera_calibrated"] is False
    assert report["camera_quality_ok"] is False
    assert report["physical_gate_ready"] is False


def test_profile_preflight_rejects_camera_without_quality_evidence(tmp_path):
    profile_dir = tmp_path / "mini-board"
    shutil.copytree(FIXTURES / "mini-board", profile_dir)
    (profile_dir / "camera.json").write_text(
        json.dumps({
            "fx": 600.0, "fy": 600.0, "cx": 320.0, "cy": 240.0,
            "dist": [0.0] * 5,
        }),
        encoding="utf-8",
    )
    report = inspect_profile(profile_dir / "board.json")
    assert report["camera_calibrated"] is True
    assert report["camera_quality_ok"] is False
    assert report["camera_quality_status"] is None
    assert any("quality_status" in warning for warning in report["warnings"])
    assert report["physical_gate_ready"] is False


def test_recorded_pins_restore_profile_metadata():
    reference = [PinDetection("D7", 0.0, 0.0, 1.0, True, "JDIGITAL", 7)]
    pins = _pins_from_pose_record(
        {"pins": [{"id": "D7", "x": 11, "y": 22, "c": 0.7, "v": True}]},
        reference,
    )
    assert len(pins) == 1
    assert (pins[0].x, pins[0].y) == (11.0, 22.0)
    assert pins[0].header == "JDIGITAL"
    assert pins[0].index == 7


def test_aggregate_recall_counts_expected_endpoints_per_frame():
    report = {
        "frames": 3,
        "truth_pin_endpoints": 6,
        "matched_truth_endpoints": 4,
        "correct_pin_assignments": 3,
        "unmatched_truth_endpoints": 2,
        "unmatched_observed_endpoints": 0,
        "endpoint_error_px_median": 1.0,
        "endpoint_error_pitch_median": 0.1,
        "raw_endpoint_error_px_median": 20.0,
        "raw_endpoint_error_pitch_median": 2.0,
        "pin_projection_error_px_median": 0.5,
        "empty_scene_wire_fp_total": 0,
        "flips": 0,
        "flip_transitions": 2,
        "flips_per_minute": 0.0,
        "wire_interval_s": 0.5,
        "same_row_neighbour_errors": 0,
        "wrong_pin_matches": 0,
    }
    aggregate = _aggregate([report])
    assert aggregate["wire_recall"] == pytest.approx(4 / 6)
    assert aggregate["pin_assignment_accuracy"] == pytest.approx(3 / 4)
    assert aggregate["raw_endpoint_error_median_of_config_medians_px"] == pytest.approx(20.0)
    assert aggregate["raw_endpoint_error_pitch_median_of_config_medians"] == pytest.approx(2.0)


def test_replay_matches_resolved_endpoints_at_canonical_pin_position():
    """Ferrule/cut offset must not turn a correct pin into an unmatched one."""
    result = WireTraceResult(
        frame_id=1,
        ts_ms=1.0,
        board_tracking="locked",
        wires=[WireInstance(
            wire_id=0,
            color="red",
            path_px=[(80.0, 100.0), (200.0, 130.0)],
            endpoint_a=WireEndpoint(
                kind="pin", px=(80.0, 100.0), pin_id="D7", confidence=0.9,
            ),
            endpoint_b=WireEndpoint(
                kind="floating", px=(200.0, 130.0), confidence=0.0,
            ),
            confidence=0.9,
            ambiguous=False,
        )],
        pin_positions={"D7": (100.0, 100.0)},
    )
    observed = replay_module._observed_endpoints(result)
    assert observed[0]["px"] == (100.0, 100.0)
    assert observed[0]["raw_px"] == (80.0, 100.0)
    assert observed[1]["px"] == (200.0, 130.0)
    assert observed[1]["raw_px"] == (200.0, 130.0)
    truth = [{"pin_id": "D7", "px": (100.0, 100.0)}]
    assert len(replay_module._match(truth, observed[:1], max_distance=12.0)) == 1


def test_baseline_checks_new_lower_is_better_metrics():
    actual = {
        "pin_assignment_accuracy": 0.95,
        "unmatched_truth_endpoints": 1,
        "unmatched_observed_endpoints": 1,
        "endpoint_error_median_of_config_medians_px": 1.0,
        "endpoint_error_pitch_median_of_config_medians": 0.1,
        "pin_projection_error_median_of_config_medians_px": 0.4,
        "same_row_neighbour_error_rate": 0.0,
        "empty_scene_wire_fp_total": 0,
        "empty_scene_fp_per_frame": 0.0,
        "flips": 0,
        "flips_per_minute": 0.0,
    }
    baseline = dict(actual, unmatched_observed_endpoints=0)
    failures = _check_baseline(actual, baseline, 0.05)
    assert any("unmatched_observed_endpoints" in failure for failure in failures)


@pytest.mark.parametrize("pose_mode, expected_instances", [("sequential", 1), ("perframe", 2)])
def test_detector_pose_modes_keep_the_intended_lifetime(tmp_path, monkeypatch, pose_mode, expected_instances):
    """Sequential keeps tracker state; perframe deliberately resets it."""
    config_dir = tmp_path / "cfg-01"
    config_dir.mkdir()
    for frame_id in range(2):
        frame = np.zeros((12, 16, 3), dtype=np.uint8)
        assert cv2.imwrite(str(config_dir / f"f{frame_id:03d}.jpg"), frame)

    instances = []

    class FakeDetector:
        def __init__(self):
            self.calls = []
            self.closed = False
            instances.append(self)

        def detect(self, frame, frame_id, ts_ms):
            self.calls.append((frame_id, ts_ms))
            return DetectionResult(
                board_id="mini",
                frame_id=frame_id,
                ts_ms=ts_ms,
                tracking="locked",
                confidence=1.0,
                pins=[],
            )

        def close(self):
            self.closed = True

    monkeypatch.setattr(replay_module, "create_detector", lambda *args, **kwargs: FakeDetector())
    monkeypatch.setattr(
        replay_module,
        "trace",
        lambda frame, pins, frame_id, ts_ms, tracking, **kwargs: replay_module.WireTraceResult(
            frame_id=frame_id,
            ts_ms=ts_ms,
            board_tracking=tracking,
            wires=[],
            video_size=(16, 12),
        ),
    )

    report = _replay_config(
        config_dir,
        [],
        {"pins_px": {}, "pitch_px": 5.0, "connections": []},
        None,
        False,
        pose_mode,
        0.5,
        profile=object(),
        profile_dir=tmp_path,
    )
    assert report["pose_mode"] == pose_mode
    assert report["frames"] == 2
    assert len(instances) == expected_instances
    assert all(instance.closed for instance in instances)
    if pose_mode == "sequential":
        assert [call[0] for call in instances[0].calls] == [0, 1]
    else:
        assert [len(instance.calls) for instance in instances] == [1, 1]
