"""Physical support counts and bounded, current-photo reference hypotheses."""
from types import SimpleNamespace as NS

import cv2
import numpy as np

import app.photo_reference as module
from app.photo_reference import Correspondence, PhotoReferenceRecovery, unique_physical_pairs, corroborated_pairs
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.yolo_pose import BoardPoseObservation


def test_descriptor_banks_and_sift_orientations_cannot_multiply_physical_votes():
    pairs=[]
    for representation in range(3):
        for x,y in ((10.,10.),(50.,10.),(50.,50.),(10.,50.)):
            for angle in range(4):
                pairs.append(Correspondence(np.array([x,y]),np.array([x+100,y+100]),10.+angle+representation))
    unique,conflicts=unique_physical_pairs(pairs)
    assert len(pairs)==48 and len(unique)==4 and conflicts==0
    assert all(pair.distance==10. for pair in unique)


def test_same_reference_point_with_competing_destinations_is_rejected():
    pairs=[Correspondence(np.array([20.,20.]),np.array([100.,100.]),1.),
        Correspondence(np.array([20.2,20.1]),np.array([150.,150.]),2.),
        Correspondence(np.array([80.,80.]),np.array([180.,180.]),5.)]
    unique,conflicts=unique_physical_pairs(pairs)
    assert conflicts==2 and len(unique)==1
    np.testing.assert_allclose(unique[0].source,[80,80])


def test_spatial_index_preserves_exact_conflicts_and_unique_physical_votes():
    rng=np.random.default_rng(51)
    pairs=[Correspondence(rng.uniform(-2,8,2),rng.uniform(-2,8,2),float(i),str(i%3)) for i in range(200)]
    valid=[p for p in pairs if not any(np.linalg.norm(p.source-q.source)<1.
        and np.linalg.norm(p.destination-q.destination)>2. for q in pairs)]
    expected=[]
    for p in sorted(valid,key=lambda p:p.distance):
        if not any(np.linalg.norm(p.source-q.source)<1. or np.linalg.norm(p.destination-q.destination)<1. for q in expected):
            expected.append(p)
    actual,conflicts=unique_physical_pairs(pairs)
    assert [id(p) for p in actual]==[id(p) for p in expected] and conflicts==len(pairs)-len(valid)
    expected=[p for p in pairs if any(p.representation!=q.representation and np.linalg.norm(p.source-q.source)<1.
        and np.linalg.norm(p.destination-q.destination)<1. for q in pairs)]
    assert [id(p) for p in corroborated_pairs(pairs)]==[id(p) for p in expected]


def synthetic_reference_scene():
    random=np.random.default_rng(101)
    gray=random.integers(0,256,(200,300),dtype=np.uint8)
    gray=cv2.GaussianBlur(gray,(3,3),.7)
    reference=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
    quad=np.float32([[110,100],[460,115],[440,350],[100,330]])
    transform=cv2.getPerspectiveTransform(np.float32([[0,0],[299,0],[299,199],[0,199]]),quad)
    frame=cv2.warpPerspective(reference,transform,(600,450))
    region=BoardPoseObservation(quad,.99,np.ones(4),tuple(np.r_[quad.min(0),quad.max(0)]))
    return reference,frame,region


def test_duplicate_reference_representation_does_not_raise_unique_count_or_quality():
    reference,frame,region=synthetic_reference_scene()
    raw=ReferencePoseRecovery(reference)
    first=PhotoReferenceRecovery(reference,recovery=raw)
    copied=first.supplemented("same_pixels_duplicate",raw.keypoints,raw.descriptors)
    located=first.locate(frame,region=region)
    duplicated=copied.locate(frame,region=region)
    assert located is not None and duplicated is not None
    assert first.evidence["unique_inliers"]==copied.evidence["unique_inliers"]
    assert first.evidence["unique_matches"]==copied.evidence["unique_matches"]
    assert copied.evidence["raw_correspondences"]==2*first.evidence["raw_correspondences"]
    np.testing.assert_allclose(located.corners_px,duplicated.corners_px,atol=.01)
    assert located.source=="reference_sift" and not copied.evidence["uses_previous_photo"]


def test_current_photo_missing_features_never_returns_previous_reference_pose():
    reference,frame,region=synthetic_reference_scene()
    matcher=PhotoReferenceRecovery(reference)
    assert matcher.locate(frame,region=region) is not None
    assert matcher.locate(np.full_like(frame,128),region=region) is None
    assert not matcher.evidence["accepted"] and matcher.evidence["unique_matches"]==0


