"""Offline fake-source contracts; no camera, Pi or cloud calls."""
from types import SimpleNamespace as NS

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameSlot
from app.debug_capture import DebugCaptureError, TFTPhaseSampler, capture_debug_evidence, current_debug_camera


class Clock:
    def __init__(self): self.now = 100.
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


def setup():
    clock = Clock()
    image = np.random.default_rng(4).integers(30, 225, (200, 320, 3), dtype=np.uint8)
    calls = [0]
    def frame(**_):
        calls[0] += 1
        return FrameSlot(image, calls[0], clock()*1000, calls[0])
    state = NS(config=NS(camera=NS(source="device")),
               source=NS(current_index=0, device_name="private camera name",
                         capture_mode=dict(width=320, height=200, fps=30)),
               runtime_manager=NS(snapshot=lambda: NS(board_id="raspberry-pi-5", runtime_revision=3)),
               frame_bus=NS(get_latest=frame))
    return state, clock, image


def test_new_raw_webcam_snapshot_has_immutable_metadata_and_no_overlays():
    state, clock, image = setup()
    images, metadata = capture_debug_evidence(state, "tft_screen", clock=clock, sleep=clock.sleep)
    assert list(images) == ["overview"]
    assert metadata["source"] == "device" and metadata["runtime_revision"] == 3
    assert metadata["camera_id"] == current_debug_camera(state)
    assert "private camera name" not in metadata["camera_id"]
    assert metadata["selection"]["candidate_count"] == 9
    assert metadata["ts_ms"] >= metadata["selection"]["requested_ts_ms"]
    assert metadata["stability"]["stable"] and metadata["quality"]["framing_ready"]
    assert not metadata["electrical_verified"] and not metadata["visibility_verified"]
    before = images["overview"]
    image[:] = 0
    assert images["overview"] == before and cv2.imdecode(np.frombuffer(before, np.uint8), 1).mean() > 50


@pytest.mark.parametrize("source", ["synthetic", "window", "xreal"])
def test_only_physical_webcam_source_is_accepted(source):
    state, clock, _ = setup()
    state.config.camera.source = source
    with pytest.raises(DebugCaptureError, match="webcam_required"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)


def test_stale_pre_request_and_eye_restore_sources_are_rejected():
    state, clock, image = setup()
    state.frame_bus.get_latest = lambda **_: FrameSlot(image, 1, 99000, 1)
    with pytest.raises(DebugCaptureError, match="camera_frame_not_new"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)
    state.glasses_stream = NS(snapshot=lambda: {"active": False, "state": "restoring"})
    with pytest.raises(DebugCaptureError, match="webcam_restore_required"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)


def test_runtime_switch_and_invalid_pixels_fail_closed():
    state, clock, _ = setup()
    state.runtime_manager.snapshot = lambda: NS(board_id="raspberry-pi-5", runtime_revision=3 if clock()<100.2 else 4)
    with pytest.raises(DebugCaptureError, match="camera_changed"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)
    state, clock, _ = setup()
    state.frame_bus.get_latest = lambda **_: FrameSlot(np.zeros((4, 4, 3), np.uint8), 1, clock()*1000, 1)
    with pytest.raises(DebugCaptureError, match="camera_frame_invalid"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)


def test_low_quality_is_a_visible_warning_not_a_hardware_verdict():
    state, clock, image = setup()
    image[:] = 255
    _, metadata = capture_debug_evidence(state, clock=clock, sleep=clock.sleep)
    assert not metadata["quality"]["framing_ready"]
    assert "exposure_clipping" in metadata["quality"]["warnings"]
    assert not metadata["visibility_verified"]


@pytest.mark.parametrize("change", ["replace", "mode", "device"])
def test_source_change_during_burst_rejected_without_runtime_revision_change(change):
    state, clock, _ = setup()
    original_id = current_debug_camera(state)
    def sleep(seconds):
        clock.sleep(seconds)
        if clock() >= 100.2:
            if change == "replace":
                state.source = NS(**vars(state.source))
            elif change == "mode":
                state.source.capture_mode = dict(width=640, height=480, fps=30)
            else:
                state.source.current_index = 1
    with pytest.raises(DebugCaptureError, match="camera_changed"):
        capture_debug_evidence(state, clock=clock, sleep=sleep)
    assert state.runtime_manager.snapshot().runtime_revision == 3
    assert current_debug_camera(state) != original_id


