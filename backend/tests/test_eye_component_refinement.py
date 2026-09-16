"""Eye uses native mounting-hole pixels, preserving YOLO identity and webcam."""
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameBus, FrameSlot
from app.component_worker import (ComponentPoseState, ComponentPoseWorker,
    ComponentVisionProfile, project_component_pins, refine_eye_component_from_local_image)
from app.vision.yolo_pose import BoardPoseObservation

ROOT=Path(__file__).resolve().parents[2]


def scene():
    frame=np.full((420,640,3),105,np.uint8)
    actual=np.array([[490.,95.],[500.,330.],[145.,325.],[150.,90.]])
    for x,y in actual.astype(int):
        cv2.circle(frame,(x,y),13,(245,245,245),-1)
        cv2.circle(frame,(x,y),7,(55,55,55),-1)
    predicted=actual+[[22,-18],[18,34],[-20,15],[-24,-28]]
    observation=BoardPoseObservation(predicted,.8,np.full(4,.9),(110.,50.,535.,370.),predicted.copy())
    return frame,actual,observation


class Locator:
    def __init__(self,outputs):self.outputs=iter(outputs);self.calls=0
    def locate(self,frame):self.calls+=1;return next(self.outputs)


def worker(component,outputs):
    locator=Locator(outputs)
    result=ComponentPoseWorker(bus=FrameBus(),state=ComponentPoseState(),model_path='unused',
        profile_path=ROOT/f'profiles/components/{component}/vision_profile.json',
        publish=lambda _:pytest.fail('Group owns publication'),locator=locator)
    result.set_yolo_only(True)
    return result,locator


def test_actual_holes_improve_native_pin_positions_with_one_forward_and_unchanged_identity():
    frame,actual,observation=scene()
    subject,locator=worker('mrd-tf240-8p-cs',[observation])
    before=observation.corners_px.copy()
    result=subject.detect_yolo_frame(FrameSlot(frame,17,1234.,1))
    expected=project_component_pins(subject._profile,actual,.8,(640,420))
    assert locator.calls==1
    assert result.frame_id==17 and result.ts_ms==1234.
    assert result.confidence==.8 and result.model_confidence==.8
    assert result.body['box']==list(observation.box_xyxy)
    assert result.corner_refinement['status']=='adjusted'
    assert max(np.hypot(p.x-q.x,p.y-q.y) for p,q in zip(result.pins,expected))<3
    assert [p.id for p in result.pins]==[p.id for p in expected]
    np.testing.assert_array_equal(observation.corners_px,before)
    np.testing.assert_array_equal(observation.landmarks_px,before)


def test_only_current_yolo_body_with_circle_support_is_passed_without_resize(monkeypatch):
    import app.component_worker as module
    frame,_,observation=scene()
    profile=ComponentVisionProfile.load(ROOT/'profiles/components/mrd-tf240-8p-cs/vision_profile.json')
    calls=[]
    def finder(crop,local,*,allow_three_anchors,evidence):
        calls.append(crop)
        assert allow_three_anchors is True
        assert crop.shape==(366,471,3)  # 19px maximum circle radius + 4px halo.
        assert np.shares_memory(crop,frame)
        np.testing.assert_array_equal(crop,frame[27:393,87:558])
        np.testing.assert_allclose(local.corners_px,observation.corners_px-[87,27])
        assert local.box_xyxy==(23.,23.,448.,343.)
        evidence.update(status='adjusted',observed=4,inferred=0)
        return replace(local,corners_px=local.corners_px+[2,-3])
    monkeypatch.setattr(module,'refine_component_corners_from_mounting_holes',finder)
    refined,evidence=refine_eye_component_from_local_image(frame,observation,profile)
    assert len(calls)==1 and evidence['status']=='adjusted'
    assert evidence['support_padding_px']==23
    assert evidence['input_corners_px']==observation.corners_px.tolist()
    assert evidence['input_box_xyxy']==list(observation.box_xyxy)
    np.testing.assert_allclose(refined.corners_px,observation.corners_px+[2,-3])
    np.testing.assert_allclose(refined.landmarks_px,refined.corners_px)
    np.testing.assert_array_equal(refined.keypoint_confidences,observation.keypoint_confidences)
    assert refined.box_xyxy==observation.box_xyxy and refined.source==observation.source


