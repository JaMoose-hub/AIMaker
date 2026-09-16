"""Zero-training guided endpoint verification from before/after ROI patches.

This deliberately answers a narrow MVP question: after a guidance step starts,
did stable new visual evidence appear at *both* the expected UNO pin and the
expected component terminal?  It does not claim electrical continuity and it
does not search every pin.  The result is published as supplemental
``visual_check`` evidence; Serial remains the final authority.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class _Baseline:
    step_id: str
    board_center: tuple[float, float]
    component_center: tuple[float, float]
    board_patch: np.ndarray
    component_patch: np.ndarray


def _position(item, *, board: bool) -> tuple[float, float] | None:
    visible = getattr(item, "visible" if board else "visible", True)
    if not visible:
        return None
    return float(item.x), float(item.y)


def _extract_patch(frame_bgr: np.ndarray, center: tuple[float, float], radius: int) -> np.ndarray | None:
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    height, width = frame_bgr.shape[:2]
    x, y = int(round(center[0])), int(round(center[1]))
    if x < 0 or x >= width or y < 0 or y >= height:
        return None
    padded = cv2.copyMakeBorder(
        frame_bgr, radius, radius, radius, radius, cv2.BORDER_REFLECT_101
    )
    x += radius
    y += radius
    return padded[y - radius:y + radius + 1, x - radius:x + radius + 1].copy()


def _skin_fraction(patch_bgr: np.ndarray) -> float:
    ycrcb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(
        ycrcb,
        np.array([0, 133, 77], dtype=np.uint8),
        np.array([255, 180, 135], dtype=np.uint8),
    )
    return float(cv2.countNonZero(skin)) / max(float(skin.size), 1.0)


def _patch_quality_ok(patch_bgr: np.ndarray) -> bool:
    gray = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    return 18.0 <= mean <= 242.0 and float(np.std(gray)) >= 5.0


def _aligned_overlap(
    reference_bgr: np.ndarray,
    current_bgr: np.ndarray,
    max_shift_px: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Align tiny endpoint patches against detector jitter before differencing.

    YOLO/Profile points can move a few pixels on an otherwise static 25px
    crop. A bounded integer search is deterministic and cheap (at most 49
    comparisons), while median brightness removal and clipped error keep a
    newly appeared connector from becoming the alignment target itself.
    """
    height, width = reference_bgr.shape[:2]
    if current_bgr.shape[:2] != (height, width) or height < 3 or width < 3:
        return reference_bgr, current_bgr
    ref_gray = cv2.GaussianBlur(
        cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0
    )
    cur_gray = cv2.GaussianBlur(
        cv2.cvtColor(current_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0
    )
    best: tuple[float, tuple[slice, slice], tuple[slice, slice]] | None = None
    limit = max(0, min(int(max_shift_px), min(height, width) // 4))
    for dy in range(-limit, limit + 1):
        for dx in range(-limit, limit + 1):
            ref_y = slice(max(0, -dy), min(height, height - dy))
            ref_x = slice(max(0, -dx), min(width, width - dx))
            cur_y = slice(max(0, dy), min(height, height + dy))
            cur_x = slice(max(0, dx), min(width, width + dx))
            ref_view = ref_gray[ref_y, ref_x].astype(np.int16)
            cur_view = cur_gray[cur_y, cur_x].astype(np.int16)
            if ref_view.size == 0 or ref_view.shape != cur_view.shape:
                continue
            delta = cur_view - ref_view
            delta -= int(np.median(delta))
            # Clip large local differences so a connector occupying a minority
            # of the patch cannot pull alignment away from the static texture.
            score = float(np.mean(np.minimum(np.abs(delta), 48)))
            candidate = (score, (ref_y, ref_x), (cur_y, cur_x))
            if best is None or candidate[0] < best[0]:
                best = candidate
    if best is None:
        return reference_bgr, current_bgr
    _, (ref_y, ref_x), (cur_y, cur_x) = best
    return reference_bgr[ref_y, ref_x], current_bgr[cur_y, cur_x]


def _change_fraction(reference_bgr: np.ndarray, current_bgr: np.ndarray) -> float:
    """Lighting-tolerant changed-pixel fraction for two same-sized patches."""
    reference_bgr, current_bgr = _aligned_overlap(reference_bgr, current_bgr)
    ref_hsv = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2HSV)
    cur_hsv = cv2.cvtColor(current_bgr, cv2.COLOR_BGR2HSV)
    ref_gray = cv2.GaussianBlur(cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    cur_gray = cv2.GaussianBlur(cv2.cvtColor(current_bgr, cv2.COLOR_BGR2GRAY), (3, 3), 0)

    # Remove the patch-wide brightness shift before thresholding, so webcam
    # auto-exposure is not mistaken for a connector appearing.
    gray_delta = cur_gray.astype(np.int16) - ref_gray.astype(np.int16)
    gray_delta -= int(np.median(gray_delta))
    gray_changed = np.abs(gray_delta) >= 22
    saturation_changed = (
        np.abs(cur_hsv[:, :, 1].astype(np.int16) - ref_hsv[:, :, 1].astype(np.int16))
        >= 32
    )
    changed = np.asarray(gray_changed | saturation_changed, dtype=np.uint8) * 255
    changed = cv2.morphologyEx(
        changed, cv2.MORPH_OPEN, np.ones((2, 2), dtype=np.uint8)
    )
    return float(cv2.countNonZero(changed)) / max(float(changed.size), 1.0)


class GuidedRoiVerifier:
    """Stateful before/after verifier for one active guidance step."""

    def __init__(
        self,
        *,
        radius_px: int = 12,
        change_fraction: float = 0.08,
        max_change_fraction: float = 0.72,
        stable_motion_fraction: float = 0.10,
        stable_hits: int = 2,
        # Live C920 calibration 2026-08-05: the gray desk and pale-yellow
        # jumper both fall partly inside the broad YCrCb skin band.  Their
        # measured endpoint patches were 0.218/0.227, while a real hand in
        # the same frame measured 0.730.  The previous 0.16 threshold
        # therefore blocked the visual verifier whenever this yellow wire
        # was present.  Keep margin above the desk/wire cluster and below
        # the measured hand rather than treating generic warm pixels as a
        # hand by themselves.
        skin_fraction: float = 0.40,
        max_pose_shift_px: float = 4.0,
    ) -> None:
        self.radius_px = max(6, int(radius_px))
        self.change_threshold = float(change_fraction)
        self.max_change_threshold = float(max_change_fraction)
        self.stable_motion_threshold = float(stable_motion_fraction)
        self.required_stable_hits = max(1, int(stable_hits))
        self.skin_threshold = float(skin_fraction)
        self.max_pose_shift_px = float(max_pose_shift_px)
        self._baseline: _Baseline | None = None
        self._previous_board_patch: np.ndarray | None = None
        self._previous_component_patch: np.ndarray | None = None
        self._candidate_hits = 0
        self._preview_ready_hits = 0

    def reset(self) -> None:
        self._baseline = None
        self._previous_board_patch = None
        self._previous_component_patch = None
        self._candidate_hits = 0
        self._preview_ready_hits = 0

    @staticmethod
    def _result(status: str, reason: str, **extra) -> dict:
        return {"status": status, "reason": reason, **extra}

    def update(self, step, frame_bgr: np.ndarray, detection, component_pose) -> dict | None:
        if not getattr(step, "component_id", None) or not getattr(step, "expected_role", None):
            self.reset()
            return None
        if detection is None or getattr(detection, "tracking", "searching") != "locked":
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "board_not_tracked")
        if (
            component_pose is None
            or getattr(component_pose, "component_id", None) != step.component_id
            or getattr(component_pose, "tracking", "searching") not in {"locked", "stale"}
        ):
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "component_not_tracked")

        board_pin = next(
            (pin for pin in detection.pins if pin.pin_id == step.expected_pin_id), None
        )
        component_pin = next(
            (pin for pin in component_pose.pins if pin.id == step.expected_role), None
        )
        if board_pin is None or component_pin is None:
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "endpoint_not_visible")
        board_center = _position(board_pin, board=True)
        component_center = _position(component_pin, board=False)
        if board_center is None or component_center is None:
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "endpoint_not_visible")

        board_patch = _extract_patch(frame_bgr, board_center, self.radius_px)
        component_patch = _extract_patch(frame_bgr, component_center, self.radius_px)
        if board_patch is None or component_patch is None:
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "endpoint_not_visible")
        if not _patch_quality_ok(board_patch) or not _patch_quality_ok(component_patch):
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "lighting_unready")

        if self._baseline is None or self._baseline.step_id != step.step_id:
            if (
                _skin_fraction(board_patch) >= self.skin_threshold
                or _skin_fraction(component_patch) >= self.skin_threshold
            ):
                self._preview_ready_hits = 0
                return self._result("uncertain", "hand_occlusion")
            self._baseline = _Baseline(
                step_id=step.step_id,
                board_center=board_center,
                component_center=component_center,
                board_patch=board_patch,
                component_patch=component_patch,
            )
            self._previous_board_patch = board_patch
            self._previous_component_patch = component_patch
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("baseline", "baseline_captured")

        board_pose_shift = float(
            np.linalg.norm(np.asarray(board_center) - self._baseline.board_center)
        )
        component_pose_shift = float(
            np.linalg.norm(np.asarray(component_center) - self._baseline.component_center)
        )
        pose_shift = max(board_pose_shift, component_pose_shift)
        if pose_shift > self.max_pose_shift_px:
            # Camera/objects moved: use the new stable view as the reference,
            # never interpret geometry motion as a newly inserted connector.
            self._baseline = _Baseline(
                step_id=step.step_id,
                board_center=board_center,
                component_center=component_center,
                board_patch=board_patch,
                component_patch=component_patch,
            )
            self._previous_board_patch = board_patch
            self._previous_component_patch = component_patch
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result(
                "baseline",
                "baseline_rebased",
                pose_shift_px=round(pose_shift, 2),
                board_pose_shift_px=round(board_pose_shift, 2),
                component_pose_shift_px=round(component_pose_shift, 2),
            )

        board_change = _change_fraction(self._baseline.board_patch, board_patch)
        component_change = _change_fraction(self._baseline.component_patch, component_patch)
        board_motion = _change_fraction(self._previous_board_patch, board_patch)
        component_motion = _change_fraction(self._previous_component_patch, component_patch)
        self._previous_board_patch = board_patch
        self._previous_component_patch = component_patch
        details = {
            "board_change": round(board_change, 3),
            "component_change": round(component_change, 3),
            "stable_hits": self._candidate_hits,
        }

        if (
            _skin_fraction(board_patch) >= self.skin_threshold
            or _skin_fraction(component_patch) >= self.skin_threshold
        ):
            self._candidate_hits = 0
            self._preview_ready_hits = 0
            return self._result("uncertain", "hand_occlusion", **details)
        # This counter is deliberately independent from pixel-change scoring:
        # it only says both profile targets remained trackable, lit, unoccluded,
        # and within the pose gate for consecutive guidance ticks. It may
        # unlock a one-shot VLM preview, never a deterministic visual pass.
        self._preview_ready_hits += 1
        details["preview_stable_hits"] = self._preview_ready_hits
        if (
            board_change >= self.max_change_threshold
            or component_change >= self.max_change_threshold
            or board_motion >= self.stable_motion_threshold
            or component_motion >= self.stable_motion_threshold
        ):
            self._candidate_hits = 0
            return self._result("uncertain", "scene_moving", **details)

        board_present = board_change >= self.change_threshold
        component_present = component_change >= self.change_threshold
        if board_present and component_present:
            self._candidate_hits += 1
            details["stable_hits"] = self._candidate_hits
            if self._candidate_hits >= self.required_stable_hits:
                confidence = min(
                    1.0,
                    max(0.0, min(board_change, component_change) / 0.30),
                )
                return self._result(
                    "candidate", "both_endpoints_changed",
                    confidence=round(confidence, 3), **details,
                )
            return self._result("pending", "awaiting_stability", **details)

        self._candidate_hits = 0
        if board_present:
            reason = "board_endpoint_only"
        elif component_present:
            reason = "component_endpoint_only"
        else:
            reason = "waiting_for_both_endpoints"
        return self._result("pending", reason, **details)