def test_source_change_during_frame_read_rejected_and_missing_source_fails_closed():
    state, clock, _ = setup()
    read = state.frame_bus.get_latest
    def changed(**kwargs):
        slot = read(**kwargs)
        state.source = NS(**vars(state.source))
        return slot
    state.frame_bus.get_latest = changed
    with pytest.raises(DebugCaptureError, match="camera_changed"):
        capture_debug_evidence(state, clock=clock, sleep=clock.sleep)
    state.source = None
    with pytest.raises(DebugCaptureError, match="camera_source_unavailable"):
        current_debug_camera(state)


def test_sampler_collects_live_phase_candidates_once_and_respects_bounds():
    state, clock, _ = setup()
    run = dict(id="run", reserved=True, outcome="running", phase="display_red", camera_assisted=True)
    tests = NS(snapshot=lambda: {"results": [run]})
    sampler = TFTPhaseSampler(state, tests, "run", clock=clock)
    for sequence, phase in enumerate(["display_red", "display_lime", "display_blue", "display_code"], 1):
        run.update(phase=phase, camera_phase=dict(run_id="run", seq=sequence, phase=phase,
            committed_at=1700000000., received_monotonic_ms=clock()*1000))
        sampler.tick()  # The frame before PC receipt + settling is ineligible.
        for _ in range(6):
            clock.sleep(.2)
            sampler.tick()
    records = sampler.stop()
    assert len(records) == 12
    assert {metadata["phase_seq"] for _, metadata in records} == {1, 2, 3, 4}
    assert all(metadata["phase_association"] == "candidate_requires_marker" for _, metadata in records)
    assert all(metadata["camera_id"] == current_debug_camera(state) for _, metadata in records)
    assert all(metadata["ts_ms"] >= metadata["phase_evidence"]["received_monotonic_ms"]+150 for _, metadata in records)
    assert sum(len(raw) for images, _ in records for raw in images.values()) < 64*1024*1024


def test_sampler_does_not_reconstruct_missed_phases_or_reuse_foreign_run():
    state, clock, _ = setup()
    run = dict(id="run", reserved=True, outcome="awaiting_confirmation", phase="awaiting_visual")
    sampler = TFTPhaseSampler(state, NS(snapshot=lambda: {"results": [run]}), "run", clock=clock)
    sampler.tick()
    assert sampler.stop() == []
    run.update(outcome="running", phase="display_red", camera_phase=dict(run_id="other", seq=1))
    sampler = TFTPhaseSampler(state, NS(snapshot=lambda: {"results": [run]}), "run", clock=clock)
    sampler.tick()
    assert sampler.stop() == []


def test_sampler_stops_on_runtime_switch_and_has_strict_memory_cap():
    state, clock, _ = setup()
    run = dict(id="run", reserved=True, outcome="running", phase="display_red",
               camera_phase=dict(run_id="run", seq=1, phase="display_red", received_monotonic_ms=99000))
    sampler = TFTPhaseSampler(state, NS(snapshot=lambda: {"results": [run]}), "run", clock=clock, max_bytes=1)
    sampler.tick()
    assert sampler.snapshot() == []
    state.runtime_manager.snapshot = lambda: NS(board_id="raspberry-pi-5", runtime_revision=4)
    sampler.tick()
    assert sampler.error == "camera_changed" and sampler.done.is_set()


@pytest.mark.parametrize("change", ["replace", "mode"])
def test_sampler_stops_on_source_or_mode_change_before_next_phase(change):
    state, clock, _ = setup()
    run = dict(id="run", reserved=True, outcome="running", phase="display_red",
               camera_phase=dict(run_id="run", seq=1, phase="display_red", received_monotonic_ms=99000))
    sampler = TFTPhaseSampler(state, NS(snapshot=lambda: {"results": [run]}), "run", clock=clock)
    sampler.tick()
    assert len(sampler.snapshot()) == 1
    if change == "replace":
        state.source = NS(**vars(state.source))
    else:
        state.source.capture_mode["fps"] = 15
    run.pop("camera_phase")  # Source binding is checked even between stage events.
    sampler.tick()
    assert sampler.error == "camera_changed" and sampler.done.is_set()
    assert len(sampler.stop()) == 1


