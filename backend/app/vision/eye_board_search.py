"""One current-frame YOLO forward per Eye board detection."""
from __future__ import annotations

from dataclasses import replace
import numpy as np

from app.vision.scale_recovery import ComponentScaleRecovery


class EyeBoardYoloSearch:
    """Search existing models/regions across frames, retaining no predictions.

    Primary full frame, reference-model full frame, and one reference-model
    tile take turns after misses. A successful strategy processes the next
    fresh frame again. The reference model is a body detector, not a semantic
    GPIO pose model; mark its provenance and periodically retry the primary.
    Inference never stacks forwards or reuses an old observation.
    """

    def __init__(self) -> None:
        self._tiles = ComponentScaleRecovery(vertical_strips=True)
        self.reset()

    def reset(self) -> None:
        self._strategy = 'primary_full'
        self._shape = None
        self._strategies = ()
        self._reference_hits = 0
        self._tiles.reset()

    def advance(self) -> None:
        """Try another strategy next frame, including after invalid geometry."""
        if self._strategies:
            index = self._strategies.index(self._strategy)
            self._strategy = self._strategies[(index + 1) % len(self._strategies)]

    def locate(self, frame: np.ndarray, primary, reference=None, *, allow_tiles=True):
        if frame is None or frame.size == 0:
            return None
        shape = frame.shape[:2]
        if shape != self._shape:
            self.reset()
            self._shape = shape
        strategies = []
        if primary is not None and primary.available:
            strategies.append('primary_full')
        if reference is not None and reference.available:
            strategies.append('reference_full')
            if allow_tiles:
                strategies.append('reference_tile')
        self._strategies = tuple(strategies)
        if not strategies:
            return None
        if self._strategy not in strategies:
            self._strategy = strategies[0]
        strategy = self._strategy
        if self._strategy == 'primary_full':
            observation = primary.locate(frame)
        elif self._strategy == 'reference_full':
            observation = reference.locate(frame)
        else:
            observation = self._tiles.locate(frame, reference)
        if observation is None:
            self._reference_hits = 0
            self.advance()
        elif strategy.startswith('reference_'):
            observation = replace(observation, source='yolo_reference_body_only')
            self._reference_hits += 1
            if self._reference_hits >= 3 and 'primary_full' in strategies:
                self._strategy = 'primary_full'
                self._reference_hits = 0
        else:
            self._reference_hits = 0
        return observation