def test_unavailable_holes_keep_new_current_model_geometry_not_old_adjustment():
    frame,_,observation=scene()
    moved=replace(observation,corners_px=observation.corners_px+[4,1],landmarks_px=None)
    subject,locator=worker('mrd-tf240-8p-cs',[observation,moved,None])
    first=subject.detect_yolo_frame(FrameSlot(frame,1,1000.,1))
    assert first.corner_refinement['status']=='adjusted'
    blank=np.full_like(frame,105)
    second=subject.detect_yolo_frame(FrameSlot(blank,2,1033.,2))
    expected=project_component_pins(subject._profile,moved.corners_px,.8,(640,420))
    assert second.corner_refinement['status']=='unavailable'
    assert second.frame_id==2 and second.pins==expected
    missing=subject.detect_yolo_frame(FrameSlot(blank,3,1066.,3))
    assert missing.pins==() and missing.body is None and locator.calls==3


def test_box_crossing_mounting_rings_keeps_circle_support_without_another_search():
    from app.component_worker import refine_component_corners_from_mounting_holes
    frame,actual,observation=scene()
    # A correct class box can cut through each physical mounting ring. Its
    # hard edge deletes the Hough evidence even when the semantic centres are
    # only a few pixels from the correct holes.
    box=(148.,93.,497.,327.)
    predicted=actual+[[8,-6],[6,8],[-6,6],[-7,-6]]
    observation=replace(observation,box_xyxy=box,corners_px=predicted,landmarks_px=None)
    strict=replace(observation,corners_px=predicted-[148,93],box_xyxy=(0.,0.,349.,234.))
    assert refine_component_corners_from_mounting_holes(frame[93:327,148:497],strict) is None
    profile=ComponentVisionProfile.load(ROOT/'profiles/components/mrd-tf240-8p-cs/vision_profile.json')
    refined,evidence=refine_eye_component_from_local_image(frame,observation,profile)
    assert evidence['status']=='adjusted'
    assert evidence['support_padding_px']==18
    assert np.max(np.linalg.norm(refined.corners_px-actual,axis=1))<3
    assert refined.box_xyxy==observation.box_xyxy


@pytest.mark.parametrize('component',['hw-123','hc-sr04'])
def test_other_components_keep_yolo_without_unproven_refinement(component,monkeypatch):
    import app.component_worker as module
    def forbidden(*_):pytest.fail('Unproven local correction must not run')
    for name in ['refine_component_corners_from_mounting_holes','refine_component_corners_from_pcb','orient_component_corners_from_pin_row']:
        monkeypatch.setattr(module,name,forbidden)
    frame,_,observation=scene()
    subject,locator=worker(component,[observation])
    result=subject.detect_yolo_frame(FrameSlot(frame,1,1000.,1))
    assert result.pins and result.corner_refinement is None and locator.calls==1


def test_leaving_eye_skips_local_refinement_and_retains_original_projection(monkeypatch):
    import app.component_worker as module
    frame,_,observation=scene()
    subject,_=worker('mrd-tf240-8p-cs',[])
    subject.set_yolo_only(False)
    monkeypatch.setattr(module,'refine_eye_component_from_local_image',lambda *_:pytest.fail('Webcam must not call Eye refinement'))
    result=subject._direct_yolo_result(FrameSlot(frame,1,1000.,1),observation)
    expected=project_component_pins(subject._profile,observation.corners_px,.8,(640,420))
    assert result.corner_refinement is None and result.pins==expected


def test_image_processing_error_retains_current_yolo(monkeypatch):
    import app.component_worker as module
    def broken(*_,**__):raise cv2.error('unavailable')
    monkeypatch.setattr(module,'refine_component_corners_from_mounting_holes',broken)
    frame,_,observation=scene()
    subject,_=worker('mrd-tf240-8p-cs',[observation])
    result=subject.detect_yolo_frame(FrameSlot(frame,1,1000.,1))
    assert result.tracking=='locked' and len(result.pins)==8
    assert result.corner_refinement['status']=='unavailable'


