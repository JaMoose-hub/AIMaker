"""Phone live overlays: real catalog geometry, fake models/RTC, no hardware."""
import asyncio
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import numpy as np
import pytest

from app.component_worker import ComponentVisionProfile
from app.mobile_photo import MobilePhotoAnalyzer
from app.profiles.store import ProfileStore
from app.vision.yolo_pose import BoardPoseObservation
from app.vision.yolo_profile_detector import _project_profile_on_observed_quad
from test_mobile import setup, preview, context

PROFILES = Path(__file__).resolve().parents[2] / "profiles"


def analyzer(monkeypatch):
    quads = [np.float32(q) for q in (
        [[200,180],[620,180],[620,900],[200,900]],
        [[1040,250],[1510,250],[1510,450],[1040,450]],
        [[1040,620],[1510,620],[1510,820],[1040,820]])]
    ids = ("raspberry-pi-5", "hc-sr04", "mrd-tf240-8p-cs")
    models = {}
    for cid, corners in zip(ids, quads):
        profile = ProfileStore(PROFILES).profile(cid) if cid == ids[0] else ComponentVisionProfile.load(PROFILES / "components" / cid / "vision_profile.json")
        obs = BoardPoseObservation(corners, .95, np.ones(4), tuple(np.r_[corners.min(0), corners.max(0)]))
        models[cid] = NS(_profile=profile, _locator=NS(locate=Mock(return_value=obs), close=Mock()))
    correction = Mock(side_effect=lambda frame, profile, pins, size: pins)
    monkeypatch.setattr("app.mobile_photo._correct_pi5_j8_from_image", correction)
    state = NS(source=Mock(), frame_bus=Mock(), vision_worker=Mock())
    return MobilePhotoAnalyzer(state, contexts=models), models, state, correction


def test_preview_projects_catalog_pins_with_shared_webcam_geometry_and_one_inference_per_model(monkeypatch):
    service, models, state, correction = analyzer(monkeypatch)
    frame = np.zeros((1080,1920,3), np.uint8)
    packet = service.preview(frame, dict(context_id="ctx", design={"component_ids":["hc-sr04","mrd-tf240-8p-cs"]}),
        dict(session_id="phone", generation=5, sample_seq=22, ts_ms=1234))["recognition"]
    assert (packet["source"], packet["session_id"], packet["generation"], packet["context_id"], packet["frame_seq"]) == ("phone","phone",5,"ctx",22)
    assert packet["coordinates_are_hints_only"]
    assert len(packet["detection"]["pins"]) == 40
    expected, _ = _project_profile_on_observed_quad(models["raspberry-pi-5"]._profile,
        models["raspberry-pi-5"]._locator.locate.return_value.corners_px, (1920,1080), .95)
    np.testing.assert_allclose([[p["x"],p["y"]] for p in packet["detection"]["pins"]], [[p.x,p.y] for p in expected], atol=.051)
    assert {p["component_id"] for p in packet["components"]} == {"hc-sr04","mrd-tf240-8p-cs"}
    for pose in [packet["detection"], *packet["components"]]:
        assert pose["frame_id"] == 22 and pose["runtime_revision"] == 5 and pose["video_size"] == [1920,1080]
        assert pose["pins"]
    for model in models.values():
        model._locator.locate.assert_called_once()
        assert model._locator.locate.call_args.args[0] is frame
    correction.assert_called_once()
    assert state.source.mock_calls == state.frame_bus.mock_calls == state.vision_worker.mock_calls == []
    service.close()
    for model in models.values():
        model._locator.close.assert_not_called()


@pytest.mark.parametrize("corners", [
    [[200,180],[200,180],[200,180],[200,180]],
    [[200,180],[620,900],[620,180],[200,900]],
    [[200,180],[float("nan"),180],[620,900],[200,900]],
    [[200,180],[210,180],[210,190],[200,190]],
    [[-20,180],[620,180],[620,900],[-20,900]],
])
def test_invalid_or_clipped_phone_quad_cannot_authorize_gpio(monkeypatch, corners):
    service, models, _, _ = analyzer(monkeypatch)
    models["raspberry-pi-5"]._locator.locate.return_value = BoardPoseObservation(np.float32(corners), .95, np.ones(4), (200,180,620,900))
    result = service.preview(np.zeros((1080,1920,3),np.uint8), dict(context_id="ctx",design={"component_ids":["hc-sr04"]}), dict(sample_seq=1,generation=1))
    assert not result["board_present"]
    assert result["recognition"]["detection"]["tracking"] == "searching"
    assert result["recognition"]["detection"]["pins"] == []
    assert result["recognition"]["components"][0]["pins"], "an invalid Pi must not hide independently observed modules"


