"""Bounded source-pixel search using the already loaded component pose model."""
from dataclasses import replace

import numpy as np

from app.vision.yolo_pose import BoardPoseLocator, BoardPoseObservation


class ComponentScaleRecovery:
    """Try one half-frame tile after a miss; keep a successful tile until it misses.

    The caller still runs full-frame inference first. No cached observation is
    returned: every successful result belongs to the supplied frame. Pin
    refinement and orientation checks still run after this model observation.
    """

    def __init__(self, *, vertical_strips: bool = False) -> None:
        self._vertical_strips = vertical_strips
        self.reset()

    def reset(self) -> None:
        self._cursor = 0
        self._shape = None

    def locate(self, frame: np.ndarray, locator: BoardPoseLocator, *, accept=None) -> BoardPoseObservation | None:
        height, width = frame.shape[:2]
        if height < 2 or width < 2:
            return None
        if self._shape != (height, width):
            self.reset()
            self._shape = (height, width)
        tile_width = (width + 1) // 2
        tile_height = height if self._vertical_strips else (height + 1) // 2
        offsets = (((width - tile_width) // 2, 0), (0, 0), (width - tile_width, 0)) if self._vertical_strips else (
            (0, 0), (width - tile_width, 0), (0, height - tile_height),
            (width - tile_width, height - tile_height))
        x, y = offsets[self._cursor]
        observation = locator.locate(frame[y:y + tile_height, x:x + tile_width])
        if observation is not None and self._vertical_strips:
            bx1, _, bx2, _ = observation.box_xyxy
            # A clipped TFT half produced a confident false rectangle beside
            # its actual body. Never accept a box crossing an artificial edge.
            if (x > 0 and bx1 < 0) or (x + tile_width < width and bx2 > tile_width):
                observation = None
        if observation is None:
            self._cursor = (self._cursor + 1) % len(offsets)
            return None
        offset = np.array([x, y], dtype=float)
        recovered = replace(
            observation,
            corners_px=observation.corners_px + offset,
            box_xyxy=tuple((np.asarray(observation.box_xyxy) + np.tile(offset, 2)).tolist()),
            landmarks_px=(None if observation.landmarks_px is None
                          else observation.landmarks_px + offset),
            source='yolo_tile',
        )
        if accept is not None and not accept(recovered):
            self._cursor = (self._cursor + 1) % len(offsets)
            return None
        return recovered
