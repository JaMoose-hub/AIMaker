from copy import deepcopy
from types import SimpleNamespace
import time

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import ComponentPinPosition, ComponentPoseState, ComponentPoseResult
from app.motion_worker import TRACKED_COMPONENT_IDS, MotionFrameState, MotionOverlayWorker
from app.vision.interface import DetectionResult, PinDetection
from app.vision.motion_tracking import MotionTrack, PlanarFlow, transform
from app.vision_worker import DetectionState


def scene():
    frame = np.full((400, 640), 40, np.uint8)
    rng = np.random.default_rng(77)
    frame[100:260, 120:360] = cv2.GaussianBlur(
        rng.integers(15, 245, (160, 240), dtype=np.uint8), (3, 3), 0,
    )
    quad = np.float32([[120, 100], [360, 100], [360, 260], [120, 260]])
    return frame, quad


def pose(quad, frame_id=0, ts=0):
    return {'type': 'detection', 'board_id': 'raspberry-pi-5', 'runtime_revision': 1,
            'frame_id': frame_id, 'ts_ms': ts, 'tracking': 'locked', 'confidence': .9,
            'video_size': [640, 400], 'outline': quad.tolist(),
            'pins': [{'id': 'J8:11', 'x': 145., 'y': 125., 'v': True, 'c': .9}]}


@pytest.mark.parametrize('reason', ['corner_box_inconsistent', 'pcb_boundary_unverified'])
def test_rejected_model_geometry_preserves_only_supported_flow(reason):
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    assert tracker.message is not None
    rejected = pose(quad, frame_id=1, ts=33)
    rejected.update(tracking='searching', outline=None, pins=[],
                    pose_quality={'stability': reason})
    tracker.observe(rejected, frame, 1)
    assert tracker.message is not None
    assert tracker.confirmed_ts == 0
    assert tracker.confirmation_debug['accepted'] is False
    moved = cv2.warpAffine(frame, np.float32([[1, 0, 6], [0, 1, 2]]), (640, 400))
    result = tracker.update(moved, 2, 66)
    assert result is not None
    assert result['frame_id'] == 2
    assert result['pins'][0]['x'] == pytest.approx(151, abs=1)
    # A rejected model proposal cannot preserve geometry on a covered image.
    assert tracker.update(np.full_like(frame, 40), 3, 99, search_budget=lambda: False) is None


@pytest.mark.parametrize('reason', ['corner_box_inconsistent', 'pcb_boundary_unverified'])
def test_rejected_proposal_cannot_seed_or_renew_lease(reason):
    frame, quad = scene()
    rejected = pose(quad, frame_id=1, ts=33)
    rejected.update(tracking='searching', pose_quality={'stability': reason})
    empty = MotionTrack()
    empty.observe(rejected, frame, 1)
    assert empty.message is None
    tracker = MotionTrack(lease_ms=100, outline_lease_ms=200)
    tracker.observe(pose(quad), frame, 1)
    for i in range(1, 8):
        rejected.update(frame_id=i, ts_ms=i*33)
        tracker.observe(rejected, frame, 1)
        result = tracker.update(frame, i, i*33)
        assert tracker.confirmed_ts == 0
        if result is not None and i*33 > 100:
            assert not result['pins']
    assert result is None


@pytest.mark.parametrize('dx,angle,scale', [(6, 0, 1), (0, 2, 1), (3, 1, 1.012)])
def test_translation_rotation_and_scale_follow_each_frame(dx, angle, scale):
    frame, quad = scene()
    tracker = MotionTrack()
    seed = pose(quad)
    tracker.observe(seed, frame, 1)
    for i in range(1, 11):
        affine = cv2.getRotationMatrix2D((240, 180), angle * i, scale ** i)
        affine[:, 2] += [dx * i, i * 2]
        matrix = np.vstack([affine, [0, 0, 1]])
        moved = cv2.warpPerspective(frame, matrix, (640, 400), borderValue=40)
        result = tracker.update(moved, i, i * 33)
        assert result is not None
        assert np.max(np.linalg.norm(np.asarray(result['outline']) - transform(quad, matrix), axis=1)) < 1.0
        expected_pin = transform([[145, 125]], matrix)[0]
        assert np.linalg.norm(np.array([result['pins'][0]['x'], result['pins'][0]['y']]) - expected_pin) < 1
    assert seed == pose(quad), 'tracking must not mutate detector result'


