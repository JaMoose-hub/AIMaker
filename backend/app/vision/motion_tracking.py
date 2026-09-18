"""Bounded image-only tracking for the *display*, not electrical verification.

The slow semantic detectors remain independent. Each object has its own LK
features, forward/backward check, RANSAC homography and detector lease. No
velocity extrapolation is used when image evidence disappears.
"""
from __future__ import annotations

from copy import deepcopy
import time

import cv2
import numpy as np

from app.vision.pin_regions import PinRegions
from app.vision.pi_pin_visibility import PiPinVisibility


def transform(points, matrix: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(
        np.asarray(points, np.float32).reshape(-1, 1, 2), matrix,
    ).reshape(-1, 2)


def warm_motion_runtime():
    """Initialize lazy ORB/numpy kernels before the live display loop.

    Procedural noise is used only to initialize libraries, never as a model
    seed, camera result or hardware evidence. Run on the tracking thread.
    """
    texture = np.random.default_rng(4).integers(0, 256, (160, 192), dtype=np.uint8)
    orb = cv2.ORB_create(nfeatures=1800, edgeThreshold=12, fastThreshold=10)
    _, descriptors = orb.detectAndCompute(texture, np.full_like(texture, 255))
    if descriptors is not None and len(descriptors) >= 2:
        cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(descriptors, descriptors, k=2)
    np.percentile(np.arange(16, dtype=np.float32), 90)


class PlanarFlow:
    def __init__(self, *, pi5_cable_guard: bool = False) -> None:
        self.pi5_cable_guard = pi5_cable_guard
        self.support_cells = 0
        self.support_quadrants = 0
        self.gray = None
        self.points = None
        self.quad = None
        self.support = 0
        self.error_px = 0.0
        self.steps = 0
        self.failure_reason: str | None = None
        self.recovered = False
        self.partial = False
        self.support_ratio = 1.0
        self.anchor = None
        self.anchor_matrix = np.eye(3)
        self._orb = cv2.ORB_create(nfeatures=1800, edgeThreshold=12, fastThreshold=10)
        self._descriptors = None
        self._keypoints = None
        self.next_search_ms = float('-inf')
        self.search_ran = False
        self.search_deferred = False
        self.background_recovery = None

    def seed(self, gray: np.ndarray, quad: np.ndarray) -> bool:
        # Atomic refresh: a texture-poor refresh must not erase a still-valid
        # previous template and unexpectedly lose the object on the next frame.
        quad = np.asarray(quad, np.float32)
        if quad.shape != (4, 2) or not np.isfinite(quad).all() or not cv2.isContourConvex(quad):
            self.failure_reason = 'seed_invalid_geometry'
            return False
        height, width = gray.shape
        if (np.any(quad[:, 0] < 1) or np.any(quad[:, 0] >= width - 1)
                or np.any(quad[:, 1] < 1) or np.any(quad[:, 1] >= height - 1)):
            self.failure_reason = 'seed_outside_frame'
            return False
        lo, hi = self._roi(quad, gray.shape, 8)
        if np.any(hi-lo < 8):
            self.failure_reason = 'seed_too_small'
            return False
        crop = gray[lo[1]:hi[1], lo[0]:hi[0]]
        mask = self._feature_mask(crop.shape, quad-lo)
        points = cv2.goodFeaturesToTrack(
            crop, maxCorners=300 if self.pi5_cable_guard else 100,
            qualityLevel=0.015, minDistance=5, mask=mask,
        )
        if points is not None:
            points = np.float32(points + lo)
            if self.pi5_cable_guard:
                points = points[self._balanced_indices(points, quad)]
        if points is None or len(points) < 16 or not self._spread(points, quad):
            self.failure_reason = 'seed_insufficient_texture'
            return False
        if self.pi5_cable_guard and not self._distributed_support(points, quad):
            self.failure_reason = 'seed_localized_features'
            return False
        self.gray, self.points, self.quad = gray, points, quad
        self.anchor = (gray, points.copy(), quad.copy())
        self.anchor_matrix = np.eye(3)
        self.partial = False
        self.support_ratio = 1.0
        self._descriptors = self._keypoints = None
        self.failure_reason = None
        return True

    @staticmethod
    def _board_coordinates(points, quad):
        canonical = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
        mapping = cv2.getPerspectiveTransform(np.float32(quad), canonical)
        return transform(points, mapping)

    def _feature_mask(self, shape, quad):
        mask = np.zeros(shape, np.uint8)
        cv2.fillConvexPoly(mask, np.rint(quad).astype(np.int32), 255)
        mask = cv2.erode(mask, np.ones((5, 5), np.uint8))
        if not self.pi5_cable_guard:
            return mask
        canonical = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
        mapping = cv2.getPerspectiveTransform(canonical, np.float32(quad))
        inner = transform([[.05, .05], [.95, .05], [.95, .95], [.05, .95]], mapping)
        interior = np.zeros(shape, np.uint8)
        cv2.fillConvexPoly(interior, np.rint(inner).astype(np.int32), 255)
        mask = cv2.bitwise_and(mask, interior)
        # The Pi profile's canonical reference has USB-C at the top-right
        # (GPIO along the bottom). Exclude only that connector neighbourhood,
        # not a screen-fixed rectangle or the GPIO row. This is NOT a cable
        # segmentation mask and must never be used as electrical evidence.
        connector = transform([[.76, 0], [1, 0], [1, .25], [.76, .25]], mapping)
        cv2.fillConvexPoly(mask, np.rint(connector).astype(np.int32), 0)
        return mask

    def _balanced_indices(self, points, quad):
        uv = self._board_coordinates(points, quad)
        cells = np.clip((uv * 3).astype(int), 0, 2)
        ids = cells[:, 1] * 3 + cells[:, 0]
        # GFTT returns strongest first. Cap each cell so one high-contrast
        # connector/cable cannot consume the whole feature budget.
        return np.concatenate([np.flatnonzero(ids == i)[:12] for i in range(9)])

    def _distributed_support(self, points, quad):
        uv = self._board_coordinates(points, quad)
        valid = np.isfinite(uv).all(axis=1) & (uv >= 0).all(axis=1) & (uv <= 1).all(axis=1)
        uv = uv[valid]
        cells = np.clip((uv * 3).astype(int), 0, 2)
        counts = np.bincount(cells[:, 1] * 3 + cells[:, 0], minlength=9)
        quadrants = (uv[:, 0] >= .5).astype(int) + 2 * (uv[:, 1] >= .5).astype(int)
        self.support_cells = int(np.count_nonzero(counts >= 3))
        self.support_quadrants = int(np.count_nonzero(np.bincount(quadrants, minlength=4) >= 3))
        # A genuinely visible half-board can still support a transform. Do
        # not require all four quadrants or regress existing partial tracking.
        span = np.ptp(uv, axis=0) if len(uv) else np.zeros(2)
        broad_half = float(span.min()) >= .30 and float(span.max()) >= .65
        return self.support_cells >= 4 and (self.support_quadrants >= 3 or broad_half)

    @staticmethod
    def _roi(points, shape, margin):
        """Pyramid-aligned crop; all public geometry remains in frame pixels."""
        points = np.asarray(points).reshape(-1, 2)
        lo = np.maximum(0, np.floor((points.min(0) - margin) / 8) * 8).astype(int)
        hi = np.minimum([shape[1], shape[0]], np.ceil((points.max(0) + margin) / 8) * 8).astype(int)
        return lo, hi

    @staticmethod
    def _spread(points: np.ndarray, quad: np.ndarray) -> bool:
        # Features concentrated on a finger, one transducer or a single edge
        # cannot support a trustworthy whole-object transform.
        area = abs(cv2.contourArea(quad.astype(np.float32)))
        hull = cv2.convexHull(points.astype(np.float32))
        return area > 50 and abs(cv2.contourArea(hull)) / area >= 0.20

    def step(self, gray: np.ndarray, *, ts_ms=None, recovering=False, search_budget=None) -> np.ndarray | None:
        self.recovered = False
        self.failure_reason = None
        self.search_ran = self.search_deferred = False
        if self.points is None or self.gray is None or self.gray.shape != gray.shape:
            self.failure_reason = 'no_template'
            return None
        # After support drops, always compare to the last clear keyframe. A
        # hand must never become a new feature source, nor may the reduced
        # feature set masquerade as 100% support on the next frame.
        was_partial = self.partial
        # Pi cable guard measures against a clear keyframe even when all
        # points survive. Integrating tiny connector/noise displacements and
        # reseeding every 15 frames otherwise makes a stationary box drift.
        used_anchor = self.pi5_cable_guard or was_partial or recovering
        matrix = (self._lk_step(gray, self.anchor_matrix, anchored=True, allow_partial=True)
                  if used_anchor else self._lk_step(gray))
        if matrix is not None:
            if self.partial and not was_partial and not used_anchor:
                # Once motion is known, align the clear keyframe again. Fast
                # motion can lose LK points without any actual obstruction.
                refined = self._lk_step(gray, self.anchor_matrix, anchored=True, allow_partial=True)
                if refined is not None:
                    return refined @ matrix
            return matrix
        # Try the existing clear anchor before paying for descriptor recovery.
        # This uses current pixels and all normal LK gates, never a held pose.
        if not used_anchor:
            matrix = self._lk_step(gray, self.anchor_matrix, anchored=True, allow_partial=True)
            if matrix is not None:
                self.recovered = True
                return matrix
        # A descriptor match proposes a wider search only; it does not itself
        # authorize pins. The proposal must pass the same forward/backward LK,
        # spatial support and reprojection checks as the normal path.
        now = time.monotonic() * 1000 if ts_ms is None else ts_ms
        eligible = now >= self.next_search_ms
        permitted = eligible and (search_budget is None or search_budget())
        self.search_deferred = not permitted
        hint = None
        if self.background_recovery is not None:
            hint, submitted = self.background_recovery.propose(self, gray, now, permitted)
            self.search_ran = submitted
            self.search_deferred = hint is None
            if submitted:
                self.next_search_ms = now + 200
        elif permitted:
            self.next_search_ms = now + 200
            self.search_ran = True
            hint = self._wide_search(gray)
        if hint is not None:
            matrix = self._lk_step(gray, hint, anchored=True, allow_partial=True)
            if matrix is not None:
                self.recovered = True
                return matrix
        # The clear-anchor match already failed on this exact image. Running
        # it twice during every covered frame adds cost, not new evidence.
        return None

    def _wide_search(self, gray: np.ndarray) -> np.ndarray | None:
        anchor_gray, _, anchor_quad = self.anchor
        if self._descriptors is None:
            lo, hi = self._roi(anchor_quad, anchor_gray.shape, 32)
            crop = anchor_gray[lo[1]:hi[1], lo[0]:hi[0]]
            if self.pi5_cable_guard:
                mask = self._feature_mask(crop.shape, anchor_quad-lo)
            else:
                mask = np.zeros_like(crop)
                cv2.fillConvexPoly(mask, np.rint(anchor_quad-lo).astype(np.int32), 255)
            keypoints, self._descriptors = self._orb.detectAndCompute(crop, mask)
            self._keypoints = np.float32([np.array(k.pt) + lo for k in keypoints])
        if self._descriptors is None or len(self._descriptors) < 16:
            return None
        diagonal = float(np.linalg.norm(self.quad[2] - self.quad[0]))
        margin = max(120., diagonal)
        lo, hi = self._roi(getattr(self, 'search_quad', self.quad), gray.shape, margin)
        keypoints, descriptors = self._orb.detectAndCompute(gray[lo[1]:hi[1], lo[0]:hi[0]], None)
        if descriptors is None or len(descriptors) < 16:
            return None
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        pairs = matcher.knnMatch(self._descriptors, descriptors, k=2)
        # Mutual matches + ratio prevent many repetitive header/transducer
        # details from collapsing onto one apparently plausible destination.
        reverse = matcher.match(descriptors, self._descriptors)
        reverse_index = {match.queryIdx: match.trainIdx for match in reverse}
        matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
                   if a.distance < 64 and a.distance < .72 * b.distance
                   and reverse_index.get(a.trainIdx) == a.queryIdx]
        if len(matches) < 16:
            return None
        a = np.float32([self._keypoints[m.queryIdx] for m in matches])
        b = np.float32([np.array(keypoints[m.trainIdx].pt) + lo for m in matches])
        if self.pi5_cable_guard:
            # Balance correspondences, preserving source/destination pairing.
            indices = self._balanced_indices(a, anchor_quad)
            a, b = a[indices], b[indices]
            if len(a) < 16:
                return None
        # ORB keypoint coordinates are coarser than subpixel LK. This is only
        # an initialization proposal; the 1.5 px LK/RANSAC gate below remains.
        matrix, inliers = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
        if matrix is None or inliers is None or not np.isfinite(matrix).all():
            return None
        keep = inliers.ravel().astype(bool)
        if keep.sum() < 16 or keep.mean() < .65 or not self._spread(a[keep], anchor_quad):
            return None
        if self.pi5_cable_guard and not self._distributed_support(a[keep], anchor_quad):
            return None
        # Every visible corner must still obey shape, orientation and bounds.
        if not self._valid_transform(matrix @ np.linalg.inv(self.anchor_matrix), gray.shape, wide=True):
            return None
        return matrix

    def _lk_step(self, gray: np.ndarray, hint: np.ndarray | None = None, *,
                 anchored: bool = False, allow_partial: bool = False) -> np.ndarray | None:
        source_gray, p0, source_quad = self.anchor if anchored else (self.gray, self.points, self.quad)
        # Align the old image as well as the points: an initial translation
        # guess alone does not handle the rotated texture inside LK's window.
        reference_points = p0 if hint is None else transform(p0, hint).reshape(-1, 1, 2)
        # Keep enough context for the existing maxLevel=3 LK window. Cropping
        # reduces repeated pyramid construction/warps for small components.
        margin = max(96., float(np.linalg.norm(source_quad[2]-source_quad[0])) * .4 + 24)
        lo, hi = self._roi(reference_points, gray.shape, margin)
        if np.any(hi-lo < 24):
            self.failure_reason = 'outside_frame'
            return None
        current = gray[lo[1]:hi[1], lo[0]:hi[0]]
        reference = source_gray[lo[1]:hi[1], lo[0]:hi[0]]
        if hint is not None:
            to_crop = np.float64([[1,0,-lo[0]], [0,1,-lo[1]], [0,0,1]])
            reference = cv2.warpPerspective(source_gray, to_crop @ hint, tuple((hi-lo).tolist()))
        reference_points = np.float32(reference_points - lo)
        p1, forward, error = cv2.calcOpticalFlowPyrLK(
            reference, current, reference_points, None, winSize=(21, 21), maxLevel=3,
        )
        if p1 is None or forward is None or error is None:
            self.failure_reason = 'lk_missing'
            return None
        back, backward, _ = cv2.calcOpticalFlowPyrLK(
            current, reference, p1, None, winSize=(21, 21), maxLevel=3,
        )
        if back is None or backward is None:
            self.failure_reason = 'lk_missing'
            return None
        valid = ((forward.ravel() == 1) & (backward.ravel() == 1)
                 & (error.ravel() < 25)
                 & (np.linalg.norm(back - reference_points, axis=2).ravel() < 0.8))
        if valid.sum() < 16 or (not allow_partial and valid.mean() < 0.65):
            self.failure_reason = 'lk_support'
            return None
        a, b = p0[valid], np.float32(p1[valid] + lo)
        matrix, inliers = cv2.findHomography(a, b, cv2.RANSAC, 1.5)
        if matrix is None or inliers is None or not np.isfinite(matrix).all():
            self.failure_reason = 'homography_failed'
            return None
        keep = inliers.ravel().astype(bool)
        if (keep.sum() < 16 or keep.mean() < (0.80 if allow_partial else 0.75)
                or not self._spread(a[keep], source_quad)):
            self.failure_reason = 'spatial_support'
            return None
        if self.pi5_cable_guard and not self._distributed_support(a[keep], source_quad):
            # Not eligible for velocity prediction: a localized cable/hand
            # motion must not keep tugging the board after image rejection.
            self.failure_reason = 'localized_motion'
            return None
        increment = matrix @ np.linalg.inv(self.anchor_matrix) if anchored else matrix
        quad = transform(source_quad, matrix)
        if not self._valid_transform(increment, gray.shape, wide=hint is not None):
            return None
        residuals = np.linalg.norm(transform(a[keep], matrix) - b[keep].reshape(-1, 2), axis=1)
        self.error_px = float(np.percentile(residuals, 90))
        self.support = int(keep.sum())
        self.support_ratio = self.support / len(self.anchor[1])
        self.partial = self.support_ratio < (.95 if self.partial else .90)
        self.anchor_matrix = matrix if anchored else matrix @ self.anchor_matrix
        self.gray, self.points, self.quad = gray, b[keep], quad
        self.steps += 1
        anchor_quad = self.anchor[2]
        moved_from_anchor = float(np.max(np.linalg.norm(quad-anchor_quad, axis=1)))
        meaningful_motion = moved_from_anchor > .20 * float(np.linalg.norm(anchor_quad[2]-anchor_quad[0]))
        if (self.steps % 15 == 0 and self.support_ratio >= .97
                and (not self.pi5_cable_guard or meaningful_motion)):
            # Replenish only after a fully validated image step. The semantic
            # lease remains bounded independently of this feature refresh.
            self.seed(gray, quad)
        self.failure_reason = None
        return increment

    def _valid_transform(self, matrix: np.ndarray, shape, *, wide: bool) -> bool:
        quad = transform(self.quad, matrix)
        old_area = cv2.contourArea(self.quad, oriented=True)
        area = cv2.contourArea(quad, oriented=True)
        if (not np.isfinite(quad).all() or not cv2.isContourConvex(quad)
                or old_area * area <= 0 or not 0.70 <= area / old_area <= 1.40):
            self.failure_reason = 'shape_change'
            return False
        diagonal = max(float(np.linalg.norm(self.quad[2] - self.quad[0])), 1)
        # Only the independently matched recovery path may exceed the small
        # inter-frame motion bound. Keep a hard frame-relative search limit.
        height, width = shape
        limit = min(max(120., diagonal), np.hypot(width, height) * .4) if wide else diagonal * .4
        if float(np.max(np.linalg.norm(quad - self.quad, axis=1))) > limit:
            self.failure_reason = 'motion_bound'
            return False
        if np.any(quad[:, 0] < 1) or np.any(quad[:, 0] >= width - 1) or np.any(quad[:, 1] < 1) or np.any(quad[:, 1] >= height - 1):
            self.failure_reason = 'outside_frame'
            return False
        return True


