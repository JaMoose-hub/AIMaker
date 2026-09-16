"""Regression coverage for startup skin false positives and poisoned baselines."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.component_worker import ComponentPoseTracker, ComponentVisionProfile, component_pose_message
from app.vision.yolo_pose import BoardPoseObservation


ROOT = Path(__file__).resolve().parents[2]
QUAD = np.float64([[90, 65], [245, 85], [225, 205], [70, 185]])
MODULES = [("hc-sr04", .25), ("hw-123", .30), ("mrd-tf240-8p-cs", .08)]


def observation(quad=QUAD):
    return BoardPoseObservation(quad.copy(), .7, np.full(4, .8),
        (*quad.min(axis=0), *quad.max(axis=0)))


def profile(cid="hc-sr04"):
    return ComponentVisionProfile.load(ROOT / "profiles/components" / cid / "vision_profile.json")


def board_frame(background=(80, 130, 190)):
    frame = np.full((280, 360, 3), background, np.uint8)
    cv2.fillConvexPoly(frame, QUAD.astype(np.int32), (180, 60, 20))
    return frame


def test_warm_desk_outside_the_polygon_does_not_block_cold_start():
    frame = board_frame()
    tracker = ComponentPoseTracker(profile(), reacquire_min_visible_fraction=.25)
    assert tracker._hand_fraction(frame, QUAD) < .01
    result = tracker.update(frame, observation(), frame_id=1, ts_ms=1000)
    assert result.tracking == "locked"
    assert len(result.pins) == 4


@pytest.mark.parametrize("cid,minimum", MODULES)
def test_real_skin_inside_the_component_still_blocks_even_after_expiry(cid, minimum):
    frame = board_frame((60, 60, 60))
    tracker = ComponentPoseTracker(profile(cid), reacquire_min_visible_fraction=minimum)
    assert tracker.update(frame, observation(), frame_id=1, ts_ms=1000).tracking == "locked"
    cv2.rectangle(frame, (80, 65), (160, 210), (80, 130, 190), -1)
    assert tracker._hand_fraction(frame, QUAD) > .2
    for i in range(2, 25):
        result = tracker.update(frame, observation(), frame_id=i, ts_ms=1000+i*300)
        assert result.tracking != "locked"
        if i > 8:
            assert result.pins == () and result.outline_px is None


@pytest.mark.parametrize("cid,minimum", MODULES)
@pytest.mark.parametrize("moved", [False, True])
def test_old_material_peak_expires_and_rebuilds_from_new_consensus(monkeypatch, cid, minimum, moved):
    frame = board_frame((60, 60, 60))
    tracker = ComponentPoseTracker(profile(cid), visibility_warmup_frames=1,
        reacquire_min_visible_fraction=minimum, reacquire_confirm_frames=3)
    fraction = [.8]
    monkeypatch.setattr(tracker, "_visible_fraction", lambda *args: fraction[0])
    monkeypatch.setattr(tracker, "_hand_fraction", lambda *args: 0.)
    original = tracker.update(frame, observation(), frame_id=1, ts_ms=1000)
    assert original.tracking == "locked"
    fraction[0] = .39
    proposed = observation(QUAD + ([35, 0] if moved else [0, 0]))
    held = tracker.update(frame, proposed, frame_id=2, ts_ms=1300)
    assert held.tracking == "stale"
    for i in range(3):
        result = tracker.update(frame, proposed, frame_id=3+i, ts_ms=3100+i*300)
        if i < 2:
            assert result.tracking == "searching" and result.pins == ()
    assert result.tracking == "locked"
    assert result.stability == "reacquired"
    assert np.allclose(result.outline_px, proposed.corners_px)
    assert tracker._visibility_baseline == pytest.approx(.39)
    message = component_pose_message(result)
    assert message["pose_quality"]["reset_count"] == 1
    assert message["pose_quality"]["reset_reason"] == "tracking_expired"


@pytest.mark.parametrize("cid,minimum", MODULES)
def test_missing_model_expires_without_reviving_old_geometry(cid, minimum):
    frame = board_frame((60, 60, 60))
    tracker = ComponentPoseTracker(profile(cid), reacquire_min_visible_fraction=minimum, reacquire_confirm_frames=3)
    tracker.update(frame, observation(), frame_id=1, ts_ms=1000)
    for i in range(2, 18):
        result = tracker.update(frame, None, frame_id=i, ts_ms=1000+i*300)
    assert result.tracking == "searching" and result.pins == ()
    assert tracker._last_good is None and tracker._visibility_baseline is None
    assert component_pose_message(result)["pose_quality"]["reason"] == "model_missing"
    for i in range(3):
        result = tracker.update(frame, observation(), frame_id=20+i, ts_ms=7000+i*300)
    assert result.tracking == "locked"


@pytest.mark.parametrize("interruption", ["missing", "invalid", "gap", "duplicate"])
def test_recovery_counts_only_distinct_consecutive_valid_observations(interruption):
    frame = board_frame((60, 60, 60))
    tracker = ComponentPoseTracker(profile(), reacquire_min_visible_fraction=.25, reacquire_confirm_frames=3)
    tracker.update(frame, observation(), frame_id=1, ts_ms=1000)
    tracker.update(frame, None, frame_id=2, ts_ms=3200)
    tracker.update(frame, observation(), frame_id=3, ts_ms=3500)
    if interruption == "duplicate":
        for _ in range(5):
            result = tracker.update(frame, observation(), frame_id=3, ts_ms=3500)
            assert result.tracking == "searching"
    elif interruption == "missing":
        tracker.update(frame, None, frame_id=4, ts_ms=3800)
    elif interruption == "invalid":
        tracker.update(frame, observation(QUAD[[0, 2, 1, 3]]), frame_id=4, ts_ms=3800)
    start = 5500 if interruption == "gap" else 4100
    result = tracker.update(frame, observation(), frame_id=5, ts_ms=start)
    assert result.tracking == "searching"
    if interruption != "duplicate":
        result = tracker.update(frame, observation(), frame_id=6, ts_ms=start+300)
        assert result.tracking == "searching"
    result = tracker.update(frame, observation(), frame_id=7, ts_ms=start+600)
    assert result.tracking == "locked"


@pytest.mark.parametrize("change", ["size", "clock", "frame_id"])
def test_camera_restart_cannot_reuse_old_pose_or_consensus(change):
    tracker = ComponentPoseTracker(profile(), reacquire_min_visible_fraction=.25)
    frame = board_frame((60, 60, 60))
    tracker.update(frame, observation(), frame_id=12, ts_ms=9000)
    if change == "size":
        frame = cv2.resize(frame, (720, 560))
    result = tracker.update(frame, None, frame_id=1 if change == "frame_id" else 13,
        ts_ms=1000 if change == "clock" else 9300)
    assert result.tracking == "searching" and result.pins == ()
    assert tracker._visibility_baseline is None
    assert component_pose_message(result)["pose_quality"]["reset_count"] == 1


def test_cold_start_without_any_component_material_does_not_lock():
    tracker = ComponentPoseTracker(profile(), reacquire_min_visible_fraction=.25)
    frame = np.full((280, 360, 3), 180, np.uint8)
    for i in range(10):
        result = tracker.update(frame, observation(), frame_id=i, ts_ms=1000+i*300)
        assert result.tracking == "searching" and result.pins == ()


def test_expiry_of_one_module_never_resets_another():
    frame = board_frame((60, 60, 60))
    first = ComponentPoseTracker(profile(), reacquire_min_visible_fraction=.25)
    second = ComponentPoseTracker(profile("hw-123"), reacquire_min_visible_fraction=.3)
    for tracker in (first, second):
        tracker.update(frame, observation(), frame_id=1, ts_ms=1000)
    for i in range(2, 12):
        first.update(frame, None, frame_id=i, ts_ms=1000+i*300)
        result = second.update(frame, observation(), frame_id=i, ts_ms=1000+i*300)
        assert result.tracking == "locked"
    assert first._last_good is None
    assert component_pose_message(result)["pose_quality"]["reset_count"] == 0


def test_worker_reports_orientation_rejection_separately_from_missing_model(monkeypatch):
    from types import SimpleNamespace
    from app.capture.bus import FrameSlot
    from app.component_worker import ComponentPoseState, ComponentPoseWorker
    frame = board_frame((60, 60, 60))
    slot = FrameSlot(frame, 1, 1000, 1)
    state = ComponentPoseState()
    worker = ComponentPoseWorker(bus=SimpleNamespace(get_latest=lambda **kw: slot), state=state,
        model_path="unused", profile_path=ROOT / "profiles/components/hw-123/vision_profile.json",
        locator=SimpleNamespace(locate=lambda _: observation()), publish=lambda _: worker._stop.set())
    monkeypatch.setattr("app.component_worker.refine_component_corners_from_pcb", lambda _, obs, **kw: obs)
    monkeypatch.setattr("app.component_worker.orient_component_corners_from_pin_row", lambda *args: None)
    worker._run()
    message = component_pose_message(state.get("hw-123"))
    assert message["pins"] == []
    assert message["pose_quality"]["model_confidence"] == .7
    assert message["pose_quality"]["reason"] == "pin_orientation_unverified"