def wiring_setup(monkeypatch):
    from app.debug_diagrams import resolve_wiring_target
    from app.designs import demo_design
    import app.cloud_wiring as cloud
    state, clock, _ = setup()
    image = np.random.default_rng(8).integers(20, 230, (600, 1000, 3), dtype=np.uint8)
    target = resolve_wiring_target(demo_design(["hc-sr04"]),
                                  dict(component_id="hc-sr04", wire_id="hc-sr04:trig"))
    source = [None]
    def frame(**_):
        number = round(clock()*1000)
        source[0] = FrameSlot(image, number, clock()*1000, number)
        return source[0]
    def pose(pin, x):
        return dict(frame_id=source[0].frame_id, ts_ms=source[0].ts_ms, tracking="locked",
                    video_size=[1000, 600], pose_quality={},
                    pins=[dict(id=pin, x=x, y=300, v=True), dict(id="neighbor", x=x+30, y=300, v=True)])
    def pair():
        slot = source[0]
        packet = dict(frame_id=slot.frame_id, seq=slot.seq, ts_ms=slot.ts_ms, runtime_revision=3,
                      board_id="raspberry-pi-5", detection=pose("GPIO17", 220),
                      components=[dict(**pose("TRIG", 760), component_id="hc-sr04")])
        return packet, slot
    state.config.realtime_tracking = True
    state.frame_bus.get_latest = frame
    state.motion_frame_state = NS(get_capture=pair)
    monkeypatch.setattr(cloud, "time", NS(monotonic=clock))
    return state, clock, image, target


@pytest.mark.parametrize("mode", ["fast", "thorough"])
def test_multiview_raw_crops_are_lossless_bound_to_target_and_source(monkeypatch, mode):
    state, clock, original, target = wiring_setup(monkeypatch)
    images, metadata = capture_debug_evidence(state, "module_header", wiring_target=target, response_mode=mode,
                                             clock=clock, sleep=clock.sleep)
    assert metadata["wiring_target"] == target and metadata["locator"] == "same_frame_raw_tracking"
    assert metadata["same_frame"] and metadata["capture_skew_ms"] == 0
    assert set(images) == ({"overview", "pi_pins", "component_pins"} |
                          ({"pi_reading", "component_reading", "pi_contact", "component_contact"} if mode == "thorough" else set()))
    for view in metadata["views"]:
        assert view["ts_ms"] >= metadata["selection"]["requested_ts_ms"]
        assert view["sha256"] and view["mime_type"] == ("image/jpeg" if view["name"] == "overview" else "image/png")
        if view["name"].endswith("_pins"):
            x0, y0, x1, y1 = view["crop"]
            pixels = cv2.imdecode(np.frombuffer(images[view["name"]], np.uint8), 1)
            assert np.array_equal(pixels, original[y0:y1, x0:x1])
    original[:] = 0
    target["board_pin"] = "changed"
    assert metadata["wiring_target"]["board_pin"] == "GPIO17"
    assert cv2.imdecode(np.frombuffer(images["component_pins"], np.uint8), 1).mean() > 50


@pytest.mark.parametrize("reason", ["pre_request", "held", "predicted", "partial", "frame_mismatch", "display_only"])
def test_untrusted_pose_produces_only_fresh_overview(monkeypatch, reason):
    state, clock, _, target = wiring_setup(monkeypatch)
    read = state.motion_frame_state.get_capture
    def bad_pair():
        packet, slot = read()
        if reason == "pre_request":
            packet["ts_ms"] = 99000.
            slot = FrameSlot(slot.frame, slot.frame_id, 99000., slot.seq)
        elif reason == "frame_mismatch":
            slot = FrameSlot(slot.frame, slot.frame_id+1, slot.ts_ms, slot.seq)
        else:
            packet["detection"]["pose_quality"] = {
                "held": {"stability": "occlusion_hold"}, "predicted": {"predicted": True},
                "partial": {"partial": True}}.get(reason, {})
        return packet, slot
    state.motion_frame_state.get_capture = bad_pair
    if reason == "display_only":
        state.motion_frame_state = NS(get=lambda **_: read()[0])
    images, metadata = capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)
    assert list(images) == ["overview"] and metadata["mode"] == "overview"
    assert metadata["ts_ms"] >= metadata["selection"]["requested_ts_ms"]


