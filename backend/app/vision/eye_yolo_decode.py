"""Equivalent early score filtering for the Eye CUDA decoder."""
from __future__ import annotations

import numpy as np


def prefilter_class_scores(output, *, num_classes=1, class_id=0,
                           keypoint_count=4, confidence_threshold=.45, **_):
    """Remove only rows the existing decoder must reject on class score.

    Keep original row order, float32 comparisons, and the complete retained
    rows. The ordinary decoder still owns every box/keypoint check and NMS.
    Malformed layouts go through unchanged to its existing validation.
    """
    if not 0 <= class_id < num_classes or keypoint_count < 4:
        return output
    channels = 4 + int(num_classes) + int(keypoint_count) * 3
    array = np.asarray(output, dtype=np.float32)
    if array.ndim == 3 and array.shape[0] == 1:
        array = array[0]
    if array.ndim != 2:
        return output
    if array.shape[0] == channels:
        channel_rows = array
    elif array.shape[1] == channels:
        channel_rows = array.T
    else:
        return output
    scores = channel_rows[4 + class_id]
    valid = np.isfinite(scores) & (scores >= confidence_threshold)
    return channel_rows[:, valid]
