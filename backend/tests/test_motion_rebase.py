"""Reacquire an aged Pi template without learning a hand or rewinding frames."""
from copy import deepcopy

import cv2
import numpy as np
import pytest

from app.vision.motion_tracking import MotionTrack
from test_motion_tracking import scene, pose


def aging_scene():
    original, quad = scene()
    # Global blur changes LK features, without hiding/replacing a board region.
    current = cv2.GaussianBlur(original, (7,7), 0)
    track = MotionTrack()
    track.observe(pose(quad), original, 1)
    result = track.update(current, 1, 33)
    assert result and result['tracking'] == 'stale' and not result['pins']
    return track, current, quad


def confirmed(quad, i, ts=None):
    message = pose(quad, i, i*33 if ts is None else ts)
    message['pose_quality'] = {'image_confirmed': True}
    return message


def test_fresh_independent_image_evidence_rebases_partial_track():
    track, frame, quad = aging_scene()
    old_anchor = track.flow.anchor
    for i in range(1, 4):
        message = confirmed(quad, i)
        original = deepcopy(message)
        track.observe(message, frame, 1)
        assert message == original
        result = track.update(frame, i+1, (i+1)*33)
        if i < 3:
            assert result['tracking'] == 'stale' and not result['pins']
            assert track.flow.anchor is old_anchor
    assert track.rebase_count == 1
    assert track.flow.anchor is not old_anchor
    assert result['tracking'] == 'locked' and len(result['pins']) == 1
    assert result['pins'][0]['x'] == pytest.approx(145, abs=1)
    assert result['pose_quality']['rebase_count'] == 1
    assert track.update(frame, 5, 165)['tracking'] == 'locked'


def test_repeated_message_does_not_count_as_three_confirmations():
    track, frame, quad = aging_scene()
    for _ in range(10):
        track.observe(confirmed(quad, 1), frame, 1)
    assert track.rebase_count == 0 and track.flow.partial


@pytest.mark.parametrize('bad', ['stale', 'no_evidence', 'geometry', 'component', 'no_history', 'shape', 'scale'])
def test_invalid_confirmation_cannot_rebase_or_bridge_a_streak(bad):
    track, frame, quad = aging_scene()
    old_anchor = track.flow.anchor
    for i in range(1, 4):
        message = confirmed(quad, i)
        image, scale = frame, 1
        if i == 2:
            if bad == 'stale': message['tracking'] = 'stale'
            if bad == 'no_evidence': message['pose_quality'] = {}
            if bad == 'geometry': message['outline'] = (quad + [50,0]).tolist()
            if bad == 'component': message['board_id'] = 'hc-sr04'
            if bad == 'no_history': track.history.pop(i, None)
            if bad == 'shape': image = frame[:300]
            if bad == 'scale': scale = .5
        track.observe(message, image, scale)
        track.update(frame, i+1, (i+1)*33)
    assert track.rebase_count == 0 and track.flow.anchor is old_anchor


def test_failed_feature_seed_does_not_erase_partial_template(monkeypatch):
    track, frame, quad = aging_scene()
    anchor = track.flow.anchor
    for i in range(1,4):
        track.observe(confirmed(quad, i), frame, 1)
        if i == 2:
            monkeypatch.setattr(cv2, 'goodFeaturesToTrack', lambda *a, **kw: None)
        track.update(frame, i+1, (i+1)*33)
    assert track.rebase_count == 0 and track.flow.anchor is anchor
    assert track._refresh_after > 99


def test_old_or_out_of_order_source_evidence_cannot_refresh():
    track, frame, quad = aging_scene()
    for i in range(1, 4):
        track.update(frame, i+1, (i+1)*33)
        # Geometry has a history entry but the timestamp is stale/invalid.
        track.observe(confirmed(quad, i, ts=-500+i), frame, 1)
    assert track.rebase_count == 0


def test_worker_uses_exact_paired_model_image_when_rebasing(monkeypatch):
    from types import SimpleNamespace
    from app.capture.bus import FrameBus, FrameSlot
    from app.component_worker import ComponentPoseState
    from app.motion_worker import MotionOverlayWorker, MotionFrameState
    from app.vision.interface import DetectionResult, PinDetection
    from app.vision_worker import DetectionState
    track, source_gray, quad = aging_scene()
    for i in (1, 2):
        track.observe(confirmed(quad,i),source_gray,1)
        track.update(source_gray,i+1,(i+1)*33)
    source = FrameSlot(cv2.cvtColor(source_gray,cv2.COLOR_GRAY2BGR),3,99,3)
    state = DetectionState()
    state.set(DetectionResult('raspberry-pi-5',3,99,'locked',.9,
        [PinDetection('J8:11',145,125,.9)],quad.tolist(),pose_image_confirmed=True),source)
    runtime = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5',runtime_revision=1))
    worker = MotionOverlayWorker(FrameBus(),state,ComponentPoseState(),runtime,MotionFrameState())
    worker.tracks['board'] = track
    # Prevent the first context initialization from discarding our aged fixture.
    worker.context = ('raspberry-pi-5',1,source.frame.shape)
    current = np.full_like(source.frame,90)  # a hand arrived AFTER the model frame
    packet = worker.process(FrameSlot(current,4,132,4))
    assert track.rebase_count == 1
    np.testing.assert_array_equal(track.flow.anchor[0], source_gray)
    assert not packet['detection']['pins']
    assert packet['detection']['frame_id'] == 4


@pytest.mark.parametrize('fraction', [.25, .4, .55])
def test_model_lock_alone_never_learns_a_persistent_hand(fraction):
    frame, quad = scene()
    covered = frame.copy()
    end = 120 + round(240*fraction)
    covered[100:260,120:end] = np.random.default_rng(357).integers(15,245,(160,end-120),dtype=np.uint8)
    track = MotionTrack()
    track.observe(pose(quad), frame, 1)
    anchor = track.flow.anchor
    for i in range(1,100):
        output = track.update(covered, i, i*33)
        # Even repeated semantic locks must not turn the finger into a template.
        track.observe(pose(quad, i, i*33), covered, 1)
        assert output is not None and output['pins'] == []
        assert output['tracking'] == 'stale' and track.flow.anchor is anchor
    assert track.rebase_count == 0


def test_new_occlusion_after_delayed_confirmed_frame_is_checked_before_pins():
    track, frame, quad = aging_scene()
    for i in (1,2):
        track.observe(confirmed(quad,i), frame, 1)
        track.update(frame,i+1,(i+1)*33)
    track.observe(confirmed(quad,3), frame, 1)
    assert track.rebase_count == 1
    # Model confirmed the prior clear frame, not today's fully covered image.
    result = track.update(np.full_like(frame,90),4,132)
    assert result is None or not result['pins']