def test_static_frames_stay_fixed_and_model_noise_cannot_tug_track():
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    for i in range(1, 70):
        result = tracker.update(frame, i, i * 33)
        assert result is not None
        tracker.observe(pose(quad + [3, -2], i, i * 33), frame, 1)
        assert np.max(abs(np.asarray(result['outline']) - quad)) < .01


def test_short_occlusion_retains_template_but_never_emits_old_coordinates():
    frame, quad = scene()
    tracker = MotionTrack(recovery_ms=250)
    tracker.observe(pose(quad), frame, 1)
    covered = frame.copy()
    covered[100:240, 120:360] = 80
    assert tracker.update(covered, 1, 33) is None
    assert tracker.recovering
    # Image evidence returns within 250ms: no slow-model reacquisition needed.
    result = tracker.update(frame, 2, 66)
    assert result is not None and result['pose_quality']['recovered']
    assert result['frame_id'] == 2
    assert tracker.update(covered, 3, 99) is None
    assert tracker.update(covered, 4, 330) is None
    assert tracker.message is None
    tracker.observe(pose(quad), frame, 1)  # old result cannot resurrect a lost track
    assert tracker.update(frame, 5, 363) is None
    tracker.observe(pose(quad, 5, 363), frame, 1)
    assert tracker.update(frame, 6, 396) is not None


@pytest.mark.parametrize('dx,angle', [(70, 0), (130, 0), (60, 12), (-75, -10)])
def test_large_image_motion_recovers_without_new_detector_observation(dx, angle):
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    affine = cv2.getRotationMatrix2D((240, 180), angle, 1)
    affine[:, 2] += [dx, 0]
    matrix = np.vstack([affine, [0, 0, 1]])
    moved = cv2.warpPerspective(frame, matrix, (640, 400), borderValue=40)
    result = tracker.update(moved, 1, 33)
    assert result is not None
    assert np.max(np.linalg.norm(np.asarray(result['outline']) - transform(quad, matrix), axis=1)) < 1
    assert result['pins'][0]['x'] == pytest.approx(transform([[145, 125]], matrix)[0, 0], abs=1)


def test_refresh_failure_does_not_erase_valid_lk_points(monkeypatch):
    frame, quad = scene()
    flow = PlanarFlow()
    assert flow.seed(frame, quad)
    flow.steps = 14
    monkeypatch.setattr(cv2, 'goodFeaturesToTrack', lambda *a, **k: None)
    assert flow.step(frame) is not None
    assert flow.points is not None
    assert flow.step(frame) is not None


def test_a_coarse_search_hint_cannot_authorize_an_occluded_object(monkeypatch):
    frame, quad = scene()
    flow = PlanarFlow()
    assert flow.seed(frame, quad)
    monkeypatch.setattr(flow, '_wide_search', lambda _: np.eye(3))
    assert flow.step(np.full_like(frame, 90)) is None


def test_recovery_rejects_wrong_texture_even_at_expected_location():
    frame, quad = scene()
    rng = np.random.default_rng(991)
    wrong = frame.copy()
    wrong[100:260, 120:360] = rng.integers(0, 255, (160, 240), dtype=np.uint8)
    tracker = MotionTrack(recovery_ms=250)
    tracker.observe(pose(quad), frame, 1)
    assert tracker.update(wrong, 1, 33) is None
    assert tracker.update(wrong, 2, 150) is None
    assert tracker.update(wrong, 3, 280) is None
    assert tracker.message is None


def test_features_only_on_background_or_one_small_patch_cannot_seed():
    frame, quad = scene()
    inverse = 255 - frame
    inverse[100:260, 120:360] = 40
    assert not PlanarFlow().seed(inverse, quad)
    inverse[130:150, 160:180] = frame[130:150, 160:180]
    assert not PlanarFlow().seed(inverse, quad)


def test_recovery_search_is_throttled_but_clear_local_texture_recovers_immediately(monkeypatch):
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    calls = []
    monkeypatch.setattr(tracker.flow, '_wide_search', lambda _: calls.append(1))
    covered = np.full_like(frame, 95)
    for i in range(1, 8):
        assert tracker.update(covered, i, i*33) is None
        assert len(calls) == 1
        if i > 1:
            assert tracker.flow.search_deferred
    assert tracker.update(covered, 8, 264) is None
    assert len(calls) == 2
    restored = tracker.update(frame, 9, 297)
    assert restored and restored['tracking'] == 'locked'
    assert restored['pose_quality']['recovered']
    assert len(calls) == 2, 'cooldown must not postpone cheap local reacquisition'


