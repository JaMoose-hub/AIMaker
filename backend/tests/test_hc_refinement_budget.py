"""Color refinement must not manufacture motion or disable HC reacquisition."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameSlot
from app.component_worker import (ComponentPoseState, ComponentPoseTracker,
    ComponentPoseWorker, ComponentVisionProfile, bound_hc_corner_refinement,
    refine_component_corners_from_pcb)
from app.vision.yolo_pose import BoardPoseObservation

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / 'profiles/components/hc-sr04/vision_profile.json'
PROFILE = ComponentVisionProfile.load(PROFILE_PATH)
QUAD = np.float64([[100, 100], [420, 100], [420, 240], [100, 240]])


def observation(q=QUAD):
    return BoardPoseObservation(q.copy(), .7, np.full(4, .8),
                                (*q.min(0), *q.max(0)))


@pytest.mark.parametrize('handoff,rings,hand,expected',[(True,True,.12,True),(False,True,.12,False),(True,False,.12,False),(True,True,.25,False)])
def test_hc_edge_grip_needs_current_rings_and_bounded_hand(monkeypatch,handoff,rings,hand,expected):
    tracker=ComponentPoseTracker(PROFILE,motion_handoff=handoff)
    monkeypatch.setattr(tracker,'_visible_fraction',lambda *a:.34)
    monkeypatch.setattr(tracker,'_hand_fraction',lambda *a:hand)
    monkeypatch.setattr(tracker,'_hc_transducers_visible',lambda *a:rings)
    for i in range(1,6):
        result=tracker.update(np.zeros((480,640,3),np.uint8),observation(),frame_id=i,ts_ms=1000+i*100)
    assert (result.tracking=='locked') == expected


def test_saved_held_hc_edge_grip_regression():
    folder=ROOT/'runs/acceptance/2026-09-16/hc-held-diagnosis'
    if not (folder/'inspection.json').exists(): pytest.skip('optional held capture')
    data=json.loads((folder/'inspection.json').read_text())
    image=cv2.imread(str(folder/'source.jpg'))
    raw=observation(np.asarray(data['raw_corners']))
    before=ComponentPoseTracker(PROFILE,motion_handoff=False)
    after=ComponentPoseTracker(PROFILE,motion_handoff=True)
    assert before.update(image,raw,frame_id=1,ts_ms=1000).tracking=='searching'
    for i in range(1,6):
        result=after.update(image,raw,frame_id=i,ts_ms=1000+i*100)
    assert result.tracking=='locked'


@pytest.mark.parametrize('scale', [.5, 1., 2.])
@pytest.mark.parametrize('angle', [0, 90, 180, 270])
def test_budget_scales_with_pitch_and_preserves_semantic_order(scale, angle):
    rotation = cv2.getRotationMatrix2D((260, 170), angle, scale)
    q = cv2.transform(QUAD.reshape(1, 4, 2), rotation)[0] + [500, 500]
    raw = observation(q)
    minor = observation(q + [.25 * scale, 0])
    large = observation(q + [20 * scale, 0])
    accepted, evidence = bound_hc_corner_refinement(PROFILE, raw, minor, (1920, 1080))
    rejected, rejected_evidence = bound_hc_corner_refinement(PROFILE, raw, large, (1920, 1080))
    assert accepted is minor and evidence['status'] == 'bounded_adjustment'
    assert rejected is raw and rejected_evidence['status'] == 'retained_model'
    assert 4 * scale < evidence['limit_px'] < 5 * scale
    flipped = observation(np.roll(q, 2, axis=0))
    assert bound_hc_corner_refinement(PROFILE, raw, flipped, (1920, 1080))[0] is raw


def test_no_refinement_or_invalid_raw_does_not_invent_geometry():
    raw = observation()
    assert bound_hc_corner_refinement(PROFILE, raw, None, (640, 400))[0] is raw
    invalid = observation(QUAD[[0, 2, 1, 3]])
    result, evidence = bound_hc_corner_refinement(PROFILE, invalid, raw, (640, 400))
    assert result is invalid and evidence['status'] == 'invalid_geometry'


@pytest.mark.parametrize('cid', ['hw-123', 'mrd-tf240-8p-cs'])
def test_other_component_paths_are_unchanged(cid):
    profile = ComponentVisionProfile.load(ROOT / f'profiles/components/{cid}/vision_profile.json')
    raw, refined = observation(), observation(QUAD + 40)
    assert bound_hc_corner_refinement(profile, raw, refined, (640, 400)) == (refined, None)
    assert bound_hc_corner_refinement(profile, raw, None, (640, 400)) == (raw, None)


def test_legacy_appended_landmark_hc_path_is_unchanged():
    profile = replace(PROFILE, keypoint_count=8)
    raw, refined = observation(), observation(QUAD + 40)
    assert bound_hc_corner_refinement(profile, raw, refined, (640, 400)) == (refined, None)


def test_worker_recovers_after_loss_despite_jumping_color_proposals(monkeypatch):
    frame = np.full((400, 640, 3), 60, np.uint8)
    cv2.fillConvexPoly(frame, QUAD.astype(np.int32), (180, 60, 20))
    timestamps = [1000, 3300, 3600, 3900, 4200, 4500, 4800]
    outputs, cursor = [], [-1]
    class FastStop(threading.Event):
        def wait(self, timeout=None):
            return self.is_set()
    def next_frame(**kwargs):
        cursor[0] += 1
        if cursor[0] == len(timestamps):
            worker._stop.set()
            return None
        i = cursor[0]
        return FrameSlot(frame, i, timestamps[i], i)
    worker = ComponentPoseWorker(bus=SimpleNamespace(get_latest=next_frame),
        state=ComponentPoseState(), model_path='unused', profile_path=PROFILE_PATH,
        locator=SimpleNamespace(locate=lambda _: None if cursor[0] == 1 else observation()),
        publish=outputs.append, reacquire_min_visible_fraction=.25)
    worker._stop = FastStop()
    monkeypatch.setattr('app.component_worker.refine_component_corners_from_pcb',
                        lambda _, obs, **kw: observation(QUAD + [(-1)**cursor[0]*20, 0]))
    worker._run()
    assert outputs[0]['tracking'] == 'locked'
    assert [o['tracking'] for o in outputs[1:5]] == ['searching'] * 4
    assert all(not o['pins'] for o in outputs[1:5])
    assert outputs[5]['tracking'] == outputs[6]['tracking'] == 'locked'
    assert outputs[5]['pose_quality']['stability'] == 'reacquired'
    assert outputs[5]['pose_quality']['corner_refinement']['status'] == 'retained_model'
    assert np.array_equal(outputs[5]['outline'], QUAD)


def test_saved_stationary_hc_reacquires_without_color_induced_motion():
    folder = ROOT / 'runs/acceptance/2026-09-13'
    cache = folder / 'hc-recovery-cache/S07-HC-reacquire-before-01-hc-sr04.json'
    if not cache.exists():
        pytest.skip('optional on-site sequence unavailable')
    items = json.loads(cache.read_text())['inputs']
    tracker = ComponentPoseTracker(PROFILE, reacquire_min_visible_fraction=.25)
    # Exercise re-lock rather than letting a cold start bypass consensus.
    tracker._forget_pose('tracking_expired')
    results, raw_motion, color_motion = [], [], []
    last_raw = last_refined = None
    for i, item in enumerate(items):
        data = item['observation']
        raw = BoardPoseObservation(np.array(data['corners_px']), data['confidence'],
            np.array(data['keypoint_confidences']), tuple(data['box_xyxy']))
        frame = cv2.imread(str(folder / 'S07-HC-reacquire-before-01' / item['image_path']))
        refined = refine_component_corners_from_pcb(frame, raw)
        chosen, evidence = bound_hc_corner_refinement(PROFILE, raw, refined, (1920, 1080))
        assert evidence['status'] == 'retained_model'
        if last_raw is not None:
            raw_motion.append(np.linalg.norm(raw.corners_px-last_raw, axis=1).mean())
            color_motion.append(np.linalg.norm(refined.corners_px-last_refined, axis=1).mean())
        last_raw, last_refined = raw.corners_px, refined.corners_px
        results.append(tracker.update(frame, chosen, frame_id=item['frame_id'], ts_ms=item['ts_ms']))
    assert max(raw_motion) < 2
    assert max(color_motion) > 40
    assert all(r.tracking == 'searching' and not r.pins for r in results[:3])
    assert all(r.tracking == 'locked' for r in results[3:])


@pytest.mark.parametrize('missing', [None, 'left', 'right', 'both', 'contrast', 'blue'])
def test_transducer_support_requires_two_rings_and_some_blue(missing):
    frame = np.full((200, 360, 3), 60, np.uint8)
    quad = np.float64([[20, 20], [340, 20], [340, 180], [20, 180]])
    cv2.rectangle(frame, (20, 155), (340, 180), (180, 60, 20), -1)
    for name, cx in [('left', 85), ('right', 270)]:
        if missing in (name, 'both'):
            continue
        cv2.circle(frame, (cx, 75), 48, (200, 200, 200), -1)
        cv2.circle(frame, (cx, 75), 35, (40, 40, 40) if missing != 'contrast' else (200, 200, 200), -1)
    support = ComponentPoseTracker._hc_transducers_visible(frame, quad, 0 if missing == 'blue' else .20)
    assert support == (missing is None)


@pytest.mark.parametrize('case', ['S02-white-four-parts-01', 'S08-HC-single-end-01'])
def test_real_sparse_blue_hc_can_lock_without_inflating_visibility_baseline(case):
    folder = ROOT / 'runs/acceptance/2026-09-13'
    cache = folder / f'hc-recovery-cache/{case}-hc-sr04.json'
    if not cache.exists():
        pytest.skip('optional on-site sequence unavailable')
    item = json.loads(cache.read_text())['inputs'][0]
    data = item['observation']
    raw = BoardPoseObservation(np.array(data['corners_px']), data['confidence'],
        np.array(data['keypoint_confidences']), tuple(data['box_xyxy']))
    frame = cv2.imread(str(folder / case / item['image_path']))
    tracker = ComponentPoseTracker(PROFILE, reacquire_min_visible_fraction=.25)
    blue = tracker._blue_fraction(frame, raw.corners_px)
    assert .12 < blue < .25
    assert tracker._hc_transducers_visible(frame, raw.corners_px, blue)
    result = tracker.update(frame, raw, frame_id=1, ts_ms=1000)
    assert result.tracking == 'locked'
    assert result.visibility_baseline == pytest.approx(blue)
    assert result.visible_fraction == pytest.approx(blue)


def test_hw_false_hc_candidate_cannot_gain_transducer_support():
    path = ROOT / 'runs/acceptance/2026-09-13/S05-HC-handheld-01/frames/000020.jpg'
    if not path.exists():
        pytest.skip('optional on-site source unavailable')
    frame = cv2.imread(str(path))
    q = np.float64([[570.1177, 590.9385], [607.1466, 776.1682],
                    [525.0159, 784.5873], [482.2598, 596.5690]])
    blue = ComponentPoseTracker._blue_fraction(frame, q)
    assert not ComponentPoseTracker._hc_transducers_visible(frame, q, blue)
