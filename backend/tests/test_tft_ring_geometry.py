from dataclasses import replace

import cv2
import numpy as np
import pytest

from app.vision.tft_ring_geometry import refine_tft_rings
from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from test_motion_consensus import observation, scene, shifted


def panel(missing=False):
    image = np.full((600,800,3),100,np.uint8)
    image[70:490,240:560]=(180,65,20)
    image[110:450,275:525]=(25,25,25)
    quad=np.float32([[262,94],[538,94],[538,466],[262,466]])
    for index,point in enumerate(quad):
        if missing and index==2:
            continue
        center=tuple(point.astype(int))
        cv2.circle(image,center,11,(230,230,230),-1)
        cv2.circle(image,center,7,(45,45,45),-1)
    return image,quad


def test_four_actual_rings_correct_shifted_model_without_inventing_an_anchor():
    image,quad=panel(); evidence={}
    result=refine_tft_rings(image,observation(quad+[35.,20.]),evidence)
    assert result is not None, evidence
    np.testing.assert_allclose(result.corners_px,quad,atol=2.5)
    assert result.source=='tft_ring_geometry'


@pytest.mark.parametrize('kind',['missing','blank','lettering'])
def test_no_four_blue_pcb_rings_means_no_geometry(kind):
    image,quad=panel(missing=kind=='missing')
    if kind in ('blank','lettering'):
        image[:]=140
        if kind=='lettering':
            cv2.putText(image,'ProArt',(250,300),cv2.FONT_HERSHEY_SIMPLEX,2,(20,20,20),4)
    evidence={}
    assert refine_tft_rings(image,observation(quad),evidence) is None
    assert not evidence['accepted']


def test_two_measured_ring_poses_can_acquire_while_moving_and_missing_resets():
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('mrd-tf240-8p-cs',(('GND',.2,.1),)),motion_handoff=True)
    for i in range(2):
        moved,corners=shifted(frame,quad,20*i)
        result=tracker.update(moved,replace(observation(corners),source='tft_ring_geometry'),frame_id=i,ts_ms=i*125)
    assert result.tracking=='locked'
    assert result.visual_continuity['source']=='current_tft_ring_geometry'
    np.testing.assert_allclose(result.outline_px,corners,atol=.1)
    tracker.update(moved,None,frame_id=2,ts_ms=250)
    assert tracker._geometry_previous is None


def test_tft_model_pose_can_reacquire_with_image_window_without_four_rings():
    # Translation plus alternating detector jitter: compare in board coordinates,
    # not screen coordinates. No ring observation is supplied in this sequence.
    frame, quad = scene()
    tracker = ComponentPoseTracker(
        ComponentVisionProfile('mrd-tf240-8p-cs', (('GND', .2, .1),)),
        motion_handoff=True)
    accepted = False
    for i in range(6):
        moved, corners = shifted(frame, quad, i * 8)
        noisy = corners + [(-1 if i % 2 else 1) * 3.8, 0]
        accepted = tracker._confirm_reacquisition(noisy, i, i * 100, moved)
        if accepted:
            break
    assert accepted
    assert tracker._reacquire_estimate is not None
    assert tracker._reacquire_evidence['source'] == 'image_aligned_pose_window'
    np.testing.assert_allclose(tracker._reacquire_estimate, corners, atol=2)


def test_glare_at_two_holes_does_not_require_blue_at_every_corner():
    image,quad=panel()
    for point in quad[2:]:
        x,y=point.astype(int)
        image[y-24:y+25,x-24:x+25]=190
        cv2.circle(image,(x,y),11,(230,230,230),-1)
        cv2.circle(image,(x,y),7,(45,45,45),-1)
    evidence={}
    result=refine_tft_rings(image,observation(quad+[35.,20.]),evidence)
    assert result is not None, evidence
    np.testing.assert_allclose(result.corners_px,quad,atol=2.5)


def test_blank_four_hole_plate_without_lcd_is_not_a_screen():
    image,quad=panel()
    image[110:450,275:525]=(180,65,20)
    evidence={}
    assert refine_tft_rings(image,observation(quad),evidence) is None


