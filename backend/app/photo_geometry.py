"""Stateless, current-photograph geometry for the GPIO POC.

The existing YOLO forward supplies identity and a bounded search region. Local
reference/PCB/header/ring measurements corroborate geometry in those *same*
pixels. No previous pose, worker tracker, model retries or temporal consensus
can authorize a pin. Even an accepted coordinate remains a navigation hint,
not an observed electrical contact.
"""
from __future__ import annotations

from dataclasses import replace
from itertools import combinations
import logging

import cv2
import numpy as np

from app.component_worker import project_component_outline, project_component_pins
from app.photo_reference import PhotoReferenceRecovery
from app.photo_panel import photo_lcd_orientation
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision.tft_ring_geometry import (TftRingAcquirer, _contour_rings,
    _screen_frame_supported, orient_tft_from_panel_inset)
from app.vision.yolo_pose import BoardPoseObservation, refine_board_corners_from_pcb
from app.vision.yolo_profile_detector import (_correct_pi5_j8_from_image,
    _project_profile_on_observed_quad)

log = logging.getLogger(__name__)
UNIT = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])


def _points(value):
    if value is None:
        return None
    points = np.asarray(value, dtype=float)
    return points.tolist() if points.shape == (4, 2) and np.isfinite(points).all() else None


def _quad_valid(corners, frame):
    if _points(corners) is None:
        return False
    points = np.asarray(corners, np.float32)
    height, width = frame.shape[:2]
    edges = np.linalg.norm(points-np.roll(points, -1, axis=0), axis=1)
    return bool(cv2.isContourConvex(points) and cv2.contourArea(points, oriented=True) > 0
        and min(edges) >= 25 and max(edges)/min(edges) <= 5
        and 400 <= cv2.contourArea(points) <= .75*width*height
        and np.all(points > 2) and np.all(points < [width-3, height-3]))


def _observation(corners, confidence, body):
    points = np.asarray(corners, dtype=float)
    box = (body or {}).get("box")
    if box is None or np.asarray(box).shape != (4,):
        box = np.r_[points.min(0), points.max(0)].tolist()
    return BoardPoseObservation(points, float(confidence), np.full(4, confidence), tuple(box))


def _body_search_region(body, frame):
    """A fresh body box may bound reference search, never define board corners.

    The direct model can reject its quad as clipped even when the actual PCB
    is fully visible inside its oversized box. Reference correspondences on
    this photo must establish semantic corners before any pin projection.
    """
    if not isinstance(body, dict):
        return None
    try:
        box = np.asarray(body.get("box"), dtype=float)
        confidence = float(body.get("confidence", 0.))
    except (TypeError, ValueError):
        return None
    if (box.shape != (4,) or not np.isfinite(box).all()
            or not np.isfinite(confidence) or not 0. < confidence <= 1.
            or np.any(box[2:] <= box[:2])):
        return None
    lo = np.maximum(box[:2], [0, 0])
    hi = np.minimum(box[2:], [frame.shape[1], frame.shape[0]])
    if np.any(hi-lo < 32):
        return None
    x0, y0 = lo
    x1, y1 = hi
    # These axis-aligned points are only an API carrier for the ROI. They
    # are not retained as a raw/corrected outline or passed to pin projection.
    points = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    return BoardPoseObservation(points, confidence, np.full(4, confidence),
                                tuple(np.r_[lo, hi]), source="photo_body_roi")


def _localization(object_id, raw, confidence, locator=None):
    model_path = getattr(locator, "model_path", None)
    return dict(object_id=object_id, status="uncertain" if raw is not None else "not_found",
        method="yolo_candidate", reason="geometry_unverified", raw_outline_px=_points(raw),
        corrected_outline_px=None, candidate_pins=[], evidence=dict(model_confidence=float(confidence),
        model_path=str(model_path) if model_path is not None else None, model_forwards=1,
        source="one_current_photo", board_geometry_verified=False, pin_geometry_verified=False,
        pin_coordinates_basis="profile_projection", pin_method="profile_projection", contact_visibility_verified=False,
        electrical_verified=False))