def framing_packet(board=None, components=()):
    return dict(detection=dict(tracking="locked" if board is not None else "searching",
                               outline=board, confidence=.95, pins=[]),
                components=[dict(component_id=cid, tracking="locked", outline=quad, confidence=.95, pins=[])
                            for cid, quad in components])


@pytest.mark.parametrize("has_target", [False, True])
def test_missing_pi_has_one_specific_reason_even_when_the_target_is_present(has_target):
    service = MobilePhotoAnalyzer(NS())
    service._models = Mock(side_effect=AssertionError("framing an existing packet must not run models"))
    quad = [[100,100],[400,100],[400,300],[100,300]]
    components = [("hc-sr04", quad)] if has_target else []
    packet = framing_packet(components=components)
    result = service.preview_packet(np.zeros((1080,1920,3),np.uint8),
        dict(context_id="ctx", design={"component_ids":["hc-sr04"]}), dict(sample_seq=1), packet)
    assert result["reason"] == "find_board"
    assert not result["board_present"] and result["target_present"] is has_target
    assert result["target_id"] == "hc-sr04" and not result["framed"] and not result["sharp"]
    assert result["recognition"]["components"] == [{**component, "runtime_revision":0, "frame_id":1}
                                                   for component in packet["components"]]
    service._models.assert_not_called()


@pytest.mark.parametrize("target,observed", [("hc-sr04","mrd-tf240-8p-cs"), ("mrd-tf240-8p-cs","hc-sr04")])
def test_missing_required_component_is_distinct_from_missing_pi_and_an_unrelated_module(target, observed):
    service = MobilePhotoAnalyzer(NS())
    board = [[200,200],[700,200],[700,550],[200,550]]
    module = [[1100,250],[1450,250],[1450,450],[1100,450]]
    context = dict(context_id="ctx", design={"component_ids":["hc-sr04","mrd-tf240-8p-cs"]},
                   context={"debug_context":{"wiring_target":{"component_id":target}}})
    result = service.preview_packet(np.zeros((1080,1920,3),np.uint8), context, dict(sample_seq=1),
                                    framing_packet(board, [(observed,module)]))
    assert result["reason"] == "find_target_component"
    assert result["board_present"] and not result["target_present"] and result["target_id"] == target
    assert {obj["id"] for obj in result["objects"]} == {"raspberry-pi-5", observed}
    assert result["quality"]["raspberry-pi-5"]["warnings"], "missing target has priority over poor Pi lighting"


@pytest.mark.parametrize("expected", ["find_board", "find_target_component", "keep_targets_in_frame",
                                      "move_closer", "improve_focus_or_light", "ready"])
