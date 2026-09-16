"""Webcam TFT acquisition from four visible PCB mounting rings.

The existing model supplies identity and semantic orientation, not exact hole
centres. Search its bounded ROI jointly so a shifted model corner need not
already be within the historical per-corner 96px search. No hidden hole is
inferred and no previous frame is returned as a current observation.
"""
from dataclasses import replace
from itertools import combinations

import cv2
import numpy as np


class TftRingAcquirer:
    """Model-identified acquisition, then fresh local four-hole measurements.

    A previous pose only bounds a search for 600ms; it is never returned as a
    measurement. Missing rings/LCD produce no result; camera changes and gaps
    invalidate the search anchor.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._last = None
        self.evidence = {}

    def locate(self, frame, observation, frame_id, ts_ms):
        previous = self._last
        if previous is not None:
            _, old_id, old_ts, shape = previous
            if frame.shape != shape or frame_id <= old_id or not 0 < ts_ms-old_ts <= 600:
                previous = self._last = None
        evidence = {}
        refined = refine_tft_rings(frame, observation, evidence) if observation is not None else None
        if refined is None and previous is not None:
            evidence = {'search': 'recent_measured_rings', 'model_attempt': evidence}
            refined = refine_tft_rings(frame, previous[0], evidence)
        panel_seed = previous[0] if previous is not None else observation
        if refined is None and panel_seed is not None:
            panel_evidence = {}
            refined = refine_tft_panel(frame, panel_seed, panel_evidence)
            if refined is not None:
                evidence = panel_evidence
            else:
                evidence['panel_attempt'] = panel_evidence
        self.evidence = evidence
        if refined is not None:
            self._last = (refined, frame_id, ts_ms, frame.shape)
        return refined


def _contour_rings(gray, blue, short):
    """Dark closed holes inside bright plating; blue need not surround every hole."""
    light = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,-8)
    contours, hierarchy = cv2.findContours(light, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    result=[]
    for contour, parent in zip(contours,hierarchy[0]):
        if parent[3]<0 or len(contour)<5:
            continue
        area=cv2.contourArea(contour)
        perimeter=cv2.arcLength(contour,True)
        if area<12 or 4*np.pi*area/max(perimeter**2,1)<.72:
            continue
        (x,y),(a,b),_=cv2.fitEllipse(contour)
        radius=(a+b)/4
        if min(a,b)/max(a,b,1)<.65 or not max(2.5,.009*short)<=radius<=max(6,.055*short):
            continue
        margin=int(np.ceil(radius*2.7))
        x1,y1=max(0,int(x)-margin),max(0,int(y)-margin)
        x2,y2=min(gray.shape[1],int(x)+margin+1),min(gray.shape[0],int(y)+margin+1)
        yy,xx=np.mgrid[y1:y2,x1:x2]
        distance=np.sqrt((xx-x)**2+(yy-y)**2)/radius
        inner=distance<.65
        plating=(distance>1.15)&(distance<1.6)
        surroundings=(distance>1.8)&(distance<2.6)
        if not inner.any() or not plating.any() or not surroundings.any():
            continue
        patch=gray[y1:y2,x1:x2]
        contrast=float(np.median(patch[plating]))-float(np.median(patch[inner]))
        if contrast<35:
            continue
        fraction=float(np.mean(blue[y1:y2,x1:x2][surroundings]>0))
        result.append((fraction,np.float32([x,y]),radius*1.4))
    return result


def _screen_frame_supported(frame, corners):
    """Require an independently visible large rectangular panel between the rings."""
    # The mounting-hole centres are inset from the PCB: the LCD side rails
    # extend outside their quadrilateral. Include those rails in the warp.
    target=np.float32([[24,24],[183,24],[183,243],[24,243]])
    canonical=cv2.warpPerspective(frame,cv2.getPerspectiveTransform(np.float32(corners),target),(208,268))
    gray=cv2.cvtColor(canonical,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,35,100)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if cv2.contourArea(contour)<.50*160*220:
            continue
        quad=cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True).reshape(-1,2)
        if len(quad)!=4 or not cv2.isContourConvex(quad):
            continue
        # The PCB itself is also a rectangle: require the inset LCD, not the
        # board outline or a four-hole blank plate.
        if quad[:,1].min()<28 or quad[:,1].max()>239:
            continue
        center=(quad.mean(0)-24)/[160,220]
        if np.max(np.abs(center-.5))>.16:
            continue
        vectors=np.abs(quad-np.roll(quad,-1,axis=0))
        if np.all(vectors.min(1)/np.maximum(vectors.max(1),1)<.30):
            return True
    return False


def refine_tft_panel(frame, observation, evidence):
    """Four observed LCD edges + >=3 real rings, when a wire covers one hole.

    Project the mounting system from the LCD (not a fabricated fourth ring).
    The LCD's inset relative to the holes disambiguates its top/bottom strip.
    """
    evidence.update(accepted=False,source='tft_panel_geometry')
    predicted=np.float32(observation.corners_px)
    box=np.asarray(observation.box_xyxy,float)
    if predicted.shape!=(4,2) or box.shape!=(4,) or not np.isfinite(predicted).all() or not np.isfinite(box).all():
        return None
    extent=box[2:]-box[:2]
    if min(extent)<50 or not cv2.isContourConvex(predicted):
        return None
    margin=.3 if observation.source in ('tft_ring_geometry','tft_panel_geometry') else 1.2
    lo=np.maximum(0,np.floor(box[:2]-margin*extent)).astype(int)
    hi=np.minimum([frame.shape[1],frame.shape[0]],np.ceil(box[2:]+margin*extent)).astype(int)
    if np.any(hi-lo<32):
        return None
    crop=frame[lo[1]:hi[1],lo[0]:hi[0]]
    scale=min(1.,800/max(crop.shape[:2]))
    if scale<1:
        crop=cv2.resize(crop,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    inverse_warp=None
    if observation.source in ('tft_ring_geometry','tft_panel_geometry'):
        # Align the current image, not a cached image. This joins thin LCD
        # rails consistently while allowing the new edge measurements to move.
        target=np.float32([[32,32],[271,32],[271,471],[32,471]])
        warp=cv2.getPerspectiveTransform(predicted,target)
        crop=cv2.warpPerspective(frame,warp,(304,504))
        inverse_warp=np.linalg.inv(warp)
        scale=1.;lo=np.array([0,0]);extent=np.array([240.,440.])
    gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    blue=cv2.inRange(cv2.cvtColor(crop,cv2.COLOR_BGR2HSV),np.uint8([75,65,20]),np.uint8([145,255,255]))
    circles=cv2.HoughCircles(cv2.GaussianBlur(gray,(5,5),1),cv2.HOUGH_GRADIENT,1.2,
        minDist=12,param1=90,param2=17,minRadius=4,maxRadius=max(8,round(min(extent)*scale*.06)))
    rings=[]
    for x,y,r in ([] if circles is None else circles[0]):
        yy,xx=np.ogrid[:gray.shape[0],:gray.shape[1]]
        d=(xx-x)**2+(yy-y)**2
        annulus=(d>(r*1.1)**2)&(d<(r*1.9)**2)
        if annulus.any() and np.mean(blue[annulus]>0)>=.25:
            rings.append([x,y])
    for fraction,point,radius in _contour_rings(gray,blue,min(extent)*scale):
        if fraction>=.25:
            rings=[r for r in rings if np.linalg.norm(np.asarray(r)-point)>radius*.75]
            rings.append(point.tolist())
    evidence['blue_ring_candidates']=len(rings)
    if len(rings)<3:
        return None
    edges=cv2.morphologyEx(cv2.Canny(gray,35,100),cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    lcd=np.float32([[-.04,.075],[1.045,.075],[1.045,.865],[-.04,.865]])
    mounts=np.float32([[0,0],[1,0],[1,1],[0,1]])
    measured=np.float32(rings)
    best=None
    evidence['rectangles']=0
    for contour in contours:
        area=cv2.contourArea(contour)
        if not 2500<=area<=.7*gray.size:
            continue
        quad=cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True).reshape(-1,2)
        if len(quad)!=4 or not cv2.isContourConvex(quad):
            continue
        evidence['rectangles']+=1
        center=quad.mean(0)
        quad=quad[np.argsort(np.arctan2(quad[:,1]-center[1],quad[:,0]-center[0]))]
        for shift in range(4):
            ordered=np.float32(np.roll(quad,shift,axis=0))
            transform=cv2.getPerspectiveTransform(lcd,ordered)
            projected=cv2.perspectiveTransform(mounts[None],transform)[0]
            lengths=np.linalg.norm(projected-np.roll(projected,-1,axis=0),axis=1)
            if not .35<=(lengths[0]+lengths[2])/(lengths[1]+lengths[3])<=1.2:
                continue
            distances=np.linalg.norm(projected[:,None]-measured[None],axis=2)
            nearest=distances.argmin(1)
            errors=distances[np.arange(4),nearest]
            visible=errors<=max(3.,.05*min(lengths))
            if visible.sum()<3 or len(set(nearest[visible]))!=visible.sum():
                continue
            # Refine using all LCD corners and the real visible hole centres.
            # Repeated hole correspondences give precise landmarks more weight
            # than the variable inner edge of the reflective silver rail.
            source=np.concatenate([lcd,*([mounts[visible]]*3)])
            destination=np.concatenate([ordered,*([measured[nearest[visible]]]*3)])
            fitted,_=cv2.findHomography(source,destination,0)
            if fitted is None:
                continue
            projected=cv2.perspectiveTransform(mounts[None],fitted)[0]
            hole_error=np.linalg.norm(projected[visible]-measured[nearest[visible]],axis=1)
            if not cv2.isContourConvex(projected) or max(hole_error)>max(2.,.015*min(lengths)):
                continue
            score=float(np.mean(hole_error))
            if best is None or score<best[0]:
                best=(score,projected.copy(),int(visible.sum()))
    if best is None:
        return None
    corners=best[1]/scale+lo
    if inverse_warp is not None:
        corners=cv2.perspectiveTransform(np.float32(corners)[None],inverse_warp)[0]
    evidence.update(accepted=True,source='tft_panel_geometry',screen_supported=True,
        observed_rings=best[2],reason='lcd_edges_and_visible_rings',ring_error_px=best[0]/scale,
        missing_corner='projected_from_current_lcd_not_observed_ring')
    return replace(observation,corners_px=corners.astype(float),
        box_xyxy=tuple(np.r_[corners.min(0),corners.max(0)]),source='tft_panel_geometry')


def refine_tft_rings(frame, observation, evidence):
    evidence.update(accepted=False, source='tft_ring_geometry')
    predicted = np.asarray(observation.corners_px, np.float32)
    box = np.asarray(observation.box_xyxy, dtype=float)
    if predicted.shape != (4,2) or box.shape != (4,) or not np.isfinite(predicted).all() or not np.isfinite(box).all():
        return None
    extent = box[2:]-box[:2]
    if min(extent) < 50 or not cv2.isContourConvex(predicted):
        return None
    lo = np.maximum(0, np.floor(box[:2]-.3*extent)).astype(int)
    hi = np.minimum([frame.shape[1],frame.shape[0]], np.ceil(box[2:]+.3*extent)).astype(int)
    if np.any(hi-lo < 32):
        return None
    crop = frame[lo[1]:hi[1],lo[0]:hi[0]]
    scale = min(1., 800/max(crop.shape[:2]))
    if scale < 1:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    blue = cv2.inRange(hsv, np.uint8([75,65,20]), np.uint8([145,255,255]))
    native_gray = cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(native_gray,(5,5),1.)
    short = min(extent)*scale
    rings = cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,dp=1.2,
        minDist=max(12,short*.06),param1=90,param2=24,
        minRadius=max(3,round(short*.012)),maxRadius=max(6,round(short*.060)))
    candidates = []
    for x,y,radius in ([] if rings is None else rings[0]):
        radius = float(radius)
        margin = int(np.ceil(radius*1.9))
        x1,y1=max(0,int(x)-margin),max(0,int(y)-margin)
        x2,y2=min(gray.shape[1],int(x)+margin+1),min(gray.shape[0],int(y)+margin+1)
        yy,xx=np.mgrid[y1:y2,x1:x2]
        dist=(xx-x)**2+(yy-y)**2
        annulus=(dist>=(radius*1.15)**2)&(dist<=(radius*1.85)**2)
        fraction=float(np.mean(blue[y1:y2,x1:x2][annulus]>0)) if annulus.any() else 0.
        if fraction >= .30:
            candidates.append((fraction,np.array([x,y])/scale+lo,radius/scale))
    contour_rings=_contour_rings(native_gray,blue,short)
    evidence['plated_hole_candidates']=len(contour_rings)
    for fraction,point,radius in contour_rings:
        point=point/scale+lo
        radius=radius/scale
        # One real hole must not become two votes (Hough + contour).
        candidates=[c for c in candidates if np.linalg.norm(c[1]-point)>max(c[2],radius)*.75]
        candidates.append((fraction,point,radius))
    candidates=sorted(candidates,key=lambda c:c[0],reverse=True)[:12]
    evidence['ring_candidates']=len(candidates)
    if len(candidates)<4:
        evidence['reason']='four_visible_pcb_rings_required'
        return None
    best=None
    area=abs(cv2.contourArea(predicted))
    diagonal=max(np.linalg.norm(predicted[2]-predicted[0]),1.)
    for chosen in combinations(candidates,4):
        # Glare may wash out two corners, but retain independent PCB identity
        # near at least two rings, plus a screen-frame check below.
        if sum(c[0]>=.30 for c in chosen)<2:
            continue
        quad=np.float32([c[1] for c in chosen])
        center=quad.mean(0)
        quad=quad[np.argsort(np.arctan2(quad[:,1]-center[1],quad[:,0]-center[0]))]
        if not cv2.isContourConvex(quad) or not .35*area <= cv2.contourArea(quad) <= 2.5*area:
            continue
        for shift in range(4):
            ordered=np.roll(quad,shift,axis=0)
            distances=np.linalg.norm(ordered-predicted,axis=1)
            if max(distances)>.45*diagonal:
                continue
            edges=np.linalg.norm(ordered-np.roll(ordered,-1,axis=0),axis=1)
            ratio=(edges[0]+edges[2])/(edges[1]+edges[3])
            if not .35<=ratio<=1.2 or max(edges[0]/edges[2],edges[2]/edges[0],edges[1]/edges[3],edges[3]/edges[1])>1.8:
                continue
            score=float(np.mean(distances))
            if (best is None or score<best[0]) and _screen_frame_supported(frame,ordered):
                best=(score,ordered.copy())
    if best is None:
        evidence['reason']='ring_layout_unverified'
        return None
    # All four independently visible centres supply the new geometry. The
    # screen coordinate system/order remains the closest original model order.
    corners=best[1].astype(float)
    evidence.update(accepted=True, reason='four_visible_pcb_rings', screen_supported=True, mean_delta_px=best[0],
                    corners=corners.tolist())
    return replace(observation,corners_px=corners,box_xyxy=tuple(np.r_[corners.min(0),corners.max(0)]),source='tft_ring_geometry')
