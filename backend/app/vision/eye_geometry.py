"""Eye geometry checks for coordinates clipped by the image boundary."""
import numpy as np


def clipped_corners(corners, video_size, box_xyxy=None):
    # The shared YOLO decoder clamps off-image keypoints to [0, size-1].
    # Such a quad has lost its actual corner positions; projecting a complete
    # pin lattice through it distorts the visible board. This is not a model
    # confidence threshold and is used only by Eye's direct projection path.
    width, height = video_size
    if box_xyxy is not None:
        x1, y1, x2, y2 = box_xyxy
        # The raw box can extend past the image even when noisy keypoints
        # briefly move inward. Do not flicker between pins and a cut body.
        if x1 <= 2. or y1 <= 2. or x2 >= width - 3. or y2 >= height - 3.:
            return True
    return bool(np.any(corners <= 1.) or np.any(corners >= [width - 2., height - 2.]))
