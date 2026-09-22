from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.vision.yolo_pose import BoardPoseObservation, refine_board_corners_from_pcb
from app.vision.yolo_profile_detector import HybridBoardDetector
from app.vision.motion_tracking import MotionTrack, PlanarFlow
from app.vision.interface import DetectionResult, PinDetection


def observation(quad, box=None):
    quad = np.asarray(quad, np.float64)
    return BoardPoseObservation(quad, .9, np.full(4, .9),
        tuple(box or (*quad.min(0), *quad.max(0))))


@pytest.mark.parametrize('angle', [0, 90, 180, 270])
def test_compact_board_keeps_semantic_order(angle):
    frame = np.full((700, 900, 3), 100, np.uint8)
    quad = np.float32([[280,240],[620,240],[620,460],[280,460]])
    matrix = cv2.getRotationMatrix2D((450,350), angle, 1)
    quad = cv2.transform(quad[None], matrix)[0]
    cv2.fillConvexPoly(frame, quad.astype(np.int32), (70,150,65))
    evidence = {}
    result = refine_board_corners_from_pcb(frame, observation(quad), boundary_evidence=evidence)
    assert result is not None and not evidence.get('rejected')
    assert np.max(np.linalg.norm(result.corners_px-quad, axis=1)) < 2


def test_search_rectangle_is_not_a_physical_board_edge():
    frame = np.full((700,900,3), (70,150,65), np.uint8)
    obs = observation([[280,240],[620,240],[620,460],[280,460]])
    evidence = {}
    assert refine_board_corners_from_pcb(frame, obs, boundary_evidence=evidence) is None
    assert evidence['rejected'] and evidence['at_search_edge']


@pytest.mark.parametrize('case,quad,box', [
    ('S07-HC-moved-settled-01', [[1016.9106,468.1682],[1525.3893,611.0059],[1451.4877,909.5902],[932.3552,790.0446]],
     [868.2158,372.355,1617.4004,1021.9829]),
    ('S07-Pi-wires-aside-01', [[1043.5906,373.3682],[1603.9581,677.7482],[1461.5842,985.854],[884.4942,697.6581]],
     [886.7206,291.8571,1663.3739,1028.4656]),
])
def test_saved_wire_expansion_is_rejected_without_changing_legacy(case, quad, box):
    path = Path(__file__).resolve().parents[2]/'runs/acceptance/2026-09-13'/case/'frames/000000.jpg'
    if not path.exists():
        pytest.skip('Optional local acceptance image')
    frame = cv2.imread(str(path)); obs = observation(quad, box); evidence = {}
    legacy = refine_board_corners_from_pcb(frame, obs)
    assert legacy is not None  # Exercise the old false expansion.
    assert refine_board_corners_from_pcb(frame, obs, boundary_evidence=evidence) is None
    assert evidence['rejected'] and (evidence['fill'] < .65 or evidence['at_search_edge'])
    np.testing.assert_array_equal(refine_board_corners_from_pcb(frame, obs).corners_px, legacy.corners_px)


@pytest.mark.parametrize('fallback_status', ['locked','stale','searching'])
@pytest.mark.parametrize('frame_current', [True, False])
def test_bad_primary_only_yields_to_fresh_feature_lock(fallback_status, frame_current):
    rejected = DetectionResult('raspberry-pi-5', 1, 100., 'searching', 0,
                               pose_stability_state='pcb_boundary_unverified',
                               reference_evidence={'accepted':False, 'reason':'insufficient_matches'})
    fallback = DetectionResult('raspberry-pi-5', 1 if frame_current else 0, 100., fallback_status, .8,
                               pins=[PinDetection('J8:1', 100., 100., .8)],
                               outline_px=[(100,100),(300,100),(300,230),(100,230)])
    primary = SimpleNamespace(available=True, detect=lambda *a: rejected, _searching=lambda *a, **kw: rejected)
    detector = HybridBoardDetector(primary, SimpleNamespace(detect=lambda *a: fallback))
    detector._board_id = 'raspberry-pi-5'
    result = detector.detect(None, 1, 100)
    accepted = fallback_status == 'locked' and frame_current
    assert result.tracking == ('locked' if accepted else 'searching')
    assert bool(result.pins) == accepted
    assert result.frame_id == 1
    if not accepted:
        assert result.reference_evidence == rejected.reference_evidence


@pytest.mark.parametrize('missing', ['timestamp', 'pins', 'outline'])
def test_boundary_fallback_must_have_current_complete_geometry(missing):
    rejected = DetectionResult('raspberry-pi-5', 1, 100., 'searching', 0,
                               pose_stability_state='pcb_boundary_unverified')
    fallback = DetectionResult('raspberry-pi-5', 1, 100., 'locked', .8,
                               pins=[PinDetection('J8:1', 100., 100., .8)],
                               outline_px=[(100,100),(300,100),(300,230),(100,230)])
    if missing == 'timestamp':
        fallback.ts_ms = 50.
    elif missing == 'pins':
        fallback.pins = []
    else:
        fallback.outline_px = None
    primary = SimpleNamespace(available=True, detect=lambda *a: rejected, _searching=lambda *a, **kw: rejected)
    detector = HybridBoardDetector(primary, SimpleNamespace(detect=lambda *a: fallback))
    detector._board_id = 'raspberry-pi-5'
    result = detector.detect(None, 1, 100.)
    assert result.tracking == 'searching' and not result.pins


def test_failed_seed_replaces_old_reason_and_later_good_seed_recovers():
    gray = np.random.default_rng(17).integers(0,255,(540,960),dtype=np.uint8)
    track = MotionTrack(); track.failure_reason = 'semantic_lease_expired'
    message = {'board_id':'raspberry-pi-5', 'tracking':'locked', 'frame_id':1, 'ts_ms':100,
               'video_size':[1920,1080], 'outline':[[659,280],[1884,280],[1884,1079],[659,1079]], 'pins':[]}
    track.observe(message, gray, .5)
    assert track.failure_reason == 'seed_outside_frame' and track.message is None
    message.update(frame_id=2, ts_ms=200, outline=[[400,300],[1200,300],[1200,900],[400,900]])
    track.observe(message, gray, .5)
    assert track.message is not None and track.failure_reason is None


def test_invalid_and_textureless_seed_reasons_are_distinct():
    flow = PlanarFlow(); gray = np.full((400,640),80,np.uint8)
    assert not flow.seed(gray, np.zeros((4,2),np.float32))
    assert flow.failure_reason == 'seed_invalid_geometry'
    assert not flow.seed(gray, np.float32([[120,100],[360,100],[360,260],[120,260]]))
    assert flow.failure_reason == 'seed_insufficient_texture'


def test_fresh_bad_boundary_does_not_renew_existing_flow_lease():
    gray = np.random.default_rng(4).integers(0,255,(400,640),dtype=np.uint8)
    track = MotionTrack()
    message = {'board_id':'raspberry-pi-5','tracking':'locked','frame_id':1,'ts_ms':100,
               'outline':[[120,100],[360,100],[360,260],[120,260]],'pins':[]}
    track.observe(message,gray,1)
    assert track.message is not None
    message.update(frame_id=2,ts_ms=200,tracking='searching',pose_quality={'stability':'pcb_boundary_unverified'})
    track.observe(message,gray,1)
    # Current-frame optical flow may still support an existing pose, but the
    # rejected model is not a new semantic confirmation. See motion tests for
    # removal/covering and expiry: neither an old lock nor a bad quad can persist.
    assert track.message is not None and track.confirmed_ts == 100
    assert track.confirmation_debug['accepted'] is False