def _delta(evidence, raw, corrected):
    if _points(raw) is not None and _points(corrected) is not None:
        shift = np.linalg.norm(np.asarray(corrected)-np.asarray(raw), axis=1)
        evidence.update(corner_delta_px=np.round(shift, 3).tolist(),
            max_corner_delta_px=round(float(shift.max()), 3), corrected_corner_count=int((shift > .5).sum()))


def _reference_supported(evidence):
    """Keep the reference acceptance contract explicit at the photo boundary."""
    return bool(evidence.get("accepted") is True and evidence.get("source")=="reference_sift"
        and evidence.get("inliers",0)>=16 and evidence.get("inlier_ratio",0)>=.45
        and evidence.get("unique_inliers",0)>=16 and evidence.get("quadrants",0)>=3
        and evidence.get("coverage",0)>=.18 and evidence.get("error_px",float("inf"))<=2.)


def _native_board_reference(profile,profile_dir,canonical):
    """Reuse native pixels of the ONE profile reference, transforming only keypoints."""
    from pathlib import Path
    reference=cv2.imread(str(Path(profile_dir)/profile.reference.image))
    if reference is None:
        return None
    width,height=profile.board.outline_mm
    mm=np.float64([[0,0,1],[width,0,1],[width,height,1],[0,height,1]])
    projected=mm@np.asarray(profile.reference.mm_to_px).T
    if np.any(np.abs(projected[:,2])<1e-9):
        return None
    source=np.float32(projected[:,:2]/projected[:,2,None])
    if not cv2.isContourConvex(source) or np.any(source<0) or np.any(source>=[reference.shape[1],reference.shape[0]]):
        return None
    x,y,crop_width,crop_height=cv2.boundingRect(source)
    cropped=reference[y:y+crop_height,x:x+crop_width]
    mask=np.zeros(cropped.shape[:2],np.uint8)
    cv2.fillConvexPoly(mask,np.int32(source-[x,y]),255)
    native=ReferencePoseRecovery(cropped,feature_mask=mask)
    if native.descriptors is None:
        return None
    ch,cw=canonical.shape[:2]
    transform=cv2.getPerspectiveTransform(source,np.float32([[0,0],[cw-1,0],[cw-1,ch-1],[0,ch-1]]))
    points=np.float32([np.asarray(key.pt)+[x,y] for key in native.keypoints])
    points=cv2.perspectiveTransform(points[None],transform)[0]
    native.keypoints=[cv2.KeyPoint(float(point[0]),float(point[1]),key.size) for point,key in zip(points,native.keypoints)]
    return native


def _reference_orientation(frame, corners, reference):
    """A PCB contour alone has no pin-1 semantics; require reference appearance."""
    if reference is None:
        return {"verified": False, "reason": "reference_missing"}
    height, width = reference.shape[:2]
    destination = np.float32([[0,0],[width-1,0],[width-1,height-1],[0,height-1]])
    def appearance(image):
        return cv2.GaussianBlur(cv2.equalizeHist(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)), (5,5), 0)
    target = appearance(reference)
    scores = []
    for shift in range(4):
        patch = cv2.warpPerspective(frame, cv2.getPerspectiveTransform(
            np.float32(np.roll(corners, shift, axis=0)), destination), (width,height))
        scores.append(float(cv2.matchTemplate(appearance(patch), target, cv2.TM_CCOEFF_NORMED)[0,0]))
    finite = np.isfinite(scores).all()
    order = np.argsort(scores)[::-1]
    margin = float(scores[order[0]]-scores[order[1]]) if finite else 0.
    verified = bool(finite and order[0] == 0 and scores[0] >= .20 and margin >= .15)
    return dict(verified=verified, score=round(scores[0],4) if finite else None,
        margin=round(margin,4), reason="matched_reference_orientation" if verified else "ambiguous_reference_orientation")