@pytest.mark.parametrize("skew", [150, 251])
def test_paired_detector_crops_use_each_own_new_source_and_reject_excess_skew(monkeypatch, skew):
    from app.component_worker import ComponentPoseResult, ComponentPinPosition
    from app.vision.interface import DetectionResult, PinDetection
    state, clock, board_image, target = wiring_setup(monkeypatch)
    module_image = np.full_like(board_image, (30, 100, 200))
    state.config.realtime_tracking = False
    def board():
        timestamp = clock()*1000
        return FrameSlot(board_image, 10, timestamp, 10), DetectionResult("raspberry-pi-5", 10, timestamp,
                "locked", .9, pins=[PinDetection("GPIO17", 220, 300, .9)])
    def module(_):
        timestamp = clock()*1000-skew
        return FrameSlot(module_image, 11, timestamp, 11), ComponentPoseResult("hc-sr04", 11, timestamp,
                "locked", .9, (1000, 600), None, (ComponentPinPosition("TRIG", 760, 300, .9),), "locked")
    state.detection_state = NS(get_synchronized=board)
    state.component_pose_state = NS(get_synchronized=module)
    images, metadata = capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)
    if skew > 250:
        assert list(images) == ["overview"]
    else:
        assert "component_overview" in images and not metadata["same_frame"]
        assert metadata["capture_skew_ms"] == skew
        pixels = cv2.imdecode(np.frombuffer(images["component_pins"], np.uint8), 1)
        assert np.all(pixels == (30, 100, 200))
        assert all(view["ts_ms"] >= metadata["selection"]["requested_ts_ms"] for view in metadata["views"])


def test_camera_mode_change_while_obtaining_crop_sources_rejected(monkeypatch):
    state, clock, _, target = wiring_setup(monkeypatch)
    read = state.motion_frame_state.get_capture
    def changed():
        result = read()
        state.source.capture_mode["fps"] = 15
        return result
    state.motion_frame_state.get_capture = changed
    with pytest.raises(DebugCaptureError, match="camera_changed"):
        capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)


def test_invented_wiring_pin_rejected_before_capture(monkeypatch):
    state, clock, _, target = wiring_setup(monkeypatch)
    target["board_pin"] = "GPIO22"
    with pytest.raises(DebugCaptureError, match="invalid_wiring_target"):
        capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)


def test_thorough_wiring_hook_uses_budget_callback_and_returns_localized_views(monkeypatch):
    from pathlib import Path
    from app.debug_capture import inspect_debug_wiring
    from test_cloud_connectors import endpoint, route
    state, clock, _, target = wiring_setup(monkeypatch)
    state.motion_frame_state = NS(get_capture=lambda: None)
    images, metadata = capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)
    replies = iter([
        {"pi": {"source_view": "pi_overview", "x0": 100, "y0": 250, "x1": 350, "y1": 750, "evidence": "board header"},
         "component": {"source_view": "pi_overview", "x0": 600, "y0": 250, "x1": 900, "y1": 750, "evidence": "sensor header"}},
        endpoint("component"), endpoint("board"), route()])
    paths, calls = [], []
    def budgeted(prompt, schema, **kwargs):
        assert len(calls) < 4
        calls.append(prompt)
        paths.extend(kwargs["image_paths"])
        assert all(Path(path).is_file() for path in kwargs["image_paths"])
        return next(replies)
    result = inspect_debug_wiring(target, images, metadata, generate=budgeted, model="fixture", effort="low")
    assert len(calls) == 4 and result["opinion"]["authority"] == "visual_advisory"
    assert {"pi_pins", "component_pins", "pi_reading", "component_reading"} <= set(result["images"])
    assert all(not Path(path).exists() for path in paths)
    assert all(view["sha256"] and view["mime_type"] for view in result["metadata"]["views"])
    assert all(view["name"] != "pi_overview" for view in result["metadata"]["views"])


def test_thorough_hook_rejects_a_different_valid_wire_without_model_call(monkeypatch):
    from app.debug_capture import inspect_debug_wiring
    state, clock, _, target = wiring_setup(monkeypatch)
    images, metadata = capture_debug_evidence(state, wiring_target=target, clock=clock, sleep=clock.sleep)
    other = {**target, "wire_id": "hc-sr04:echo", "component_pin": "ECHO", "board_pin": "GPIO18"}
    def must_not_call(*_, **__):
        pytest.fail("changed target reached cloud")
    with pytest.raises(DebugCaptureError, match="capture_wiring_target_changed"):
        inspect_debug_wiring(other, images, metadata, generate=must_not_call, model="fixture", effort="low")