def test_exhausted_search_budget_never_reuses_geometry_or_consumes_cooldown(monkeypatch):
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    calls = []
    monkeypatch.setattr(tracker.flow, '_wide_search', lambda _: calls.append(1))
    covered = np.full_like(frame, 95)
    assert tracker.update(covered, 1, 33, search_budget=lambda: False) is None
    assert calls == [] and tracker.flow.search_deferred
    assert tracker.update(covered, 2, 66, search_budget=lambda: True) is None
    assert calls == [1]


@pytest.mark.parametrize('offset', [(13, 9), (-110, -90), (250, 125)])
def test_cropped_flow_preserves_global_coordinates_near_frame_edges(offset):
    frame, quad = scene()
    origin = np.float64([[1,0,offset[0]], [0,1,offset[1]], [0,0,1]])
    source = cv2.warpPerspective(frame, origin, (640,400), borderValue=40)
    shifted_quad = transform(quad, origin)
    seed = pose(shifted_quad)
    seed['pins'][0].update(x=145+offset[0], y=125+offset[1])
    tracker = MotionTrack()
    tracker.observe(seed, source, 1)
    delta = np.float64([[1,0,4], [0,1,2], [0,0,1]])
    result = tracker.update(cv2.warpPerspective(source,delta,(640,400),borderValue=40), 1, 33)
    assert result and result['tracking'] == 'locked'
    assert result['pins'][0]['x'] == pytest.approx(149+offset[0], abs=1)
    assert result['pins'][0]['y'] == pytest.approx(127+offset[1], abs=1)


def test_worker_recovery_budget_is_one_per_frame_and_fair_to_all_objects(monkeypatch):
    gray, quad = scene()
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    source = FrameSlot(frame, 0, 0, 0)
    detection, components = DetectionState(), ComponentPoseState()
    detection.set(DetectionResult('raspberry-pi-5',0,0,'locked',.9,[],quad.tolist()), source)
    for key in TRACKED_COMPONENT_IDS:
        components.set(ComponentPoseResult(key,0,0,'locked',.9,(640,400),quad,(),'tracking'), source)
    manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1))
    worker = MotionOverlayWorker(FrameBus(), detection, components, manager, MotionFrameState())
    monkeypatch.setattr(PlanarFlow, '_lk_step', lambda *a, **k: None)
    attempted = []
    monkeypatch.setattr(PlanarFlow, '_wide_search', lambda self, _: attempted.append(id(self)))
    counts = []
    for i in range(1, 17):
        packet = worker.process(FrameSlot(frame,i,i*33,i))
        assert packet['recovery_searches'] <= 1
        counts.append(packet['recovery_searches'])
        assert all(p['outline'] is None and not p['pins'] for p in [packet['detection'], *packet['components']])
        assert [p['component_id'] for p in packet['components']] == list(TRACKED_COMPONENT_IDS)
        assert set(packet['timing_ms']['objects']) == {'board', *TRACKED_COMPONENT_IDS}
    assert set(attempted) == {id(t.flow) for t in worker.tracks.values()}
    assert len(attempted) == sum(counts)


@pytest.mark.parametrize('kind', ['resize', 'gap', 'lease', 'backward_time'])
def test_loss_guards(kind):
    frame, quad = scene()
    tracker = MotionTrack(lease_ms=100, outline_lease_ms=100)
    tracker.observe(pose(quad), frame, 1)
    test_frame, ts = frame, 33
    if kind == 'resize': test_frame = frame[:200]
    if kind == 'gap': ts = 500
    if kind == 'lease': ts = 150
    if kind == 'backward_time': ts = -1
    assert tracker.update(test_frame, 1, ts) is None


def test_delayed_model_corroboration_uses_model_frame_not_current_frame():
    frame, quad = scene()
    tracker = MotionTrack(lease_ms=150)
    tracker.observe(pose(quad), frame, 1)
    for i in range(1, 11):
        moved = cv2.warpAffine(frame, np.float32([[1, 0, i * 4], [0, 1, 0]]), (640, 400), borderValue=40)
        result = tracker.update(moved, i, i * 33)
        assert result is not None
        old_i = max(1, i - 1)
        # Even a held detector can corroborate, but only its NEW raw quad.
        delayed = pose(quad, old_i, old_i * 33)
        delayed['tracking'] = 'stale'
        delayed['motion_outline'] = (quad + [old_i * 4, 0]).tolist()
        tracker.observe(delayed, frame, 1)
    assert result['pins'][0]['x'] == pytest.approx(185, abs=.5)