def test_local_search_measures_new_image_and_stops_when_screen_disappears():
    from app.vision.tft_ring_geometry import TftRingAcquirer
    acquirer=TftRingAcquirer()
    frame,quad=panel()
    assert acquirer.locate(frame,None,1,100) is None  # Cannot invent identity.
    assert acquirer.locate(frame,observation(quad),2,200) is not None
    moved=cv2.warpAffine(frame,np.float32([[1,0,15],[0,1,8]]),(800,600))
    result=acquirer.locate(moved,None,3,300)
    assert result is not None
    np.testing.assert_allclose(result.corners_px,quad+[15,8],atol=2.5)
    assert acquirer.evidence['search']=='recent_measured_rings'
    assert acquirer.locate(np.full_like(frame,100),None,4,400) is None
    assert acquirer.locate(moved,None,5,1000) is None  # Search anchor expired.


@pytest.mark.parametrize('change',['duplicate','reverse','resize'])
def test_local_search_resets_on_sequence_or_camera_change(change):
    from app.vision.tft_ring_geometry import TftRingAcquirer
    acquirer=TftRingAcquirer();frame,quad=panel()
    assert acquirer.locate(frame,observation(quad),2,200) is not None
    image=cv2.resize(frame,(400,300)) if change=='resize' else frame
    assert acquirer.locate(image,None,2 if change=='duplicate' else 1 if change=='reverse' else 3,300) is None


def test_confirmed_tft_geometry_seeds_flow_and_keeps_independent_correction():
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('mrd-tf240-8p-cs',(('GND',.2,.1),)),motion_handoff=True)
    for i in range(3):
        moved,corners=shifted(frame,quad,10*i)
        result=tracker.update(moved,replace(observation(corners),source='tft_ring_geometry'),frame_id=i,ts_ms=i*100)
    assert result.tracking=='locked'
    assert result.visual_continuity['source']=='current_tft_ring_geometry'
    np.testing.assert_allclose(result.outline_px,corners,atol=.1)
    assert tracker.visual_continuity.flow is not None


def lcd_panel(missing=1):
    image,quad=panel()
    image[70:490,240:560]=(180,65,20)
    lcd=np.float32([[-.04,.075],[1.045,.075],[1.045,.865],[-.04,.865]])
    transform=cv2.getPerspectiveTransform(np.float32([[0,0],[1,0],[1,1],[0,1]]),quad)
    points=cv2.perspectiveTransform(lcd[None],transform)[0]
    cv2.fillConvexPoly(image,np.int32(points),(25,25,25))
    for index,point in enumerate(quad):
        if index<missing:
            continue
        center=tuple(point.astype(int))
        cv2.circle(image,center,11,(230,230,230),-1)
        cv2.circle(image,center,7,(45,45,45),-1)
    return image,quad


def test_lcd_edges_and_three_rings_project_missing_corner_without_claiming_four():
    from app.vision.tft_ring_geometry import refine_tft_panel
    frame,quad=lcd_panel();evidence={}
    result=refine_tft_panel(frame,observation(quad),evidence)
    assert result is not None, evidence
    assert result.source=='tft_panel_geometry'
    assert evidence['observed_rings']==3
    assert evidence['missing_corner']=='projected_from_current_lcd_not_observed_ring'
    np.testing.assert_allclose(result.corners_px,quad,atol=3)


def test_two_rings_or_four_hole_plate_cannot_use_panel_recovery():
    from app.vision.tft_ring_geometry import refine_tft_panel
    frame,quad=lcd_panel(missing=2)
    assert refine_tft_panel(frame,observation(quad),{}) is None
    frame,quad=panel();frame[110:450,275:525]=(180,65,20)
    assert refine_tft_panel(frame,observation(quad),{}) is None


def test_current_partial_panel_moves_and_full_occlusion_never_reuses_it():
    from app.vision.tft_ring_geometry import TftRingAcquirer
    acquirer=TftRingAcquirer();frame,quad=lcd_panel()
    assert acquirer.locate(frame,observation(quad),1,100) is not None
    moved=cv2.warpAffine(frame,np.float32([[1,0,8],[0,1,5]]),(800,600))
    result=acquirer.locate(moved,None,2,200)
    assert result is not None
    np.testing.assert_allclose(result.corners_px,quad+[8,5],atol=4)
    assert acquirer.locate(np.full_like(frame,100),None,3,300) is None
