"""Photo-only distributed reference matching with unique physical supports.

Descriptor representations can differ; evidence votes cannot. A reference
location or a current-photo location contributes at most one correspondence.
RANSAC's strongest local connector cluster is never accepted merely for its
count: every candidate must meet the same distribution and geometry gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor
import time

import cv2
import numpy as np

from app.vision.reference_recovery import ReferencePoseRecovery, _mutual_ratio_matches
from app.vision.yolo_pose import BoardPoseObservation


@dataclass(frozen=True)
class Correspondence:
    source: np.ndarray
    destination: np.ndarray
    distance: float
    representation: str = ""


class _PointIndex:
    """Exact radius lookup in a small pixel grid, avoiding quadratic scans."""
    def __init__(self,tolerance):
        if tolerance<=0:
            raise ValueError("Point tolerance must be positive")
        self.tolerance=tolerance
        self.buckets={}

    def _key(self,point):
        return floor(point[0]/self.tolerance),floor(point[1]/self.tolerance)

    def add(self,point,value):
        self.buckets.setdefault(self._key(point),[]).append((point,value))

    def nearby(self,point):
        x,y=self._key(point)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for other,value in self.buckets.get((x+dx,y+dy),()):
                    if (point[0]-other[0])**2+(point[1]-other[1])**2<self.tolerance**2:
                        yield value


def corroborated_pairs(pairs,tolerance_px=1.):
    """Require agreement across representations, not duplicate SIFT angles."""
    index=_PointIndex(tolerance_px)
    for pair in pairs:
        index.add(pair.source,pair)
    return [pair for pair in pairs if any(other.representation!=pair.representation
        and np.sum((pair.destination-other.destination)**2)<tolerance_px**2
        for other in index.nearby(pair.source))]


def unique_physical_pairs(pairs, tolerance_px=1., conflict_px=2.):
    """Drop competing destinations, then count a physical location only once.

    SIFT emits multiple orientations at one position; raw/CLAHE and native/
    rectified representations may observe it again. Neither can create votes.
    Pixel tolerances are in canonical-reference and original-photo spaces.
    """
    source_index=_PointIndex(tolerance_px)
    for pair in pairs:
        source_index.add(pair.source,pair)
    valid=[]; conflicts=0
    for pair in pairs:
        if any(np.sum((pair.destination-other.destination)**2)>conflict_px**2
                for other in source_index.nearby(pair.source)):
            conflicts+=1
        else:
            valid.append(pair)
    kept=[]; kept_source=_PointIndex(tolerance_px); kept_destination=_PointIndex(tolerance_px)
    for pair in sorted(valid,key=lambda pair:pair.distance):
        if next(kept_source.nearby(pair.source),None) is not None or next(kept_destination.nearby(pair.destination),None) is not None:
            continue
        kept.append(pair)
        kept_source.add(pair.source,pair); kept_destination.add(pair.destination,pair)
    return kept,conflicts


class PhotoReferenceRecovery:
    """Cached fixed descriptors, fresh features and at most two homographies."""
    def __init__(self,reference_bgr,*,recovery=None,banks=None,query_clahe=False,query_scales=(1.,),query_pcb_mask=False):
        original=recovery or ReferencePoseRecovery(reference_bgr)
        self.reference=original.reference
        self.sift=cv2.SIFT_create(nfeatures=3000)
        self.banks=banks or [(original.descriptor_space,original.keypoints,original.descriptors)]
        self.query_clahe=query_clahe
        self.query_scales=query_scales
        self.query_pcb_mask=query_pcb_mask
        self.evidence={}

    def supplemented(self,representation,keypoints,descriptors):
        return PhotoReferenceRecovery(self.reference,banks=[*self.banks,(representation,keypoints,descriptors)])

    def with_current_clahe(self):
        return PhotoReferenceRecovery(self.reference,banks=self.banks,query_clahe=True)

    def with_pcb_query_pyramid(self):
        """Recover small phone PCB texture without counting resampling as votes."""
        return PhotoReferenceRecovery(self.reference,banks=self.banks,query_clahe=True,
            query_scales=(1.,2.,3.),query_pcb_mask=True)

    def with_pcb_view_bank(self):
        """Bounded photo-only views of the SAME calibrated reference PCB.

        Oblique phone views can lose native SIFT support. Cache five modest
        affine views in raw/CLAHE form, mapping features back to canonical
        reference pixels before physical deduplication. Never count a view as
        another vote, use transducer texture, or relax the acceptance gates.
        """
        gray=cv2.cvtColor(self.reference,cv2.COLOR_BGR2GRAY)
        blue=cv2.inRange(cv2.cvtColor(self.reference,cv2.COLOR_BGR2HSV),
            np.uint8([75,35,12]),np.uint8([145,255,255]))
        mask=cv2.dilate(blue,np.ones((3,3),np.uint8))
        banks=list(self.banks)
        for sx,sy in ((1.,1.),(1.,.7),(.7,1.),(1.,1.4),(1.4,1.)):
            view=cv2.resize(self.reference,None,fx=sx,fy=sy)
            view_gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
            view_mask=cv2.resize(mask,(view.shape[1],view.shape[0]),interpolation=cv2.INTER_NEAREST)
            for contrast in (False,True):
                pixels=cv2.createCLAHE(clipLimit=3.,tileGridSize=(4,4)).apply(view_gray) if contrast else view_gray
                keys,descriptors=self.sift.detectAndCompute(pixels,view_mask)
                # Use effective dimensions, including resize rounding.
                scale=np.array([view.shape[1]/gray.shape[1],view.shape[0]/gray.shape[0]])
                points=[cv2.KeyPoint(float(k.pt[0]/scale[0]),float(k.pt[1]/scale[1]),k.size) for k in keys]
                banks.append((f"pcb_view_{sx}_{sy}_{'clahe' if contrast else 'raw'}",points,descriptors))
        return PhotoReferenceRecovery(self.reference,banks=banks,query_clahe=True)

    def locate(self,frame,region):
        started=time.perf_counter()
        self.evidence=dict(source="reference_sift",accepted=False,
            descriptor_space="photo_unique",reference_representations=[bank[0] for bank in self.banks],
            current_preprocessing=["raw","clahe_3_grid4"] if self.query_clahe else ["raw"],
            query_scales=list(self.query_scales),query_pcb_mask=self.query_pcb_mask,
            unique_tolerance_px=1.,conflict_tolerance_px=2.,uses_previous_photo=False)
        try:
            return self._locate(frame,region)
        finally:
            self.evidence["ms"]=round((time.perf_counter()-started)*1000,2)

    def _locate(self,frame,region):
        if frame is None or frame.size==0 or region is None:
            self.evidence["reason"]="roi_model_missing"
            return None
        height,width=frame.shape[:2]
        box=np.asarray(region.box_xyxy,float)
        if box.shape!=(4,) or not np.isfinite(box).all():
            self.evidence["reason"]="invalid_roi"
            return None
        margin=.15*max(box[2:]-box[:2])
        lo=np.maximum(0,np.floor(box[:2]-margin)).astype(int)
        hi=np.minimum([width,height],np.ceil(box[2:]+margin)).astype(int)
        if np.any(hi-lo<32):
            self.evidence["reason"]="insufficient_roi"
            return None
        crop=frame[lo[1]:hi[1],lo[0]:hi[0]]
        original_gray=cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY)
        pcb_mask=None
        if self.query_pcb_mask:
            pcb_mask=cv2.inRange(cv2.cvtColor(crop,cv2.COLOR_BGR2HSV),
                np.uint8([75,35,12]),np.uint8([145,255,255]))
            pcb_mask=cv2.dilate(pcb_mask,np.ones((3,3),np.uint8))
        views=[]
        for requested_scale in self.query_scales:
            scale=min(requested_scale,1440/max(original_gray.shape) if self.query_pcb_mask else 960/max(original_gray.shape))
            gray=cv2.resize(original_gray,None,fx=scale,fy=scale,
                interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR) if scale!=1 else original_gray
            # Use effective per-axis scale after resize rounding.
            factor=np.array([gray.shape[1]/original_gray.shape[1],gray.shape[0]/original_gray.shape[0]])
            mask=cv2.resize(pcb_mask,(gray.shape[1],gray.shape[0]),interpolation=cv2.INTER_NEAREST) if pcb_mask is not None else None
            views.append((gray,mask,factor))
            if self.query_clahe:
                views.append((cv2.createCLAHE(clipLimit=3.,tileGridSize=(4,4)).apply(gray),mask,factor))
        pairs=[]
        for view,mask,factor in views:
            points,descriptors=self.sift.detectAndCompute(view,mask)
            if descriptors is None or len(points)<16:
                continue
            for representation,keypoints,reference_descriptors in self.banks:
                if reference_descriptors is None:
                    continue
                for match in _mutual_ratio_matches(reference_descriptors,descriptors):
                    pairs.append(Correspondence(np.asarray(keypoints[match.queryIdx].pt),
                        np.asarray(points[match.trainIdx].pt)/factor+lo,float(match.distance),representation))
        raw_count=len(pairs)
        if self.query_pcb_mask:
            # Reject a match seen only in one reference representation. This
            # filters ambiguous descriptor proposals, never adds evidence votes.
            pairs=corroborated_pairs(pairs)
        unique,conflicts=unique_physical_pairs(pairs)
        self.evidence.update(roi_confidence=float(region.confidence),raw_correspondences=raw_count,
            corroborated_correspondences=len(pairs),
            conflicting_correspondences=conflicts,matches=len(unique),unique_matches=len(unique))
        if len(unique)<16:
            self.evidence["reason"]="insufficient_unique_matches"
            return None
        source=np.float32([pair.source for pair in unique])
        destination=np.float32([pair.destination for pair in unique])
        rh,rw=self.reference.shape[:2]
        canonical=np.float32([[0,0],[rw-1,0],[rw-1,rh-1],[0,rh-1]])
        attempts=[]; accepted=[]
        # Fixed bounded hypotheses. MAGSAC can find distributed PCB support
        # when ordinary maximum-count RANSAC selects a repetitive USB cluster.
        for method_name,method in (("ransac",cv2.RANSAC),("magsac",cv2.USAC_MAGSAC)):
            matrix,mask=cv2.findHomography(source,destination,method,3.)
            if matrix is None or mask is None or not np.isfinite(matrix).all():
                attempts.append(dict(method=method_name,accepted=False,reason="homography_missing"))
                continue
            errors=np.linalg.norm(cv2.perspectiveTransform(source[None],matrix)[0]-destination,axis=1)
            # Robust-estimator masks can retain an outlier after refitting.
            # It must not inflate unique count, coverage or source quadrants.
            inliers=mask.ravel().astype(bool)&np.isfinite(errors)&(errors<=3.)
            count,ratio=int(inliers.sum()),float(inliers.mean())
            if count<4:
                attempts.append(dict(method=method_name,accepted=False,reason="insufficient_inliers",inliers=count))
                continue
            coverage=cv2.contourArea(cv2.convexHull(source[inliers]))/(rw*rh)
            quadrants=((source[inliers,0]>=rw/2).astype(int)+2*(source[inliers,1]>=rh/2).astype(int))
            error=float(np.median(errors[inliers]))
            report=dict(method=method_name,accepted=False,inliers=count,unique_inliers=count,
                inlier_ratio=round(ratio,3),coverage=round(coverage,3),quadrants=int(len(np.unique(quadrants))),
                error_px=round(error,3),reason="weak_distributed_support")
            attempts.append(report)
            if count<16 or ratio<.45 or coverage<.18 or len(np.unique(quadrants))<3 or error>2.:
                continue
            corners=cv2.perspectiveTransform(canonical[None],matrix)[0]
            area=cv2.contourArea(corners,oriented=True)
            edges=np.linalg.norm(corners-np.roll(corners,-1,axis=0),axis=1)
            if (not np.isfinite(corners).all() or not cv2.isContourConvex(corners)
                    or not .005*width*height<=area<=.6*width*height or edges.min()<25
                    or edges.max()/edges.min()>4 or np.any(corners<lo) or np.any(corners>hi)):
                report["reason"]="invalid_geometry"
                continue
            report.update(accepted=True,reason="matched_reference")
            accepted.append((count,coverage,-error,report,BoardPoseObservation(corners.astype(float),min(.9,.5+.5*ratio),
                np.full(4,min(.9,.5+.5*ratio)),tuple(np.r_[corners.min(0),corners.max(0)]),source="reference_sift")))
        if accepted:
            best=max(accepted,key=lambda item:item[:3])
            self.evidence.update(best[3],hypotheses=attempts)
            return best[4]
        self.evidence.update(attempts[-1] if attempts else {"reason":"homography_missing"},hypotheses=attempts)
        return None