def test_expired_track_accepts_new_paired_lock_without_resetting_seed_watermark():
    frame, quad = scene()
    tracker = MotionTrack(lease_ms=100, outline_lease_ms=100)
    tracker.observe(pose(quad, 1, 0), frame, 1)
    assert tracker.update(frame, 2, 150) is None
    assert tracker.failure_reason == 'semantic_lease_expired'
    tracker.observe(pose(quad, 1, 0), frame, 1)
    assert tracker.message is None  # do not resurrect already consumed image
    tracker.observe(pose(quad, 3, 160), frame, 1)
    result = tracker.update(frame, 4, 193)
    assert result is not None and result['tracking'] == 'locked'


def test_worker_reports_missing_paired_source():
    frame, _ = scene()
    manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1))
    worker = MotionOverlayWorker(FrameBus(), DetectionState(), ComponentPoseState(), manager, MotionFrameState())
    packet = worker.process(FrameSlot(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR), 1, 33, 1))
    assert packet['detection']['pose_quality']['model_source'] == {'paired': False}


def test_objects_have_independent_tracking_and_loss():
    frame, quad = scene()
    first, second = MotionTrack(), MotionTrack()
    for tracker in (first, second): tracker.observe(pose(quad), frame, 1)
    assert first.update(np.full_like(frame, 80), 1, 33) is None
    assert second.update(frame, 1, 33) is not None


@pytest.mark.parametrize('fraction', [.25, .4, .55])
def test_partial_occlusion_follows_visible_texture_without_pins_or_template_pollution(fraction):
    frame, quad = scene()
    covered = frame.copy()
    x_end = 120 + round(240 * fraction)
    rng = np.random.default_rng(357)
    # Textured obstruction rather than a uniform mask: it must not be learned.
    covered[100:260, 120:x_end] = rng.integers(15, 245, (160, x_end-120), dtype=np.uint8)
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    anchor = tracker.flow.anchor
    for i in range(1, 32):
        matrix = np.float64([[1,0,i],[0,1,i*.3],[0,0,1]])
        moved = cv2.warpPerspective(covered, matrix, (640,400), borderValue=40)
        result = tracker.update(moved, i, i*33)
        assert result is not None
        assert result['tracking'] == 'stale' and result['pins'] == []
        assert result['pose_quality']['outline_only']
        # Outline-only extrapolation has a 2%-of-diagonal budget, not a pin-
        # precision promise for the hidden side of the object.
        assert np.max(np.linalg.norm(np.float32(result['outline'])-transform(quad,matrix), axis=1)) < .02*np.linalg.norm(quad[2]-quad[0])
        assert tracker.flow.anchor is anchor, 'never replenish features from a hand'
    clear = cv2.warpPerspective(frame, matrix, (640,400), borderValue=40)
    restored = tracker.update(clear, 32, 1056)
    assert restored['tracking'] == 'locked'
    assert restored['pins'][0]['x'] == pytest.approx(176, abs=1)


def test_one_second_complete_occlusion_hides_then_reacquires_moved_clear_texture():
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    for i in range(1, 6):
        assert tracker.update(np.full_like(frame, 95), i, i*200) is None
        assert tracker.recovering and tracker.message is not None
    matrix = np.float64([[1,0,80],[0,1,8],[0,0,1]])
    restored = tracker.update(cv2.warpPerspective(frame,matrix,(640,400),borderValue=40), 6, 1200)
    assert restored is not None and restored['tracking'] == 'locked'
    assert restored['pins'][0]['x'] == pytest.approx(225, abs=1)
    assert restored['pose_quality']['recovered']


def test_sustained_total_occlusion_expires_without_ever_returning_old_geometry():
    frame, quad = scene()
    tracker = MotionTrack()
    tracker.observe(pose(quad), frame, 1)
    for i in range(1, 10):
        assert tracker.update(np.full_like(frame, 95), i, i*200) is None
    assert tracker.message is None
    assert tracker.update(frame, 10, 2000) is None


