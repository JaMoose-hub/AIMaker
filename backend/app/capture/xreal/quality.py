"""Real-time spatial and motion-gated temporal denoising at native resolution."""
import cv2
import numpy as np


class RgbDenoiser:
    MODES = ("original", "clean", "strong")

    def __init__(self, mode="clean"):
        if mode not in self.MODES:
            raise ValueError(f"Unknown quality mode: {mode}")
        self.mode = mode
        self.history = None
        self.previous_motion_luma = None
        self.previous_chroma = None
        self.motion_kernel = np.ones((5, 5), np.uint8)
        self.clean_motion_kernel = np.ones((3, 3), np.uint8)
        self.last_motion_fraction = 0.0

    def reset(self):
        self.history = None
        self.previous_motion_luma = None
        self.previous_chroma = None
        self.last_motion_fraction = 0.0

    def process(self, frame):
        if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("Expected uint8 BGR frame")
        if self.mode == "original":
            return frame
        if self.mode == "clean":
            return self._process_clean(frame)
        strong = self.mode == "strong"
        ycc = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
        y, cr, cb = cv2.split(ycc)
        motion_luma = cv2.GaussianBlur(y, (5, 5), 1.0)
        # Bilateral filtering smooths small fluctuations while retaining edges.
        y = cv2.bilateralFilter(y, 5, 16 if strong else 10, 1.7 if strong else 1.3)
        # Color speckles are less visible spatial detail than luminance edges.
        cr = cv2.GaussianBlur(cr, (5, 5), 1.0 if strong else 0.7)
        cb = cv2.GaussianBlur(cb, (5, 5), 1.0 if strong else 0.7)
        current = cv2.merge((y, cr, cb))
        if self.history is None or self.history.shape != current.shape:
            self.history = current.astype(np.float32)
        else:
            difference = cv2.absdiff(motion_luma, self.previous_motion_luma)
            # Expand changed areas so moving boundaries do not inherit old pixels.
            _, moving = cv2.threshold(difference, 7 if strong else 5, 255, cv2.THRESH_BINARY)
            color_difference = cv2.max(cv2.absdiff(cr, self.previous_chroma[0]),
                                      cv2.absdiff(cb, self.previous_chroma[1]))
            _, color_moving = cv2.threshold(color_difference, 12 if strong else 10,
                                           255, cv2.THRESH_BINARY)
            moving = cv2.bitwise_or(moving, color_moving)
            moving = cv2.dilate(moving, self.motion_kernel)
            self.last_motion_fraction = cv2.countNonZero(moving) / moving.size
            cv2.accumulateWeighted(current, self.history, 1.0, mask=moving)
            cv2.accumulateWeighted(current, self.history, 0.28 if strong else 0.42,
                                   mask=cv2.bitwise_not(moving))
        self.previous_motion_luma = motion_luma
        self.previous_chroma = (cr, cb)
        return cv2.cvtColor(cv2.convertScaleAbs(self.history), cv2.COLOR_YCrCb2BGR)

    def _process_clean(self, frame):
        """Light Eye cleanup that retains fine GPIO detail and responds to motion.

        Keep only uint8 YCrCb history: weighted blending plus a current-pixel
        copy avoids two full float32 accumulation passes. STRONG retains its
        heavier filtering for scenes where noise suppression matters more.
        """
        y, cr, cb = cv2.split(cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb))
        motion_luma = cv2.GaussianBlur(y, (3, 3), 0.8)
        y = cv2.bilateralFilter(y, 3, 7, 0.8)
        cr = cv2.GaussianBlur(cr, (3, 3), 0.7)
        cb = cv2.GaussianBlur(cb, (3, 3), 0.7)
        current = cv2.merge((y, cr, cb))
        if self.history is None or self.history.shape != current.shape:
            self.history = current
            self.last_motion_fraction = 0.0
        else:
            difference = cv2.absdiff(motion_luma, self.previous_motion_luma)
            moving = cv2.threshold(difference, 3, 255, cv2.THRESH_BINARY)[1]
            color_difference = cv2.max(cv2.absdiff(cr, self.previous_chroma[0]),
                                      cv2.absdiff(cb, self.previous_chroma[1]))
            color_moving = cv2.threshold(color_difference, 8, 255, cv2.THRESH_BINARY)[1]
            moving = cv2.dilate(cv2.bitwise_or(moving, color_moving), self.clean_motion_kernel)
            self.last_motion_fraction = cv2.countNonZero(moving) / moving.size
            blended = cv2.addWeighted(current, 0.6, self.history, 0.4, 0)
            cv2.copyTo(current, moving, blended)
            self.history = blended
        self.previous_motion_luma = motion_luma
        self.previous_chroma = (cr, cb)
        return cv2.cvtColor(self.history, cv2.COLOR_YCrCb2BGR)
