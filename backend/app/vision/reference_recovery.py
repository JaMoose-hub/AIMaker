"""Recover semantic PCB coordinates from the existing calibrated reference.

YOLO's box only bounds computation. It never supplies GPIO orientation here:
mutual SIFT correspondences + distributed homography inliers establish that.
"""
from __future__ import annotations

import time
import json
from pathlib import Path
import cv2
import numpy as np

from app.vision.yolo_pose import BoardPoseObservation
from app.vision.scale_recovery import ComponentScaleRecovery


def _mutual_ratio_matches(reference_descriptors, frame_descriptors):
    """Exact mutual matching, but reverse-check only ratio-test survivors.

    Reverse neighbours for the other frame descriptors cannot affect the
    result. Avoiding those unused exhaustive searches keeps the same L2,
    ratio and reciprocal gates while reducing recovery latency.
    """
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(reference_descriptors, frame_descriptors, k=2)
    tentative = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
                 if a.distance < .72 * b.distance]
    if not tentative:
        return []
    indices = np.unique([match.trainIdx for match in tentative])
    reverse = matcher.match(frame_descriptors[indices], reference_descriptors)
    reverse_indices = {int(indices[m.queryIdx]): m.trainIdx for m in reverse}
    return [m for m in tentative if reverse_indices.get(m.trainIdx) == m.queryIdx]