def test_old_semantic_lease_only_allows_bounded_outline_never_guidance_pins():
    frame, quad = scene()
    tracker = MotionTrack(lease_ms=100, outline_lease_ms=400)
    tracker.observe(pose(quad), frame, 1)
    outline = tracker.update(frame, 1, 150)
    assert outline['tracking'] == 'stale' and outline['pins'] == []
    assert outline['pose_quality']['reason'] == 'awaiting_model_confirmation'
    assert tracker.update(frame, 2, 300) is not None
    assert tracker.update(frame, 3, 450) is None


def test_fresh_same_frame_model_can_restore_guidance_after_outline_only_lease():
    frame, quad = scene()
    tracker = MotionTrack(lease_ms=100, outline_lease_ms=400)
    tracker.observe(pose(quad), frame, 1)
    assert tracker.update(frame, 1, 150)['pins'] == []
    tracker.observe(pose(quad, 1, 150), frame, 1)
    result = tracker.update(frame, 2, 183)
    assert result['tracking'] == 'locked' and len(result['pins']) == 1


def test_worker_synchronizes_source_frame_and_leaves_verification_state_unchanged():
    gray, quad = scene()
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    source = FrameSlot(frame, 10, 1000, 10)
    result = DetectionResult('raspberry-pi-5', 10, 1000, 'locked', .9,
                             [PinDetection('J8:11', 145, 125, .9)], quad.tolist())
    detection = DetectionState()
    detection.set(result, source)
    components = ComponentPoseState()
    runtime = SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1)
    manager = SimpleNamespace(snapshot=lambda: runtime)
    worker = MotionOverlayWorker(FrameBus(), detection, components, manager, MotionFrameState())
    matrix = np.float32([[1, 0, 6], [0, 1, 4]])
    moved = cv2.warpAffine(frame, matrix, (640, 400), borderValue=(40, 40, 40))
    packet = worker.process(FrameSlot(moved, 11, 1033, 11))
    assert packet['frame_id'] == packet['detection']['frame_id'] == 11
    assert packet['display_only'] is True
    assert packet['image'].startswith('data:image/jpeg;base64,')
    assert packet['detection']['pins'][0]['x'] == pytest.approx(151, abs=.5)
    assert detection.get() is result and result.pins[0].x == 145
    # Same-size camera restart and a runtime switch discard previous templates.
    detection.clear()
    restarted = worker.process(FrameSlot(frame, 0, 1100, 12))
    assert restarted['detection']['tracking'] == 'searching'
    runtime.board_id = 'arduino-uno-q'
    assert worker.process(FrameSlot(frame, 1, 1133, 13)) is None


def test_component_source_pair_cannot_survive_unsynchronized_write():
    gray, _ = scene()
    source = FrameSlot(gray, 1, 0, 1)
    state = ComponentPoseState()
    result = ComponentPoseResult('hc-sr04', 1, 0, 'searching', 0, (640, 400), None, (), 'searching')
    state.set(result, source)
    assert state.get_synchronized('hc-sr04') == (source, result)
    state.set(result)
    assert state.get_synchronized('hc-sr04') is None