def refine_photo_tft_rings(frame, observation, evidence):
    """Measure small PCB holes, rejecting large LCD/text/wire circles.

    The hole search radius scales with the mounting rectangle's short edge,
    rather than the rotation-inflated detector box. That box formerly allowed
    28px text/glare circles to suppress a real 12px hole. All four visible
    rings, the independent LCD frame and asymmetric header-end inset remain
    mandatory. This is photo-only; live ring acquisition is unchanged.
    """
    evidence.update(accepted=False, source="photo_tft_small_rings", observed_rings=0)
    predicted = np.asarray(observation.corners_px, np.float32)
    if not _quad_valid(predicted, frame):
        evidence["reason"] = "invalid_mount_geometry"
        return None
    box = np.asarray(observation.box_xyxy, float)
    extent = box[2:]-box[:2]
    if np.any(extent < 50):
        evidence["reason"] = "insufficient_mount_geometry"
        return None
    lo = np.maximum(0, np.floor(box[:2]-.3*extent)).astype(int)
    hi = np.minimum([frame.shape[1],frame.shape[0]], np.ceil(box[2:]+.3*extent)).astype(int)
    crop = frame[lo[1]:hi[1], lo[0]:hi[0]]
    scale = min(1., 800/max(crop.shape[:2]))
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    short = float(np.linalg.norm(predicted-np.roll(predicted,-1,axis=0),axis=1).min())*scale
    hsv = cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv,np.uint8([75,65,20]),np.uint8([145,255,255]))
    gray = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    minimum, maximum = max(3,round(short*.015)), max(6,round(short*.065))
    evidence.update(hole_radius_range_px=[minimum/scale,maximum/scale],
        radius_basis="current_model_mount_short_edge", mount_short_edge_px=round(short/scale,3))
    circles = cv2.HoughCircles(cv2.GaussianBlur(gray,(5,5),1.),cv2.HOUGH_GRADIENT,
        dp=1.2,minDist=max(12,short*.06),param1=90,param2=24,minRadius=minimum,maxRadius=maximum)
    candidates = []
    for x,y,radius in ([] if circles is None else circles[0]):
        margin = int(np.ceil(radius*1.9))
        x0,y0=max(0,int(x)-margin),max(0,int(y)-margin)
        x1,y1=min(gray.shape[1],int(x)+margin+1),min(gray.shape[0],int(y)+margin+1)
        yy,xx=np.mgrid[y0:y1,x0:x1]
        distance=(xx-x)**2+(yy-y)**2
        annulus=(distance>=(radius*1.15)**2)&(distance<=(radius*1.85)**2)
        fraction=float(np.mean(blue[y0:y1,x0:x1][annulus]>0)) if annulus.any() else 0.
        if fraction >= .30:
            candidates.append((fraction,np.array([x,y])/scale+lo,float(radius)/scale))
    for fraction,point,radius in _contour_rings(gray,blue,short):
        if radius > maximum or fraction < .20:
            continue
        point, radius = point/scale+lo, radius/scale
        candidates=[c for c in candidates if np.linalg.norm(c[1]-point)>max(c[2],radius)*.75]
        candidates.append((fraction,point,radius))
    candidates=sorted(candidates,key=lambda item:item[0],reverse=True)[:16]
    evidence["ring_candidates"]=len(candidates)
    evidence["candidate_centers_px"]=[np.round(c[1],2).tolist() for c in candidates]
    if len(candidates)<4:
        evidence["reason"]="four_visible_pcb_rings_required"
        return None
    area=abs(cv2.contourArea(predicted)); diagonal=max(np.linalg.norm(predicted[2]-predicted[0]),1.)
    best=None
    for chosen in combinations(candidates,4):
        if max(c[2] for c in chosen)>1.6*min(c[2] for c in chosen):
            continue
        quad=np.float32([c[1] for c in chosen]); center=quad.mean(0)
        quad=quad[np.argsort(np.arctan2(quad[:,1]-center[1],quad[:,0]-center[0]))]
        if not cv2.isContourConvex(quad) or not .35*area<=cv2.contourArea(quad)<=2.5*area:
            continue
        for shift in range(4):
            ordered=np.roll(quad,shift,axis=0)
            distance=np.linalg.norm(ordered-predicted,axis=1)
            if max(distance)>.45*diagonal:
                continue
            edges=np.linalg.norm(ordered-np.roll(ordered,-1,axis=0),axis=1)
            ratio=(edges[0]+edges[2])/(edges[1]+edges[3])
            if (not .35<=ratio<=1.2 or max(edges[0]/edges[2],edges[2]/edges[0],
                    edges[1]/edges[3],edges[3]/edges[1])>1.8):
                continue
            score=float(distance.mean())
            if best is not None and score>=best[0]:
                continue
            measured=replace(observation,corners_px=ordered.astype(float),source="photo_tft_small_rings")
            orientation={}
            if _screen_frame_supported(frame,ordered):
                measured=orient_tft_from_panel_inset(frame,measured,orientation)
            if not orientation.get("verified"):
                measured=photo_lcd_orientation(frame,measured,orientation)
                if measured is None:
                    continue
            best=(score,measured,orientation,[round(c[2],2) for c in chosen])
    if best is None:
        evidence["reason"]="ring_layout_or_header_unverified"
        return None
    evidence.update(accepted=True,reason="four_rings_lcd_and_header",observed_rings=4,
        holes_supported=4,screen_supported=True,orientation=best[2],ring_radii_px=best[3],
        mean_delta_px=round(best[0],3),observed_mounts_px=best[1].corners_px.tolist())
    return best[1]


