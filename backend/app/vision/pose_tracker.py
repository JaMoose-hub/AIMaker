"""Feature-based 6-DoF board pose tracker.

Per frame, one of two paths:
- full detection: HSV ROI gate -> ORB features -> descriptor matching
  (knn + Lowe 0.75, one-to-one reference descriptors) -> RANSAC homography
  (outlier culling + sanity checks)
  -> solvePnP(IPPE, both solutions, physical-normal disambiguation)
  -> solvePnPRefineLM;
- tracking: pyramidal LK on the previous inlier points with a
  forward-backward roundtrip check, pose = solvePnPRefineLM on survivors;
  a full re-detect triggers when survivors < 60%, mean reprojection error
  > 2.5 px, or every 10th frame.

State machine: SEARCHING -(3 consecutive good poses)-> LOCKED; LOCKED -(bad
frame)-> STALE (last pose frozen); STALE -(good pose)-> LOCKED; STALE -(15
consecutive bad)-> SEARCHING.

All rvec/tvec are in the right-handed "vision frame" documented in
camera_model.py (board-mm with z negated; z=0 plane unchanged).
The published pose is One-Euro filtered (smoothing.PoseFilter); the raw
pose is kept internally for LK bootstrapping.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.vision.camera_model import (
    CameraModel,
    board_outline_mm,
    load_camera,
    project_board,
    project_wire_exclusion,
    project_points,
)
from app.vision.interface import DetectionResult
from app.vision.smoothing import PoseFilter

__all__ = ["PoseTracker", "TrackerStateMachine", "TrackerParams"]


def _unique_lowe_matches(
        knn_matches: list[list[cv2.DMatch]],
        reference_xy_mm: np.ndarray,
        keypoints: list[cv2.KeyPoint],
        offset: tuple[int, int],
        ratio: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return Lowe-ratio matches with one query per reference descriptor.

    ``BFMatcher.knnMatch(query, train, k=2)`` guarantees that each *query*
    descriptor appears once, but it does not prevent many query descriptors
    from selecting the same reference descriptor.  That is particularly easy
    with repeated header-hole/label texture.  Keeping all of those matches can
    inflate a homography's inlier count without adding independent geometry;
    the resulting PnP pose may then be confidently wrong.  Sort accepted
    candidates by descriptor distance and keep the strongest candidate for each
    reference descriptor.  The output is intentionally not returned in image
    order: RANSAC and PnP only require paired rows, not a particular ordering.
    """
    candidates: list[tuple[float, int, int]] = []
    for pair in knn_matches:
        if len(pair) < 2:
            continue
        best, second = pair
        if float(best.distance) < ratio * float(second.distance):
            candidates.append((float(best.distance), int(best.trainIdx),
                               int(best.queryIdx)))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    used_train: set[int] = set()
    mm: list[np.ndarray] = []
    px: list[tuple[float, float]] = []
    for _distance, train_idx, query_idx in candidates:
        if train_idx in used_train:
            continue
        used_train.add(train_idx)
        mm.append(reference_xy_mm[train_idx])
        point = keypoints[query_idx].pt
        px.append((point[0] + offset[0], point[1] + offset[1]))
    if not mm:
        return np.empty((0, 2), dtype=np.float64), np.empty((0, 2),
                                                              dtype=np.float64)
    return np.asarray(mm, dtype=np.float64), np.asarray(px, dtype=np.float64)


def _inlier_board_area_fraction(
        points_mm: np.ndarray,
        board_wh: tuple[float, float],
) -> float:
    """Return the convex-hull coverage of inliers in board-mm space.

    A large projected board quad is not enough to validate a homography: a
    cluster of repeated header texture can extrapolate to a plausible-looking
    quad while contributing many nominal inliers.  Measuring the inlier hull in
    the reference board coordinates catches that failure without depending on
    camera resolution or pose.
    """
    points = np.asarray(points_mm, dtype=np.float32).reshape(-1, 2)
    board_area = float(board_wh[0]) * float(board_wh[1])
    if board_area <= 0.0 or len(points) < 3:
        return 0.0
    hull = cv2.convexHull(points)
    return float(cv2.contourArea(hull)) / board_area