def test_three_objects_move_independently_and_one_occlusion_does_not_hide_others(monkeypatch):
    # Raw tracking isolation; display-prediction tests cover the bounded stale outline separately.
    monkeypatch.setattr('app.motion_worker.DisplayPrediction.apply', lambda self, message: message)
    boxes = [(30, 25, 180, 135), (235, 25, 365, 125),
             (465, 25, 565, 125), (235, 235, 395, 355)]
    keys = ['board', *TRACKED_COMPONENT_IDS]
    shifts = [(3, 2), (-4, 3), (5, 4), (-3, -4)]
    rng = np.random.default_rng(345)
    textures = [cv2.GaussianBlur(rng.integers(15, 245, (b-y, r-x), dtype=np.uint8), (3, 3), 0)
                for x, y, r, b in boxes]

    def render(step, hidden=None):
        gray = np.full((400, 640), 40, np.uint8)
        for key, box, texture, (dx, dy) in zip(keys, boxes, textures, shifts):
            if key == hidden:
                continue
            x, y, r, b = box
            gray[y+dy*step:b+dy*step, x+dx*step:r+dx*step] = texture
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    frame = render(0)
    source = FrameSlot(frame, 10, 1000, 10)
    detection, components = DetectionState(), ComponentPoseState()
    originals = {}
    for key, (x, y, r, b) in zip(keys, boxes):
        quad = np.float32([[x, y], [r, y], [r, b], [x, b]])
        if key == 'board':
            result = DetectionResult('raspberry-pi-5', 10, 1000, 'locked', .9,
                                     [PinDetection('J8:6', x+20, y+20, .9)], quad.tolist())
            detection.set(result, source)
        else:
            # Same pin name on different objects must not share tracks.
            result = ComponentPoseResult(key, 10, 1000, 'locked', .9, (640, 400), quad,
                                         (ComponentPinPosition('GND', x+20, y+20, .9),), 'tracking')
            components.set(result, source)
        originals[key] = result
    manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1))
    worker = MotionOverlayWorker(FrameBus(), detection, components, manager, MotionFrameState())
    for step in range(1, 7):
        hidden = 'mrd-tf240-8p-cs' if step == 4 else None
        packet = worker.process(FrameSlot(render(step, hidden), 10+step, 1000+step*33, 10+step))
        messages = {'board': packet['detection'], **{p['component_id']: p for p in packet['components']}}
        assert set(messages) == set(keys)
        for key, (x, y, r, b), (dx, dy) in zip(keys, boxes, shifts):
            message = messages[key]
            assert message['frame_id'] == packet['frame_id']
            if key == hidden:
                assert message['tracking'] == 'searching'
                assert message['pins'] == [] and message['outline'] is None
                assert message['pose_quality']['recovering']
                continue
            assert message['tracking'] == 'locked', (key, message['pose_quality'])
            assert message['pins'][0]['x'] == pytest.approx(x+20+dx*step, abs=1)
            assert message['pins'][0]['y'] == pytest.approx(y+20+dy*step, abs=1)
    assert len({id(t.flow) for t in worker.tracks.values()}) == 3
    assert detection.get() is originals['board']
    for key in TRACKED_COMPONENT_IDS:
        assert components.get(key) is originals[key]
        assert components.get(key).frame_id == 10


@pytest.mark.parametrize('component_id', TRACKED_COMPONENT_IDS)
def test_component_cannot_seed_from_unpaired_or_unverified_model_result(component_id):
    gray, quad = scene()
    frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    source = FrameSlot(frame, 10, 1000, 10)
    components = ComponentPoseState()
    result = ComponentPoseResult(component_id, 10, 1000, 'locked', .9, (640, 400), quad,
                                 (ComponentPinPosition('GND', 145, 125, .9),), 'tracking')
    manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5', runtime_revision=1))
    worker = MotionOverlayWorker(FrameBus(), DetectionState(), components, manager, MotionFrameState())
    components.set(result)  # No source image: a recent pose alone is not enough.
    packet = worker.process(source)
    assert packet['components'][0]['tracking'] == 'searching'
    assert packet['components'][0]['pins'] == []
    from dataclasses import replace
    components.set(replace(result, tracking='stale'), source)
    packet = worker.process(FrameSlot(frame, 11, 1033, 11))
    assert packet['components'][0]['tracking'] == 'searching'
    assert packet['components'][0]['outline'] is None


def test_packet_state_never_returns_stale_camera_frame():
    state = MotionFrameState()
    state.set({'seq': 2, 'ts_ms': time.monotonic() * 1000 - 1000})
    assert state.get(timeout=0) is None
    state.set({'seq': 3, 'ts_ms': time.monotonic() * 1000})
    assert state.get(after=2, timeout=0)['seq'] == 3
    assert state.get(after=3, timeout=0) is None


@pytest.mark.parametrize('enabled,board_id,revision,status', [
    (False, 'raspberry-pi-5', 1, 404),
    (True, 'arduino-uno-q', 1, 404),
    (True, 'raspberry-pi-5', 1, 200),
    (True, 'raspberry-pi-5', 2, 204),
])
def test_frame_endpoint_runtime_and_disabled_gates(enabled, board_id, revision, status):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.tracking import router
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(realtime_tracking=enabled)
    app.state.runtime_manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id=board_id, runtime_revision=revision))
    packet = {'seq': 3, 'ts_ms': time.monotonic() * 1000, 'runtime_revision': 1, 'board_id': 'raspberry-pi-5'}
    app.state.motion_frame_state = SimpleNamespace(get=lambda after: packet)
    with TestClient(app) as client:
        response = client.get('/api/tracking/frame?after=2')
        assert response.status_code == status
        if status == 200:
            assert response.json() == packet
            assert response.headers['cache-control'] == 'no-store'