def test_pcb_view_bank_is_bounded_and_cannot_locate_a_blank_current_photo():
    reference,frame,region=synthetic_reference_scene()
    # Existing calibrated PCB colors, not new labeled photographs.
    reference[:,:,0]=np.clip(reference[:,:,0].astype(int)+65,0,255)
    reference[:,:,2]=reference[:,:,2]//3
    recovery=PhotoReferenceRecovery(reference).with_pcb_view_bank()
    assert len(recovery.banks)==11 and recovery.query_clahe
    assert all(np.isfinite([k.pt for k in keys]).all() for _,keys,_ in recovery.banks)
    assert recovery.locate(np.full_like(frame,128),region) is None
    assert not recovery.evidence['accepted'] and recovery.evidence['unique_matches']==0


def test_small_pcb_query_pyramid_is_bounded_and_missing_current_features_stay_untrusted():
    reference,frame,region=synthetic_reference_scene()
    recovery=PhotoReferenceRecovery(reference).with_pcb_view_bank().with_pcb_query_pyramid()
    assert recovery.query_scales==(1.,2.,3.) and len(recovery.banks)==11
    assert recovery.locate(np.full_like(frame,128),region) is None
    assert not recovery.evidence['accepted'] and recovery.evidence['unique_matches']==0
    assert recovery.evidence['uses_previous_photo'] is False


def test_small_pcb_pyramid_duplicate_banks_cannot_multiply_physical_support():
    reference,_,region=synthetic_reference_scene()
    reference[:,:,0]=np.maximum(reference[:,:,0],180)
    reference[:,:,2]=reference[:,:,2]//4
    transform=cv2.getPerspectiveTransform(
        np.float32([[0,0],[299,0],[299,199],[0,199]]),region.corners_px.astype(np.float32))
    frame=cv2.warpPerspective(reference,transform,(600,450))
    matcher=PhotoReferenceRecovery(reference).with_pcb_view_bank().with_pcb_query_pyramid()
    first=matcher.locate(frame,region)
    assert first is not None,matcher.evidence
    duplicate=PhotoReferenceRecovery(reference,banks=matcher.banks*2,query_clahe=True,query_scales=(1.,2.,3.),query_pcb_mask=True)
    second=duplicate.locate(frame,region)
    assert second is not None,duplicate.evidence
    assert matcher.evidence['unique_inliers']==duplicate.evidence['unique_inliers']
    np.testing.assert_allclose(second.corners_px,first.corners_px,atol=.01)
    assert matcher.evidence['coverage']>=.18 and matcher.evidence['inlier_ratio']>=.45


def test_augmented_reference_preserves_canonical_coordinates_and_deduplication():
    reference,frame,region=synthetic_reference_scene()
    base=PhotoReferenceRecovery(reference)
    bank=base.with_pcb_view_bank()
    result=bank.locate(frame,region)
    assert result is not None
    np.testing.assert_allclose(result.corners_px,region.corners_px,atol=2)
    assert bank.evidence['unique_inliers']>=16 and bank.evidence['coverage']>=.18
    # A duplicate of the whole bank must not increase evidence counts.
    repeated=PhotoReferenceRecovery(reference,banks=bank.banks*2,query_clahe=True)
    assert repeated.locate(frame,region) is not None
    assert repeated.evidence['unique_inliers']==bank.evidence['unique_inliers']


def test_estimator_mask_outlier_cannot_inflate_unique_inliers_or_coverage(monkeypatch):
    reference=np.full((200,200,3),120,np.uint8)
    source=[(20+(index%5)*5,20+(index//5)*5) for index in range(15)]+[(180,180)]
    destination=source[:-1]+[(250,250)]
    keys=[cv2.KeyPoint(float(x),float(y),3.) for x,y in source]
    descriptors=np.ones((16,128),np.float32)
    matcher=PhotoReferenceRecovery(reference,banks=[("native",keys,descriptors)])
    matcher.sift=NS(detectAndCompute=lambda image,mask:([cv2.KeyPoint(float(x),float(y),3.) for x,y in destination],descriptors))
    monkeypatch.setattr(module,"_mutual_ratio_matches",lambda source,target:[cv2.DMatch(i,i,1.) for i in range(16)])
    calls=[]
    def bad_estimator(source,destination,method,threshold):
        calls.append((method,threshold))
        return np.eye(3),np.ones((16,1),np.uint8)
    monkeypatch.setattr(module.cv2,"findHomography",bad_estimator)
    region=BoardPoseObservation(np.float32([[0,0],[299,0],[299,299],[0,299]]),.99,np.ones(4),(0,0,299,299))
    assert matcher.locate(np.full((300,300,3),100,np.uint8),region=region) is None
    assert matcher.evidence["unique_inliers"]==15
    assert len(calls)==2 and {threshold for _,threshold in calls}=={3.}
    assert all(report["unique_inliers"]==15 and not report["accepted"] for report in matcher.evidence["hypotheses"])