def test_framing_reason_is_identical_for_native_portrait_and_landscape_without_an_orientation_veto(expected):
    service = MobilePhotoAnalyzer(NS())
    service._models = Mock(side_effect=AssertionError("existing packet needs no new inference"))
    board = [[200,200],[700,200],[700,550],[200,550]]
    target = [[1100,250],[1450,250],[1450,450],[1100,450]]
    if expected == "find_board":
        board = None
    elif expected == "keep_targets_in_frame":
        board = [[1,200],[500,200],[500,550],[1,550]]
    elif expected == "move_closer":
        board = [[200,200],[300,200],[300,300],[200,300]]
    components = [] if expected == "find_target_component" else [("hc-sr04",target)]
    context = dict(context_id="ctx", design={"component_ids":["hc-sr04"]})
    identity = dict(session_id="phone",generation=2,sample_seq=3)
    y,x = np.indices((1080,1920))
    pixels = np.where((x//12+y//12)%2,192,64).astype(np.uint8)
    landscape = np.repeat(pixels[...,None],3,axis=2)
    if expected == "improve_focus_or_light":
        landscape.fill(0)
    portrait = np.rot90(landscape,-1).copy()
    def rotate(points):
        points = np.asarray(points)
        return np.column_stack((1079-points[:,1],points[:,0])).tolist()
    original = framing_packet(board,components)
    rotated = framing_packet(rotate(board) if board is not None else None,
                             [(cid,rotate(quad)) for cid,quad in components])
    runtime = {"raspberry-pi-5":{"providers":["CUDAExecutionProvider"]}}
    before = service.preview_packet(landscape,context,identity,original,model_runtime=runtime)
    after = service.preview_packet(portrait,context,identity,rotated,model_runtime=runtime)
    assert before["reason"] == after["reason"] == expected
    for key in ("board_present","target_present","target_id","sharp","framed"):
        assert before[key] == after[key]
    assert before["recognition"]["video_size"] == [1920,1080]
    assert after["recognition"]["video_size"] == [1080,1920]
    assert before["model_runtime"] == after["model_runtime"] == runtime
    for before_object, after_object in zip(before["objects"],after["objects"]):
        assert before_object["area_fraction"] == pytest.approx(after_object["area_fraction"])
        np.testing.assert_allclose(after_object["outline_px"],rotate(before_object["outline_px"]))
    assert original["detection"]["outline"] == board and rotated["detection"]["outline"] == (rotate(board) if board is not None else None)
    service._models.assert_not_called()


def recognition(phone, seq, *, context_id=None, generation=1):
    return dict(source="phone",session_id=phone["session_id"], generation=generation,
        context_id=context_id or phone["context_id"], frame_seq=seq, video_size=[100,100],
        coordinates_are_hints_only=True, detection={}, components=[])


def test_live_recognition_survives_unready_capture_but_expires_and_clears_on_stop(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    service.accept_preview(sid,1,1,clock.now,preview(sharp=False,reason="improve_focus_or_light",recognition=recognition(phone,1)),(100,100),phone["context_id"])
    first = service.snapshot(sid)
    assert first["stream"]["recognition"]["frame_seq"] == 1 and not first["stream"]["can_capture"]
    clock.now += 1
    assert service.snapshot(sid)["stream"]["recognition"]["valid_for_ms"] == 500
    clock.now += .6
    assert service.snapshot(sid)["stream"]["recognition"] is None
    service.accept_preview(sid,1,2,clock.now,preview(recognition=recognition(phone,2)),(100,100),phone["context_id"])
    asyncio.run(service.stop_stream(sid))
    assert service.snapshot(sid)["stream"]["recognition"] is None


@pytest.mark.parametrize("change", [dict(source="webcam"),dict(session_id="other"),dict(generation=2),dict(context_id="old"),dict(frame_seq=0),dict(video_size=[1920,1080])])
def test_preview_refuses_foreign_recognition_packet(setup, change):
    service, phone, clock = setup
    asyncio.run(service.start_stream(phone["session_id"]))
    packet = {**recognition(phone,1), **change}
    service.accept_preview(phone["session_id"],1,1,clock.now,preview(recognition=packet),(100,100),phone["context_id"])
    assert service.snapshot(phone["session_id"])["stream"]["recognition"] is None


def test_live_analysis_follows_desktop_step_but_keeps_frozen_phone_context_and_revokes_capture(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    new = service.publish_context(context(context={"guide":{"confirmed":["wire-1","wire-2"]}}))
    calls = []
    def analyze(frame, ctx, identity):
        calls.append((deepcopy(ctx),identity))
        return preview(recognition=recognition(phone,identity["seq"],context_id=ctx["context_id"]))
    service.state.mobile_photo.preview = analyze
    asyncio.run(service.on_frame(sid,1,np.zeros((100,100,3),np.uint8),1,clock.now))
    current = service.snapshot(sid)
    assert calls[0][0]["context_id"] == new["context_id"]
    assert current["stream"]["recognition"]["context_id"] == new["context_id"]
    assert current["context_id"] == phone["context_id"]
    assert not current["stream"]["can_capture"] and current["stream"]["reason"] == "desktop_context_changed"
    assert service.rtc.closed == [], "step changes must not restart the phone camera"
    service.publish_context(context("other-project"))
    assert service.snapshot(sid)["stream"]["recognition"] is None


def test_portrait_preview_preserves_native_rotated_outline_and_pin_coordinates(monkeypatch):
    service, models, state, _ = analyzer(monkeypatch)
    context = dict(context_id="portrait", design={"component_ids": ["hc-sr04", "mrd-tf240-8p-cs"]})
    identity = dict(session_id="phone", generation=1, sample_seq=1)
    landscape = service.preview(np.zeros((1080, 1920, 3), np.uint8), context, identity)["recognition"]
    def rotate(points):
        points = np.asarray(points)
        return np.column_stack((1080 - points[:, 1], points[:, 0]))
    for model in models.values():
        obs = model._locator.locate.return_value
        corners = rotate(obs.corners_px).astype(np.float32)
        model._locator.locate.return_value = BoardPoseObservation(
            corners, obs.confidence, np.ones(4), tuple(np.r_[corners.min(0), corners.max(0)]))
    frame = np.zeros((1920, 1080, 3), np.uint8)
    portrait = service.preview(frame, context, {**identity, "generation": 2})["recognition"]
    assert portrait["video_size"] == [1080, 1920] and portrait["generation"] == 2
    for before, after in zip([landscape["detection"], *landscape["components"]],
                             [portrait["detection"], *portrait["components"]]):
        assert after["video_size"] == [1080, 1920] and after["runtime_revision"] == 2
        assert len(before["pins"]) == len(after["pins"]) > 0
        np.testing.assert_allclose(after["outline"], rotate(before["outline"]), atol=.11)
        old = [[pin["x"], pin["y"]] for pin in before["pins"]]
        new = np.asarray([[pin["x"], pin["y"]] for pin in after["pins"]])
        np.testing.assert_allclose(new, rotate(old), atol=.11)
        assert np.all(new >= 0) and np.all(new < [1080, 1920])
    assert all(model._locator.locate.call_count == 2 for model in models.values())
    assert state.source.mock_calls == state.frame_bus.mock_calls == []


def test_late_landscape_analysis_cannot_restore_geometry_or_lease_after_portrait_restart(setup):
    service, phone, clock = setup
    sid, context_id = phone["session_id"], phone["context_id"]
    entered, release = threading.Event(), threading.Event()
    def packet(seq, generation, size):
        return {**recognition(phone, seq, generation=generation), "video_size": list(size)}
    def delayed(frame, context, identity):
        entered.set()
        assert release.wait(2), "test must release the old inference thread"
        return preview(recognition=packet(identity["seq"], identity["generation"], (1920, 1080)))
    async def scenario():
        await service.start_stream(sid)
        for seq, stamp in enumerate((100., 100.5, 101.1), 1):
            clock.now = stamp
            service.on_receive(sid, 1, seq, stamp, clock.wall(), (1920, 1080))
            service.accept_preview(sid, 1, seq, stamp,
                preview(recognition=packet(seq, 1, (1920, 1080))), (1920, 1080), context_id)
        assert service.snapshot(sid)["stream"]["can_capture"]
        service.state.mobile_photo.preview = delayed
        pending = asyncio.create_task(service.on_frame(sid, 1, np.zeros((1080, 1920, 3), np.uint8), 4, clock.now))
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            await service.stop_stream(sid)
            await service.start_stream(sid)
            service.on_receive(sid, 2, 1, clock.now, clock.wall(), (1080, 1920))
            service.accept_preview(sid, 2, 1, clock.now,
                preview(sharp=False, recognition=packet(1, 2, (1080, 1920))), (1080, 1920), context_id)
            before = service.snapshot(sid)["stream"]
            release.set()
            await pending
            # Receipt, metrics and disconnect callbacks from the retired peer
            # must not replace the new portrait state either.
            service.on_receive(sid, 1, 1000, clock.now, clock.wall(), (1920, 1080))
            await service.on_video_metrics(sid, 1, dict(video_fps=60, video_size=[1920, 1080]))
            await service.on_rtc_state(sid, 1, "disconnected")
            after = service.snapshot(sid)["stream"]
            assert after == before
            assert after["generation"] == 2 and after["video_size"] == [1080, 1920]
            assert after["recognition"]["generation"] == 2 and after["preview_seq"] == 1
            assert after["active"] and after["video_receive_fresh"] and not after["can_capture"]
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)
            await service.stop_stream(sid)
    asyncio.run(scenario())
