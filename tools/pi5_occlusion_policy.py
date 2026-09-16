"""Pure hard-example rules used by the Pi 5 occlusion capture tool.

The rules intentionally consume the public ``/ws/detections`` payload rather
than detector internals.  Keeping this module free of OpenCV and application
imports makes the trigger logic cheap to test and safe to reuse.
"""
from __future__ import annotations

from math import hypot, isfinite
from typing import Any


HOLD_STATES = frozenset({"occlusion_hold", "jump_hold"})


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def pin_motion_in_pitch(previous: dict[str, Any] | None, current: dict[str, Any]) -> float | None:
    """Return robust P90 matching-Pin motion normalized by current Pin pitch."""
    if not previous:
        return None
    geometry = current.get("geometry") or previous.get("geometry") or {}
    pitch = _finite_number(geometry.get("pitch_px"))
    if pitch is None or pitch <= 0.0:
        return None

    previous_pins: dict[str, tuple[float, float]] = {}
    for pin in previous.get("pins") or []:
        if not pin.get("v", True):
            continue
        x = _finite_number(pin.get("x"))
        y = _finite_number(pin.get("y"))
        pin_id = pin.get("id")
        if pin_id is not None and x is not None and y is not None:
            previous_pins[str(pin_id)] = (x, y)

    distances: list[float] = []
    for pin in current.get("pins") or []:
        if not pin.get("v", True):
            continue
        prior = previous_pins.get(str(pin.get("id")))
        x = _finite_number(pin.get("x"))
        y = _finite_number(pin.get("y"))
        if prior is not None and x is not None and y is not None:
            distances.append(hypot(x - prior[0], y - prior[1]) / pitch)

    if not distances:
        return None
    distances.sort()
    p90_index = max(0, min(len(distances) - 1, int(0.9 * len(distances) + 0.999999) - 1))
    return float(distances[p90_index])


def hard_case_reasons(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    confidence_drop: float = 0.18,
    motion_pitch: float = 0.45,
    min_visible_fraction: float = 0.75,
    visible_fraction_drop: float = 0.18,
    min_landmarks: int = 4,
) -> list[str]:
    """Explain why a detection frame is useful as an occlusion hard example."""
    reasons: list[str] = []
    quality = current.get("pose_quality") or {}
    stability = str(quality.get("stability") or "").strip().lower()
    if stability in HOLD_STATES:
        reasons.append(stability)

    if previous:
        previous_tracking = str(previous.get("tracking") or "").lower()
        current_tracking = str(current.get("tracking") or "").lower()
        if previous_tracking == "locked" and current_tracking != "locked":
            reasons.append("tracking_lost")

        prior_confidence = _finite_number(previous.get("confidence"))
        current_confidence = _finite_number(current.get("confidence"))
        if (
            prior_confidence is not None
            and current_confidence is not None
            and prior_confidence - current_confidence >= max(0.0, confidence_drop)
        ):
            reasons.append("confidence_drop")

        normalized_motion = pin_motion_in_pitch(previous, current)
        if normalized_motion is not None and normalized_motion >= max(0.0, motion_pitch):
            reasons.append("pin_motion")

        # ``visible_fraction`` is detector-path dependent.  The current Pi 5
        # four-point fallback can have a healthy baseline around 0.4, while an
        # eight-point model may sit much higher.  Trigger on a downward edge,
        # never on a fixed low value repeated forever.
        previous_quality = previous.get("pose_quality") or {}
        previous_visible = _finite_number(previous_quality.get("visible_fraction"))
        visible_fraction = _finite_number(quality.get("visible_fraction"))
        crossed_absolute_gate = (
            previous_visible is not None
            and visible_fraction is not None
            and previous_visible >= min_visible_fraction
            and visible_fraction < min_visible_fraction
        )
        relative_drop = (
            previous_visible is not None
            and visible_fraction is not None
            and previous_visible - visible_fraction >= max(0.0, visible_fraction_drop)
        )
        if crossed_absolute_gate or relative_drop:
            reasons.append("visibility_drop")

    visible_landmarks = current.get("pose_landmarks_visible")
    if visible_landmarks is not None:
        try:
            visible_landmarks = int(visible_landmarks)
        except (TypeError, ValueError):
            visible_landmarks = None
        if visible_landmarks is not None and visible_landmarks < max(1, min_landmarks):
            reasons.append("landmark_drop")

    # Preserve a stable user-facing order while removing duplicates.
    return list(dict.fromkeys(reasons))