@dataclass
class TrackerParams:
    # Reference features
    orb_nfeatures: int = 1500          # per reference scale level
    ref_scales: tuple[float, ...] = (1.0, 0.5, 0.25)
    # Matching
    lowe_ratio: float = 0.75
    # Homography sanity
    ransac_px: float = 3.0
    min_inliers: int = 25
    # Reject a high-inlier homography supported only by a small repeated-texture
    # patch (for example one header row).  5% retains the measured 40%-occluded
    # synthetic board (~10% coverage) while rejecting local texture locks.
    min_inlier_board_area_frac: float = 0.05
    min_area_frac: float = 0.02
    max_area_frac: float = 0.90
    # LK tracking
    fb_max_px: float = 1.0
    min_survivor_frac: float = 0.60
    max_track_reproj_px: float = 2.5
    redetect_every: int = 10
    min_track_points: int = 8
    # State machine
    lock_after_good: int = 3
    search_after_bad: int = 15
    # ROI gate (HSV, OpenCV ranges)
    color_roi_enabled: bool = True
    roi_hsv_lo: tuple[int, int, int] = (95, 60, 30)
    roi_hsv_hi: tuple[int, int, int] = (135, 255, 255)
    roi_margin: float = 0.15
    roi_min_frac: float = 0.002
    # Pose acceptance
    max_reproj_px: float = 3.0
    # Smoothing, retuned 2026-07-29 against BOTH acceptance axes at once:
    # live static jitter (real C920, board ~275px wide = 4px/mm, 15s locked,
    # median per-pin sigma) AND the synthetic moving-trajectory test
    # (test_pipeline_accuracy_over_trajectory, median pin error <=5px):
    #   min_cutoff 1.5 / beta 0.3  -> static 3.03px, moving PASS   (old)
    #   min_cutoff 0.15/ beta 0.3  -> static 0.71px, moving 13.8px FAIL
    #   min_cutoff 0.3 / beta 2.0  -> moving 5.98px FAIL
    #   min_cutoff 0.3 / beta 4.0  -> static 0.85px, 1080p moving 5.76px
    #   min_cutoff 0.3 / beta 8.0  -> static cutoff unchanged, but the
    #                              270-degree 1080p regression still reaches
    #                              5.08px median because of motion lag
    #   min_cutoff 0.3 / beta 12.0 -> the same regression is 4.32px median;
    #                              static synthetic noise remains <0.25px
    #   min_cutoff 0.3 / beta 30.0 -> the same regression is 2.74px median /
    #                              5.19px p95; static noise remains <0.25px
    # One-Euro property: min_cutoff bounds the static bandwidth (lower =
    # calmer when still), beta scales cutoff with speed (higher = less lag
    # when moving) - so the pair is tuned jointly, never min_cutoff alone.
    # Residual ~0.85px static is the scale-noise floor at 4px/mm; getting
    # under the 0.5px M4 target needs the camera closer, not more filtering.
    filter_min_cutoff: float = 0.3
    filter_beta: float = 30.0
    # SIFT fallback (rate-limited: it is a rescue path for scale/rotation
    # extremes, not something to burn 40 ms on for every empty-desk frame)
    enable_sift_fallback: bool = True
    sift_retry_every: int = 4
    sift_ref_max_px: int = 900
    sift_frame_max_px: int = 0  # 0 preserves full-resolution legacy search
    # SIFT is only entered after the cheaper ORB path has failed.  Its
    # descriptors lose more valid pairs under severe foreshortening, so allow
    # a slightly wider Lowe ratio here while keeping the same homography,
    # coverage, PnP and reprojection gates.  This is a rescue-path recall
    # setting, not a relaxation of the accepted-pose evidence floor.
    sift_lowe_ratio: float = 0.80