class MotionTrack:
    """Track a semantic pose; model corroboration extends a bounded lease.

    A small history pairs delayed detector observations with their own frame,
    never the current frame. Model jitter cannot tug an established flow track.
    """
    def __init__(self, lease_ms: float = 2000.0, max_gap_ms: float = 350.0,
                 recovery_ms: float = 1500.0, outline_lease_ms: float = 8000.0) -> None:
        self.lease_ms, self.max_gap_ms = lease_ms, max_gap_ms
        self.flow = PlanarFlow()
        self.message: dict | None = None
        self.last_ts = 0.0
        self.last_seen_ts = 0.0
        self.confirmed_ts = 0.0
        self.history: dict[int, np.ndarray] = {}
        self.seen_seed = -1
        self.scale = 1.0
        self.recovery_ms = recovery_ms
        self.outline_lease_ms = max(lease_ms, outline_lease_ms)
        self.recovering = False
        self.failure_reason: str | None = None
        self.ever_locked = False
        self._refresh_count = 0
        self._refresh_last_ts = float('-inf')
        self._refresh_after = float('-inf')
        self.rebase_count = 0
        self.pin_regions = None
        self.confirmation_debug = {}
        self.source_absent_ts = None
        self.pi_visibility = PiPinVisibility()
        self.fresh_recovery_enabled = False

    def reset(self) -> None:
        self.pi_visibility = PiPinVisibility()
        self.flow = PlanarFlow()
        self.message = None
        self.confirmation_debug = {}
        self.source_absent_ts = None
        self.pin_regions = None
        self.history.clear()
        self.recovering = False
        self._refresh_count = 0
        self._refresh_last_ts = float('-inf')
        self._refresh_after = float('-inf')

    def needs_source_image(self, message: dict) -> bool:
        """Normal corroboration is cheap; only initialization/rebase needs pixels."""
        if message.get('tracking') != 'locked':
            return False
        if self.message is None:
            return True
        if self._can_reseed(message):
            return True
        quality = message.get('pose_quality', {})
        confirmed = (message.get('board_id') == 'raspberry-pi-5' and quality.get('image_confirmed') is True)
        if message.get('component_id') in ('hc-sr04', 'mrd-tf240-8p-cs'):
            hand, visible, baseline = (quality.get(k) for k in ('hand_fraction', 'visible_fraction', 'visibility_baseline'))
            confirmed = (quality.get('stability') in ('tracking', 'deadband', 'reacquired')
                         and all(isinstance(v, (int, float)) and np.isfinite(v) for v in (hand, visible, baseline))
                         and 0 <= hand < .08 and baseline > 0 and visible >= baseline*.8)
        return ((self.flow.partial or self.message.get('pose_quality', {}).get('hidden_pin_count', 0) > 0)
                and not self.recovering and confirmed
                and message['ts_ms'] >= self._refresh_after)

    def _can_reseed(self, message):
        identity = message.get('component_id', message.get('board_id'))
        previous_identity = (self.message or {}).get('component_id', (self.message or {}).get('board_id'))
        return (self.fresh_recovery_enabled and self.recovering and self.message is not None
                and identity == previous_identity
                and identity in ('raspberry-pi-5', 'hc-sr04', 'mrd-tf240-8p-cs')
                and message.get('runtime_revision') == self.message.get('runtime_revision')
                and message.get('tracking') == 'locked' and bool(message.get('outline'))
                and bool(message.get('pins'))
                and self.last_ts < message['ts_ms'] <= self.last_seen_ts
                and self.last_seen_ts-message['ts_ms'] <= 250)

    def observe(self, message: dict, source_gray: np.ndarray, scale: float) -> None:
        frame_id = message['frame_id']
        if frame_id <= self.seen_seed:
            return
        self.seen_seed = frame_id
        self.source_absent_ts = (message['ts_ms'] if message.get('tracking') == 'searching' else None)
        if message.get('pose_quality', {}).get('reason') == 'pin_orientation_unverified':
            self.reset()
            self.failure_reason = 'pin_orientation_unverified'
            return
        if message.get('pose_quality', {}).get('stability') in ('corner_box_inconsistent', 'pcb_boundary_unverified'):
            if message.get('board_id') == 'raspberry-pi-5' and self.message is not None:
                # Reject this detector proposal, not independently supported
                # current-frame flow. Do not renew the semantic lease or use
                # any of the rejected coordinates. update() still validates
                # image support, bounds and expiry on every displayed frame.
                self._refresh_count = 0
                self.confirmation_debug = {
                    'source_frame_id': frame_id, 'accepted': False,
                    'evidence': 'rejected_model_proposal',
                    'reason': message['pose_quality']['stability'],
                }
                return
            self.reset()
            self.failure_reason = message['pose_quality']['stability']
            return
        if self.message is not None and not self._can_reseed(message):
            # A slow detector may deliberately hold its displayed geometry
            # during movement. Its fresh raw quad can corroborate the flow,
            # but can never initialize it or become wiring proof.
            observed = message.get('motion_outline')
            evidence = 'raw_motion'
            if (message.get('board_id') == 'raspberry-pi-5'
                    and message.get('tracking') == 'locked'
                    and message.get('pose_quality', {}).get('image_confirmed') is True):
                # The local J8 image anchor has independently corroborated the
                # displayed pose. Comparing noisy raw corners instead defeats
                # that anchor and lets a stationary board's lease expire.
                observed = message.get('outline')
                evidence = 'image_confirmed_outline'
            if observed is None and message['tracking'] == 'locked':
                observed = message.get('outline')
                evidence = 'locked_outline'
            if observed is None:
                self._refresh_count = 0
                return
            quad = np.asarray(observed, np.float32)
            past = self.history.get(frame_id)
            corroborated = False
            self.confirmation_debug = {'source_frame_id': frame_id, 'history_hit': past is not None,
                                       'evidence': evidence}
            if past is not None and quad.shape == (4, 2) and np.isfinite(quad).all():
                tolerance = max(6.0, float(np.linalg.norm(quad[2] - quad[0])) * 0.06)
                self.confirmation_debug.update(error_px=float(np.max(np.linalg.norm(quad-past, axis=1))), tolerance_px=tolerance)
                if float(np.max(np.linalg.norm(quad - past, axis=1))) <= tolerance:
                    self.confirmed_ts = max(self.confirmed_ts, message['ts_ms'])
                    corroborated = True
            self.confirmation_debug['accepted'] = corroborated
            if corroborated and self.needs_source_image(message):
                self._try_rebase(message, source_gray, scale, past)
            else:
                self._refresh_count = 0
            return
        if message['tracking'] != 'locked' or not message.get('outline'):
            return
        quad = np.asarray(message['outline'], np.float32)
        candidate = PlanarFlow(pi5_cable_guard=message.get('board_id') == 'raspberry-pi-5')
        if not candidate.seed(source_gray, quad * scale):
            self.failure_reason = candidate.failure_reason or 'seed_rejected'
            return
        self.flow = candidate
        self.scale = scale
        self.message = deepcopy(message)
        self.pi_visibility = PiPinVisibility()
        self.pin_regions = PinRegions(source_gray, quad, message.get('pins', []), scale,
                                     align_header=message.get('board_id') == 'raspberry-pi-5')
        self.ever_locked = True
        self.message.pop('motion_outline', None)
        self.last_ts = self.confirmed_ts = message['ts_ms']
        self.last_seen_ts = message['ts_ms']
        self.history = {frame_id: quad}
        self.recovering = False
        self.failure_reason = None

    def _try_rebase(self, message, source_gray, scale, past):
        """Replace aged display features only with independent fresh evidence.

        A model lock alone is insufficient: require independent Pi J8/texture
        confirmation, or component material/hand checks in three distinct frames.
        Use the model's paired image, then update forward to the display frame;
        never combine old geometry with today's pixels or learn a partial hand.
        """
        ts = message['ts_ms']
        max_age = 500 if message.get('component_id') else 250
        quad = np.asarray(message.get('outline'), np.float32)
        age = self.last_ts - ts
        tolerance = max(6., float(np.linalg.norm(past[2] - past[0])) * .06)
        if (source_gray is None or scale != self.scale or not 0 <= age <= max_age
                or source_gray.shape != self.flow.gray.shape
                or quad.shape != (4, 2) or not np.isfinite(quad).all()
                or np.max(np.linalg.norm(quad - past, axis=1)) > tolerance):
            self._refresh_count = 0
            return
        if not 0 < ts - self._refresh_last_ts <= max_age:
            self._refresh_count = 0
        self._refresh_count += 1
        self._refresh_last_ts = ts
        if self._refresh_count < 3:
            return
        self._refresh_count = 0
        self._refresh_after = ts + 500  # bound allocations / retries
        candidate = PlanarFlow(pi5_cable_guard=message.get('board_id') == 'raspberry-pi-5')
        if not candidate.seed(source_gray, quad * scale):
            return  # failed candidate never erases the old visible outline
        self.flow = candidate
        self.message = deepcopy(message)
        self.pi_visibility = PiPinVisibility()
        self.pin_regions = PinRegions(source_gray, quad, message.get('pins', []), scale,
                                     align_header=message.get('board_id') == 'raspberry-pi-5')
        self.message.pop('motion_outline', None)
        self.last_ts = self.last_seen_ts = self.confirmed_ts = ts
        self.history = {message['frame_id']: quad.copy()}
        self.rebase_count += 1

    def update(self, gray: np.ndarray, frame_id: int, ts_ms: float, *, search_budget=None) -> dict | None:
        self.flow.search_ran = self.flow.search_deferred = False
        if self.message is None:
            return None
        delta = ts_ms - self.last_ts
        frame_gap = ts_ms - self.last_seen_ts
        self.last_seen_ts = ts_ms
        if (frame_gap < 0 or frame_gap > self.max_gap_ms or delta < 0
                or ts_ms - self.confirmed_ts > self.outline_lease_ms
                or gray.shape != self.flow.gray.shape
                or (self.recovering and delta > self.recovery_ms)):
            self.failure_reason = (
                'clock_reversed' if frame_gap < 0 or delta < 0 else
                'frame_gap' if frame_gap > self.max_gap_ms else
                'semantic_lease_expired' if ts_ms - self.confirmed_ts > self.outline_lease_ms else
                'frame_shape_changed' if gray.shape != self.flow.gray.shape else
                'recovery_timeout'
            )
            self.reset()
            return None
        if frame_id != self.message['frame_id']:
            matrix = self.flow.step(gray, ts_ms=ts_ms, recovering=self.recovering, search_budget=search_budget)
            if matrix is None:
                # Keep a bounded clean keyframe, but emit NO old coordinates.
                # A subsequent sharp frame can recover without waiting for
                # the slower detector to settle for several observations.
                self.failure_reason = self.flow.failure_reason
                self.recovering = True
                if delta > self.recovery_ms:
                    self.reset()
                return None
            # Convert tracking-resolution coordinates back to source pixels.
            scaling = np.diag([self.scale, self.scale, 1.0])
            matrix = np.linalg.inv(scaling) @ matrix @ scaling
            # Accumulating tiny real movements is intentional; freezing each
            # small frame delta would prevent slow handheld movement entirely.
            self.message['outline'] = transform(self.message['outline'], matrix).tolist()
            pins = self.message['pins']
            if pins:
                positions = transform([[p['x'], p['y']] for p in pins], matrix)
                width, height = self.message['video_size']
                for pin, (x, y) in zip(pins, positions):
                    pin.update(x=float(x), y=float(y), v=bool(0 <= x < width and 0 <= y < height))
            # Projected scale is not a new independent calibration measurement.
            self.message.pop('geometry', None)
        self.last_ts = ts_ms
        recovered = self.recovering or self.flow.recovered
        self.recovering = False
        self.failure_reason = None
        lease_valid = ts_ms - self.confirmed_ts <= self.lease_ms
        regions = self.pin_regions.check(gray, self.message['outline'], self.scale) if self.pin_regions else {}
        supported = {key for key, value in regions.items() if value['supported']}
        if (self.message.get('board_id') == 'raspberry-pi-5' and regions and not supported
                and self.source_absent_ts is not None
                and 0 <= ts_ms - self.source_absent_ts <= 750):
            # Background texture can sustain flow after removal. Neither a
            # current semantic detection nor any J8 region supports this pose.
            self.reset()
            self.failure_reason = 'source_absent_no_pin_support'
            return None
        pi_geometry = self.message.get('board_id') == 'raspberry-pi-5' and len(self.message['pins']) == 40
        if pi_geometry:
            supported = self.pi_visibility.supported(self.message['pins'], regions, self.flow.partial)
        dx, dy = self.pin_regions.offset_px if self.pin_regions is not None else (0., 0.)
        height, width = gray.shape
        visible = [p for p in self.message['pins'] if p.get('v') and p['id'] in supported
                   and (not pi_geometry or (0 <= (p['x']+dx)*self.scale < width
                                            and 0 <= (p['y']+dy)*self.scale < height))] if lease_valid else []
        hidden_count = len(self.message['pins']) - len(visible)
        outline_only = not lease_valid or (bool(self.message['pins']) and not visible)
        partial = self.flow.partial or hidden_count > 0
        self.message.update(frame_id=frame_id, ts_ms=ts_ms, tracking='stale' if outline_only else 'locked')
        self.message['pose_quality'] = {
            'path': 'track', 'stability': 'optical_flow_partial' if partial or outline_only else 'optical_flow',
            'inliers': self.flow.support, 'reproj_px': self.flow.error_px / self.scale,
            'detector_age_ms': round(ts_ms - self.confirmed_ts, 1),
            'recovered': recovered,
            'support_ratio': round(self.flow.support_ratio, 3),
            'feature_policy': 'pi5_cable_guard' if self.flow.pi5_cable_guard else 'standard',
            'support_cells': self.flow.support_cells,
            'support_quadrants': self.flow.support_quadrants,
            'outline_only': outline_only,
            'partial': partial,
            'object_supported': True,
            'visible_pin_count': len(visible), 'hidden_pin_count': hidden_count,
            'pin_regions': regions,
            'pin_evidence': 'projected_geometry_not_contact_verification' if pi_geometry else 'local_appearance_not_contact_verification',
            'pin_visibility_policy': 'pi_geometry_debounced_partial_support' if pi_geometry else 'local_appearance',
            'reason': ('awaiting_model_confirmation' if not lease_valid else
                       'partial_support' if self.flow.partial else 'pin_region_changed') if outline_only else
                      ('partial_pin_support' if partial else None),
            'rebase_count': self.rebase_count,
            'confirmation': deepcopy(self.confirmation_debug),
        }
        self.history[frame_id] = np.asarray(self.message['outline'], np.float32)
        while len(self.history) > 90:
            del self.history[next(iter(self.history))]
        output = deepcopy(self.message)
        # Keep every projected coordinate internally so a hidden region can
        # recover on a later image. Pi GPIO are geometric guides, not a claim
        # that each socket has an unchanged appearance or a verified contact.
        output['pins'] = deepcopy(visible)
        if self.pin_regions is not None:
            # Draw at the measured local location, not merely declare support
            # at a neighbouring patch while keeping the old GPIO coordinates.
            dx, dy = self.pin_regions.offset_px
            for pin in output['pins']:
                pin['x'] += float(dx)
                pin['y'] += float(dy)
            output['pose_quality']['pin_alignment_offset_px'] = [float(dx), float(dy)]
        if outline_only:
            output['confidence'] = min(output.get('confidence', 0), .49)
        return output