class ReferencePoseRecovery:
    def __init__(self, reference_bgr, roi_locator=None, feature_mask=None):
        self.roi_locator = roi_locator
        self.sift = cv2.SIFT_create(nfeatures=3000)
        self.reference = reference_bgr
        self.keypoints, self.descriptors = ([], None)
        self.evidence = {}
        self.descriptor_space = 'rectified'
        # Fresh YOLO identity is useful even when SIFT cannot establish pins.
        self.last_observation: BoardPoseObservation | None = None
        self._scale_recovery = ComponentScaleRecovery(vertical_strips=True)
        self._scale_recovery_enabled = False
        if reference_bgr is not None:
            self.keypoints, self.descriptors = self.sift.detectAndCompute(
                cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY), feature_mask)

    @classmethod
    def from_component_profile(cls, profile_path):
        """Optional real reference with previously verified semantic corners."""
        path = Path(profile_path)
        spec = json.loads(path.read_text(encoding='utf-8')).get('reference_pose')
        if spec is None:
            return None
        source = np.asarray(spec['corners_px'], np.float32)
        if (source.shape != (4, 2) or not np.isfinite(source).all()
                or not cv2.isContourConvex(source) or cv2.contourArea(source, oriented=True) <= 0):
            raise ValueError('reference_pose requires four ordered semantic corners')
        image = cv2.imread(str(path.parent / spec['image']))
        if image is None:
            raise ValueError('reference_pose image is missing')
        if np.any(source < 0) or np.any(source >= [image.shape[1], image.shape[0]]):
            raise ValueError('reference_pose corners must be inside its image')
        width, height = (int(v) for v in spec.get('rectified_size', [320, 240]))
        if not (32 <= width <= 960 and 32 <= height <= 960):
            raise ValueError('reference_pose size must be between 32 and 960')
        target = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
        source_to_canonical = cv2.getPerspectiveTransform(source, target)
        reference = cv2.warpPerspective(image, source_to_canonical, (width, height))
        descriptor_space = spec.get('descriptor_space', 'rectified')
        if descriptor_space not in ('rectified', 'native'):
            raise ValueError('reference_pose descriptor_space must be rectified or native')
        if descriptor_space == 'native':
            # Warping the image before SIFT changes local gradients/scale. Keep
            # descriptors from the real capture, and transform only their
            # coordinates into the shared, semantic PCB system.
            x, y, crop_width, crop_height = cv2.boundingRect(source)
            cropped = image[y:y+crop_height, x:x+crop_width]
            polygon = np.zeros(cropped.shape[:2], np.uint8)
            cv2.fillConvexPoly(polygon, np.int32(source-[x, y]), 255)
            mask = polygon
            if spec.get('feature_region') == 'blue_pcb':
                hsv = cv2.cvtColor(cropped, cv2.COLOR_BGR2HSV)
                blue = cv2.inRange(hsv, np.uint8([75,35,12]), np.uint8([145,255,255]))
                mask = cv2.dilate(blue, np.ones((3,3), np.uint8)) & polygon
            recovery = cls(cropped, feature_mask=mask)
            if recovery.keypoints:
                positions = np.float32([np.asarray(k.pt)+[x, y] for k in recovery.keypoints])
                positions = cv2.perspectiveTransform(positions[None], source_to_canonical)[0]
                recovery.keypoints = [cv2.KeyPoint(float(p[0]), float(p[1]), k.size)
                                      for p, k in zip(positions, recovery.keypoints)]
            recovery.reference = reference
            recovery.descriptor_space = 'native'
            return recovery
        feature_mask = None
        if spec.get('feature_region') == 'blue_pcb':
            hsv = cv2.cvtColor(reference, cv2.COLOR_BGR2HSV)
            blue = cv2.inRange(hsv,np.uint8([75,35,12]),np.uint8([145,255,255]))
            feature_mask = cv2.dilate(blue,np.ones((3,3),np.uint8))
        return cls(reference, feature_mask=feature_mask)

    def locate(self, frame, region=None):
        started = time.perf_counter()
        self.evidence = {'source': 'reference_sift', 'accepted': False,
                         'descriptor_space': self.descriptor_space}
        self.last_observation = None
        try:
            return self._locate(frame, region)
        finally:
            self.evidence['ms'] = round((time.perf_counter() - started) * 1000, 2)

    def set_scale_recovery(self, enabled: bool) -> None:
        self._scale_recovery_enabled = bool(enabled)
        self._scale_recovery.reset()

    def reset_tracking(self) -> None:
        self.last_observation = None
        self.evidence = {}
        self._scale_recovery.reset()

    def locate_yolo(self, frame):
        """Run the existing YOLO locator and optional crop, without SIFT."""
        self.last_observation = None
        if frame is None or frame.size == 0 or self.roi_locator is None:
            return None
        observation = self.roi_locator.locate(frame)
        if observation is None and self._scale_recovery_enabled:
            observation = self._scale_recovery.locate(frame, self.roi_locator)
        self.last_observation = observation
        return observation

    def _locate(self, frame, region):
        if frame is None or frame.size == 0:
            return None
        if region is None and self.roi_locator is not None:
            region = self.locate_yolo(frame)
        if region is None:
            self.evidence['reason'] = 'roi_model_missing'
            return None
        self.last_observation = region
        self.evidence['roi_confidence'] = float(region.confidence)
        if self.descriptors is None:
            self.evidence['reason'] = 'missing_reference_features'
            return None
        height, width = frame.shape[:2]
        box = np.asarray(region.box_xyxy, dtype=float)
        if box.shape != (4,) or not np.isfinite(box).all():
            return None
        margin = .15 * max(box[2:] - box[:2])
        x1, y1 = np.maximum(0, np.floor(box[:2] - margin)).astype(int)
        x2, y2 = np.minimum([width, height], np.ceil(box[2:] + margin)).astype(int)
        if x2-x1 < 32 or y2-y1 < 32:
            return None
        gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        scale = min(1., 960. / max(gray.shape))
        if scale < 1:
            gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        points, descriptors = self.sift.detectAndCompute(gray, None)
        if descriptors is None or len(points) < 16:
            self.evidence['reason'] = 'insufficient_texture'
            return None
        matches = _mutual_ratio_matches(self.descriptors, descriptors)
        self.evidence['matches'] = len(matches)
        if len(matches) < 16:
            self.evidence['reason'] = 'insufficient_matches'
            return None
        src = np.float32([self.keypoints[m.queryIdx].pt for m in matches])
        dst = np.float32([np.asarray(points[m.trainIdx].pt)/scale + [x1, y1] for m in matches])
        matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.)
        if matrix is None or mask is None or not np.isfinite(matrix).all():
            return None
        inliers = mask.ravel().astype(bool)
        count, ratio = int(inliers.sum()), float(inliers.mean())
        rh, rw = self.reference.shape[:2]
        coverage = cv2.contourArea(cv2.convexHull(src[inliers])) / (rw * rh)
        quadrants = ((src[inliers, 0] >= rw/2).astype(int)
                     + 2*(src[inliers, 1] >= rh/2).astype(int))
        errors = np.linalg.norm(cv2.perspectiveTransform(src[None], matrix)[0]-dst, axis=1)
        error = float(np.median(errors[inliers]))
        self.evidence.update(inliers=count, inlier_ratio=round(ratio, 3),
                             coverage=round(coverage, 3), error_px=round(error, 3))
        if count < 16 or ratio < .45 or coverage < .18 or len(np.unique(quadrants)) < 3 or error > 2.:
            self.evidence['reason'] = 'weak_distributed_support'
            return None
        canonical = np.float32([[0, 0], [rw-1, 0], [rw-1, rh-1], [0, rh-1]])
        corners = cv2.perspectiveTransform(canonical[None], matrix)[0]
        area = cv2.contourArea(corners, oriented=True)
        edges = np.linalg.norm(corners - np.roll(corners, -1, axis=0), axis=1)
        # No reflections, degenerate quads, extrapolation far outside ROI, or
        # repetitive connector matches collapsed into a small local patch.
        if (not np.isfinite(corners).all() or not cv2.isContourConvex(corners)
                or not .005 * width * height <= area <= .6 * width * height
                or edges.min() < 25 or edges.max()/edges.min() > 4
                or np.any(corners < [x1, y1]) or np.any(corners > [x2, y2])):
            self.evidence['reason'] = 'invalid_geometry'
            return None
        self.evidence.update(accepted=True, reason='matched_reference')
        return BoardPoseObservation(
            corners_px=corners.astype(float), confidence=min(.9, .5 + .5*ratio),
            keypoint_confidences=np.full(4, min(.9, .5+.5*ratio)),
            box_xyxy=tuple(np.r_[corners.min(0), corners.max(0)].tolist()),
            source='reference_sift',
        )

    def close(self):
        self.last_observation = None
        if self.roi_locator is not None:
            self.roi_locator.close()
