from dataclasses import replace
from pathlib import Path
import cv2
import numpy as np
import pytest
from app.component_worker import ComponentPoseTracker, ComponentVisionProfile
from app.vision.reference_recovery import ReferencePoseRecovery
from test_motion_consensus import scene, shifted, observation

ROOT=Path(__file__).resolve().parents[2]


def test_hc_reference_requires_two_current_matches_and_missing_resets():
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker._forget_pose('test')
    first=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),frame_id=1,ts_ms=100)
    assert first.tracking!='locked'
    moved,corners=shifted(frame,quad,12)
    second=tracker.update(moved,replace(observation(corners),source='hc_reference_sift'),frame_id=2,ts_ms=200)
    assert second.tracking=='locked'
    assert second.visual_continuity['source']=='current_hc_reference_geometry'
    tracker.update(moved,None,frame_id=3,ts_ms=300)
    assert tracker._geometry_previous is None


@pytest.mark.parametrize('kind',['blank','blue_only','wrong_roi'])
def test_reference_does_not_match_empty_or_other_component(kind):
    recovery=ReferencePoseRecovery.from_component_profile(ROOT/'profiles/components/hc-sr04/vision_profile.json')
    frame=np.full((1080,1920,3),100,np.uint8)
    region=observation(np.float32([[800,300],[1200,300],[1200,500],[800,500]]))
    if kind=='blue_only': frame[300:500,800:1200]=(180,60,20)
    if kind=='wrong_roi':
        path=ROOT/'runs/acceptance/2026-09-16/hc-synchronized-held-01/model/12760.png'
        if not path.exists(): pytest.skip('optional independent capture')
        frame=cv2.imread(str(path))
        region=observation(np.float32([[1480,385],[1840,385],[1840,610],[1480,610]]))
    assert recovery.locate(frame,region=region) is None


def test_reference_only_uses_masked_features():
    frame,_=scene()
    mask=np.zeros(frame.shape[:2],np.uint8)
    recovery=ReferencePoseRecovery(frame,feature_mask=mask)
    assert recovery.descriptors is None


def test_hc_reference_survives_continuation_and_reseeds_corrected_anchor(monkeypatch):
    from types import SimpleNamespace
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    seeds=[];resets=[]
    continuation=SimpleNamespace(
        evidence={'accepted':True,'source':'webcam_pcb_flow'},
        propose=lambda f,o,*args: replace(o,corners_px=o.corners_px+[10,0],source='webcam_pcb_flow'),
        seed=lambda f,q,*args,**kwargs: seeds.append(q.copy()),
        reset=lambda: resets.append(True))
    tracker.visual_continuity=continuation
    for fid in (1,2):
        result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),frame_id=fid,ts_ms=fid*100)
    assert result.tracking=='locked'
    assert result.visual_continuity['source']=='current_hc_reference_geometry'
    np.testing.assert_allclose(result.outline_px,quad,atol=.1)
    np.testing.assert_allclose(seeds[-1],quad,atol=.1)
    assert resets==[True]


def test_single_reference_does_not_override_supported_flow():
    from types import SimpleNamespace
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker.visual_continuity=SimpleNamespace(
        evidence={'accepted':True,'source':'webcam_pcb_flow'},
        propose=lambda f,o,*args: replace(o,corners_px=o.corners_px+[8,0],source='webcam_pcb_flow'))
    result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),frame_id=1,ts_ms=100)
    assert result.visual_continuity['source']=='webcam_pcb_flow'
    np.testing.assert_allclose(result.outline_px,quad+[8,0],atol=.1)


def test_old_anchor_expiry_keeps_recent_independent_reference_pair(monkeypatch):
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),
        motion_handoff=True,occlusion_hold_s=2.)
    tracker._last_good_ts_ms=0
    tracker._geometry_previous=(quad.copy(),1950)
    monkeypatch.setattr(tracker.visual_continuity,'propose',lambda *a:None)
    result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),frame_id=20,ts_ms=2100)
    assert result.tracking=='locked'
    assert result.visual_continuity['source']=='current_hc_reference_geometry'


def test_camera_change_discards_reference_pair():
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker._geometry_previous=(quad.copy(),1950)
    tracker._last_input=(30,1950,(320,240))
    result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),frame_id=31,ts_ms=2100)
    assert result.tracking!='locked'


def strong_evidence(fid=1):
    return {'source':'reference_sift','accepted':True,'frame_id':fid,
            'inliers':40,'inlier_ratio':.9,'coverage':.4,'error_px':.4}


def test_strong_current_reference_reacquires_in_one_image():
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker._forget_pose('test')
    result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),
                          frame_id=1,ts_ms=100,reference_evidence=strong_evidence())
    assert result.tracking=='locked'
    assert result.visual_continuity['confirmation']=='strong_current_match'
    assert result.visual_continuity['consecutive_images']==1
    np.testing.assert_allclose(result.outline_px,quad,atol=.1)


@pytest.mark.parametrize('key,value',[
    ('frame_id',0),('accepted',False),('source','yolo'),('inliers',31),
    ('inlier_ratio',.79),('coverage',.29),('error_px',.81),('error_px',float('nan')),
])
def test_one_frame_reacquisition_requires_all_current_image_evidence(key,value):
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker._forget_pose('test')
    evidence=strong_evidence();evidence[key]=value
    result=tracker.update(frame,replace(observation(quad),source='hc_reference_sift'),
                          frame_id=1,ts_ms=100,reference_evidence=evidence)
    assert result.tracking!='locked'


@pytest.mark.parametrize('component,motion_handoff,source',[
    ('hc-sr04',False,'hc_reference_sift'),('hc-sr04',True,'yolo'),
    ('hw-123',True,'hc_reference_sift'),('mrd-tf240-8p-cs',True,'hc_reference_sift')])
def test_strong_reference_only_applies_to_hc_webcam(component,motion_handoff,source):
    frame,quad=scene()
    tracker=ComponentPoseTracker(ComponentVisionProfile(component,(('GND',.2,.1),)),motion_handoff=motion_handoff)
    tracker._forget_pose('test')
    result=tracker.update(frame,replace(observation(quad),source=source),
                          frame_id=1,ts_ms=100,reference_evidence=strong_evidence())
    assert not result.visual_continuity or result.visual_continuity.get('confirmation')!='strong_current_match'


def test_fully_covered_frame_cannot_supply_strong_reference_evidence():
    frame,quad=scene()
    frame[:]=90
    recovery=ReferencePoseRecovery.from_component_profile(ROOT/'profiles/components/hc-sr04/vision_profile.json')
    found=recovery.locate(frame,observation(quad))
    assert found is None
    evidence=dict(recovery.evidence,frame_id=1)
    tracker=ComponentPoseTracker(ComponentVisionProfile('hc-sr04',(('GND',.2,.1),)),motion_handoff=True)
    tracker._forget_pose('test')
    result=tracker.update(frame,found,frame_id=1,ts_ms=100,reference_evidence=evidence)
    assert result.tracking!='locked'
    assert result.tracking_reason=='model_missing'