class TrackerStateMachine:
    """searching / locked / stale transitions (unit-testable in isolation)."""

    def __init__(self, lock_after_good: int = 3,
                 search_after_bad: int = 15) -> None:
        self.lock_after_good = int(lock_after_good)
        self.search_after_bad = int(search_after_bad)
        self.state = "searching"
        self._good_streak = 0
        self._bad_streak = 0

    def update(self, good: bool) -> str:
        if self.state == "searching":
            if good:
                self._good_streak += 1
                if self._good_streak >= self.lock_after_good:
                    self.state = "locked"
            else:
                self._good_streak = 0
        elif self.state == "locked":
            if not good:
                self.state = "stale"
                self._bad_streak = 1
        elif self.state == "stale":
            if good:
                self.state = "locked"
                self._bad_streak = 0
            else:
                self._bad_streak += 1
                if self._bad_streak >= self.search_after_bad:
                    self.state = "searching"
                    self._good_streak = 0
        return self.state

    def reset(self) -> None:
        self.state = "searching"
        self._good_streak = 0
        self._bad_streak = 0


@dataclass
class _PoseObs:
    rvec: np.ndarray
    tvec: np.ndarray
    n_inliers: int
    reproj_px: float
    inlier_board_area_frac: float
    # points for the LK tracker: frame px (N,1,2) f32 + board-mm xy (N,2) f64
    track_px: np.ndarray | None = None
    track_mm: np.ndarray | None = None