class PhotoGeometry:
    """Reusable descriptors only; each measurement resets its frame evidence."""
    def __init__(self):
        self._board_reference=None
        self._reference_image=None
        self._board_fallback=None
        self._component_references={}

    def board(self, frame, result, detector):
        primary=getattr(detector,"primary",detector)
        profile=getattr(primary,"_profile",None)
        reference=getattr(primary,"_reference_board_bgr",None)
        raw=_points(result.outline_px)
        model_confidence=float((result.body or {}).get("confidence",result.confidence))
        local=_localization(result.board_id,raw,model_confidence,getattr(primary,"_locator",None))
        local["evidence"]["model_pose_path"]=result.pose_path
        evidence=local["evidence"]
        def rejected(reason):
            local["reason"]=reason
            return replace(result,tracking="searching",pins=[],outline_px=None,
                pose_stability_state="photo_geometry_unverified",pose_image_confirmed=False),local
        if result.body:
            local["status"]="uncertain"
        if profile is None:
            return rejected("profile_missing")
        has_quad = raw is not None and _quad_valid(raw, frame)
        observation = (_observation(raw,result.confidence,result.body) if has_quad
                       else _body_search_region(result.body, frame))
        if observation is None:
            return rejected("invalid_or_clipped_geometry" if raw is not None
                            else "model_body_only" if result.body else "model_missing")
        evidence["search_region_basis"] = "model_quad" if has_quad else "body_roi_only"
        evidence["search_region_px"] = list(observation.box_xyxy)
        try:
            boundary={}
            # A box carries no semantic orientation: it cannot seed the PCB
            # corner fallback. Only independent reference matching may recover it.
            pcb=(refine_board_corners_from_pcb(frame,observation,reference_board_bgr=reference,boundary_evidence=boundary)
                 if has_quad else None)
            evidence["pcb_boundary"]=boundary
            matched=None
            native_attempted=False
            def match_native():
                nonlocal native_attempted
                native_attempted=True
                profile_dir=getattr(primary,"_profile_dir",None)
                if self._board_fallback is None and profile_dir is not None:
                    native=_native_board_reference(profile,profile_dir,reference)
                    if native is not None:
                        self._board_fallback=self._board_reference.supplemented("native",native.keypoints,native.descriptors)
                if self._board_fallback is None:
                    return None, {}
                candidate=self._board_fallback.locate(frame,region=observation)
                report=dict(self._board_fallback.evidence)
                report["reference_source"]="one_existing_profile_reference"
                evidence["reference_attempts"].append(dict(strategy="rectified_plus_native_unique",**report))
                return (candidate if _reference_supported(report) else None), report

            if reference is not None:
                if reference is not self._reference_image:
                    self._board_reference=PhotoReferenceRecovery(reference)
                    self._reference_image=reference
                    self._board_fallback=None
                matched=self._board_reference.locate(frame,region=observation)
                evidence["reference"]=dict(self._board_reference.evidence)
                evidence["reference_attempts"]=[dict(strategy="raw_unique",**evidence["reference"])]
                if not _reference_supported(evidence["reference"]):
                    matched,fallback=match_native()
                    if matched is not None:
                        evidence["reference"]=fallback
            if matched is not None:
                corrected=matched; method="reference_sift_j8"
                evidence.update(inliers=evidence["reference"].get("inliers"),
                    reprojection_px=evidence["reference"].get("error_px"),
                    reference_coverage=evidence["reference"].get("coverage"))
            elif pcb is not None:
                orientation=_reference_orientation(frame,pcb.corners_px,reference)
                evidence["pcb_orientation"]=orientation
                corrected=pcb if orientation["verified"] else None
                method="pcb_reference_j8"
            else:
                corrected=None; method="yolo_candidate"
            if corrected is None or not _quad_valid(corrected.corners_px,frame):
                return rejected("board_geometry_unverified")
            size=(frame.shape[1],frame.shape[0])
            confidence = result.confidence if has_quad else float(corrected.confidence)
            pins,outline=_project_profile_on_observed_quad(profile,corrected.corners_px,size,confidence)
            j8={}
            pins=_correct_pi5_j8_from_image(frame,profile,pins,size,diagnostic=j8)
            # A minimally supported board homography may be too imprecise at
            # the thin header. Try the existing native-reference bank once,
            # only accepting a nearby hypothesis with MORE distributed board
            # support, then independently check the current image's J8 rows.
            # Never choose a competing board merely because it yields pins.
            if (not j8.get("accepted") and matched is not None and not native_attempted):
                candidate,report=match_native()
                base=evidence["reference"]
                if candidate is not None and _quad_valid(candidate.corners_px,frame):
                    shift=float(np.linalg.norm(candidate.corners_px-corrected.corners_px,axis=1).max())
                    diagonal=float(np.linalg.norm(corrected.corners_px[2]-corrected.corners_px[0]))
                    stronger=(report.get("unique_inliers",0)>base.get("unique_inliers",0)
                              and report.get("coverage",0)>=base.get("coverage",0)
                              and shift<=.05*diagonal)
                    evidence["native_refinement"]={"stronger_board_support":stronger,"max_corner_shift_px":round(shift,3)}
                    if stronger:
                        candidate_confidence=result.confidence if has_quad else float(candidate.confidence)
                        candidate_pins,candidate_outline=_project_profile_on_observed_quad(profile,candidate.corners_px,size,candidate_confidence)
                        candidate_j8={}
                        candidate_pins=_correct_pi5_j8_from_image(frame,profile,candidate_pins,size,diagnostic=candidate_j8)
                        evidence["j8_attempts"]=[dict(strategy="rectified",**j8),dict(strategy="rectified_plus_native",**candidate_j8)]
                        corrected=candidate; confidence=candidate_confidence
                        pins,outline,j8=candidate_pins,candidate_outline,candidate_j8
                        evidence["reference"]=report
                        evidence.update(inliers=report.get("inliers"),reprojection_px=report.get("error_px"),reference_coverage=report.get("coverage"))
            local.update(method=method,corrected_outline_px=_points(corrected.corners_px))
            _delta(evidence,raw,corrected.corners_px)
            evidence["board_geometry_verified"]=True
            evidence["j8"]=j8
            evidence["j8_support_samples"]=sum(j8.get("support",[])) if j8.get("accepted") else 0
            evidence["candidate_contact_support"]=j8.get("support",[])
            evidence["contact_support_is_contrast_only"]=True
            evidence["pin_coordinates_basis"]="profile_projection_with_current_image_alignment"
            evidence["pin_method"]="profile_projection_j8_rows" if j8.get("accepted") else "profile_projection_j8_unverified"
            local["candidate_pins"]=[dict(id=p.pin_id,x=p.x,y=p.y,v=p.visible) for p in pins]
            if not j8.get("accepted"):
                return rejected("j8_rows_unverified")
            local.update(status="located",reason="board_and_j8_supported")
            evidence["pin_geometry_verified"]=True
            return replace(result,tracking="locked",confidence=confidence,pins=pins,outline_px=outline,
                pose_path="photo_"+method,pose_stability_state="current_photo_supported",
                pose_inliers=evidence.get("inliers"),pose_reproj_px=evidence.get("reprojection_px"),
                pin_alignment=j8,pose_image_confirmed=False),local
        except (ValueError,TypeError,AttributeError,cv2.error):
            log.exception("Photo board geometry failed closed")
            return rejected("local_geometry_error")

    def component(self,frame,result,worker):
        profile=getattr(worker,"_profile",None)
        raw=_points(result.outline_px)
        confidence=result.model_confidence if result.model_confidence is not None else result.confidence
        local=_localization(result.component_id,raw,confidence,getattr(worker,"_locator",None))
        local["evidence"]["model_pose_path"]=result.stability
        evidence=local["evidence"]
        def rejected(reason):
            local["reason"]=reason
            return replace(result,tracking="searching",pins=(),outline_px=None,
                stability="photo_geometry_unverified",tracking_reason=reason),local
        if raw is None:
            if result.body:
                local["status"]="uncertain"
            return rejected("invalid_model_geometry" if result.body else "model_missing")
        if profile is None:
            return rejected("profile_missing")
        try:
            # The direct DTO contains the display outline, not mount centres.
            # Invert that exact profile transform before measuring real rings.
            transform=cv2.getPerspectiveTransform(np.float32(profile.display_outline),np.float32(raw))
            mounts=cv2.perspectiveTransform(UNIT[None],transform)[0]
            if not _quad_valid(mounts,frame):
                return rejected("invalid_or_clipped_geometry")
            observation=_observation(mounts,confidence,result.body)
            if result.component_id=="mrd-tf240-8p-cs":
                ring={}
                corrected=refine_photo_tft_rings(frame,observation,ring)
                evidence["rings"]=ring
                evidence["ring_attempts"]=[dict(search_expansion=1.,**ring)]
                if corrected is None:
                    # A small single-frame model box must not crop away real
                    # mounts. One bounded wider search still requires FOUR
                    # measured holes and independent LCD/header orientation.
                    box=np.asarray(observation.box_xyxy,float)
                    center=(box[:2]+box[2:])/2; extent=(box[2:]-box[:2])*.75
                    expanded=replace(observation,
                        corners_px=mounts.mean(0)+(mounts-mounts.mean(0))*1.5,
                        box_xyxy=tuple(np.r_[center-extent,center+extent]))
                    ring={}
                    corrected=refine_photo_tft_rings(frame,expanded,ring)
                    evidence["ring_attempts"].append(dict(search_expansion=1.5,**ring))
                    evidence["rings"]=ring
                if corrected is None:
                    # Fresh acquirer has no previous pose/orientation anchor.
                    acquirer=TftRingAcquirer()
                    fallback=acquirer.locate(frame,observation,result.frame_id,result.ts_ms)
                    evidence["ring_fallback"]=acquirer.evidence
                    accepted=acquirer.evidence.get("accepted") and acquirer.evidence.get("orientation",{}).get("verified")
                    # Three rings + inferred fourth are diagnostic only here.
                    count=acquirer.evidence.get("observed_rings",4 if acquirer.evidence.get("reason")=="four_visible_pcb_rings" else 0)
                    if fallback is not None and accepted and count==4:
                        corrected=fallback; ring=acquirer.evidence
                        evidence["rings"]=ring
                evidence["holes_supported"]=4 if corrected is not None else 0
                method="tft_rings_lcd_header"
                reason="four_rings_lcd_and_header"
            else:
                recovery=getattr(worker,"_reference_recovery",None)
                if recovery is not None:
                    if id(recovery) not in self._component_references:
                        primary=PhotoReferenceRecovery(recovery.reference,recovery=recovery)
                        self._component_references[id(recovery)]=[primary,primary.with_current_clahe(),None,None]
                    references=self._component_references[id(recovery)]
                    primary,fallback=references[:2]
                    corrected=primary.locate(frame,region=observation)
                    evidence["reference"]=dict(primary.evidence)
                    evidence["reference_attempts"]=[dict(strategy="raw_unique",**evidence["reference"])]
                    if corrected is None or not _reference_supported(evidence["reference"]):
                        corrected=fallback.locate(frame,region=observation)
                        evidence["reference"]=dict(fallback.evidence)
                        evidence["reference_attempts"].append(dict(strategy="raw_plus_current_clahe_unique",**evidence["reference"]))
                    if corrected is None or not _reference_supported(evidence["reference"]):
                        if references[2] is None:
                            references[2]=primary.with_pcb_view_bank()
                        corrected=references[2].locate(frame,region=observation)
                        evidence["reference"]=dict(references[2].evidence)
                        evidence["reference_attempts"].append(dict(strategy="bounded_pcb_views_unique",**evidence["reference"]))
                    if corrected is None or not _reference_supported(evidence["reference"]):
                        if references[3] is None:
                            references[3]=references[2].with_pcb_query_pyramid()
                        corrected=references[3].locate(frame,region=observation)
                        evidence["reference"]=dict(references[3].evidence)
                        evidence["reference_attempts"].append(dict(strategy="small_pcb_query_pyramid_unique",**evidence["reference"]))
                else:
                    corrected=None
                    evidence["reference"]={"accepted":False,"reason":"reference_missing"}
                if not _reference_supported(evidence["reference"]):
                    corrected=None
                evidence.update(inliers=evidence["reference"].get("inliers"),
                    reprojection_px=evidence["reference"].get("error_px"),reference_coverage=evidence["reference"].get("coverage"))
                method="hc_reference_sift"; reason="distributed_reference_supported"
            if corrected is None or not _quad_valid(corrected.corners_px,frame):
                return rejected("ring_layout_or_header_unverified" if result.component_id=="mrd-tf240-8p-cs" else "component_reference_unverified")
            outline=project_component_outline(profile,corrected.corners_px)
            if not _quad_valid(outline,frame):
                return rejected("invalid_or_clipped_geometry")
            pins=project_component_pins(profile,corrected.corners_px,confidence,(frame.shape[1],frame.shape[0]))
            if not all(np.isfinite([p.x,p.y]).all() and p.visible for p in pins):
                return rejected("projected_pins_outside_photo")
            local.update(status="located",method=method,reason=reason,corrected_outline_px=_points(outline),
                candidate_pins=[dict(id=p.id,x=p.x,y=p.y,v=p.visible) for p in pins])
            evidence.update(board_geometry_verified=True,pin_geometry_verified=True,
                pin_coordinates_basis="profile_projection_from_current_image_anchors",
                pin_method="profile_projection_current_anchors")
            _delta(evidence,raw,outline)
            return replace(result,tracking="locked",pins=pins,outline_px=outline,confidence=float(confidence),
                stability="current_photo_supported",tracking_reason=reason,corner_refinement=evidence),local
        except (ValueError,TypeError,AttributeError,cv2.error):
            log.exception("Photo component geometry failed closed")
            return rejected("local_geometry_error")


