"""Regression coverage for an HC false positive on a TFT end strip."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import (ComponentPoseState, ComponentPoseResult,
    ComponentPoseTracker, ComponentPoseWorker)
from app.motion_worker import MotionOverlayWorker, MotionFrameState
from app.vision.component_identity import hc_tft_conflict
from app.vision.yolo_pose import BoardPoseObservation

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'profiles/components/hc-sr04/vision_profile.json'


def scene():
    frame = np.full((500, 700, 3), 130, np.uint8)
    tft = np.float32([[200, 80], [360, 80], [360, 320], [200, 320]])
    cv2.rectangle(frame, (200, 80), (360, 320), (180, 65, 20), -1)
    cv2.rectangle(frame, (210, 108), (350, 292), (24, 24, 24), -1)
    hc = np.float32([[195, 77], [355, 77], [355, 137], [195, 137]])
    return frame, hc, tft


def conflict(frame, hc, tft, **kwargs):
    return hc_tft_conflict(frame, hc, tft,
        hc_visible=ComponentPoseTracker._hc_transducers_visible, **kwargs)


@pytest.mark.parametrize('angle', [0, 45, 90, 180, 270])
@pytest.mark.parametrize('scale', [.6, 1.0])
def test_false_hc_on_tft_rejected_across_rotation_and_scale(angle, scale):
    frame, hc, tft = scene()
    m = cv2.getRotationMatrix2D((350, 250), angle, scale)
    transformed = cv2.warpAffine(frame, m, (700, 500), borderValue=(130, 130, 130))
    h = cv2.transform(hc[None], m)[0]
    t = cv2.transform(tft[None], m)[0]
    evidence = conflict(transformed, h, t)
    assert evidence and evidence['tft_panel_visible']
    assert evidence['overlap_fraction'] > .70


@pytest.mark.parametrize('case', ['separate', 'touching', 'blank', 'blue', 'dark', 'invalid', 'no_tft', 'reference'])
def test_overlap_or_missing_rings_alone_cannot_veto_hc(case):
    frame, hc, tft = scene()
    if case == 'separate': hc = hc + [300, 0]
    if case == 'touching': hc = hc + [120, 0]
    if case == 'blank': frame[:] = 130
    if case == 'blue': frame[:] = (180, 65, 20)
    if case == 'dark': frame[:] = 20
    if case == 'invalid': hc[0] = np.nan
    if case == 'no_tft': tft = None
    assert conflict(frame, hc, tft, reference_confirmed=case == 'reference') is None


def test_real_transducer_evidence_wins_even_when_regions_overlap():
    frame, hc, tft = scene()
    calls = []
    assert hc_tft_conflict(frame, hc, tft,
        hc_visible=lambda *a: calls.append(True) or True) is None
    assert calls == [True]


def result(tft, frame_id=10, ts_ms=1000):
    return ComponentPoseResult('mrd-tf240-8p-cs', frame_id, ts_ms, 'locked', .6,
        (700, 500), tft, (), 'tracking')


def worker_for(frame, tft, *, handoff=True):
    state = ComponentPoseState()
    state.set(result(tft), FrameSlot(frame, 10, 1000, 10))
    return ComponentPoseWorker(bus=FrameBus(), state=state, model_path='unused',
        profile_path=PROFILE, publish=lambda _: None, webcam_motion_handoff=handoff,
        locator=SimpleNamespace(locate=lambda _: None))


def obs(hc):
    # Deliberately very high confidence: no independent-model score competition.
    return BoardPoseObservation(hc, .99, np.full(4, .99), (*hc.min(0), *hc.max(0)))


@pytest.mark.parametrize('age,accepted', [(0, True), (150, True), (201, False), (-1, False)])
def test_worker_peer_must_be_fresh_non_future_and_image_supported(age, accepted):
    frame, hc, tft = scene()
    worker = worker_for(frame, tft)
    slot = FrameSlot(frame, 11, 1000+age, 11)
    assert bool(worker._identity_conflict(slot, obs(hc), None)) == accepted


def test_eye_nonhandoff_path_and_confirmed_current_reference_unchanged():
    frame, hc, tft = scene()
    slot = FrameSlot(frame, 11, 1100, 11)
    assert worker_for(frame, tft, handoff=False)._identity_conflict(slot, obs(hc), None) is None
    worker = worker_for(frame, tft)
    assert worker._identity_conflict(slot, obs(hc), {'accepted': True, 'frame_id': 11}) is None
    assert worker._identity_conflict(slot, obs(hc), {'accepted': True, 'frame_id': 9})


def test_worker_rejects_before_publishing_and_clears_cached_identity():
    frame, hc, tft = scene()
    worker = worker_for(frame, tft)
    outputs = []
    worker._publish = outputs.append
    worker._locate = lambda _: obs(hc)
    worker._reference_recovery = None
    def next_frame(**_):
        worker._stop.set()
        return FrameSlot(frame, 11, 1100, 11)
    worker._bus = SimpleNamespace(get_latest=next_frame)
    worker._run()
    published = outputs[-1]
    assert published['pose_quality']['reason'] == 'component_identity_conflict'
    assert published['pose_quality']['model_confidence'] == .99
    assert published['outline'] is None and published['pins'] == []
    assert published['body'] is None and 'diagnostic' not in published
    assert worker._tracker._last_good is None
    # A real HC outside the TFT can be acquired on later frames; veto is not sticky.
    assert worker._identity_conflict(FrameSlot(frame, 12, 1120, 12), obs(hc+[300, 0]), None) is None


def motion_worker():
    return MotionOverlayWorker(None, None, None, None, MotionFrameState())


def test_display_veto_clears_wrong_flow_and_prediction_not_other_components():
    frame, hc, tft = scene()
    worker = motion_worker()
    outputs = {'hc-sr04': {'component_id': 'hc-sr04', 'tracking': 'locked',
        'outline': hc.tolist(), 'pins': [{'id': 'VCC'}], 'pose_quality': {}},
        'mrd-tf240-8p-cs': {'tracking': 'locked', 'outline': tft.tolist()}, 'board': {'tracking': 'locked'}}
    original = deepcopy(outputs)
    worker.tracks = {key: object() for key in outputs}
    worker.component_predictions['hc-sr04'].latest = {'old': True}
    worker._resolve_component_identities(outputs, FrameSlot(frame, 11, 1100, 11), {})
    assert outputs['hc-sr04']['outline'] is None
    assert outputs['hc-sr04']['pins'] == []
    assert 'hc-sr04' not in worker.tracks
    assert worker.component_predictions['hc-sr04'].latest is None
    assert outputs['board'] == original['board']
    assert outputs['mrd-tf240-8p-cs'] == original['mrd-tf240-8p-cs']


def test_upstream_veto_clears_old_display_even_when_tft_currently_missing():
    frame, hc, tft = scene()
    worker = motion_worker()
    message = {'component_id': 'hc-sr04', 'tracking': 'searching', 'outline': None,
        'pins': [], 'pose_quality': {'reason': 'component_identity_conflict',
        'identity_check': {'rejected': True}}}
    outputs = {'hc-sr04': dict(message, outline=hc.tolist())}
    slot = FrameSlot(frame, 11, 1100, 11)
    worker._resolve_component_identities(outputs, slot, {'hc-sr04': (slot, message)})
    assert outputs['hc-sr04']['outline'] is None
    assert outputs['hc-sr04']['pose_quality']['reason'] == 'component_identity_conflict'


def test_saved_real_tft_false_positive_regression():
    folder = ROOT / 'runs/identity-guard-20260917'
    if not (folder / 'before.json').exists():
        pytest.skip('optional local live capture')
    data = json.loads((folder / 'before.json').read_text(encoding='utf-8-sig'))
    frame = cv2.imread(str(folder / 'before.jpg'))
    parts = {p['component_id']: p for p in data['components']}
    assert conflict(frame, parts['hc-sr04']['outline'], parts['mrd-tf240-8p-cs']['outline'])


@pytest.mark.parametrize('case', ['S02-white-four-parts-01', 'S08-HC-single-end-01'])
def test_existing_real_hc_visual_evidence_is_preserved(case):
    folder = ROOT / 'runs/acceptance/2026-09-13'
    cache = folder / f'hc-recovery-cache/{case}-hc-sr04.json'
    if not cache.exists():
        pytest.skip('optional existing HC capture')
    item = json.loads(cache.read_text())['inputs'][0]
    frame = cv2.imread(str(folder / case / item['image_path']))
    hc = np.float32(item['observation']['corners_px'])
    assert ComponentPoseTracker._hc_transducers_visible(frame, hc, 1.)
    # Even an overlapping TFT hypothesis must not delete supported HC identity.
    assert conflict(frame, hc, hc + [-5, -5]) is None
