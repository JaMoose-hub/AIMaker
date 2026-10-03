"""Current-photo geometry contracts; real synthetic pixels, fake model calls."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

import app.photo_geometry as geometry_module
from app.component_worker import ComponentPoseResult, ComponentVisionProfile, project_component_outline
from app.photo_geometry import PhotoGeometry, refine_photo_tft_rings, replay_saved_photo
from app.profiles.store import ProfileStore
from app.vision.interface import DetectionResult
from app.vision.yolo_pose import BoardPoseObservation
from test_tft_ring_geometry import lcd_panel, panel

PROFILES=Path(__file__).resolve().parents[2]/"profiles"


def observation(corners,confidence=.95):
    corners=np.asarray(corners,float)
    return BoardPoseObservation(corners,confidence,np.full(4,confidence),tuple(np.r_[corners.min(0),corners.max(0)]))


def component_result(profile,quad,frame):
    return ComponentPoseResult(profile.component_id,17,1234.,"locked",.93,
        (frame.shape[1],frame.shape[0]),project_component_outline(profile,quad),(),"yolo_direct",model_confidence=.93)


def test_four_real_tft_holes_lcd_and_orientation_correct_same_photo_without_models():
    frame,quad=lcd_panel(missing=0)
    evidence={}
    result=refine_photo_tft_rings(frame,observation(quad+[10.,5.]),evidence)
    assert result is not None, evidence
    np.testing.assert_allclose(result.corners_px,quad,atol=2.)
    assert evidence["holes_supported"]==4 and evidence["orientation"]["verified"]
    assert evidence["radius_basis"]=="current_model_mount_short_edge"
    assert evidence["hole_radius_range_px"][1]==round(276*.065)


@pytest.mark.parametrize("missing",[1,2])
def test_missing_real_mounts_are_not_inferred_or_completed_from_profile(missing):
    frame,quad=lcd_panel(missing=missing)
    evidence={}
    assert refine_photo_tft_rings(frame,observation(quad),evidence) is None
    assert not evidence["accepted"] and evidence["observed_rings"]==0
    assert evidence["ring_candidates"]<4


def test_four_holes_without_independent_full_lcd_or_header_end_are_untrusted():
    frame,quad=panel()
    evidence={}
    assert refine_photo_tft_rings(frame,observation(quad),evidence) is None
    assert not evidence["accepted"]


def test_tft_projects_display_outline_from_mounts_and_preserves_model_confidence():
    frame,quad=lcd_panel(missing=0)
    profile=ComponentVisionProfile.load(PROFILES/"components/mrd-tf240-8p-cs/vision_profile.json")
    worker=NS(_profile=profile,_locator=NS(model_path="existing.onnx"),_yolo_only=False)
    raw=component_result(profile,quad+[10.,5.],frame)
    updated,local=PhotoGeometry().component(frame,raw,worker)
    assert local["status"]=="located" and updated.tracking=="locked"
    assert len(updated.pins)==8 and local["evidence"]["holes_supported"]==4
    assert local["evidence"]["model_confidence"]==.93 and updated.confidence==.93
    expected=project_component_outline(profile,quad)
    np.testing.assert_allclose(updated.outline_px,expected,atol=2.)
    assert not np.allclose(updated.outline_px,quad)  # Display edges are not hole centres.
    assert not worker._yolo_only
    assert local["evidence"]["contact_visibility_verified"] is False


def test_small_model_box_gets_one_wider_search_not_invented_mounts():
    frame,quad=lcd_panel(missing=0)
    profile=ComponentVisionProfile.load(PROFILES/"components/mrd-tf240-8p-cs/vision_profile.json")
    worker=NS(_profile=profile,_locator=NS(model_path="existing.onnx"))
    small=quad.mean(0)+(quad-quad.mean(0))*.6
    updated,local=PhotoGeometry().component(frame,component_result(profile,small,frame),worker)
    assert local['status']=='located',local
    assert len(local['evidence']['ring_attempts'])==2
    assert local['evidence']['ring_attempts'][1]['search_expansion']==1.5
    assert local['evidence']['holes_supported']==4 and len(updated.pins)==8
    np.testing.assert_allclose(updated.outline_px,project_component_outline(profile,quad),atol=2.)


def test_missing_tft_ring_fallback_cannot_use_a_previous_photo(monkeypatch):
    frame,quad=lcd_panel(missing=1)
    profile=ComponentVisionProfile.load(PROFILES/"components/mrd-tf240-8p-cs/vision_profile.json")
    worker=NS(_profile=profile,_locator=NS(model_path="existing.onnx"))
    instances=[]
    class Acquirer:
        def __init__(self):
            instances.append(self); self.evidence={"accepted":True,"observed_rings":3,"orientation":{"verified":True}}
        def locate(self,frame,region,frame_id,ts_ms):
            return region  # A panel can infer the fourth; POC requires four observed holes.
    monkeypatch.setattr(geometry_module,"TftRingAcquirer",Acquirer)
    geometry=PhotoGeometry()
    for frame_id in (17,18):
        raw=replace(component_result(profile,quad,frame),frame_id=frame_id)
        updated,local=geometry.component(frame,raw,worker)
        assert local["status"]=="uncertain" and updated.pins==() and updated.outline_px is None
    assert len(instances)==2 and instances[0] is not instances[1]


def pi_setup(monkeypatch,*,j8_accepted,reference_evidence=None):
    profile=ProfileStore(PROFILES).profile("raspberry-pi-5")
    frame=np.full((800,1000,3),110,np.uint8)
    raw=np.float32([[200,200],[650,200],[650,500],[200,500]])
    corrected=raw+np.float32([30,15])
    reference=np.zeros((100,150,3),np.uint8)
    detector=NS(primary=NS(_profile=profile,_reference_board_bgr=reference,_locator=NS(model_path="pi-existing.onnx")))
    evidence=reference_evidence or dict(source="reference_sift",accepted=True,inliers=19,inlier_ratio=.65,
        unique_inliers=19,quadrants=3,coverage=.3,error_px=.7)
    recovery=NS(evidence=evidence,locate=Mock(return_value=observation(corrected,.8)))
    factory=Mock(return_value=recovery)
    monkeypatch.setattr(geometry_module,"PhotoReferenceRecovery",factory)
    monkeypatch.setattr(geometry_module,"refine_board_corners_from_pcb",Mock(return_value=None))
    def j8(image,board,pins,size,*,diagnostic):
        assert image is frame
        diagnostic.update(accepted=j8_accepted,reason="contact_rows" if j8_accepted else "ambiguous_rows",support=[19,20])
        return pins
    monkeypatch.setattr(geometry_module,"_correct_pi5_j8_from_image",j8)
    result=DetectionResult("raspberry-pi-5",27,1234.,"locked",.95,outline_px=raw.tolist())
    return frame,result,detector,recovery,factory,corrected


def test_pi_reference_corrects_board_but_ambiguous_j8_keeps_only_explicit_candidates(monkeypatch):
    frame,result,detector,recovery,factory,corrected=pi_setup(monkeypatch,j8_accepted=False)
    updated,local=PhotoGeometry().board(frame,result,detector)
    assert local["status"]=="uncertain" and local["reason"]=="j8_rows_unverified"
    assert updated.tracking=="searching" and updated.pins==[] and updated.outline_px is None
    np.testing.assert_allclose(local["corrected_outline_px"],corrected)
    assert len(local["candidate_pins"])==40
    assert local["evidence"]["board_geometry_verified"] and not local["evidence"]["pin_geometry_verified"]
    assert local["evidence"]["j8_support_samples"]==0  # High ambiguous contrast isn't visible contacts.
    assert local["evidence"]["candidate_contact_support"]==[19,20]
    recovery.locate.assert_called_once()
    assert recovery.locate.call_args.args[0] is frame and recovery.locate.call_args.kwargs["region"] is not None
    assert factory.call_args.args[0] is detector.primary._reference_board_bgr


def test_pi_supported_current_j8_and_board_give_projected_hints_not_contact_verification(monkeypatch):
    frame,result,detector,recovery,factory,corrected=pi_setup(monkeypatch,j8_accepted=True)
    geometry=PhotoGeometry()
    first,local=geometry.board(frame,result,detector)
    second,again=geometry.board(frame,replace(result,frame_id=28),detector)
    assert local["status"]=="located" and first.tracking=="locked" and len(first.pins)==40
    assert first.confidence==.95 and local["evidence"]["model_confidence"]==.95
    assert local["evidence"]["inliers"]==19 and local["evidence"]["reprojection_px"]==.7
    assert local["evidence"]["j8_support_samples"]==39
    assert local["evidence"]["contact_visibility_verified"] is False and not first.pose_image_confirmed
    assert factory.call_count==1 and recovery.locate.call_count==2  # Descriptors reusable, evidence freshly measured.
    assert first.frame_id==27 and second.frame_id==28


@pytest.mark.parametrize("changes",[{"inliers":15},{"coverage":.17},{"error_px":2.1},{"accepted":False}])
def test_high_model_confidence_does_not_bypass_reference_quality_gate(monkeypatch,changes):
    evidence=dict(source="reference_sift",accepted=True,inliers=19,unique_inliers=19,quadrants=3,inlier_ratio=.65,coverage=.3,error_px=.7)
    evidence.update(changes)
    frame,result,detector,_,_,_=pi_setup(monkeypatch,j8_accepted=True,reference_evidence=evidence)
    updated,local=PhotoGeometry().board(frame,result,detector)
    assert updated.pins==[] and local["status"]=="uncertain" and local["candidate_pins"]==[]
    assert not local["evidence"]["board_geometry_verified"]


def test_invalid_or_clipped_quad_is_rejected_before_local_matching(monkeypatch):
    frame,result,detector,recovery,_,_=pi_setup(monkeypatch,j8_accepted=True)
    result.outline_px=[[1,100],[650,100],[650,500],[1,500]]
    updated,local=PhotoGeometry().board(frame,result,detector)
    assert updated.pins==[] and local["reason"]=="invalid_or_clipped_geometry"
    recovery.locate.assert_not_called()


def test_saved_replay_rejects_different_photo_identity_without_building_any_detector(tmp_path):
    import json
    capture=tmp_path/"capture.json"; image=tmp_path/"photo.jpg"
    capture.write_text(json.dumps({"image_sha256":"different"}),encoding="utf-8")
    image.write_bytes(b"not the source image")
    with pytest.raises(ValueError,match="hash"):
        replay_saved_photo(capture,image,PROFILES)


@pytest.mark.parametrize("field,value",[("frame_id",99),("ts_ms",99),("video_size",[101,100]),("runtime_revision",2)])
def test_saved_replay_rejects_mixed_frame_dto_even_with_matching_image_hash(tmp_path,field,value):
    import hashlib
    import json
    ok,encoded=cv2.imencode(".jpg",np.full((100,100,3),100,np.uint8))
    assert ok
    image=tmp_path/"photo.jpg"; image.write_bytes(encoded.tobytes())
    dto=dict(frame_id=1,ts_ms=123.,video_size=[100,100],runtime_revision=1)
    packet=dict(image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),frame_id=1,
        capture_ts_ms=123.,video_size=[100,100],runtime_revision=1,
        detection={**dto,"board_id":"raspberry-pi-5"},components=[{**dto,field:value}])
    capture=tmp_path/"capture.json"; capture.write_text(json.dumps(packet),encoding="utf-8")
    with pytest.raises(ValueError,match="source frame/runtime"):
        replay_saved_photo(capture,image,PROFILES)