def replay_saved_photo(capture_path, photo_path, profile_dir):
    """Offline geometry replay of saved raw model DTOs; performs zero forwards.

    The unchanged JPEG hash must match the packet. DTO coordinates are rounded
    to 0.1px by the original serializer; replay is diagnostic, not new model or
    real-scene accuracy evaluation. No app/server/camera/AI/Pi is constructed.
    """
    import copy
    import hashlib
    import json
    from pathlib import Path
    from types import SimpleNamespace
    from app.component_worker import ComponentPoseResult, ComponentVisionProfile, component_pose_message
    from app.profiles.store import ProfileStore
    from app.vision.interface import DetectionResult
    from app.vision.yolo_profile_detector import _canonical_reference_board
    from app.vision_worker import detection_message
    image=Path(photo_path).read_bytes()
    packet=json.loads(Path(capture_path).read_text(encoding="utf-8"))
    if hashlib.sha256(image).hexdigest()!=packet["image_sha256"]:
        raise ValueError("Saved photograph hash does not match capture")
    frame=cv2.imdecode(np.frombuffer(image,np.uint8),cv2.IMREAD_COLOR)
    if frame is None or [frame.shape[1],frame.shape[0]]!=packet["video_size"]:
        raise ValueError("Saved photograph size does not match capture")
    for source in [packet["detection"],*packet["components"]]:
        if (source.get("frame_id")!=packet["frame_id"] or source.get("ts_ms")!=packet["capture_ts_ms"]
                or source.get("video_size")!=packet["video_size"]
                or source.get("runtime_revision")!=packet["runtime_revision"]):
            raise ValueError("Saved model DTO does not match source frame/runtime")
    if packet["detection"].get("board_id")!="raspberry-pi-5":
        raise ValueError("Saved model DTO has the wrong board identity")
    geometry=PhotoGeometry()
    store=ProfileStore(profile_dir)
    profile=store.profile("raspberry-pi-5")
    detector=SimpleNamespace(_profile=profile,
        _profile_dir=store.board_dir("raspberry-pi-5"),
        _reference_board_bgr=_canonical_reference_board(profile,store.board_dir("raspberry-pi-5")),
        _locator=SimpleNamespace(model_path="saved_model_output"))
    source=packet["detection"]
    original_local={entry["object_id"]:entry for entry in packet.get("localization",[])}
    board_outline=original_local.get(source["board_id"],{}).get("raw_outline_px",source["outline"])
    raw=DetectionResult(source["board_id"],source["frame_id"],source["ts_ms"],source["tracking"],
        source["confidence"],outline_px=board_outline,body=source.get("body"),
        pose_path=source.get("pose_quality",{}).get("path"))
    board,local=geometry.board(frame,raw,detector)
    result=copy.deepcopy(packet)
    result["detection"]=detection_message(board,tuple(packet["video_size"]),packet["runtime_revision"])
    result["localization"]=[local]; result["components"]=[]
    for source in packet["components"]:
        path=Path(profile_dir)/"components"/source["component_id"]/"vision_profile.json"
        worker=SimpleNamespace(_profile=ComponentVisionProfile.load(path),
            _reference_recovery=ReferencePoseRecovery.from_component_profile(path),
            _locator=SimpleNamespace(model_path="saved_model_output"))
        outline=original_local.get(source["component_id"],{}).get("raw_outline_px",source["outline"])
        raw=ComponentPoseResult(source["component_id"],source["frame_id"],source["ts_ms"],source["tracking"],
            source["confidence"],tuple(source["video_size"]),
            None if outline is None else np.asarray(outline),(),"saved_model_output",
            model_confidence=source.get("pose_quality",{}).get("model_confidence"),body=source.get("body"))
        component,local=geometry.component(frame,raw,worker)
        result["components"].append({**component_pose_message(component),"runtime_revision":packet["runtime_revision"]})
        result["localization"].append(local)
    result["replay"]=dict(mode="saved_detection_geometry_only",model_forwards=0,
        original_detection_precision_px=.1,source_image_sha256=packet["image_sha256"])
    return result


if __name__=="__main__":
    import argparse
    import json
    from pathlib import Path
    parser=argparse.ArgumentParser(description="Replay photo geometry from a saved same-frame packet")
    parser.add_argument("--capture",required=True)
    parser.add_argument("--photo",required=True)
    parser.add_argument("--profiles",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    packet=replay_saved_photo(args.capture,args.photo,args.profiles)
    Path(args.output).write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"frame_id":packet["frame_id"],"objects":[{"id":item["object_id"],
        "status":item["status"],"reason":item["reason"],"outline":item["corrected_outline_px"],
        "evidence":item["evidence"]} for item in packet["localization"]]},ensure_ascii=False,indent=2))
