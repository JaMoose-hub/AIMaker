"""Companion state tests use fake RTC/analyzer, synthetic files and no hardware."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from app.mobile import MobileAssets, MobileService


class Clock:
    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now

    def wall(self):
        return 1700000000. + self.now


class Assistant:
    def __init__(self):
        self.sent = []

    def read(self, cid, before=None, limit=50):
        return dict(id=cid, messages=[], jobs=[], before=before, limit=limit)

    def send(self, cid, body):
        self.sent.append((cid, body.model_dump()))
        return self.read(cid)


class Analyzer:
    def __init__(self):
        self.calls, self.released = [], []
        self.closed = False

    def preview(self, frame, context, identity):
        return preview()

    def analyze(self, asset, context, session):
        self.calls.append((asset, deepcopy(context), deepcopy(session)))
        return dict(capture_id="capture-1", source="mobile", camera_id=session["session_id"],
            video_size=[asset["width"], asset["height"]], image_sha256=asset["sha256"],
            wires=[dict(wire_id="wire-1")], components=[], detection={}, same_frame=True)

    def release(self, sid):
        self.released.append(sid)

    def close(self):
        self.closed = True


class RTC:
    def __init__(self, frame, state, **kwargs):
        self.frame, self.state = frame, state
        self.generations, self.closed = {}, []

    async def start(self, sid, bitrate_kbps=8000):
        self.bitrate_kbps = bitrate_kbps
        generation = self.generations.get(sid, 0)+1
        self.generations[sid] = generation
        return generation

    async def close(self, sid):
        self.closed.append(sid)
        if sid in self.generations:
            await self.state(sid, self.generations[sid], "stopped")

    async def close_all(self):
        for sid in self.generations:
            await self.close(sid)


def context(cid="conversation-1", **changes):
    result = dict(conversation_id=cid, title="Photo project", stage="guide", target="auto", round=2,
        design=dict(prompt="Help with the board", component_ids=["hc-sr04"], locale="en", model="fake", effort="low"),
        context={"confirmed_wire_ids": ["wire-1"]})
    result.update(changes)
    return result


def preview(offset=0, **changes):
    result = dict(board_present=True, target_present=True, sharp=True, framed=True,
        objects=[dict(id="raspberry-pi-5", outline_px=[[10+offset, 10], [70+offset, 10], [70+offset, 70], [10+offset, 70]], confidence=.9)],
        quality={"sharpness": 100}, reason="ready", model_runtime={"provider": "fake"})
    result.update(changes)
    return result


@pytest.fixture
def setup(tmp_path):
    clock = Clock()
    state = SimpleNamespace(assistant=Assistant(), mobile_photo=Analyzer())
    service = MobileService(state, tmp_path / "mobile", clock=clock, wall=clock.wall, rtc_factory=RTC)
    published = service.publish_context(context())
    pairing = service.create_pairing("conversation-1", "http://192.168.1.5:8100")
    phone = service.pair(pairing["code"], "Test phone")
    return service, phone, clock


def feed(service, phone, clock, seq, stamp, **changes):
    clock.now = stamp
    sid = phone["session_id"]
    generation = service.sessions[sid]["stream"]["generation"]
    service.on_receive(sid, generation, seq, stamp, clock.wall(), (100, 100))
    service.accept_preview(sid, generation, seq, stamp, preview(**changes), (100, 100), phone["context_id"])


def lock(service, phone, clock):
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    for seq, delta in enumerate((0, .5, 1.1), 1):
        feed(service, phone, clock, seq, 100.+delta)
    assert service.snapshot(sid)["stream"]["can_capture"]


def upload(service, phone, tmp_path, upload_id="upload-1", color="green", size=(80, 60)):
    source = tmp_path / (upload_id + ".png")
    Image.new("RGB", size, color).save(source)
    return service.assets.ingest(source, conversation_id=phone["conversation_id"],
        session_id=phone["session_id"], upload_id=upload_id, filename="test.png", content_type="image/png")


def test_context_frozen_pairing_single_use_and_scoped_token(setup):
    service, phone, clock = setup
    assert service.authorize(phone["token"]) == phone["session_id"]
    assert service.context(phone["context_id"])["design"]["model"] == "fake"
    same = service.publish_context(context())
    assert same["context_id"] == phone["context_id"]
    published = service.publish_context(context("conversation-2", title="Other project"))
    old = service.snapshot(phone["session_id"])
    assert old["conversation_id"] == "conversation-1"
    assert old["available_context"]["context_id"] == published["context_id"]
    with pytest.raises(HTTPException, match="401"):
        service.authorize("wrong-token")
    pairing = service.create_pairing("conversation-2", "http://192.168.1.5:8100")
    assert json.loads(pairing["qr_payload"])["type"] == "tinkro-mobile"
    service.pair(pairing["code"], "Second")
    with pytest.raises(HTTPException) as error:
        service.pair(pairing["code"], "Replay")
    assert error.value.status_code == 401
    expired = service.create_pairing("conversation-2", "http://192.168.1.5:8100")
    clock.now += 301
    with pytest.raises(HTTPException):
        service.pair(expired["code"], "Late")


def mobile_workspace(service):
    payload = context()
    payload["design"]["current"] = {"id": "project", "revision": 3}
    payload["context"].update(debug_session_id="desktop-case-A", project_version=3,
        guide={"run": 2, "confirmed": ["wire-1"]}, debug_context={
            "code": "print('current code')", "wiring_target": {"component_id": "hc-sr04", "wire_id": "wire-2"}})
    published = service.publish_context(payload)
    pair = service.create_pairing(payload["conversation_id"], "http://192.168.1.5:8100")
    return payload, service.pair(pair["code"], "Paired workspace"), published


def test_mobile_ignores_only_runtime_debug_id_before_hash_and_save_preserving_lock_and_ticket(setup, tmp_path):
    service, _, clock = setup
    payload, phone, published = mobile_workspace(service)
    sid = phone["session_id"]
    lock(service, phone, clock)
    original_lock = deepcopy(service.sessions[sid]["stream"])
    for replacement in ("desktop-case-B", "", None):
        current = deepcopy(payload)
        current["context"]["debug_session_id"] = replacement
        next_context = service.publish_context(current)
        assert next_context["context_id"] == published["context_id"]
        assert "debug_session_id" not in next_context["context"]
        assert service.sessions[sid]["stream"] == original_lock
    without_id = deepcopy(payload)
    del without_id["context"]["debug_session_id"]
    assert service.publish_context(without_id)["context_id"] == published["context_id"]
    assert payload["context"]["debug_session_id"] == "desktop-case-A", "Do not mutate the desktop caller"
    stored = json.loads((service.root / "contexts" / (published["context_id"]+".json")).read_text(encoding="utf-8"))
    assert "debug_session_id" not in stored["context"]
    assert stored["context"]["debug_context"] == payload["context"]["debug_context"]
    ticket = service.capture_ticket(sid)
    original_ticket = deepcopy(service.tickets[ticket["ticket_id"]])
    service.publish_context({**payload, "context": {**payload["context"], "debug_session_id": "restored-again"}})
    assert service.tickets[ticket["ticket_id"]] == original_ticket
    asset = upload(service, phone, tmp_path)
    packet = asyncio.run(service.finalize_capture(sid, dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="same-workspace-photo")))
    assert packet["context_id"] == published["context_id"]
    assert service.state.mobile_photo.calls[-1][1]["context"]["debug_context"] == payload["context"]["debug_context"]


@pytest.mark.parametrize("changed", ["target", "round", "version", "code", "guide", "epoch"])
def test_mobile_actual_workspace_changes_still_revoke_lock(setup, changed):
    service, _, clock = setup
    payload, phone, published = mobile_workspace(service)
    lock(service, phone, clock)
    if changed == "target":
        payload["context"]["debug_context"]["wiring_target"]["wire_id"] = "wire-3"
    elif changed == "round":
        payload["round"] += 1
    elif changed == "version":
        payload["design"]["current"]["revision"] += 1
        payload["context"]["project_version"] += 1
    elif changed == "code":
        payload["context"]["debug_context"]["code"] = "print('changed')"
    elif changed == "guide":
        payload["context"]["guide"]["confirmed"].append("wire-2")
    else:
        service.state.assistant.read = lambda *args: {"context_epoch": 1}
    next_context = service.publish_context(payload)
    assert next_context["context_id"] != published["context_id"]
    assert not service.snapshot(phone["session_id"])["stream"]["can_capture"]
    assert service.snapshot(phone["session_id"])["stream"]["reason"] == "desktop_context_changed"


def test_mobile_plain_message_keeps_current_wiring_and_code_without_desktop_debug_case(setup):
    service, _, _ = setup
    payload, phone, published = mobile_workspace(service)
    service.send(phone["session_id"], dict(request_id="phone-text", text="How do I wire this?",
        context_id=published["context_id"], asset_ids=[]))
    cid, message = service.state.assistant.sent[-1]
    assert cid == phone["conversation_id"] and message["source"] == "mobile"
    assert "debug_session_id" not in message["context"]
    assert message["context"]["debug_context"] == payload["context"]["debug_context"]
    assert message["context"]["guide"] == payload["context"]["guide"]
    assert message["round"] == payload["round"]
    assert message["design"]["current"] == payload["design"]["current"]


def test_profile_and_publisher_metrics_are_generation_scoped_diagnostics_only(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    stream = asyncio.run(service.start_stream(sid, bitrate_kbps=12000))
    assert stream["bitrate_kbps"] == service.rtc.bitrate_kbps == 12000
    payload = dict(generation=stream["generation"], capture_fps=30., send_fps=29.8,
                   send_bitrate_kbps=8123., width=1080, height=1920, rtt_ms=15., quality_limitation_reason="none",
                   publisher_connected=True, can_capture=True, received_frames=999)
    before = deepcopy(service.sessions[sid]["stream"])
    result = service.publisher_metrics(sid, payload)
    assert result["send_fps"] == 29.8 and result["reported_at"] == clock.wall()
    assert set(service.sessions[sid]["stream"]) == set(before)
    assert {k:v for k,v in service.sessions[sid]["stream"].items() if k != "publisher_stats"} == {k:v for k,v in before.items() if k != "publisher_stats"}
    assert not service.snapshot(sid)["stream"]["publisher_connected"]
    assert not service.snapshot(sid)["stream"]["can_capture"]
    newer = asyncio.run(service.start_stream(sid))
    assert newer["publisher_stats"] is None and newer["bitrate_kbps"] == 8000
    with pytest.raises(HTTPException) as error:
        service.publisher_metrics(sid, payload)
    assert error.value.status_code == 409
    asyncio.run(service.stop_stream(sid))
    with pytest.raises(HTTPException):
        service.publisher_metrics(sid, {**payload, "generation": newer["generation"]})
    assert service.snapshot(sid)["stream"]["publisher_stats"] is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, True, "30"])
def test_publisher_metrics_reject_invalid_numbers_without_state_change(setup, bad):
    service, phone, _ = setup
    sid = phone["session_id"]
    stream = asyncio.run(service.start_stream(sid))
    with pytest.raises(HTTPException) as error:
        service.publisher_metrics(sid, {"generation": stream["generation"], "send_fps": bad})
    assert error.value.status_code == 422
    assert service.snapshot(sid)["stream"]["publisher_stats"] is None


def test_video_receipt_expiry_revokes_lock_once_and_old_metrics_cannot_restore_live_status(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    lock(service, phone, clock)
    stream = service.sessions[sid]["stream"]
    generation = stream["generation"]
    asyncio.run(service.on_video_metrics(sid, generation, {"video_fps": 30., "received_frames": 3}))
    stream.update(recognition_fps=2.9, recognition_ms=20.)
    receipt_wall = stream["video_received_at"]
    # Wall-clock adjustment is display-only, never a freshness lease.
    service.wall = lambda: clock.wall()+100000
    live = service.snapshot(sid)["stream"]
    assert live["video_receive_fresh"] and live["video_receive_seq"] == 3
    assert live["video_received_at"] == receipt_wall and live["video_receive_age_ms"] == 0
    clock.now += 1.5
    assert service.snapshot(sid)["stream"]["video_receive_fresh"]
    clock.now += .001
    assert service._expire_stream(service.sessions[sid]) is True
    assert service._expire_stream(service.sessions[sid]) is False  # watcher broadcasts only the transition
    stale = service.snapshot(sid)["stream"]
    assert stale["active"] and stale["generation"] == generation
    assert not stale["video_receive_fresh"] and not stale["publisher_connected"] and not stale["can_capture"]
    assert stale["reason"] == "video_receive_stalled"
    assert stale["video_fps"] == stale["recognition_fps"] == 0 and stale["recognition_ms"] is None
    assert stale["video_receive_age_ms"] == 1501 and stale["recognition"] is None
    asyncio.run(service.on_video_metrics(sid, generation, {"video_fps": 30, "received_frames": 999,
        "publisher_connected": True, "last_video_received": clock(), "server_metrics": {"updated_at": service.wall()}}))
    service.publisher_metrics(sid, {"generation": generation, "capture_fps": 30., "send_fps": 30.})
    assert not service.snapshot(sid)["stream"]["publisher_connected"]
    assert service.snapshot(sid)["stream"]["video_receive_seq"] == 3
    service.on_receive(sid, generation, 3, clock(), clock.wall(), (100, 100))  # repeated identity is not a new frame
    assert not service.snapshot(sid)["stream"]["video_receive_fresh"]
    service.on_receive(sid, generation, 4, clock(), clock.wall(), (100, 100))
    resumed = service.snapshot(sid)["stream"]
    assert resumed["publisher_connected"] and resumed["video_receive_fresh"]
    assert not resumed["can_capture"] and resumed["video_fps"] is None
    before = deepcopy(service.sessions[sid])
    service.on_receive(sid, generation-1, 1000, clock(), clock.wall(), (100, 100))
    assert service.sessions[sid] == before


def test_inference_stall_does_not_claim_video_stopped_and_receipts_are_not_per_frame_broadcasts(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    lock(service, phone, clock)
    generation = service.sessions[sid]["stream"]["generation"]
    notices = []
    service.notify = lambda session: notices.append(session["stream"]["reason"])
    for seq in range(4, 65):
        clock.now += 1/30
        service.on_receive(sid, generation, seq, clock(), clock.wall(), (100, 100))
    assert not notices, "The full receive rate must not broadcast whole session snapshots"
    asyncio.run(service.on_video_metrics(sid, generation, {"video_fps": 30.}))
    value = service.snapshot(sid)["stream"]
    assert value["publisher_connected"] and value["video_receive_fresh"] and value["video_fps"] == 30
    assert value["reason"] == "preview_expired" and not value["can_capture"]
    assert value["recognition_fps"] == 0 and value["recognition_ms"] is None
    asyncio.run(service.stop_stream(sid))
    stopped = deepcopy(service.snapshot(sid)["stream"])
    service.on_receive(sid, generation, 65, clock(), clock.wall(), (100, 100))
    assert service.snapshot(sid)["stream"] == stopped


def test_snapshot_expiry_does_not_consume_the_watchers_single_stale_notification(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    lock(service, phone, clock)

    async def scenario():
        listener = service.subscribe(sid=sid)
        clock.now += 1.6
        assert service.snapshot(sid)["stream"]["reason"] == "video_receive_stalled"
        assert "_expiry_pending" not in service.snapshot(sid)["stream"]
        watcher = asyncio.create_task(service._watch())
        try:
            event = await asyncio.wait_for(listener[3].get(), 1)
            assert event["session"]["stream"]["publisher_connected"] is False
            await asyncio.sleep(.3)
            assert listener[3].empty()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            service.unsubscribe(listener)
    asyncio.run(scenario())


def test_preview_requires_unique_fresh_frames_one_second_and_loses_lock(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    feed(service, phone, clock, 1, 100.)
    feed(service, phone, clock, 1, 100.6)
    feed(service, phone, clock, 2, 100.7)
    assert service.snapshot(sid)["stream"]["state"] == "hold_still"
    feed(service, phone, clock, 3, 101.1)
    assert service.snapshot(sid)["stream"]["can_capture"]
    clock.now += .4
    assert 1000 <= service.snapshot(sid)["stream"]["valid_for_ms"] <= 1100
    feed(service, phone, clock, 4, 101.6, offset=10)
    assert service.snapshot(sid)["stream"]["state"] == "hold_still"
    feed(service, phone, clock, 5, 102.2, sharp=False)
    assert service.snapshot(sid)["stream"]["state"] == "finding"
    assert service.snapshot(sid)["stream"]["model_runtime"] == {"provider": "fake"}


def test_slow_drift_and_frame_gap_cannot_accumulate_stability(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    for seq, delta in enumerate((0, .5, 1.1), 1):
        # Each 4px step is within 8% of the 84.9px board diagonal, but the
        # cumulative 8px movement must reset the original anchor.
        feed(service, phone, clock, seq, 100.+delta, offset=(seq-1)*4)
    assert service.snapshot(sid)["stream"]["state"] == "hold_still"
    feed(service, phone, clock, 4, 106., offset=6)
    assert service.snapshot(sid)["stream"]["state"] == "hold_still"
    clock.now = 108.
    assert service.snapshot(sid)["stream"]["state"] == "finding"
    with pytest.raises(HTTPException):
        service.capture_ticket(sid)


def test_stale_generation_expired_inference_and_context_revoke(setup):
    service, phone, clock = setup
    lock(service, phone, clock)
    sid = phone["session_id"]
    generation = service.snapshot(sid)["stream"]["generation"]
    service.accept_preview(sid, generation-1, 99, clock.now, preview(), (100, 100), phone["context_id"])
    assert service.snapshot(sid)["stream"]["preview_seq"] == 3
    clock.now = 104.
    service.accept_preview(sid, generation, 4, 101.2, preview(), (100, 100), phone["context_id"])
    assert not service.snapshot(sid)["stream"]["can_capture"]


def stability_scene(translation=(0, 0), angle=0., scale=1., portrait=False):
    board = np.float64([[200, 300], [600, 300], [600, 600], [200, 600]])
    target = np.float64([[850, 400], [1050, 400], [1050, 500], [850, 500]])
    radians = np.deg2rad(angle)
    rotation = np.array([[np.cos(radians), -np.sin(radians)], [np.sin(radians), np.cos(radians)]])
    objects = []
    for cid, quad in (("raspberry-pi-5", board), ("hc-sr04", target)):
        # Rotate/scale each observed object around its center so angle and
        # size tests cannot pass merely because their translation is small.
        quad = (quad-quad.mean(0)) @ rotation.T * scale + quad.mean(0) + translation
        if portrait:
            quad = np.column_stack((1080-quad[:, 1], quad[:, 0]))
        objects.append(dict(id=cid, outline_px=quad.tolist(), confidence=.95))
    return objects


def stability_feed(service, phone, clock, seq, stamp, *, portrait=False, **changes):
    sid = phone["session_id"]
    generation = service.sessions[sid]["stream"]["generation"]
    size = (1080, 1920) if portrait else (1920, 1080)
    clock.now = stamp
    service.on_receive(sid, generation, seq, stamp, clock.wall(), size)
    result = preview(**{"target_id": "hc-sr04", "objects": stability_scene(portrait=portrait), **changes})
    service.accept_preview(sid, generation, seq, stamp, result, size, phone["context_id"])
    return service.snapshot(sid)["stream"]


def test_phone_stability_is_identical_for_landscape_and_rotated_portrait_pixels(setup):
    service, phone, clock = setup
    traces = []
    for run, portrait in enumerate((False, True)):
        asyncio.run(service.start_stream(phone["session_id"]))
        trace = []
        for seq, (stamp, offset) in enumerate(((0, (0, 0)), (.5, (6, -4)), (1.1, (-5, 6)), (1.4, (55, 0))), 1):
            value = stability_feed(service, phone, clock, seq, 100.+10*run+stamp, portrait=portrait,
                objects=stability_scene(translation=offset, portrait=portrait))
            trace.append((value["state"], value["can_capture"]))
        traces.append(trace)
    assert traces[0] == traces[1] == [("hold_still", False), ("hold_still", False), ("locked", True), ("hold_still", False)]


@pytest.mark.parametrize("movement", [dict(translation=(50, 0)), dict(angle=12), dict(scale=1.18)])
def test_phone_translation_rotation_and_scale_independently_restart_hold(setup, movement):
    service, phone, clock = setup
    asyncio.run(service.start_stream(phone["session_id"]))
    for seq, stamp in enumerate((100., 100.5, 101.1), 1):
        value = stability_feed(service, phone, clock, seq, stamp)
    assert value["can_capture"]
    value = stability_feed(service, phone, clock, 4, 101.4, objects=stability_scene(**movement))
    assert value["state"] == "hold_still" and not value["can_capture"]
    assert service.sessions[phone["session_id"]]["stream"]["stable_count"] == 1


@pytest.mark.parametrize("invalid", [dict(sharp=False, reason="improve_focus_or_light"),
                                     dict(board_present=False, objects=[], reason="find_board_and_component")])
def test_one_invalid_sample_retains_short_candidate_but_revokes_ticket_until_current_good_frame(setup, invalid):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    for seq, stamp in enumerate((100., 100.5, 101.1), 1):
        stability_feed(service, phone, clock, seq, stamp)
    stream = service.sessions[sid]["stream"]
    anchor, times = deepcopy(stream["anchor"]), list(stream["stable_times"])
    value = stability_feed(service, phone, clock, 4, 101.35, quality={"current_sample": 4}, **invalid)
    assert not value["can_capture"] and value["state"] == "finding"
    assert value["reason"] == invalid["reason"] and value["quality"] == {"current_sample": 4}
    assert value["objects"] == invalid.get("objects", stability_scene())
    assert not {"anchor", "stable_times", "qualified_received", "invalid_count", "lock_id"} & value.keys()
    assert stream["anchor"] == anchor and stream["stable_times"] == times and stream["lock_id"] is None
    with pytest.raises(HTTPException, match="mobile_capture_not_locked"):
        service.capture_ticket(sid)
    recovered = stability_feed(service, phone, clock, 5, 101.6)
    assert recovered["can_capture"] and recovered["preview_seq"] == 5
    assert stream["anchor"] == anchor and stream["invalid_count"] == 0
    assert len(stream["stable_times"]) == 3, "Old history outside the recent 1.4s window is discarded"
    assert service.capture_ticket(sid)["preview_seq"] == 5


@pytest.mark.parametrize("interruption", ["two_invalid", "dropout_timeout", "context", "generation", "ttl"])
def test_long_invalid_or_source_changes_clear_candidate_and_cannot_relock_from_old_history(setup, interruption):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    for seq, stamp in enumerate((100., 100.5, 101.1), 1):
        stability_feed(service, phone, clock, seq, stamp)
    stability_feed(service, phone, clock, 4, 101.3, sharp=False)
    if interruption == "two_invalid":
        stability_feed(service, phone, clock, 5, 101.5, sharp=False)
    elif interruption == "dropout_timeout":
        clock.now = 101.801
        service.snapshot(sid)
    elif interruption == "context":
        service.publish_context(context(title="Changed lesson"))
    elif interruption == "generation":
        asyncio.run(service.start_stream(sid))
    else:
        clock.now = 103.
        service.snapshot(sid)
    stream = service.sessions[sid]["stream"]
    assert stream["anchor"] is None and stream["stable_times"] == [] and not stream["can_capture"]
    with pytest.raises(HTTPException, match="mobile_capture_not_locked"):
        service.capture_ticket(sid)
    if interruption != "context":
        result = stability_feed(service, phone, clock, 6, max(clock.now, 101.6)+.01)
        assert not result["can_capture"] and stream["stable_count"] == 1


def test_stability_cannot_count_duplicate_source_timestamps_or_out_of_order_sequence(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    stability_feed(service, phone, clock, 1, 100.)
    stability_feed(service, phone, clock, 2, 100.5)
    clock.now = 101.1
    for seq, stamp in ((2, 101.1), (3, 100.5), (4, 100.4)):
        service.accept_preview(sid, 1, seq, stamp,
            preview(target_id="hc-sr04", objects=stability_scene()), (1920, 1080), phone["context_id"])
    stream = service.sessions[sid]["stream"]
    assert stream["stable_count"] == 2 and stream["preview_seq"] == 2 and not stream["can_capture"]
    assert stability_feed(service, phone, clock, 5, 101.1)["can_capture"]


def test_small_angle_scale_jitter_and_target_translation_share_the_pi_anchor_scale(setup):
    service, phone, clock = setup
    asyncio.run(service.start_stream(phone["session_id"]))
    stability_feed(service, phone, clock, 1, 100.)
    for seq, stamp in ((2, 100.5), (3, 101.1)):
        objects = stability_scene(angle=2 if seq == 2 else -2, scale=1.03 if seq == 2 else .98)
        # 35px is 7% of Pi's 500px diagonal, but 15.7% of this smaller
        # module's own diagonal. Required objects deliberately share Pi's D.
        objects[1]["outline_px"] = (np.asarray(objects[1]["outline_px"]) + [35, 0]).tolist()
        value = stability_feed(service, phone, clock, seq, stamp, objects=objects)
    assert value["can_capture"]


def test_long_hold_keeps_fixed_anchor_but_only_recent_valid_sample_times(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    for index in range(60):
        value = stability_feed(service, phone, clock, index+1, 100.+index/3)
    stream = service.sessions[sid]["stream"]
    assert value["can_capture"] and stream["stable_count"] in (4, 5)
    assert clock.now-stream["stable_times"][0] <= 1.4
    assert stream["anchor"] == {obj["id"]: obj["outline_px"] for obj in stability_scene()}
    # A single new good image after a gap cannot borrow this old long hold.
    value = stability_feed(service, phone, clock, 61, clock.now+.8)
    assert not value["can_capture"] and stream["stable_count"] == 1


def test_small_target_reversed_semantic_winding_cannot_hide_inside_large_pi_tolerance(setup):
    from app.mobile_stability import stable_geometry
    service, phone, clock = setup
    sid = phone["session_id"]
    objects = stability_scene()
    target = np.float64([[850, 400], [870, 400], [870, 420], [850, 420]])
    objects[1]["outline_px"] = target.tolist()
    reversed_target = target[[0, 3, 2, 1]]
    # This square has unchanged center/scale and its maximum 28.3px corner
    # displacement is below the large Pi's 60px corner tolerance. A fit of
    # rotation alone cannot distinguish this reflected semantic ordering.
    np.testing.assert_array_equal(target.mean(0), reversed_target.mean(0))
    assert np.linalg.norm(target-target.mean(0)) == np.linalg.norm(reversed_target-reversed_target.mean(0))
    assert np.max(np.linalg.norm(target-reversed_target, axis=1)) < 60
    anchor = {obj["id"]: obj["outline_px"] for obj in objects}
    mirrored = {**anchor, "hc-sr04": reversed_target.tolist()}
    assert not stable_geometry(anchor, mirrored)
    # A common 90-degree rotation preserves the winding of both observations.
    rotated = {name: np.column_stack((1080-np.asarray(quad)[:, 1], np.asarray(quad)[:, 0])).tolist()
               for name, quad in anchor.items()}
    assert stable_geometry(rotated, rotated)
    asyncio.run(service.start_stream(sid))
    for seq, stamp in enumerate((100., 100.5, 101.1), 1):
        value = stability_feed(service, phone, clock, seq, stamp, objects=objects)
    assert value["can_capture"]
    changed = deepcopy(objects)
    changed[1]["outline_px"] = reversed_target.tolist()
    value = stability_feed(service, phone, clock, 4, 101.4, objects=changed)
    assert value["state"] == "hold_still" and not value["can_capture"]
    assert service.sessions[sid]["stream"]["stable_count"] == 1
    service.publish_context(context(title="New state"))
    feed(service, phone, clock, 5, 104.1)
    assert not service.snapshot(sid)["stream"]["can_capture"]


def test_real_video_metrics_enable_preview_for_frozen_context_without_capture_lock(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    async def scenario():
        generation = (await service.start_stream(sid))["generation"]
        service.publish_context(context(title="New desktop state"))
        service.accept_preview(sid, generation, 1, clock(), preview(), (1080, 1920), phone["context_id"])
        assert not service.snapshot(sid)["stream"]["publisher_connected"]
        service.on_receive(sid, generation, 1324, clock(), clock.wall(), (1080, 1920))
        await service.on_video_metrics(sid, generation, {"received_frames": 1324, "video_fps": 29.77, "video_size": [1080, 1920]})
        session = service.snapshot(sid)
        stream = session["stream"]
        assert stream["active"] and stream["publisher_connected"]
        assert stream["received_frames"] == 1324 and stream["video_size"] == [1080, 1920]
        assert stream["video_fps"] == 29.77
        assert not stream["can_capture"]
        assert session["context_id"] == phone["context_id"] != service.latest["context_id"]
        with pytest.raises(HTTPException) as rejected:
            service.capture_ticket(sid)
        assert rejected.value.status_code == 409
    asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["stop", "rtc_failed"])
def test_video_metrics_require_real_frames_current_generation_and_open_stream(setup, ending):
    service, phone, clock = setup
    sid = phone["session_id"]
    async def scenario():
        original = (await service.start_stream(sid))["generation"]
        for values in ({"received_frames": 0, "video_fps": 30}, {"video_fps": 30}):
            await service.on_video_metrics(sid, original, values)
            assert not service.snapshot(sid)["stream"]["publisher_connected"]
        current = (await service.start_stream(sid))["generation"]
        before = service.snapshot(sid)["stream"]
        await service.on_video_metrics(sid, original, {"received_frames": 20, "video_fps": 30})
        assert service.snapshot(sid)["stream"] == before
        await service.on_video_metrics(sid, current, {"received_frames": 20, "video_fps": 30})
        assert not service.snapshot(sid)["stream"]["publisher_connected"]
        service.on_receive(sid, current, 20, clock(), clock.wall(), (100, 100))
        assert service.snapshot(sid)["stream"]["publisher_connected"]
        if ending == "stop":
            await service.stop_stream(sid)
        else:
            await service.on_rtc_state(sid, current, "failed")
        stopped = service.snapshot(sid)["stream"]
        assert not stopped["publisher_connected"] and not stopped["active"]
        await service.on_video_metrics(sid, current, {"received_frames": 99, "video_fps": 30})
        assert service.snapshot(sid)["stream"] == stopped
    asyncio.run(scenario())


def test_hold_compares_selected_target_and_board_not_unrelated_objects(setup):
    service, phone, clock = setup
    sid = phone["session_id"]
    asyncio.run(service.start_stream(sid))
    board = preview()["objects"][0]
    target = {**deepcopy(board), "id": "hc-sr04"}
    unrelated = {**deepcopy(board), "id": "mrd-tf240-8p-cs"}
    for seq, stamp in enumerate((100., 100.5, 101.1), 1):
        feed(service, phone, clock, seq, stamp, target_id="hc-sr04", objects=[board, target]+([unrelated] if seq%2 else []))
    assert service.snapshot(sid)["stream"]["can_capture"]
    moved = {**target, "outline_px": [[x+10, y] for x, y in target["outline_px"]]}
    feed(service, phone, clock, 4, 101.3, target_id="hc-sr04", objects=[board, moved])
    assert not service.snapshot(sid)["stream"]["can_capture"]


def test_image_normalized_orientation_hash_and_retry_identity(setup, tmp_path):
    service, phone, _ = setup
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 50), "red").save(source, exif=exif)
    args = dict(conversation_id=phone["conversation_id"], session_id=phone["session_id"],
                upload_id="rotated", filename="rotated.jpg", content_type="image/jpeg")
    asset = service.assets.ingest(source, **args)
    assert (asset["width"], asset["height"]) == (50, 80)
    path = service.assets.path(asset["id"])
    assert path.name == "photo.jpg"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]
    assert service.assets.ingest(source, **args)["id"] == asset["id"]
    Image.new("RGB", (80, 50), "blue").save(source)
    with pytest.raises(HTTPException) as error:
        service.assets.ingest(source, **args)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        service.assets.authorize(asset["id"], "different-conversation")
    assert error.value.status_code == 403


def test_image_pixel_cap_and_media_limit(setup, tmp_path, monkeypatch):
    service, phone, _ = setup
    monkeypatch.setattr("app.mobile.MAX_IMAGE_PIXELS", 1000)
    asset = upload(service, phone, tmp_path, size=(200, 100))
    assert asset["width"]*asset["height"] <= 1000
    paths, metadata = service.assets.resolve_images([asset["id"]])
    assert paths == [service.assets.path(asset["id"])]
    assert metadata[0]["timestamp_s"] is None
    with pytest.raises(HTTPException):
        service.assets.resolve_images([asset["id"]]*2)
    with pytest.raises(HTTPException):
        service.assets.describe("../../outside")


def test_video_extracts_bounded_timestamped_frames_and_rejects_long_video(setup, tmp_path, monkeypatch):
    service, phone, _ = setup
    calls = []
    duration = [60.]

    def subprocess_run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] <= 25
        if command[0] == "ffprobe":
            return SimpleNamespace(stdout=json.dumps(dict(streams=[dict(codec_type="video", width=640, height=480, duration=duration[0])])).encode())
        Image.new("RGB", (64, 48), "green").save(command[-1])
        return SimpleNamespace(stdout=b"")

    monkeypatch.setattr("app.mobile._program", lambda name: name)
    monkeypatch.setattr("app.mobile.subprocess.run", subprocess_run)
    source = tmp_path / "video.mov"
    source.write_bytes(b"fake-video")
    args = dict(conversation_id=phone["conversation_id"], session_id=phone["session_id"], filename="video.mov", content_type="video/quicktime")
    asset = service.assets.ingest(source, upload_id="video", **args)
    paths, metadata = service.assets.resolve_images([asset["id"]])
    assert len(paths) == 8 and len(calls) == 9
    assert [m["timestamp_s"] for m in metadata] == [3.75+i*7.5 for i in range(8)]
    assert all(m["audio_analysed"] is False for m in metadata)
    duration[0] = 60.1
    with pytest.raises(HTTPException) as error:
        service.assets.ingest(source, upload_id="video-too-long", **args)
    assert error.value.detail == "mobile_video_max_60_seconds"


def test_actual_ffmpeg_synthetic_video_extracts_without_upscaling(setup, tmp_path):
    import subprocess
    from app.mobile import _program
    try:
        binary = _program("ffmpeg")
        _program("ffprobe")
    except HTTPException:
        pytest.skip("Local FFmpeg not installed")
    service, phone, _ = setup
    source = tmp_path / "synthetic.mp4"
    subprocess.run([binary, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=red:s=64x48:r=10",
                    "-t", "1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(source)],
                   check=True, capture_output=True, timeout=10,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    asset = service.assets.ingest(source, conversation_id=phone["conversation_id"], session_id=phone["session_id"],
        upload_id="actual-video", filename="synthetic.mp4", content_type="video/mp4")
    paths, metadata = service.assets.resolve_images([asset["id"]])
    assert len(paths) == 1 and metadata[0]["timestamp_s"] == .5
    with Image.open(paths[0]) as image:
        assert image.size == (64, 48)
    assert service.assets.path(asset["id"]).read_bytes() == source.read_bytes()


def test_capture_survives_rtc_handoff_persists_and_deduplicates(setup, tmp_path):
    service, phone, clock = setup
    lock(service, phone, clock)
    sid = phone["session_id"]
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    body = dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="capture-request")

    async def scenario():
        await service.stop_stream(sid)
        first, second = await asyncio.gather(service.finalize_capture(sid, body), service.finalize_capture(sid, body))
        assert first == second
        assert first["conversation_id"] == phone["conversation_id"]
        assert first["image_sha256"] == asset["sha256"]
        assert len(service.state.mobile_photo.calls) == 1
        assert service.view(sid)["capture_id"] == first["capture_id"]
        assert service.view(sid, dict(capture_id=first["capture_id"], wire_id="wire-1"))["wire_id"] == "wire-1"
        with pytest.raises(HTTPException):
            service.view(sid, dict(capture_id=first["capture_id"], wire_id="wrong-wire"))
        with pytest.raises(HTTPException) as error:
            await service.finalize_capture(sid, {**body, "asset_id": "other"})
        assert error.value.status_code == 409
        reloaded = MobileService(service.state, service.root, rtc_factory=RTC)
        assert reloaded.get_capture(first["capture_id"]) == first
    asyncio.run(scenario())


def test_context_join_invalidates_ticket_and_releases_geometry(setup, tmp_path):
    service, phone, clock = setup
    lock(service, phone, clock)
    sid = phone["session_id"]
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    service.publish_context(context("conversation-2"))

    async def scenario():
        joined = await service.join(sid)
        assert joined["conversation_id"] == "conversation-2"
        assert service.state.mobile_photo.released == [sid]
        with pytest.raises(HTTPException):
            await service.finalize_capture(sid, dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="capture-request"))
    asyncio.run(scenario())


def test_capture_rejects_expired_ticket_and_pre_ticket_upload(setup, tmp_path):
    service, phone, clock = setup
    lock(service, phone, clock)
    asset = upload(service, phone, tmp_path)
    meta = service.assets.root / asset["id"] / "asset.json"
    value = json.loads(meta.read_text())
    value["created_at"] = clock.wall()-1
    meta.write_text(json.dumps(value))
    ticket = service.capture_ticket(phone["session_id"])
    body = dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="capture-request")
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.finalize_capture(phone["session_id"], body))
    assert error.value.detail == "mobile_fresh_camera_photo_required"
    clock.now += 121
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.finalize_capture(phone["session_id"], body))
    assert error.value.detail == "mobile_capture_ticket_expired"


def test_capture_rejects_mismatched_pixel_identity(setup, tmp_path):
    service, phone, clock = setup
    lock(service, phone, clock)
    ticket = service.capture_ticket(phone["session_id"])
    asset = upload(service, phone, tmp_path)
    service.state.mobile_photo.analyze = lambda *args: dict(capture_id="bad", image_sha256="wrong", video_size=[80, 60])
    with pytest.raises(HTTPException) as error:
        asyncio.run(service.finalize_capture(phone["session_id"], dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="capture-request")))
    assert error.value.detail == "mobile_capture_image_identity_mismatch"
    assert not service.captures


def test_messages_freeze_shared_context_and_media_scope(setup, tmp_path):
    service, phone, _ = setup
    asset = upload(service, phone, tmp_path)
    body = dict(request_id="message-1", text="Explain this", asset_ids=[asset["id"]], context_id=phone["context_id"])
    service.send(phone["session_id"], body)
    cid, sent = service.state.assistant.sent[0]
    assert cid == phone["conversation_id"]
    assert sent["source"] == "mobile" and sent["asset_ids"] == [asset["id"]]
    assert sent["design"]["model"] == "fake"
    assert sent["context"]["mobile_context_id"] == phone["context_id"]
    with pytest.raises(HTTPException):
        service.send(phone["session_id"], {**body, "context_id": "wrong"})


def test_state_event_queue_keeps_latest_view_and_shutdown_closes_owned_resources(setup):
    service, phone, clock = setup

    async def scenario():
        listener = service.subscribe(sid=phone["session_id"])
        service.view(phone["session_id"], dict(capture_id=None, wire_id=None))
        service.view(phone["session_id"], dict(capture_id=None, wire_id=None))
        await asyncio.sleep(0)
        event = listener[3].get_nowait()
        assert event["type"] == "state" and event["session"]["view"]["revision"] == 2
        assert listener[3].empty()
        service.unsubscribe(listener)
        await service.start()
        await service.close()
        assert service.state.mobile_photo.closed and service.monitor is None
    asyncio.run(scenario())


def test_disconnect_revokes_pairing_closes_resources_and_restores_desktop_pairing(setup, tmp_path):
    from app.assistant import AssistantService
    service, phone, clock = setup
    sid, cid = phone["session_id"], phone["conversation_id"]
    lock(service, phone, clock)
    ticket = service.capture_ticket(sid)
    asset = upload(service, phone, tmp_path)
    assistant = AssistantService(SimpleNamespace(mobile_service=service), root=tmp_path / "assistant")
    assistant.create(cid)
    assistant.import_messages(cid, "saved-chat", [{"id": "message", "role": "user", "text": "Saved question"}], "legacy-design")
    service.state.assistant = assistant

    async def scenario():
        capture = await service.finalize_capture(sid, dict(ticket_id=ticket["ticket_id"], asset_id=asset["id"], request_id="capture-request"))
        saved_history = assistant.read(cid)
        desktop = service.subscribe(cid=cid)
        mobile = service.subscribe(sid=sid)
        service.notify(service.require(sid))
        await service.disconnect(sid)
        await asyncio.sleep(0)
        assert desktop[3].get_nowait() == {"type": "state", "session": None}
        assert mobile[3].get_nowait()["type"] == "disconnected"
        assert service.desktop_snapshot(cid)["session"] is None
        assert sid not in service.sessions
        assert service.tickets[ticket["ticket_id"]]["invalid"]
        assert service.rtc.closed == [sid]
        assert service.state.mobile_photo.released == [sid]
        with pytest.raises(HTTPException) as revoked:
            service.authorize(phone["token"])
        assert revoked.value.status_code == 401
        service.accept_preview(sid, 1, 99, clock(), preview(), (100, 100), phone["context_id"])
        assert desktop[3].empty()
        assert service.assets.path(asset["id"]).is_file()
        assert service.get_capture(capture["capture_id"]) == capture
        assert assistant.read(cid) == saved_history
        assert AssistantService(SimpleNamespace(), root=assistant.root).read(cid) == saved_history
        assert service.create_pairing(cid, "https://192.168.1.5:8443")["web_url"]
        service.unsubscribe(desktop)
        service.unsubscribe(mobile)
    asyncio.run(scenario())


def test_disconnect_only_removes_own_phone_and_keeps_other_session(setup):
    service, phone, clock = setup
    pairing = service.create_pairing(phone["conversation_id"], "http://192.168.1.5:8100")
    other = service.pair(pairing["code"], "Other phone")
    own_sid, other_sid = phone["session_id"], other["session_id"]
    service.tickets["other-ticket"] = {"session_id": other_sid, "invalid": False}
    before = service.snapshot(other_sid)

    async def scenario():
        desktop = service.subscribe(cid=phone["conversation_id"])
        other_listener = service.subscribe(sid=other_sid)
        await service.disconnect(own_sid)
        await asyncio.sleep(0)
        assert service.authorize(other["token"]) == other_sid
        assert service.snapshot(other_sid) == before
        assert service.desktop_snapshot(phone["conversation_id"])["session"]["session_id"] == other_sid
        assert desktop[3].get_nowait()["session"]["session_id"] == other_sid
        assert other_listener[3].empty()
        assert not service.tickets["other-ticket"]["invalid"]
        assert service.rtc.closed == [own_sid] and service.state.mobile_photo.released == [own_sid]
        service.unsubscribe(desktop)
        service.unsubscribe(other_listener)
    asyncio.run(scenario())
