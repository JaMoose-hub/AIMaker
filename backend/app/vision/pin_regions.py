"""Local appearance support for display pins; NOT contact/occlusion recognition.

One clean reference per semantic seed, independent of flow feature refresh.
Batch remapping costs O(pin_count * 17 * 17), not full-frame image warping.
"""
import cv2
import numpy as np


class PinRegions:
    def __init__(self, gray, quad, pins, scale, *, align_header=False):
        self.gray = gray
        self.quad = np.asarray(quad, np.float32) * scale
        self.ids = [p['id'] for p in pins]
        centers = np.asarray([[p['x'], p['y']] for p in pins], np.float32).reshape(-1, 2) * scale
        yy, xx = np.mgrid[-8:9, -8:9]
        self.grid = centers[:, None, None, :] + np.stack([xx, yy], -1).astype(np.float32)
        self.reference, self.in_bounds = self._sample(gray, self.grid)
        self.align_header = align_header and len(pins) == 40
        self.offset_px = np.zeros(2)

    def _score(self, current, bounds):
        a = self.reference - self.reference.mean(axis=1, keepdims=True)
        b = current - current.mean(axis=1, keepdims=True)
        sa, sb = a.std(axis=1), b.std(axis=1)
        corr = (a*b).mean(axis=1) / np.maximum(sa*sb, 1e-6)
        difference = np.abs(a-b).mean(axis=1)
        exposure = np.abs(current.mean(axis=1)-self.reference.mean(axis=1))
        good = (self.in_bounds & bounds & (sa >= 6) & (sb >= 4) &
                (sb >= sa*.65) & (corr >= .82) &
                (difference <= np.maximum(15, sa*.55)) & (exposure <= 45))
        return good, corr, sa, sb

    @staticmethod
    def _sample(gray, grid):
        if not len(grid):
            return np.empty((0, 289), np.float32), np.empty(0, bool)
        h, w = gray.shape
        bounds = ((grid[..., 0] >= 0) & (grid[..., 0] < w-1) &
                  (grid[..., 1] >= 0) & (grid[..., 1] < h-1)).all(axis=(1, 2))
        maps = grid.reshape(-1, 17, 2)
        pixels = cv2.remap(gray, maps[..., 0], maps[..., 1], cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_CONSTANT).reshape(len(grid), -1).astype(np.float32)
        return pixels, bounds

    def check(self, gray, quad, scale):
        self.offset_px = np.zeros(2)
        if not self.ids:
            return {}
        matrix = cv2.getPerspectiveTransform(self.quad, np.asarray(quad, np.float32) * scale)
        grid = cv2.perspectiveTransform(self.grid.reshape(-1, 1, 2), matrix).reshape(self.grid.shape)
        current, bounds = self._sample(gray, grid)
        good, corr, sa, sb = self._score(current, bounds)
        if self.align_header and good.sum() < len(self.ids)*.9:
            centers = grid[:, 8, 8]
            distances = np.linalg.norm(centers[:, None]-centers[None, :], axis=2)
            np.fill_diagonal(distances, np.inf)
            # A common translation, strictly below a quarter of the nearest
            # pin spacing, cannot search across to an adjacent contact.
            radius = min(2., float(distances.min())*.22)
            original_count = int(good.sum())
            best_count = original_count
            _, _, axes = np.linalg.svd(centers-centers.mean(0), full_matrices=False)
            along = centers @ axes[0]
            if np.isfinite(radius) and radius >= .25:
                for dx in np.linspace(-radius, radius, 5):
                    for dy in np.linspace(-radius, radius, 5):
                        if np.hypot(dx, dy) > radius or (dx == 0 and dy == 0):
                            continue
                        pixels, inside = self._sample(gray, grid + np.float32([dx, dy]))
                        candidate = self._score(pixels, inside)
                        supported = candidate[0]
                        count = int(supported.sum())
                        # Require most of the header, across its full length;
                        # a single visible patch cannot authorize hidden pins.
                        span = np.ptp(along[supported]) if count else 0.
                        if (count < 24 or count < original_count+6 or count <= best_count
                                or span < .7*np.ptp(along)):
                            continue
                        good, corr, sa, sb = candidate
                        bounds = inside
                        self.offset_px = np.array([dx, dy])/scale
                        best_count = count
        return {key: {'supported': bool(good[i]), 'correlation': round(float(corr[i]), 3),
                      'reason': 'appearance_supported' if good[i] else
                      ('outside_frame' if not (self.in_bounds[i] and bounds[i]) else
                       'low_texture' if sa[i] < 6 or sb[i] < 4 else 'appearance_changed')}
                for i, key in enumerate(self.ids)}