class PoseTracker:
    def __init__(self, profile, reference_bgr: np.ndarray,
                 mm_to_px: np.ndarray, video_size: tuple[int, int] | None,
                 feature_mask: np.ndarray | None = None,
                 camera: CameraModel | None = None,
                 camera_json: Path | None = None,
                 horizontal_fov_deg: float | None = None,
                 params: TrackerParams | None = None) -> None:
        self.profile = profile
        self.params = params or TrackerParams()
        self._camera = camera
        self._camera_json = camera_json
        self._horizontal_fov_deg = horizontal_fov_deg
        self._video_size = tuple(video_size) if video_size else None
        if self._camera is None and self._video_size is not None:
            self._camera = load_camera(self._video_size, camera_json,
                                       horizontal_fov_deg)

        self._mm_to_px = np.asarray(mm_to_px, dtype=np.float64)
        self._px_to_mm = np.linalg.inv(self._mm_to_px)
        self._board_wh = tuple(profile.board.outline_mm)

        self._orb = cv2.ORB_create(nfeatures=self.params.orb_nfeatures)
        self._sift_ref_gray = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
        self._ref_mm, self._ref_desc = self._extract_reference_features(
            reference_bgr, feature_mask)
        self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

        # Lazy SIFT fallback (computed on first need, rate-limited).
        self._sift = None
        self._sift_ref: tuple[np.ndarray, np.ndarray] | None = None
        self._failed_detects = 0

        self.sm = TrackerStateMachine(self.params.lock_after_good,
                                      self.params.search_after_bad)
        self.pose_filter = PoseFilter(self.params.filter_min_cutoff,
                                      self.params.filter_beta)
        self._raw_pose: tuple[np.ndarray, np.ndarray] | None = None
        self._prev_gray: np.ndarray | None = None
        self._track_px: np.ndarray | None = None
        self._track_mm: np.ndarray | None = None
        self._track_baseline = 0
        self._frames_since_detect = 0
        self._last_locked_result: DetectionResult | None = None
        self._stale_frames = 0
        self._last_confidence = 0.0
        # Telemetry (read by tests / integrator; no behavioural meaning).
        self.last_path = "idle"          # "detect" | "track" | "idle"
        self.last_step_ms = 0.0

    def reset_for_camera(self, *, camera_json: Path | None = None,
                         horizontal_fov_deg: float | None = None) -> None:
        """Reset temporal state for a new source, preserving reference features."""
        self._camera_json = camera_json
        self._horizontal_fov_deg = horizontal_fov_deg
        self._camera = None
        self._video_size = None
        self.sm.reset()
        self.pose_filter.reset()
        self._raw_pose = None
        self._prev_gray = None
        self._track_px = None
        self._track_mm = None
        self._track_baseline = 0
        self._frames_since_detect = 0
        self._last_locked_result = None
        self._stale_frames = 0
        self._last_confidence = 0.0
        self._failed_detects = 0
        self.last_path = "idle"
        self.last_step_ms = 0.0

    # -- reference features ---------------------------------------------------

    def set_reference_features(self, xy_mm: np.ndarray,
                               desc: np.ndarray) -> None:
        """Install precomputed reference features (features.npz cache)."""
        self._ref_mm = np.asarray(xy_mm, dtype=np.float64).reshape(-1, 2)
        self._ref_desc = np.asarray(desc, dtype=np.uint8)

    def _extract_reference_features(
            self, reference_bgr: np.ndarray,
            feature_mask: np.ndarray | None
    ) -> tuple[np.ndarray, np.ndarray]:
        """ORB at several reference scales; keypoints stored as board-mm.

        Multi-scale extraction keeps matching robust when the board appears
        much smaller on screen than in the (high-res) reference image.
        """
        gray = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY)
        all_mm: list[np.ndarray] = []
        all_desc: list[np.ndarray] = []
        for s in self.params.ref_scales:
            if s == 1.0:
                img, mask = gray, feature_mask
            else:
                img = cv2.resize(gray, None, fx=s, fy=s,
                                 interpolation=cv2.INTER_AREA)
                mask = None
                if feature_mask is not None:
                    mask = cv2.resize(feature_mask, (img.shape[1],
                                                     img.shape[0]),
                                      interpolation=cv2.INTER_NEAREST)
            kps, desc = self._orb.detectAndCompute(img, mask)
            if desc is None or len(kps) == 0:
                continue
            px = np.array([kp.pt for kp in kps], dtype=np.float64) / s
            mm = self._apply_h(self._px_to_mm, px)
            all_mm.append(mm)
            all_desc.append(desc)
        if not all_mm:
            raise ValueError("no ORB features found on the reference image")
        return np.vstack(all_mm), np.vstack(all_desc)

    @staticmethod
    def _apply_h(h: np.ndarray, pts: np.ndarray) -> np.ndarray:
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        ones = np.ones((pts.shape[0], 1))
        q = (h @ np.hstack([pts, ones]).T).T
        return q[:, :2] / q[:, 2:3]

    # -- per-frame entry point --------------------------------------------------

    def process(self, frame_bgr: np.ndarray, frame_id: int,
                ts_ms: float) -> DetectionResult:
        t0 = time.perf_counter()
        if self._camera is None or self._video_size != (
                frame_bgr.shape[1], frame_bgr.shape[0]):
            self._video_size = (frame_bgr.shape[1], frame_bgr.shape[0])
            self._camera = load_camera(
                self._video_size, self._camera_json, self._horizontal_fov_deg
            )

        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        prev_state = self.sm.state

        obs = self._step(gray, frame_bgr)
        if obs is not None:
            # A low reprojection error on a small feature cluster does not
            # validate the extrapolated board. Check the PnP output too, not
            # only the pre-PnP homography used by full detection.
            _, outline = project_board(self.profile, self._camera, obs.rvec,
                                       obs.tvec, pin_confidence=0.0)
            if outline is None or not self._polygon_ok(np.asarray(outline)):
                obs = None
                self.pose_filter.reset()
        good = obs is not None
        state = self.sm.update(good)

        if good and state == "locked":
            if prev_state == "searching":
                # Re-acquisition: restart smoothing from the fresh pose.
                self.pose_filter.reset()
            result = self._emit_locked(obs, frame_id, ts_ms)
            self._stale_frames = 0
        elif state == "stale" and self._last_locked_result is not None:
            self._stale_frames += 1
            result = self._emit_stale(frame_id, ts_ms)
        else:  # searching (or stale with nothing to freeze — degenerate)
            result = self._emit_searching(frame_id, ts_ms)

        # Bookkeeping for the LK tracker.
        self._prev_gray = gray
        if good and obs.track_px is not None and len(obs.track_px) >= \
                self.params.min_track_points:
            self._track_px = obs.track_px
            self._track_mm = obs.track_mm
        elif not good:
            self._track_px = None
            self._track_mm = None
        self.last_step_ms = (time.perf_counter() - t0) * 1000.0
        return result

    # -- step dispatch ----------------------------------------------------------

    def _step(self, gray: np.ndarray, frame_bgr: np.ndarray) -> _PoseObs | None:
        can_track = (self.sm.state == "locked"
                     and self._prev_gray is not None
                     and self._track_px is not None
                     and self._raw_pose is not None
                     and self._frames_since_detect < self.params.redetect_every)
        if can_track:
            obs = self._track_step(gray)
            if obs is not None:
                self.last_path = "track"
                self._frames_since_detect += 1
                self._raw_pose = (obs.rvec, obs.tvec)
                return obs
        # Full detection (searching / stale / periodic / track failure).
        self.last_path = "detect"
        obs = self._detect_step(gray, frame_bgr)
        if obs is not None:
            self._frames_since_detect = 0
            self._track_baseline = len(obs.track_px)
            self._raw_pose = (obs.rvec, obs.tvec)
        return obs

    # -- full detection -----------------------------------------------------------

    def _roi_gate(self, frame_bgr: np.ndarray
                  ) -> tuple[int, int, int, int] | None:
        """Dark-blue PCB blob bbox (+margin) at quarter resolution, or None."""
        p = self.params
        if not p.color_roi_enabled:
            return None
        small = cv2.resize(frame_bgr, None, fx=0.25, fy=0.25,
                           interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(p.roi_hsv_lo, dtype=np.uint8),
                           np.array(p.roi_hsv_hi, dtype=np.uint8))
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        biggest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(biggest) < p.roi_min_frac * mask.size:
            return None
        x, y, w, h = cv2.boundingRect(biggest)
        mx, my = int(w * p.roi_margin), int(h * p.roi_margin)
        H, W = frame_bgr.shape[:2]
        x0 = max(0, (x - mx) * 4)
        y0 = max(0, (y - my) * 4)
        x1 = min(W, (x + w + mx) * 4)
        y1 = min(H, (y + h + my) * 4)
        if x1 - x0 < 32 or y1 - y0 < 32:
            return None
        return x0, y0, x1, y1

    def _match_features(self, gray_roi: np.ndarray, offset: tuple[int, int]
                        ) -> tuple[np.ndarray, np.ndarray] | None:
        """ORB + knn/Lowe matching. Returns (mm (N,2), frame px (N,2))."""
        kps, desc = self._orb.detectAndCompute(gray_roi, None)
        if desc is None or len(kps) < self.params.min_inliers:
            return None
        knn = self._matcher.knnMatch(desc, self._ref_desc, k=2)
        mm, px = _unique_lowe_matches(
            knn, self._ref_mm, kps, offset, self.params.lowe_ratio,
        )
        if len(mm) < self.params.min_inliers:
            return None
        return mm, px

    def _match_features_sift(self, gray_roi: np.ndarray,
                             offset: tuple[int, int]
                             ) -> tuple[np.ndarray, np.ndarray] | None:
        """Lazy SIFT fallback when ORB matching is too weak."""
        if not self.params.enable_sift_fallback or not hasattr(
                cv2, "SIFT_create"):
            return None
        if self._sift is None:
            self._sift = cv2.SIFT_create(nfeatures=2000)
        if self._sift_ref is None:
            # Compute once, on a size-capped reference (SIFT is scale
            # invariant; this keeps the one-time cost within frame budget).
            gray_ref = self._sift_ref_gray
            s = min(1.0, self.params.sift_ref_max_px
                    / max(gray_ref.shape[1], 1))
            if s < 0.999:
                gray_ref = cv2.resize(gray_ref, None, fx=s, fy=s,
                                      interpolation=cv2.INTER_AREA)
            kps, desc = self._sift.detectAndCompute(gray_ref, None)
            if desc is None or len(kps) < 10:
                return None
            px = np.array([kp.pt for kp in kps], dtype=np.float64) / s
            self._sift_ref = (self._apply_h(self._px_to_mm, px), desc)
        ref_mm, ref_desc = self._sift_ref
        cap = self.params.sift_frame_max_px
        search_scale = min(1., cap/max(gray_roi.shape)) if cap > 0 else 1.
        search = (cv2.resize(gray_roi, None, fx=search_scale, fy=search_scale,
                            interpolation=cv2.INTER_AREA) if search_scale < 1. else gray_roi)
        kps, desc = self._sift.detectAndCompute(search, None)
        if desc is None or len(kps) < self.params.min_inliers:
            return None
        knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc, ref_desc, k=2)
        mm, px = _unique_lowe_matches(
            knn, ref_mm, kps, (0, 0), self.params.sift_lowe_ratio,
        )
        if len(mm) < self.params.min_inliers:
            return None
        # Geometry gates and LK seeds stay in original source-image pixels.
        return mm, px/search_scale + np.asarray(offset)

    def _homography_cull(self, mm: np.ndarray, px: np.ndarray
                         ) -> tuple[np.ndarray, np.ndarray] | None:
        """RANSAC homography board-mm -> frame px with sanity checks."""
        p = self.params
        H, inl = cv2.findHomography(mm.reshape(-1, 1, 2),
                                    px.reshape(-1, 1, 2), cv2.RANSAC,
                                    p.ransac_px)
        if H is None or inl is None:
            return None
        inl = inl.ravel().astype(bool)
        if int(inl.sum()) < p.min_inliers:
            return None
        if (_inlier_board_area_fraction(mm[inl], self._board_wh)
                < p.min_inlier_board_area_frac):
            return None
        if float(np.linalg.det(H[0:2, 0:2])) <= 0.0:
            return None  # mirrored match
        corners = self._apply_h(H, board_outline_mm(self._board_wh)[:, :2])
        if not self._polygon_ok(corners):
            return None
        return mm[inl], px[inl]

    def _polygon_ok(self, quad: np.ndarray) -> bool:
        p = self.params
        quad = np.asarray(quad, dtype=np.float64)
        w, h = self._video_size
        if (quad.shape != (4, 2) or not np.isfinite(quad).all()
                or np.any(quad[:, 0] < 1) or np.any(quad[:, 0] >= w - 1)
                or np.any(quad[:, 1] < 1) or np.any(quad[:, 1] >= h - 1)):
            return False
        v = np.roll(quad, -1, axis=0) - quad
        w2 = np.roll(v, -1, axis=0)
        cross = v[:, 0] * w2[:, 1] - v[:, 1] * w2[:, 0]  # 2D cross (z comp.)
        if not (np.all(cross > 0) or np.all(cross < 0)):
            return False  # not convex
        area = 0.5 * abs(float(np.dot(quad[:, 0], np.roll(quad[:, 1], -1))
                               - np.dot(quad[:, 1], np.roll(quad[:, 0], -1))))
        w, h = self._video_size
        frac = area / float(w * h)
        return p.min_area_frac <= frac <= p.max_area_frac

    def _solve_pose(self, mm: np.ndarray, px: np.ndarray,
                    init: tuple[np.ndarray, np.ndarray] | None = None
                    ) -> tuple[np.ndarray, np.ndarray] | None:
        """IPPE PnP on coplanar (z=0) points, physical-solution selection.

        For planar targets IPPE returns two poses that reproject the plane
        identically; only one has the board's top facing the camera.  In the
        vision frame the outward board normal is (0,0,-1); the physical pose
        satisfies (R @ [0,0,-1])[2] < 0.  Picking the wrong one would flip
        the parallax of the z=8.5 mm pin openings.
        """
        obj = np.zeros((len(mm), 3), dtype=np.float64)
        obj[:, :2] = mm
        img = np.ascontiguousarray(px.reshape(-1, 1, 2))
        try:
            n_sol, rvecs, tvecs, errs = cv2.solvePnPGeneric(
                obj, img, self._camera.K, self._camera.dist,
                flags=cv2.SOLVEPNP_IPPE)
        except cv2.error:
            n_sol = 0
        best = None
        if n_sol:
            for rv, tv in zip(rvecs, tvecs):
                R, _ = cv2.Rodrigues(rv)
                if float(tv.reshape(3)[2]) <= 0.0:
                    continue
                if float((R @ np.array([0.0, 0.0, -1.0]))[2]) >= 0.0:
                    continue  # board top facing away — mirror solution
                best = (rv.reshape(3, 1), tv.reshape(3, 1))
                break
        if best is None and init is not None:
            best = (np.asarray(init[0], np.float64).reshape(3, 1).copy(),
                    np.asarray(init[1], np.float64).reshape(3, 1).copy())
        if best is None:
            return None
        try:
            rvec, tvec = cv2.solvePnPRefineLM(obj, img, self._camera.K,
                                              self._camera.dist, best[0],
                                              best[1])
        except cv2.error:
            rvec, tvec = best
        rvec = np.asarray(rvec, np.float64).reshape(3)
        tvec = np.asarray(tvec, np.float64).reshape(3)
        if tvec[2] <= 0.0:
            return None
        R, _ = cv2.Rodrigues(rvec)
        if float((R @ np.array([0.0, 0.0, -1.0]))[2]) >= 0.0:
            return None
        return rvec, tvec

    def _reproj_error(self, mm: np.ndarray, px: np.ndarray,
                      rvec: np.ndarray, tvec: np.ndarray) -> float:
        obj = np.zeros((len(mm), 3), dtype=np.float64)
        obj[:, :2] = mm
        proj = project_points(obj, self._camera, rvec, tvec)
        return float(np.mean(np.linalg.norm(proj - px, axis=1)))

    def _detect_step(self, gray: np.ndarray,
                     frame_bgr: np.ndarray) -> _PoseObs | None:
        roi = self._roi_gate(frame_bgr)
        if roi is None:
            x0, y0 = 0, 0
            gray_roi = gray
        else:
            x0, y0, x1, y1 = roi
            gray_roi = gray[y0:y1, x0:x1]

        matched = self._match_features(gray_roi, (x0, y0))
        culled = self._homography_cull(*matched) if matched else None
        if culled is None and roi is not None and gray_roi is not gray:
            # Retry on the full frame (the color gate may have missed).
            matched = self._match_features(gray, (0, 0))
            culled = self._homography_cull(*matched) if matched else None
        if culled is None and self._failed_detects % max(
                self.params.sift_retry_every, 1) == 0:
            # SIFT fallback (descriptors computed lazily on first need,
            # attempted only every Nth failed detect to bound latency).
            matched = self._match_features_sift(gray_roi, (x0, y0))
            culled = self._homography_cull(*matched) if matched else None
        if culled is None:
            self._failed_detects += 1
            return None
        self._failed_detects = 0
        mm_in, px_in = culled

        pose = self._solve_pose(mm_in, px_in, init=self._raw_pose)
        if pose is None:
            return None
        rvec, tvec = pose
        err = self._reproj_error(mm_in, px_in, rvec, tvec)
        if err > self.params.max_reproj_px:
            return None
        return _PoseObs(
            rvec=rvec, tvec=tvec, n_inliers=len(mm_in), reproj_px=err,
            inlier_board_area_frac=_inlier_board_area_fraction(
                mm_in, self._board_wh),
            track_px=np.ascontiguousarray(
                px_in.reshape(-1, 1, 2).astype(np.float32)),
            track_mm=mm_in.copy())

    # -- LK tracking ------------------------------------------------------------

    def _track_step(self, gray: np.ndarray) -> _PoseObs | None:
        p = self.params
        prev_pts = self._track_px
        fwd, st_f, _ = cv2.calcOpticalFlowPyrLK(self._prev_gray, gray,
                                                prev_pts, None)
        if fwd is None:
            return None
        bwd, st_b, _ = cv2.calcOpticalFlowPyrLK(gray, self._prev_gray, fwd,
                                                None)
        if bwd is None:
            return None
        rt = np.linalg.norm((bwd - prev_pts).reshape(-1, 2), axis=1)
        ok = (st_f.ravel() == 1) & (st_b.ravel() == 1) & (rt <= p.fb_max_px)
        w, h = self._video_size
        xy = fwd.reshape(-1, 2)
        ok &= (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & \
              (xy[:, 1] < h)
        n_ok = int(ok.sum())
        if (n_ok < p.min_track_points
                or n_ok < p.min_survivor_frac * max(self._track_baseline, 1)):
            return None
        mm = self._track_mm[ok]
        px = xy[ok]
        pose = self._solve_pose_refine_only(mm, px)
        if pose is None:
            return None
        rvec, tvec = pose
        err = self._reproj_error(mm, px, rvec, tvec)
        if err > p.max_track_reproj_px:
            return None
        return _PoseObs(
            rvec=rvec, tvec=tvec, n_inliers=n_ok, reproj_px=err,
            inlier_board_area_frac=_inlier_board_area_fraction(
                mm, self._board_wh),
            track_px=np.ascontiguousarray(
                px.reshape(-1, 1, 2).astype(np.float32)),
            track_mm=mm.copy())

    def _solve_pose_refine_only(self, mm: np.ndarray, px: np.ndarray
                                ) -> tuple[np.ndarray, np.ndarray] | None:
        obj = np.zeros((len(mm), 3), dtype=np.float64)
        obj[:, :2] = mm
        img = np.ascontiguousarray(px.reshape(-1, 1, 2))
        rv0 = np.asarray(self._raw_pose[0], np.float64).reshape(3, 1).copy()
        tv0 = np.asarray(self._raw_pose[1], np.float64).reshape(3, 1).copy()
        try:
            rvec, tvec = cv2.solvePnPRefineLM(obj, img, self._camera.K,
                                              self._camera.dist, rv0, tv0)
        except cv2.error:
            return None
        rvec = np.asarray(rvec, np.float64).reshape(3)
        tvec = np.asarray(tvec, np.float64).reshape(3)
        if tvec[2] <= 0.0:
            return None
        return rvec, tvec

    # -- result emission ----------------------------------------------------------

    def _confidence(self, obs: _PoseObs) -> float:
        inlier_score = min(1.0, obs.n_inliers / 60.0)
        reproj_score = max(0.0, 1.0 - obs.reproj_px / 4.0)
        return float(np.clip(0.4 + 0.6 * inlier_score * reproj_score,
                             0.0, 1.0))

    def _emit_locked(self, obs: _PoseObs, frame_id: int,
                     ts_ms: float) -> DetectionResult:
        rvec_f, tvec_f = self.pose_filter.apply(obs.rvec, obs.tvec,
                                                ts_ms / 1000.0)
        conf = self._confidence(obs)
        pins, outline = project_board(self.profile, self._camera, rvec_f,
                                      tvec_f, pin_confidence=conf)
        if not self._polygon_ok(np.asarray(outline)):
            # Interpolating rotations/translations across reacquisition can
            # project outside the image even when the raw pose is valid.
            self.pose_filter.reset()
            rvec_f, tvec_f = self.pose_filter.apply(obs.rvec, obs.tvec, ts_ms / 1000.0)
            pins, outline = project_board(self.profile, self._camera, rvec_f,
                                          tvec_f, pin_confidence=conf)
        wire_exclusion = project_wire_exclusion(
            self.profile, self._camera, rvec_f, tvec_f)
        result = DetectionResult(
            board_id=self.profile.board.id, frame_id=int(frame_id),
            ts_ms=float(ts_ms), tracking="locked", confidence=conf,
            pins=pins, outline_px=outline,
            wire_exclusion_px=wire_exclusion,
            rvec=[float(v) for v in rvec_f],
            tvec=[float(v) for v in tvec_f],
            pose_path=self.last_path,
            pose_inliers=int(obs.n_inliers),
            pose_reproj_px=float(obs.reproj_px),
            pose_inlier_board_area_frac=float(obs.inlier_board_area_frac))
        self._last_locked_result = result
        self._last_confidence = conf
        return result

    def _emit_stale(self, frame_id: int, ts_ms: float) -> DetectionResult:
        last = self._last_locked_result
        conf = max(0.2, self._last_confidence * (0.95 ** self._stale_frames))
        return DetectionResult(
            board_id=self.profile.board.id, frame_id=int(frame_id),
            ts_ms=float(ts_ms), tracking="stale", confidence=float(conf),
            pins=list(last.pins), outline_px=list(last.outline_px)
            if last.outline_px is not None else None,
            wire_exclusion_px=list(last.wire_exclusion_px)
            if last.wire_exclusion_px is not None else None,
            rvec=list(last.rvec) if last.rvec else None,
            tvec=list(last.tvec) if last.tvec else None,
            pose_path="stale",
            pose_inliers=last.pose_inliers,
            pose_reproj_px=last.pose_reproj_px,
            pose_inlier_board_area_frac=last.pose_inlier_board_area_frac)

    def _emit_searching(self, frame_id: int, ts_ms: float) -> DetectionResult:
        return DetectionResult(
            board_id=self.profile.board.id, frame_id=int(frame_id),
            ts_ms=float(ts_ms), tracking="searching", confidence=0.0,
            pins=[], outline_px=None, rvec=None, tvec=None)
