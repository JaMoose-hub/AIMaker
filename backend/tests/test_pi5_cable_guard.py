"""Display-only cable robustness; synthetic motion is not hardware acceptance."""
from copy import deepcopy
from pathlib import Path
import json

import cv2
import numpy as np
import pytest

from app.vision.motion_tracking import MotionTrack, PlanarFlow, transform
from app.vision.display_prediction import DisplayPrediction
from test_motion_tracking import scene, pose


@pytest.mark.parametrize('angle', [0, 65, 180, 270])
def test_connector_exclusion_rotates_with_semantic_board_not_screen(angle):
    _, quad = scene()
    affine = cv2.getRotationMatrix2D((240, 180), angle, .8)
    quad = transform(quad, np.vstack([affine, [0, 0, 1]]))
    flow = PlanarFlow(pi5_cable_guard=True)
    mask = flow._feature_mask((400, 640), quad)
    mapping = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]), quad)
    usb, chip, header = np.rint(transform([[.88,.12],[.5,.5],[.6,.9]], mapping)).astype(int)
    assert mask[usb[1],usb[0]] == 0
    assert mask[chip[1],chip[0]] == mask[header[1],header[0]] == 255
    legacy = PlanarFlow()._feature_mask((400,640), quad)
    assert legacy[usb[1],usb[0]] == 255


def test_strong_connector_features_cannot_monopolize_seed():
    frame, quad = scene()
    flow = PlanarFlow(pi5_cable_guard=True)
    assert flow.seed(frame, quad)
    uv = flow._board_coordinates(flow.points, quad)
    assert not np.any((uv[:,0] >= .76) & (uv[:,1] <= .25))
    cells = np.clip((uv*3).astype(int),0,2)
    counts = np.bincount(cells[:,1]*3+cells[:,0], minlength=9)
    assert counts.max() <= 12
    assert flow.support_cells >= 4
    assert flow.support_quadrants >= 3


@pytest.mark.parametrize('board_moves', [False, True])
def test_cable_motion_does_not_drag_stationary_or_moving_board(board_moves):
    frame, quad = scene()
    tracker = MotionTrack()
    seed = pose(quad)
    before = deepcopy(seed)
    tracker.observe(seed, frame, 1)
    errors = []
    for i in range(1,13):
        matrix = np.float64([[1,0,2*i if board_moves else 0],
                             [0,1,i*.5 if board_moves else 0],[0,0,1]])
        current = cv2.warpPerspective(frame,matrix,(640,400),borderValue=40)
        # A high-contrast cable sweeps the board; it is NOT transformed with it.
        cv2.line(current,(305+i*3,60),(345+i*2,300),245,9)
        cv2.line(current,(305+i*3,60),(345+i*2,300),20,3)
        result = tracker.update(current,i,i*33,search_budget=lambda:False)
        assert result is not None
        errors.append(float(np.max(np.linalg.norm(np.asarray(result['outline'])-transform(quad,matrix),axis=1))))
        assert result['pose_quality']['feature_policy'] == 'pi5_cable_guard'
    assert max(errors) < 1.0
    assert seed == before


def test_guard_does_not_learn_full_cover_and_recovers_on_fresh_pixels():
    frame,quad = scene()
    track = MotionTrack()
    track.observe(pose(quad),frame,1)
    anchor = track.flow.anchor
    assert track.update(np.full_like(frame,100),1,33,search_budget=lambda:False) is None
    assert track.flow.anchor is anchor
    result = track.update(frame,2,66,search_budget=lambda:False)
    assert result is not None and result['pose_quality']['recovered']
    assert np.max(np.linalg.norm(np.asarray(result['outline'])-quad,axis=1)) < 1


def test_stationary_pi_retains_clear_anchor_instead_of_integrating_reseeds():
    frame,quad = scene()
    flow = PlanarFlow(pi5_cable_guard=True)
    assert flow.seed(frame,quad)
    anchor = flow.anchor
    rng = np.random.default_rng(21)
    for i in range(1,61):
        noisy = np.clip(frame.astype(float)+rng.normal(0,.5,frame.shape),0,255).astype(np.uint8)
        assert flow.step(noisy,ts_ms=i*33,search_budget=lambda:False) is not None
        assert flow.anchor is anchor
        assert np.max(np.linalg.norm(flow.quad-quad,axis=1)) < .3


def test_guard_needs_broad_regions_but_accepts_visible_half_board():
    _,quad = scene()
    flow = PlanarFlow(pi5_cable_guard=True)
    mapping = cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]),quad)
    localized = np.float32([[x,y] for x in np.linspace(.35,.65,8) for y in np.linspace(.05,.25,8)])
    assert not flow._distributed_support(transform(localized,mapping),quad)
    visible_half = np.float32([[x,y] for x in np.linspace(.56,.96,8) for y in np.linspace(.07,.93,8)])
    assert flow._distributed_support(transform(visible_half,mapping),quad)


def test_localized_motion_may_not_be_velocity_predicted():
    frame,quad = scene()
    prediction = DisplayPrediction()
    for i in range(2):
        message = pose(quad+[i,0],i,i*33)
        message['pose_quality'] = {'object_supported':True,'partial':False}
        prediction.apply(message)
    lost = pose(quad,2,66)
    lost.update(tracking='searching',outline=None,pins=[],pose_quality={'reason':'localized_motion'})
    assert prediction.apply(lost) == lost
    assert prediction.latest is None


@pytest.mark.parametrize('identity', ['hc-sr04','mrd-tf240-8p-cs'])
def test_other_components_keep_original_feature_policy(identity):
    frame,quad = scene()
    seed = pose(quad)
    del seed['board_id']
    seed['component_id'] = identity
    tracker = MotionTrack()
    tracker.observe(seed,frame,1)
    assert not tracker.flow.pi5_cable_guard


def test_shipped_plugged_in_reference_can_seed_and_follow_pose():
    root = Path(__file__).resolve().parents[2] / 'profiles/boards/raspberry-pi-5'
    profile = json.loads((root/'board.json').read_text(encoding='utf-8'))
    frame = cv2.imread(str(root/profile['reference']['image']),cv2.IMREAD_GRAYSCALE)
    if frame is None:
        pytest.skip('local captured reference is not shipped in every checkout')
    w,h = profile['board']['outline_mm']
    quad = transform([[0,0],[w,0],[w,h],[0,h]],np.asarray(profile['reference']['mm_to_px']))
    flow = PlanarFlow(pi5_cable_guard=True)
    assert flow.seed(frame,quad)
    matrix = np.float64([[1,0,6],[0,1,3],[0,0,1]])
    moved = cv2.warpPerspective(frame,matrix,(frame.shape[1],frame.shape[0]))
    assert flow.step(moved,search_budget=lambda:False) is not None
    assert np.max(np.linalg.norm(flow.quad-transform(quad,matrix),axis=1)) < 1