def test_three_visible_current_rings_correct_quad_without_changing_ids_or_default():
    from app.component_worker import refine_component_corners_from_mounting_holes
    frame,actual,observation=scene()
    # Exactly one physical ring is absent; the remaining three supply this
    # frame's correction. A common affine displacement is recoverable.
    x,y=actual[3].astype(int)
    frame[y-20:y+21,x-20:x+21]=105
    predicted=actual+[14,-9]
    observation=replace(observation,corners_px=predicted,landmarks_px=predicted.copy())
    assert refine_component_corners_from_mounting_holes(frame,observation) is None
    subject,locator=worker('mrd-tf240-8p-cs',[observation])
    result=subject.detect_yolo_frame(FrameSlot(frame,5,1100.,5))
    expected=project_component_pins(subject._profile,actual,.8,(640,420))
    assert locator.calls==1 and result.frame_id==5
    assert result.corner_refinement['status']=='adjusted_three_anchors'
    assert result.corner_refinement['observed']==3 and result.corner_refinement['inferred']==1
    assert result.corner_refinement['input_corners_px']==predicted.tolist()
    assert [p.id for p in result.pins]==[p.id for p in expected]
    assert max(np.hypot(p.x-q.x,p.y-q.y) for p,q in zip(result.pins,expected))<3
    assert result.model_confidence==.8 and result.body['box']==list(observation.box_xyxy)
    np.testing.assert_array_equal(observation.corners_px,predicted)


def test_two_visible_rings_keep_current_yolo_after_three_anchor_adjustment():
    frame,actual,observation=scene()
    predicted=actual+[14,-9]
    observation=replace(observation,corners_px=predicted,landmarks_px=None)
    for index in [3]:
        x,y=actual[index].astype(int)
        frame[y-20:y+21,x-20:x+21]=105
    current=replace(observation,corners_px=predicted+[3,2])
    subject,locator=worker('mrd-tf240-8p-cs',[observation,current])
    first=subject.detect_yolo_frame(FrameSlot(frame,1,1000.,1))
    assert first.corner_refinement['status']=='adjusted_three_anchors'
    x,y=actual[0].astype(int)
    frame[y-20:y+21,x-20:x+21]=105
    second=subject.detect_yolo_frame(FrameSlot(frame,2,1033.,2))
    assert second.corner_refinement['status']=='unavailable'
    assert second.corner_refinement['observed']==2 and second.corner_refinement['inferred']==0
    assert second.pins==project_component_pins(subject._profile,current.corners_px,.8,(640,420))
    assert locator.calls==2 and second.frame_id==2


@pytest.mark.parametrize('predicted,centres',[
    # Every observed ring lies within the original 40px search radius, but
    # their affine completion moves the missing corner sqrt(30**2+30**2).
    ([[100,100],[200,100],[200,200],[100,200]],[[130,100],[180,100],[180,230],None]),
    # Repeated circle assignment must not produce an invertible quad.
    ([[100,100],[130,100],[130,130],[100,130]],[[115,115],[115,115],[115,115],None]),
    # Three collinear input anchors cannot define an affine correction.
    ([[100,100],[130,100],[160,100],[100,140]],[[100,100],[130,100],[160,100],None]),
])
def test_invalid_three_ring_completion_is_rejected_without_retry(predicted,centres,monkeypatch):
    from app.component_worker import refine_component_corners_from_mounting_holes
    predicted=np.asarray(predicted,dtype=float)
    observation=BoardPoseObservation(predicted,.8,np.full(4,.9),(50.,50.,250.,250.),None)
    calls=[]
    def circles(*args,**kwargs):
        index=len(calls)
        calls.append(index)
        assert kwargs['param1']==80. and kwargs['param2']==18.
        if centres[index] is None:return None
        origin=np.maximum(np.floor(predicted[index]-40),0)
        center=np.asarray(centres[index])-origin
        return np.array([[[center[0],center[1],7.]]],dtype=np.float32)
    monkeypatch.setattr(cv2,'HoughCircles',circles)
    evidence={}
    result=refine_component_corners_from_mounting_holes(np.full((300,300,3),105,np.uint8),
        observation,allow_three_anchors=True,evidence=evidence)
    assert result is None and calls==[0,1,2,3]
    assert evidence['observed']==3
