"""Review-safe Pose prelabels from already reviewed planar component images.

This is intended for the bootstrap phase before a component-specific YOLO Pose
model exists.  It registers local image features from reviewed examples to an
unlabelled image, projects the reviewed keypoints with a homography, and saves
only high-confidence results as ``auto_pending`` for human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import cv2
import numpy as np

from pose_labeling import (
    PoseAnnotation,
    PoseKeypoint,
    PoseLabelDataset,
    box_from_keypoints,
    pose_geometry_issues,
)


@dataclass(frozen=True)
class RegistrationThresholds:
    ratio_test: float = 0.74
    min_good_matches: int = 8
    min_inliers: int = 8
    min_inlier_ratio: float = 0.35
    max_median_error_px: float = 2.5
    min_board_area_px: float = 2_000.0
    max_board_area_fraction: float = 0.70
    min_blue_overlap: float = 0.35


@dataclass(frozen=True)
class RegistrationMetrics:
    good_matches: int
    inliers: int
    inlier_ratio: float
    median_error_px: float
    board_area_px: float
    blue_overlap: float
    confidence: float


@dataclass
class RegistrationResult:
    annotation: PoseAnnotation
    source_image: Path
    source_split: str
    metrics: RegistrationMetrics


@dataclass
class PrelabelSummary:
    saved: int = 0
    skipped_existing: int = 0
    no_registration: int = 0
    failed: int = 0


@dataclass
class _ImageFeatures:
    image: np.ndarray
    keypoints: list
    descriptors: np.ndarray
    blue_hull: np.ndarray


@dataclass
class _Anchor:
    image_path: Path
    split: str
    annotation: PoseAnnotation
    points_px: np.ndarray
    features: _ImageFeatures


ProgressCallback = Callable[[int, int, Path, str], None]


def _blue_context(image: np.ndarray) -> tuple[tuple[int, int, int, int], np.ndarray] | None:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        hsv,
        np.asarray((90, 45, 25), dtype=np.uint8),
        np.asarray((145, 255, 255), dtype=np.uint8),
    )
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((7, 7), dtype=np.uint8),
        iterations=2,
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [contour for contour in contours if cv2.contourArea(contour) > 250.0]
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour).astype(np.float32)
    x, y, width, height = cv2.boundingRect(contour)
    pad_x = max(25, int(width * 0.25))
    pad_y = max(25, int(height * 0.35))
    roi = (
        max(0, x - pad_x),
        max(0, y - pad_y),
        min(image.shape[1], x + width + pad_x),
        min(image.shape[0], y + height + pad_y),
    )
    return roi, hull


def _feature_detector():
    if hasattr(cv2, "SIFT_create"):
        return (
            cv2.SIFT_create(nfeatures=1500, contrastThreshold=0.02, edgeThreshold=12),
            cv2.NORM_L2,
        )
    return cv2.AKAZE_create(), cv2.NORM_HAMMING


def _extract_features(
    image_path: Path,
    detector,
) -> _ImageFeatures | None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        return None
    context = _blue_context(image)
    if context is None:
        return None
    roi, hull = context
    x0, y0, x1, y1 = roi
    feature_mask = np.zeros(image.shape[:2], dtype=np.uint8)
    feature_mask[y0:y1, x0:x1] = 255
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    keypoints, descriptors = detector.detectAndCompute(gray, feature_mask)
    if descriptors is None or len(keypoints) < 4:
        return None
    return _ImageFeatures(image, keypoints, descriptors, hull)


def _convex_overlap(first: np.ndarray, second: np.ndarray) -> float:
    first = cv2.convexHull(np.asarray(first, dtype=np.float32))
    second = cv2.convexHull(np.asarray(second, dtype=np.float32))
    first_area = abs(float(cv2.contourArea(first)))
    second_area = abs(float(cv2.contourArea(second)))
    if first_area <= 1.0 or second_area <= 1.0:
        return 0.0
    intersection, _ = cv2.intersectConvexConvex(first, second)
    return float(intersection) / min(first_area, second_area)


class ReviewedPoseRegistrar:
    def __init__(
        self,
        dataset: PoseLabelDataset,
        *,
        thresholds: RegistrationThresholds | None = None,
    ) -> None:
        self.dataset = dataset
        self.thresholds = thresholds or RegistrationThresholds()
        self.detector, norm = _feature_detector()
        self.matcher = cv2.BFMatcher(norm)
        self._feature_cache: dict[Path, _ImageFeatures | None] = {}

    def _features(self, image: Path) -> _ImageFeatures | None:
        image = image.resolve()
        if image not in self._feature_cache:
            self._feature_cache[image] = _extract_features(image, self.detector)
        return self._feature_cache[image]

    def reviewed_anchors(self, splits: Iterable[str] = ("train", "val")) -> list[_Anchor]:
        anchors: list[_Anchor] = []
        for split in splits:
            for image in self.dataset.images(split):
                key = self.dataset.key(image, split)
                if self.dataset.review.status(key) != "reviewed":
                    continue
                annotations = self.dataset.load(image, split)
                if len(annotations) != 1 or pose_geometry_issues(annotations[0]):
                    continue
                features = self._features(image)
                if features is None:
                    continue
                height, width = features.image.shape[:2]
                points = np.asarray(
                    [
                        (point.x * width, point.y * height)
                        for point in annotations[0].keypoints
                    ],
                    dtype=np.float32,
                )
                anchors.append(_Anchor(image, split, annotations[0], points, features))
        return anchors

    def _register_anchor(
        self,
        anchor: _Anchor,
        target_path: Path,
        target: _ImageFeatures,
    ) -> RegistrationResult | None:
        threshold = self.thresholds
        pairs = self.matcher.knnMatch(
            anchor.features.descriptors,
            target.descriptors,
            k=2,
        )
        good = [
            first
            for pair in pairs
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < threshold.ratio_test * second.distance
        ]
        if len(good) < threshold.min_good_matches:
            return None
        source_matches = np.asarray(
            [anchor.features.keypoints[item.queryIdx].pt for item in good],
            dtype=np.float32,
        )
        target_matches = np.asarray(
            [target.keypoints[item.trainIdx].pt for item in good],
            dtype=np.float32,
        )
        homography, inlier_mask = cv2.findHomography(
            source_matches,
            target_matches,
            cv2.RANSAC,
            3.0,
        )
        if homography is None or inlier_mask is None:
            return None
        inlier_flags = inlier_mask.ravel().astype(bool)
        inliers = int(np.count_nonzero(inlier_flags))
        inlier_ratio = inliers / max(len(good), 1)
        if inliers < threshold.min_inliers or inlier_ratio < threshold.min_inlier_ratio:
            return None
        predicted_matches = cv2.perspectiveTransform(
            source_matches.reshape(-1, 1, 2), homography
        ).reshape(-1, 2)
        errors = np.linalg.norm(predicted_matches - target_matches, axis=1)[inlier_flags]
        median_error = float(np.median(errors)) if len(errors) else float("inf")
        if median_error > threshold.max_median_error_px:
            return None

        projected = cv2.perspectiveTransform(
            anchor.points_px.reshape(-1, 1, 2), homography
        ).reshape(-1, 2)
        height, width = target.image.shape[:2]
        if not np.all(np.isfinite(projected)):
            return None
        if not np.all(
            (projected[:, 0] >= 0.0)
            & (projected[:, 0] < width)
            & (projected[:, 1] >= 0.0)
            & (projected[:, 1] < height)
        ):
            return None
        board_area = abs(float(cv2.contourArea(projected[:4].astype(np.float32))))
        if not (
            threshold.min_board_area_px <= board_area
            <= width * height * threshold.max_board_area_fraction
        ):
            return None
        projected_blue = cv2.perspectiveTransform(
            anchor.features.blue_hull.reshape(-1, 1, 2), homography
        ).reshape(-1, 2)
        blue_overlap = _convex_overlap(projected_blue, target.blue_hull)
        if blue_overlap < threshold.min_blue_overlap:
            return None

        points = [
            PoseKeypoint(
                float(x / width),
                float(y / height),
                anchor.annotation.keypoints[index].visibility,
            )
            for index, (x, y) in enumerate(projected)
        ]
        confidence = min(
            0.99,
            0.30 * min(inliers / 30.0, 1.0)
            + 0.25 * inlier_ratio
            + 0.20 * max(0.0, 1.0 - median_error / threshold.max_median_error_px)
            + 0.25 * min(blue_overlap, 1.0),
        )
        annotation = PoseAnnotation(
            anchor.annotation.class_id,
            box_from_keypoints(points),
            points,
            confidence=confidence,
            source="registration",
        )
        if pose_geometry_issues(annotation):
            return None
        metrics = RegistrationMetrics(
            good_matches=len(good),
            inliers=inliers,
            inlier_ratio=inlier_ratio,
            median_error_px=median_error,
            board_area_px=board_area,
            blue_overlap=blue_overlap,
            confidence=confidence,
        )
        return RegistrationResult(annotation, anchor.image_path, anchor.split, metrics)

    def register(
        self,
        target_path: Path,
        anchors: Iterable[_Anchor],
    ) -> RegistrationResult | None:
        target = self._features(target_path)
        if target is None:
            return None
        candidates = [
            result
            for anchor in anchors
            if anchor.image_path.resolve() != target_path.resolve()
            for result in [self._register_anchor(anchor, target_path, target)]
            if result is not None
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda item: (
                item.metrics.confidence,
                item.metrics.inliers,
                -item.metrics.median_error_px,
            ),
        )

    def prelabel_unlabelled(
        self,
        *,
        target_splits: Iterable[str] = ("train", "val"),
        source_splits: Iterable[str] = ("train", "val"),
        apply: bool = False,
        cancel_event=None,
        progress: ProgressCallback | None = None,
    ) -> PrelabelSummary:
        anchors = self.reviewed_anchors(source_splits)
        if not anchors:
            raise ValueError("at least one reviewed Pose label is required")
        targets = [
            (split, image)
            for split in target_splits
            for image in self.dataset.images(split)
        ]
        summary = PrelabelSummary()
        for index, (split, image) in enumerate(targets, 1):
            if cancel_event is not None and cancel_event.is_set():
                break
            if self.dataset.label_path(image, split).is_file():
                summary.skipped_existing += 1
                status = "existing"
            else:
                try:
                    result = self.register(image, anchors)
                    if result is None:
                        summary.no_registration += 1
                        status = "no_registration"
                    else:
                        if apply:
                            metrics = result.metrics
                            self.dataset.save(
                                image,
                                split,
                                [result.annotation],
                                status="auto_pending",
                                method="reviewed_homography",
                                registration_source=self.dataset.key(
                                    result.source_image, result.source_split
                                ),
                                registration_confidence=metrics.confidence,
                                registration_inliers=metrics.inliers,
                                registration_inlier_ratio=metrics.inlier_ratio,
                                registration_median_error_px=metrics.median_error_px,
                                registration_blue_overlap=metrics.blue_overlap,
                            )
                        summary.saved += 1
                        status = "auto_pending" if apply else "would_prelabel"
                except Exception:
                    summary.failed += 1
                    status = "failed"
            if progress is not None:
                progress(index, len(targets), image, status)
        return summary

