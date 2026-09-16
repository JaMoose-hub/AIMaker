"""Advisory coloured-insulation check for one guided Dupont connection.

This module deliberately does *not* trace a whole wire.  It looks only in a
small outward-facing sector beyond each expected pin, where the coloured
insulation emerges from the black Dupont housing.  Matching colours provide
useful association evidence for a guided, one-wire-at-a-time lesson, but never
prove insertion or electrical continuity.
"""
from __future__ import annotations

import math
import threading
from typing import Any, Iterable

import cv2
import numpy as np

from app.vision.wire_tracer import WIRE_COLOR_BANDS


# The endpoint sampler is intentionally more conservative than full wire
# tracing.  It now supports neutral Dupont insulation too, but those colours
# only pass after the thin-wire gate below so a connector or desk highlight is
# not casually treated as evidence.
ENDPOINT_WIRE_COLOR_NAMES = (
    "red", "orange", "brown", "yellow", "green", "blue", "purple", "black", "white",
)
_NEUTRAL_WIRE_NAMES = {"black", "white"}
_CHROMATIC_WIRE_NAMES = tuple(
    colour for colour in ENDPOINT_WIRE_COLOR_NAMES
    if colour not in _NEUTRAL_WIRE_NAMES
)
# A green lead laid directly over the Pi 5's green solder mask has no stable
# local colour contrast. Treating green PCB texture as a lead is worse than an
# explicit unknown result, so over-PCB adaptive sampling excludes that class.
_PI5_OVER_PCB_EXCLUDED_COLOURS = frozenset({"green"})
_MAX_SECTOR_ANGLE_DEG = 68.0
# A Pin's outward normal comes from a four-corner pose outline. On the live
# UNO Q, perspective and the small GND header can skew that normal by roughly
# 45 degrees from the visible Dupont exit. Keep this wider 60-degree fan as a
# *visual guide* only; it no longer influences the colour verdict.
_PIN_ENTRY_ANGLE_DEG = 60.0
_MIN_ENTRY_PIXELS = 4
# The wide fan is valuable feedback for the user, but it can include an
# adjacent ribbon conductor.  Colour association uses this narrower centre
# corridor, so GND's brown lead wins over a neighbouring red/orange wire that
# merely crosses the displayed fan.
_PIN_ASSOCIATION_ANGLE_DEG = 38.0
# The green HSV inspection fan is deliberately a visible, near-Pin region:
# begin just outside the detected board/component outline and retain its former
# far reach.  It must be wide enough to include the insulation as it emerges
# from the black Dupont housing. Colour remains advisory because ribbon wires
# can still overlap within this larger fan.
_PIN_ENTRY_NEAR_PIN_RADIUS_PX = 4.0
# UNO Q female headers expose coloured insulation sooner than the long Sensor
# connector. Let the HSV entry corridor begin closer to the board pin, while
# keeping its score reference at the former, conservative clearance.
_BOARD_ENTRY_INNER_PITCH_SCALE = 2.4
_BOARD_ENTRY_INNER_CAP_PX = 36.0
# This C920-mounted photoresistor module has a longer black female housing
# than the UNO Q header. It affects only where the *proximity score* starts;
# the narrow entry corridor remains unchanged, so this calibration cannot turn
# a distant crossing wire into target-Pin evidence.
_COMPONENT_HOUSING_SCORE_EXTENSION_RATIO = {
    "photoresistor-module": 0.45,
}
# The photoresistor module's black female connector is visibly longer than
# the UNO Q header.  Extend only its decision corridor by 24 px so the first
# exposed insulation remains eligible; board-side corridors stay unchanged.
_COMPONENT_CORRIDOR_DEPTH_PX = {
    "photoresistor-module": 60.0,
}
_ELECTRICALLY_EQUIVALENT_PINS: dict[str, tuple[str, ...]] = {
    "GND_P1": ("GND_P1", "GND_P2"),
    "GND_P2": ("GND_P1", "GND_P2"),
}


class GuidanceColorPreviewState:
    """Thread-safe, in-memory manual colour-sampling previews per endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jpeg_by_endpoint: dict[str, bytes] = {}

    def set(self, endpoint: str, jpeg: bytes) -> None:
        with self._lock:
            self._jpeg_by_endpoint[endpoint] = jpeg

    def get(self, endpoint: str) -> bytes | None:
        with self._lock:
            return self._jpeg_by_endpoint.get(endpoint)

    def clear(self) -> None:
        with self._lock:
            self._jpeg_by_endpoint.clear()


def _point(item: Any) -> tuple[float, float] | None:
    if not bool(getattr(item, "visible", True)):
        return None
    try:
        return float(item.x), float(item.y)
    except (AttributeError, TypeError, ValueError):
        return None


def _outline_centroid(outline: Any) -> tuple[float, float] | None:
    if outline is None:
        return None
    points = np.asarray(outline, dtype=np.float32).reshape(-1, 2)
    if len(points) < 3:
        return None
    return float(np.mean(points[:, 0])), float(np.mean(points[:, 1]))


def _resolve_outward_direction(
    center: tuple[float, float],
    centroid: tuple[float, float],
    outward_override: tuple[float, float] | None,
) -> tuple[float, float] | None:
    """Return a unit exit direction, falling back from a weak edge estimate.

    The outline-edge normal is the preferred physical direction.  On a briefly
    unstable detector frame, though, a degenerate outline can yield a zero-ish
    normal.  In that case the safer fallback is the original component-centre
    to Pin vector, rather than discarding an otherwise usable colour check.
    """
    candidates: tuple[tuple[float, float] | None, ...] = (
        outward_override,
        (center[0] - centroid[0], center[1] - centroid[1]),
    )
    for candidate in candidates:
        if candidate is None:
            continue
        outward_x, outward_y = candidate
        length = math.hypot(outward_x, outward_y)
        # Explicit edge/adaptive overrides are already unit vectors. Floating
        # point rounding may make their norm 0.9999999, so reject only a truly
        # degenerate direction rather than requiring a one-pixel magnitude.
        if length >= 1e-4:
            return outward_x / length, outward_y / length
    return None


def _component_header_outward(outline: Any, pins: Iterable[Any]) -> tuple[float, float] | None:
    """Find the outward normal of the component edge holding its Header pins.

    A small Sensor module is often long and narrow.  For an off-centre pin,
    ``component centroid -> pin`` is diagonal even though a Dupont connector
    leaves perpendicular to the shared Header edge.  Resolve that edge from
    all visible component pins, then point outward from the outline centroid to
    its midpoint.  This is rotation-safe and falls back to the older radial
    direction when the outline/pins are unavailable.
    """
    if outline is None:
        return None
    polygon = np.asarray(outline, dtype=np.float32).reshape(-1, 2)
    pin_points = [point for pin in pins if (point := _point(pin)) is not None]
    if len(polygon) < 3 or not pin_points:
        return None
    # The pose model can emit a valid quadrilateral in a non-perimeter order.
    # Work on its convex hull so only real PCB boundary edges participate.
    polygon = cv2.convexHull(polygon.astype(np.float32)).reshape(-1, 2)
    if len(polygon) < 3:
        return None
    pin_array = np.asarray(pin_points, dtype=np.float32)
    best_edge: tuple[np.ndarray, np.ndarray] | None = None
    best_distance = float("inf")
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        edge = end - start
        edge_squared = float(np.dot(edge, edge))
        if edge_squared <= 1e-5:
            continue
        relative = pin_array - start
        factors = np.clip((relative @ edge) / edge_squared, 0.0, 1.0)
        nearest = start + factors[:, None] * edge
        mean_distance = float(np.mean(np.sum((pin_array - nearest) ** 2, axis=1)))
        if mean_distance < best_distance:
            best_distance = mean_distance
            best_edge = (start, end)
    if best_edge is None:
        return None
    edge = best_edge[1] - best_edge[0]
    edge_length = float(np.linalg.norm(edge))
    if edge_length < 1e-4:
        return None
    outward = np.asarray([-edge[1], edge[0]], dtype=np.float32) / edge_length
    centroid = np.mean(polygon, axis=0)
    edge_midpoint = (best_edge[0] + best_edge[1]) * 0.5
    if float(np.dot(outward, edge_midpoint - centroid)) < 0.0:
        outward = -outward
    return float(outward[0]), float(outward[1])


def _pin_outline_edge_outward(
    outline: Any,
    center: tuple[float, float],
) -> tuple[float, float] | None:
    """Return the outward normal of the PCB edge nearest one target Pin.

    UNO pins are distributed across several headers, so unlike the Sensor we
    must not average every visible pin. A target such as GND_P1 can sit far
    along one header; the nearest PCB edge gives its physical connector exit
    direction without the diagonal bias of ``board centroid -> target Pin``.
    """
    if outline is None:
        return None
    polygon = np.asarray(outline, dtype=np.float32).reshape(-1, 2)
    if len(polygon) < 3:
        return None
    # Pose keypoints can arrive in a non-perimeter order. A convex hull makes
    # the candidate segments true PCB edges rather than accidental diagonals.
    polygon = cv2.convexHull(polygon.astype(np.float32)).reshape(-1, 2)
    if len(polygon) < 3:
        return None
    target = np.asarray(center, dtype=np.float32)
    best_edge: tuple[np.ndarray, np.ndarray] | None = None
    best_distance = float("inf")
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        edge = end - start
        edge_squared = float(np.dot(edge, edge))
        if edge_squared <= 1e-5:
            continue
        factor = float(np.clip(np.dot(target - start, edge) / edge_squared, 0.0, 1.0))
        nearest = start + factor * edge
        distance = float(np.sum((target - nearest) ** 2))
        if distance < best_distance:
            best_distance = distance
            best_edge = (start, end)
    if best_edge is None:
        return None
    edge = best_edge[1] - best_edge[0]
    edge_length = float(np.linalg.norm(edge))
    if edge_length < 1e-4:
        return None
    # A PCB connector leaves perpendicular to the header edge. Choose the
    # normal that points away from the convex outline's centroid.
    outward = np.asarray([-edge[1], edge[0]], dtype=np.float32) / edge_length
    centroid = np.mean(polygon, axis=0)
    edge_midpoint = (best_edge[0] + best_edge[1]) * 0.5
    if float(np.dot(outward, edge_midpoint - centroid)) < 0.0:
        outward = -outward
    return float(outward[0]), float(outward[1])


def _pin_pitch(pins: Iterable[Any], fallback: float = 12.0) -> float:
    points = [point for pin in pins if (point := _point(pin)) is not None]
    distances = [
        math.hypot(left[0] - right[0], left[1] - right[1])
        for index, left in enumerate(points)
        for right in points[index + 1:]
    ]
    usable = [distance for distance in distances if 4.0 <= distance <= 80.0]
    return min(usable) if usable else fallback


def _adaptive_wire_outward(
    frame_bgr: np.ndarray,
    center: tuple[float, float],
    pins: Iterable[Any],
) -> tuple[float, float] | None:
    """Find the local direction of a coloured lead around a vertical Pin.

    A Raspberry Pi J8 Pin is vertical. Once a female Dupont housing is pushed
    onto it, the flexible lead may bend over the PCB or away from any of its
    four edges. Therefore a PCB-edge normal is not a valid wire direction.
    Search a full annulus around the active Pin and accept only a thin,
    radially extended chromatic component. Broad PCB regions are rejected by
    their apparent width and lateral spread. The function is used only for a
    user-triggered endpoint capture, so it does not add work to live Pose.
    """
    height, width = frame_bgr.shape[:2]
    cx, cy = center
    pitch = _pin_pitch(pins)
    search_inner = max(7.0, min(24.0, pitch * 0.75))
    search_outer = max(58.0, min(112.0, pitch * 6.2))
    left = max(0, int(math.floor(cx - search_outer)))
    top = max(0, int(math.floor(cy - search_outer)))
    right = min(width, int(math.ceil(cx + search_outer)) + 1)
    bottom = min(height, int(math.ceil(cy + search_outer)) + 1)
    if right <= left or bottom <= top:
        return None

    crop = frame_bgr[top:bottom, left:right]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    yy, xx = np.ogrid[top:bottom, left:right]
    dx_grid = xx.astype(np.float32) - float(cx)
    dy_grid = yy.astype(np.float32) - float(cy)
    radial_grid = np.hypot(dx_grid, dy_grid)
    annulus = (
        (radial_grid >= search_inner) & (radial_grid <= search_outer)
    ).astype(np.uint8) * 255

    best: tuple[float, tuple[float, float]] | None = None
    for colour in _CHROMATIC_WIRE_NAMES:
        if colour in _PI5_OVER_PCB_EXCLUDED_COLOURS:
            continue
        mask = cv2.bitwise_and(_colour_mask(hsv, colour), annulus)
        if cv2.countNonZero(mask) < 10:
            continue
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
            mask, connectivity=8,
        )
        for label in range(1, count):
            pixels = int(stats[label, cv2.CC_STAT_AREA])
            if pixels < 10:
                continue
            selected = labels == label
            selected_y, selected_x = np.nonzero(selected)
            dx = selected_x.astype(np.float32) + float(left) - float(cx)
            dy = selected_y.astype(np.float32) + float(top) - float(cy)
            radial = radial_grid[selected]
            if radial.size == 0:
                continue
            near = float(np.percentile(radial, 5))
            far = float(np.percentile(radial, 95))
            radial_span = far - near
            if radial_span < 12.0:
                continue
            # A crossing conductor well away from the active Pin is not an
            # endpoint direction candidate.
            if near > max(search_inner + pitch * 2.2, search_outer * 0.52):
                continue

            units = np.column_stack((
                dx / np.maximum(radial, 1e-4),
                dy / np.maximum(radial, 1e-4),
            ))
            mean_direction = np.mean(units, axis=0)
            coherence = float(np.linalg.norm(mean_direction))
            if coherence < 0.62:
                continue
            direction = mean_direction / coherence
            lateral = np.abs(-dx * direction[1] + dy * direction[0])
            lateral_p90 = float(np.percentile(lateral, 90))
            if lateral_p90 > max(12.0, pitch * 1.05):
                continue
            apparent_width = pixels / max(radial_span, 1.0)
            width_limit = max(10.0, min(16.0, pitch * 0.9))
            if apparent_width > width_limit:
                continue

            proximity = 1.0 - min(
                1.0,
                max(0.0, near - search_inner)
                / max(1.0, search_outer - search_inner),
            )
            extension = min(1.0, radial_span / max(32.0, pitch * 2.2))
            thinness = 1.0 - min(1.0, apparent_width / width_limit)
            score = (
                0.42 * proximity
                + 0.30 * extension
                + 0.20 * coherence
                + 0.08 * thinness
            )
            candidate = (float(direction[0]), float(direction[1]))
            if best is None or score > best[0]:
                best = (score, candidate)
    return best[1] if best is not None else None


def _board_endpoint_sampling_geometry(
    frame_bgr: np.ndarray,
    detection: Any,
    center: tuple[float, float],
) -> tuple[Any, tuple[float, float] | None, str]:
    """Resolve one board endpoint's exclusion mask and exit direction."""
    outline = getattr(detection, "outline_px", None)
    edge_outward = _pin_outline_edge_outward(outline, center)
    if str(getattr(detection, "board_id", "")) == "raspberry-pi-5":
        adaptive = _adaptive_wire_outward(
            frame_bgr, center, getattr(detection, "pins", ()),
        )
        if adaptive is not None:
            # A Pi lead may legitimately run over the PCB. Keep the broad-PCB
            # rejection in the colour classifier, but do not erase the whole
            # board from this manually triggered sample.
            return None, adaptive, "adaptive_360"
    return outline, edge_outward, "pcb_edge"


def _sector_mask(
    shape: tuple[int, int],
    center: tuple[float, float],
    outward: tuple[float, float],
    *,
    inner_radius_px: float,
    outer_radius_px: float,
    exclusion_outline: Any,
    max_sector_angle_deg: float = _MAX_SECTOR_ANGLE_DEG,
) -> tuple[np.ndarray, tuple[int, int, int, int], np.ndarray]:
    """Return a local annular sector, its frame bounds, and radial distances."""
    height, width = shape
    cx, cy = center
    left = max(0, int(math.floor(cx - outer_radius_px)))
    top = max(0, int(math.floor(cy - outer_radius_px)))
    right = min(width, int(math.ceil(cx + outer_radius_px)) + 1)
    bottom = min(height, int(math.ceil(cy + outer_radius_px)) + 1)
    if right <= left or bottom <= top:
        return np.zeros((0, 0), dtype=np.uint8), (left, top, right, bottom), np.zeros((0, 0))

    yy, xx = np.ogrid[top:bottom, left:right]
    dx = xx.astype(np.float32) - float(cx)
    dy = yy.astype(np.float32) - float(cy)
    radial = np.hypot(dx, dy)
    ux, uy = outward
    cosine = (dx * ux + dy * uy) / np.maximum(radial, 1e-4)
    mask = (
        (radial >= inner_radius_px)
        & (radial <= outer_radius_px)
        & (cosine >= math.cos(math.radians(max_sector_angle_deg)))
    ).astype(np.uint8) * 255

    if exclusion_outline is not None:
        poly = np.asarray(exclusion_outline, dtype=np.float32).reshape(-1, 2)
        if len(poly) >= 3:
            local_poly = np.round(poly - np.array([left, top], dtype=np.float32)).astype(np.int32)
            blocked = np.zeros(mask.shape, dtype=np.uint8)
            cv2.fillPoly(blocked, [local_poly], 255)
            # A small dilation avoids sampling the saturated blue PCB edge.
            blocked = cv2.dilate(blocked, np.ones((5, 5), dtype=np.uint8), iterations=1)
            mask[blocked != 0] = 0
    return mask, (left, top, right, bottom), radial


def _pin_entry_mask(
    shape: tuple[int, int],
    center: tuple[float, float],
    outward: tuple[float, float],
    *,
    pin_pitch_px: float,
    inner_radius_px: float,
    outer_radius_px: float,
    exclusion_outline: Any,
    entry_depth_px: float | None = None,
    max_sector_angle_deg: float = _PIN_ENTRY_ANGLE_DEG,
) -> np.ndarray:
    """Return the wide near-Pin fan where insulation leaves a Pin.

    The fan begins immediately outside the detected outline around the active
    Pin and covers the same far reach as the former entry region. This matches
    the visual teaching purpose: show the area where a Dupont lead approaches
    the Pin, rather than a small distant patch of the wire.
    """
    default_entry_depth = max(18.0, min(36.0, pin_pitch_px * 2.6))
    entry_depth = max(default_entry_depth, float(entry_depth_px or 0.0))
    # The component/board outline below removes the PCB itself, so this small
    # radius lets the fan visibly reach the Pin without sampling its blue body.
    entry_inner = min(float(inner_radius_px), _PIN_ENTRY_NEAR_PIN_RADIUS_PX)
    entry_outer = min(outer_radius_px, inner_radius_px + entry_depth)
    # Keep this mask aligned with the full observation sector.  Callers compare
    # it directly with colour components from that sector, so only the active
    # radial band may move; its bounding box must not change.
    entry, (left, top, right, bottom), radial = _sector_mask(
        shape,
        center,
        outward,
        inner_radius_px=entry_inner,
        outer_radius_px=outer_radius_px,
        exclusion_outline=exclusion_outline,
        max_sector_angle_deg=max_sector_angle_deg,
    )
    entry[radial > entry_outer] = 0
    return entry


def _colour_mask(hsv: np.ndarray, colour: str) -> np.ndarray:
    result = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in WIRE_COLOR_BANDS[colour]:
        result |= cv2.inRange(hsv, np.asarray(lower, dtype=np.uint8), np.asarray(upper, dtype=np.uint8))
    return result


def _select_endpoint_colour(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve the red/orange/brown overlap using the whole wire segment.

    Brown insulation under the C920 can be either lower-saturation brown or a
    dark, saturated red-brown.  Both overlap a broad red/orange range at the
    pixel level. Prefer brown only when its component is comparably substantial
    and has one of those measured brown signatures. This is an ambiguity
    resolver, not a full-wire tracker.
    """
    brown = next((item for item in candidates if item["color"] == "brown"), None)
    warm_competitors = [
        item for item in candidates if item["color"] in {"red", "orange"}
    ]
    if brown is not None and warm_competitors:
        strongest_warm = max(
            warm_competitors,
            key=lambda item: (int(item["pixels"]), float(item["confidence"])),
        )
        low_saturation_brown = float(brown["median_saturation"]) <= 120.0
        dark_red_brown = (
            float(brown["median_hue"]) <= 4.0
            and float(brown["median_value"]) <= 105.0
        )
        if (
            (low_saturation_brown or dark_red_brown)
            and int(brown["pixels"]) >= int(strongest_warm["pixels"]) * 0.65
        ):
            return brown
    # A longer, fuller colour component is more informative than the prior
    # confidence alone, which intentionally saturates at 48 pixels.
    return max(
        candidates,
        key=lambda item: (
            float(item["confidence"]),
            int(item["pixels"]),
            float(item["radial_span_px"]),
        ),
    )


def stabilize_endpoint_colour_samples(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return one temporally stable endpoint sample from a short frame burst.

    Colour is intentionally sampled only after the user clicks the button.
    Taking a small burst makes an auto-exposure change, a hand reflection, or
    one crossing ribbon conductor less likely to become the saved colour.  A
    single usable frame remains a valid *advisory* sample when the camera is
    temporarily slow, but its reported temporal evidence makes that visible.
    """
    captured = [dict(sample) for sample in samples]
    if not captured:
        return {
            "color": None,
            "confidence": 0.0,
            "reason": "no_color_frames",
            "sample_count": 0,
            "stable_hits": 0,
            "temporal_consensus": 0.0,
            "temporal_stable": False,
        }

    coloured = [sample for sample in captured if sample.get("color")]
    if not coloured:
        result = dict(captured[-1])
        result.update({
            "sample_count": len(captured),
            "stable_hits": 0,
            "temporal_consensus": 0.0,
            "temporal_stable": False,
        })
        return result

    by_colour: dict[str, list[dict[str, Any]]] = {}
    for sample in coloured:
        by_colour.setdefault(str(sample["color"]), []).append(sample)
    ranked_colours = sorted(
        by_colour,
        key=lambda colour: (
            len(by_colour[colour]),
            np.median([float(item.get("confidence", 0.0)) for item in by_colour[colour]]),
            np.median([float(item.get("pin_proximity", 0.0)) for item in by_colour[colour]]),
        ),
        reverse=True,
    )
    selected_colour = ranked_colours[0]
    selected = by_colour[selected_colour]
    stable_hits = len(selected)
    total = len(captured)
    consensus = stable_hits / total
    required_hits = 3 if total >= 3 else 1
    temporal_stable = stable_hits >= required_hits and consensus >= 0.60
    result = dict(max(
        selected,
        key=lambda item: (
            float(item.get("confidence", 0.0)),
            float(item.get("pin_proximity", 0.0)),
            int(item.get("pixels", 0)),
        ),
    ))

    labs = [item.get("lab") for item in selected]
    valid_labs = [lab for lab in labs if isinstance(lab, (list, tuple)) and len(lab) == 3]
    if valid_labs:
        median_lab = np.median(np.asarray(valid_labs, dtype=np.float32), axis=0)
        result["lab"] = [round(float(value), 1) for value in median_lab]
    result["confidence"] = round(
        float(result.get("confidence", 0.0)) * (0.70 + 0.30 * consensus),
        3,
    )
    result.update({
        "sample_count": total,
        "stable_hits": stable_hits,
        "temporal_consensus": round(consensus, 3),
        "temporal_stable": temporal_stable,
    })

    competing = [colour for colour in ranked_colours[1:] if by_colour[colour]]
    if competing and (not temporal_stable or len(by_colour[competing[0]]) >= stable_hits):
        result["ambiguous"] = True
        result["competing_colors"] = sorted(set(result.get("competing_colors", []) + competing))
    if not temporal_stable:
        result["reason"] = "temporal_color_unstable"
    elif result.get("reason") == "color_sampled":
        result["reason"] = "color_sampled_temporal"
    return result


def _pin_proximity_score(
    *,
    nearest_radius_px: float,
    radial_span_px: float,
    pixels: int,
    inner_radius_px: float,
    outer_radius_px: float,
    housing_clearance_radius_px: float | None = None,
) -> float:
    """Score how convincingly the sampled insulation approaches its target pin.

    The black female housing immediately at a pin is deliberately excluded.
    Therefore, the score starts at the outer edge of that exclusion zone rather
    than demanding coloured insulation at the pin centre.  It combines the
    first visible coloured pixel, radial extension, and support area.  This is
    target-end association evidence only; it cannot prove a full wire path.
    """
    score_start_radius = max(
        inner_radius_px,
        min(housing_clearance_radius_px or inner_radius_px, outer_radius_px - 1.0),
    )
    inspected_depth = max(1.0, outer_radius_px - score_start_radius)
    gap_after_housing = max(0.0, nearest_radius_px - score_start_radius)
    # Once the same-colour insulation begins more than ~72% into the visible
    # sampling depth, it is too far from this target to be strong evidence.
    arrival = 1.0 - min(1.0, gap_after_housing / max(12.0, inspected_depth * 0.72))
    extension = min(1.0, radial_span_px / 28.0)
    support = min(1.0, pixels / 48.0)
    return round(0.65 * arrival + 0.25 * extension + 0.10 * support, 3)


def _sample_endpoint_colour(
    frame_bgr: np.ndarray,
    center: tuple[float, float],
    outline: Any,
    pins: Iterable[Any],
    *,
    outward_override: tuple[float, float] | None = None,
    housing_score_extension_ratio: float = 0.0,
    sampling_inner_pitch_scale: float = 3.2,
    sampling_inner_cap_px: float = 46.0,
    score_reference_inner_pitch_scale: float | None = None,
    score_reference_inner_cap_px: float | None = None,
    entry_fan_depth_px: float | None = None,
    excluded_colours: Iterable[str] = (),
) -> dict[str, Any]:
    """Sample the coloured insulation just outside one black connector.

    The sector starts roughly three header pitches from the pin.  That skips
    the black female housing while retaining enough of the insulation to make
    a colour call.  It only returns a colour when a thin, radially extended
    patch is present; desk/PCB colour alone is deliberately reported unknown.
    """
    centroid = _outline_centroid(outline)
    if centroid is None:
        if outward_override is None:
            return {"color": None, "confidence": 0.0, "reason": "outline_unavailable"}
        centroid = (
            center[0] - float(outward_override[0]),
            center[1] - float(outward_override[1]),
        )
    outward = _resolve_outward_direction(center, centroid, outward_override)
    if outward is None:
        return {"color": None, "confidence": 0.0, "reason": "outward_direction_unavailable"}
    pitch = _pin_pitch(pins)
    inner_radius = max(18.0, min(sampling_inner_cap_px, pitch * sampling_inner_pitch_scale))
    outer_radius = max(inner_radius + 32.0, min(108.0, pitch * 11.5))
    score_reference_inner_pitch_scale = (
        sampling_inner_pitch_scale
        if score_reference_inner_pitch_scale is None
        else score_reference_inner_pitch_scale
    )
    score_reference_inner_cap_px = (
        sampling_inner_cap_px
        if score_reference_inner_cap_px is None
        else score_reference_inner_cap_px
    )
    score_reference_radius = max(
        inner_radius,
        min(score_reference_inner_cap_px, pitch * score_reference_inner_pitch_scale),
    )
    score_reference_radius = min(score_reference_radius, outer_radius - 1.0)
    housing_score_extension_ratio = max(0.0, min(0.70, housing_score_extension_ratio))
    score_start_radius = score_reference_radius + (
        outer_radius - score_reference_radius
    ) * housing_score_extension_ratio
    sector, (left, top, right, bottom), radial = _sector_mask(
        frame_bgr.shape[:2],
        center,
        outward,
        inner_radius_px=inner_radius,
        outer_radius_px=outer_radius,
        exclusion_outline=outline,
    )
    if sector.size == 0 or cv2.countNonZero(sector) == 0:
        return {"color": None, "confidence": 0.0, "reason": "sampling_region_unavailable"}
    association_corridor = _pin_entry_mask(
        frame_bgr.shape[:2],
        center,
        outward,
        pin_pitch_px=pitch,
        inner_radius_px=inner_radius,
        outer_radius_px=outer_radius,
        exclusion_outline=outline,
        entry_depth_px=entry_fan_depth_px,
        max_sector_angle_deg=_PIN_ASSOCIATION_ANGLE_DEG,
    )
    crop_bgr = frame_bgr[top:bottom, left:right]
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    # HSV assigns the familiar colour name, while CIE Lab preserves a
    # lighting-tolerant measured colour signature for comparison with the
    # other end of the same Dupont lead.  OpenCV encodes L in [0, 255] and
    # a/b with 128 as neutral, so convert it before exposing the value.
    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
    candidates: list[dict[str, Any]] = []
    excluded = set(excluded_colours)
    for colour in ENDPOINT_WIRE_COLOR_NAMES:
        if colour in excluded:
            continue
        mask = _colour_mask(hsv, colour)
        mask = cv2.bitwise_and(mask, sector)
        if cv2.countNonZero(mask) < 8:
            continue
        count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        components: list[tuple[float, int, float, float, float, float, float, float, int, tuple[float, float, float]]] = []
        best: tuple[float, int, float, float, float, float, float, float, int, tuple[float, float, float]] | None = None
        for label in range(1, count):
            pixels = int(stats[label, cv2.CC_STAT_AREA])
            if pixels < 8:
                continue
            component_radial = radial[labels == label]
            if component_radial.size == 0:
                continue
            radial_span = float(np.percentile(component_radial, 95) - np.percentile(component_radial, 5))
            if radial_span < 8.0:
                continue
            component_pixels = labels == label
            corridor_pixels = int(np.count_nonzero(component_pixels & (association_corridor != 0)))
            # A coloured cable that is only seen farther out in the large
            # amber sector may be a crossing wire. It is associated with this
            # Pin only when it enters the single narrow exit corridor.
            if corridor_pixels < _MIN_ENTRY_PIXELS:
                continue
            # Neutral (black/white) areas are common around headers and the
            # desk. A real wire is a narrow, outward-reaching strip; broad
            # neutral blobs are intentionally ignored for this advisory check.
            apparent_width = pixels / max(radial_span, 1.0)
            width_limit = 9.0 if colour in _NEUTRAL_WIRE_NAMES else max(
                10.0, min(16.0, pitch * 0.9),
            )
            if apparent_width > width_limit:
                continue
            support = min(1.0, pixels / 48.0)
            extension = min(1.0, radial_span / 28.0)
            confidence = 0.42 * support + 0.58 * extension
            median_saturation = float(np.median(hsv[:, :, 1][component_pixels]))
            median_hue = float(np.median(hsv[:, :, 0][component_pixels]))
            median_value = float(np.median(hsv[:, :, 2][component_pixels]))
            median_lab_encoded = np.median(lab[component_pixels], axis=0)
            median_lab = (
                float(median_lab_encoded[0]) * 100.0 / 255.0,
                float(median_lab_encoded[1]) - 128.0,
                float(median_lab_encoded[2]) - 128.0,
            )
            nearest_radius = float(np.percentile(component_radial, 5))
            pin_proximity = _pin_proximity_score(
                nearest_radius_px=nearest_radius,
                radial_span_px=radial_span,
                pixels=pixels,
                inner_radius_px=inner_radius,
                outer_radius_px=outer_radius,
                housing_clearance_radius_px=score_start_radius,
            )
            candidate = (
                confidence,
                pixels,
                radial_span,
                median_saturation,
                median_hue,
                median_value,
                nearest_radius,
                pin_proximity,
                corridor_pixels,
                median_lab,
            )
            components.append(candidate)
            if best is None or candidate[:3] > best[:3]:
                best = candidate
        if best is not None:
            (
                confidence,
                pixels,
                radial_span,
                median_saturation,
                median_hue,
                median_value,
                nearest_radius,
                pin_proximity,
                corridor_pixels,
                median_lab,
            ) = best
            comparable_components = sum(
                1
                for item in components
                if item[8] >= max(_MIN_ENTRY_PIXELS, corridor_pixels * 0.45)
                and item[7] >= pin_proximity - 0.22
            )
            candidates.append({
                "color": colour,
                "confidence": round(float(confidence), 3),
                "pixels": int(pixels),
                "radial_span_px": round(float(radial_span), 1),
                "nearest_pin_distance_px": round(float(nearest_radius), 1),
                "pin_proximity": round(float(pin_proximity), 3),
                "proximity_reference_radius_px": round(float(score_start_radius), 1),
                "corridor_pixels": int(corridor_pixels),
                "competing_components": int(comparable_components),
                "ambiguous": comparable_components > 1,
                "median_saturation": round(float(median_saturation), 1),
                "median_hue": round(float(median_hue), 1),
                "median_value": round(float(median_value), 1),
                "lab": [round(float(value), 1) for value in median_lab],
            })

    if not candidates:
        return {
            "color": None,
            "confidence": 0.0,
            "reason": "no_colored_insulation",
            "inner_radius_px": round(inner_radius, 1),
            "outer_radius_px": round(outer_radius, 1),
        }
    best = dict(_select_endpoint_colour(candidates))
    warm_colours = {"red", "orange", "brown"}
    conflicting_colours = [
        item["color"]
        for item in candidates
        if item["color"] != best["color"]
        and not ({item["color"], best["color"]} <= warm_colours)
        and int(item["corridor_pixels"]) >= max(
            _MIN_ENTRY_PIXELS, int(best["corridor_pixels"]) * 0.45,
        )
        and float(item["pin_proximity"]) >= float(best["pin_proximity"]) - 0.22
    ]
    if conflicting_colours:
        best["ambiguous"] = True
        best["competing_colors"] = sorted(set(conflicting_colours))
    best = {
        key: value
        for key, value in best.items()
        if key not in {
            "median_saturation", "median_hue", "median_value", "corridor_pixels",
        }
    }
    return {
        **best,
        "reason": "color_sampled",
        "inner_radius_px": round(inner_radius, 1),
        "outer_radius_px": round(outer_radius, 1),
    }


def _sample_guided_board_endpoint(
    frame_bgr: np.ndarray,
    detection: Any,
    expected_pin_id: str,
) -> tuple[Any | None, dict[str, Any]]:
    """Sample the requested board endpoint, accepting equivalent UNO GNDs.

    UNO Q exposes two adjacent power-header GND holes. Either is the same
    electrical net, so the teaching flow must not describe a wire in GND_P2 as
    an error merely because the visual instruction names GND_P1. Exact target
    evidence remains preferred whenever it is available.
    """
    accepted_ids = _ELECTRICALLY_EQUIVALENT_PINS.get(expected_pin_id, (expected_pin_id,))
    by_id = {
        str(getattr(pin, "pin_id", "")): pin
        for pin in getattr(detection, "pins", ())
        if _point(pin) is not None
    }
    samples: list[tuple[Any, dict[str, Any]]] = []
    for pin_id in accepted_ids:
        pin = by_id.get(pin_id)
        center = _point(pin) if pin is not None else None
        if center is None:
            continue
        sampling_outline, outward, direction_source = _board_endpoint_sampling_geometry(
            frame_bgr, detection, center,
        )
        result = _sample_endpoint_colour(
            frame_bgr,
            center,
            sampling_outline,
            getattr(detection, "pins", ()),
            outward_override=outward,
            sampling_inner_pitch_scale=_BOARD_ENTRY_INNER_PITCH_SCALE,
            sampling_inner_cap_px=_BOARD_ENTRY_INNER_CAP_PX,
            score_reference_inner_pitch_scale=3.2,
            score_reference_inner_cap_px=46.0,
            excluded_colours=(
                _PI5_OVER_PCB_EXCLUDED_COLOURS
                if direction_source == "adaptive_360"
                else ()
            ),
        )
        result = dict(result)
        result["direction_source"] = direction_source
        if outward is not None:
            result["outward_direction"] = [
                round(float(outward[0]), 4),
                round(float(outward[1]), 4),
            ]
        if direction_source == "adaptive_360":
            result["excluded_colors"] = sorted(_PI5_OVER_PCB_EXCLUDED_COLOURS)
        samples.append((pin, result))
    if not samples:
        return None, {"color": None, "confidence": 0.0, "reason": "target_not_visible"}

    exact = next((item for item in samples if getattr(item[0], "pin_id", None) == expected_pin_id), None)
    if exact is not None and exact[1].get("color"):
        selected = exact
    else:
        selected = max(
            samples,
            key=lambda item: (
                bool(item[1].get("color")),
                float(item[1].get("pin_proximity", 0.0)),
                float(item[1].get("confidence", 0.0)),
            ),
        )
    pin, result = selected
    result = dict(result)
    resolved_pin_id = str(getattr(pin, "pin_id", expected_pin_id))
    result["pin_id"] = resolved_pin_id
    result["electrically_equivalent"] = resolved_pin_id != expected_pin_id
    return pin, result


def _sample_guided_component_endpoint(
    frame_bgr: np.ndarray,
    component_pose: Any,
    expected_role: str,
) -> tuple[Any | None, dict[str, Any]]:
    """Sample one Sensor endpoint without requiring the UNO Q pose.

    A colour sample is captured manually for each physical end of the wire.
    Keeping this operation local to the Sensor means the user may move the
    camera to a close-up after the UNO Q end was already saved.
    """
    component_pin = next(
        (pin for pin in getattr(component_pose, "pins", ()) if getattr(pin, "id", None) == expected_role),
        None,
    )
    component_center = _point(component_pin) if component_pin is not None else None
    if component_center is None:
        return None, {"color": None, "confidence": 0.0, "reason": "target_not_visible"}
    component = _sample_endpoint_colour(
        frame_bgr,
        component_center,
        getattr(component_pose, "outline_px", None),
        getattr(component_pose, "pins", ()),
        outward_override=_component_header_outward(
            getattr(component_pose, "outline_px", None),
            getattr(component_pose, "pins", ()),
        ),
        housing_score_extension_ratio=_COMPONENT_HOUSING_SCORE_EXTENSION_RATIO.get(
            getattr(component_pose, "component_id", ""), 0.0,
        ),
        entry_fan_depth_px=_COMPONENT_CORRIDOR_DEPTH_PX.get(
            getattr(component_pose, "component_id", ""), None,
        ),
    )
    component = dict(component)
    component["pin_id"] = expected_role
    return component_pin, component


def inspect_guided_board_endpoint_color(
    frame_bgr: np.ndarray,
    detection: Any,
    step: Any,
) -> dict[str, Any]:
    """Return one advisory board colour sample for the active guided Pin."""
    _pin, board = _sample_guided_board_endpoint(frame_bgr, detection, step.expected_pin_id)
    return board


def inspect_guided_component_endpoint_color(
    frame_bgr: np.ndarray,
    component_pose: Any,
    step: Any,
) -> dict[str, Any]:
    """Return one advisory Sensor colour sample for the active guided Pin."""
    _pin, component = _sample_guided_component_endpoint(frame_bgr, component_pose, step.expected_role)
    return component


def inspect_guided_endpoint_colors(
    frame_bgr: np.ndarray,
    detection: Any,
    component_pose: Any,
    step: Any,
) -> dict[str, Any]:
    """Return advisory colour consistency from one frame containing both ends.

    The manual UI now samples each endpoint independently. This combined helper
    is retained for regression tests and offline callers that already have both
    poses from the same frame.
    """
    board_pin, board = _sample_guided_board_endpoint(frame_bgr, detection, step.expected_pin_id)
    component_pin, component = _sample_guided_component_endpoint(
        frame_bgr, component_pose, step.expected_role
    )
    board_center = _point(board_pin) if board_pin is not None else None
    component_center = _point(component_pin) if component_pin is not None else None
    if board_center is None or component_center is None:
        return {"status": "unknown", "confidence": 0.0, "reason": "target_not_visible"}
    board_colour = board.get("color")
    component_colour = component.get("color")
    confidence = min(float(board.get("confidence", 0.0)), float(component.get("confidence", 0.0)))
    connection_proximity = min(
        float(board.get("pin_proximity", 0.0)),
        float(component.get("pin_proximity", 0.0)),
    )
    if board_colour and component_colour:
        if bool(board.get("ambiguous")) or bool(component.get("ambiguous")):
            status = "ambiguous"
            reason = "multiple_pin_exit_candidates"
        else:
            status = "match" if board_colour == component_colour else "mismatch"
            reason = "colors_match" if status == "match" else "colors_differ"
    elif board_colour or component_colour:
        status = "partial"
        reason = "one_endpoint_color_visible"
    else:
        status = "unknown"
        reason = "no_color_evidence"
    return {
        "status": status,
        "confidence": round(confidence, 3),
        "connection_proximity": round(connection_proximity, 3),
        "reason": reason,
        "board": board,
        "component": component,
        "advisory": True,
    }


def _preview_panel(
    image: np.ndarray,
    label: str,
    *,
    width: int = 460,
    height: int = 340,
) -> np.ndarray:
    """Fit a source image into a labelled preview without changing its content."""
    source_height, source_width = image.shape[:2]
    label_height = 28
    scale = min(width / max(1, source_width), (height - label_height) / max(1, source_height))
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    panel = np.full((height, width, 3), 12, dtype=np.uint8)
    offset_x = (width - resized_width) // 2
    offset_y = label_height + (height - label_height - resized_height) // 2
    panel[offset_y:offset_y + resized_height, offset_x:offset_x + resized_width] = resized
    cv2.rectangle(panel, (0, 0), (width - 1, label_height), (12, 12, 12), -1)
    cv2.putText(panel, label, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (98, 221, 255), 1, cv2.LINE_AA)
    return panel


def _endpoint_sampling_preview(
    frame_bgr: np.ndarray,
    center: tuple[float, float],
    outline: Any,
    pins: Iterable[Any],
    label: str,
    *,
    outward_override: tuple[float, float] | None = None,
    sampling_inner_pitch_scale: float = 3.2,
    sampling_inner_cap_px: float = 46.0,
    entry_fan_depth_px: float | None = None,
    excluded_colours: Iterable[str] = (),
) -> np.ndarray:
    """Show the exact annular sector passed to the local colour classifier."""
    centroid = _outline_centroid(outline)
    if centroid is None:
        if outward_override is None:
            return _preview_panel(
                _center_preview_crop(frame_bgr, center, 190),
                f"{label}: OUTLINE UNAVAILABLE",
            )
        centroid = (
            center[0] - float(outward_override[0]),
            center[1] - float(outward_override[1]),
        )
    outward = _resolve_outward_direction(center, centroid, outward_override)
    if outward is None:
        return _preview_panel(_center_preview_crop(frame_bgr, center, 190), f"{label}: DIRECTION UNAVAILABLE")
    pitch = _pin_pitch(pins)
    inner_radius = max(18.0, min(sampling_inner_cap_px, pitch * sampling_inner_pitch_scale))
    outer_radius = max(inner_radius + 32.0, min(108.0, pitch * 11.5))
    sector, (left, top, right, bottom), _radial = _sector_mask(
        frame_bgr.shape[:2],
        center,
        outward,
        inner_radius_px=inner_radius,
        outer_radius_px=outer_radius,
        exclusion_outline=outline,
    )
    crop = frame_bgr[top:bottom, left:right].copy()
    if crop.size == 0:
        return _preview_panel(_center_preview_crop(frame_bgr, center, 190), f"{label}: SAMPLE UNAVAILABLE")
    association_corridor = _pin_entry_mask(
        frame_bgr.shape[:2],
        center,
        outward,
        pin_pitch_px=pitch,
        inner_radius_px=inner_radius,
        outer_radius_px=outer_radius,
        exclusion_outline=outline,
        entry_depth_px=entry_fan_depth_px,
        max_sector_angle_deg=_PIN_ASSOCIATION_ANGLE_DEG,
    )
    # Darken everything not analysed. Amber is the local sector offered to the
    # classifier; green is the only decision corridor; cyan then marks the
    # subset that matches at least one enabled wire-colour band.
    rendered = cv2.convertScaleAbs(crop, alpha=0.33, beta=0)
    rendered[sector != 0] = crop[sector != 0]
    overlay = rendered.copy()
    overlay[sector != 0] = (38, 186, 255)
    rendered = cv2.addWeighted(rendered, 0.80, overlay, 0.20, 0)
    corridor_overlay = rendered.copy()
    corridor_overlay[association_corridor != 0] = (112, 255, 112)
    rendered[association_corridor != 0] = cv2.addWeighted(
        rendered, 0.26, corridor_overlay, 0.74, 0
    )[association_corridor != 0]
    corridor_contours, _hierarchy = cv2.findContours(
        association_corridor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )
    cv2.drawContours(rendered, corridor_contours, -1, (140, 255, 140), 1, cv2.LINE_AA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    classified = np.zeros(sector.shape, dtype=np.uint8)
    excluded = set(excluded_colours)
    for colour in ENDPOINT_WIRE_COLOR_NAMES:
        if colour in excluded:
            continue
        classified |= cv2.bitwise_and(_colour_mask(hsv, colour), sector)
    colour_overlay = rendered.copy()
    colour_overlay[classified != 0] = (255, 255, 0)
    rendered[classified != 0] = cv2.addWeighted(
        rendered, 0.28, colour_overlay, 0.72, 0
    )[classified != 0]
    local_center = (int(round(center[0] - left)), int(round(center[1] - top)))
    arrow_tip = (
        int(round(local_center[0] + outward[0] * outer_radius)),
        int(round(local_center[1] + outward[1] * outer_radius)),
    )
    cv2.circle(rendered, local_center, 5, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.arrowedLine(rendered, local_center, arrow_tip, (0, 220, 255), 1, cv2.LINE_AA, tipLength=0.12)
    return _preview_panel(rendered, f"{label}: AMBER=SECTOR GREEN=DECISION CYAN=HSV")


def _center_preview_crop(frame_bgr: np.ndarray, center: tuple[float, float], radius: int) -> np.ndarray:
    height, width = frame_bgr.shape[:2]
    cx, cy = int(round(center[0])), int(round(center[1]))
    left = max(0, cx - radius)
    top = max(0, cy - radius)
    right = min(width, cx + radius + 1)
    bottom = min(height, cy + radius + 1)
    return frame_bgr[top:bottom, left:right].copy()


def _build_single_endpoint_color_preview(
    frame_bgr: np.ndarray,
    center: tuple[float, float],
    outline: Any,
    pins: Iterable[Any],
    label: str,
    *,
    outward_override: tuple[float, float] | None = None,
    sampling_inner_pitch_scale: float = 3.2,
    sampling_inner_cap_px: float = 46.0,
    entry_fan_depth_px: float | None = None,
    excluded_colours: Iterable[str] = (),
) -> bytes | None:
    """Build a raw-frame plus one exact endpoint HSV sampling preview."""
    panels = (
        _preview_panel(frame_bgr, "RAW CAMERA FRAME"),
        _endpoint_sampling_preview(
            frame_bgr,
            center,
            outline,
            pins,
            label,
            outward_override=outward_override,
            sampling_inner_pitch_scale=sampling_inner_pitch_scale,
            sampling_inner_cap_px=sampling_inner_cap_px,
            entry_fan_depth_px=entry_fan_depth_px,
            excluded_colours=excluded_colours,
        ),
    )
    separator = np.full((340, 12, 3), 12, dtype=np.uint8)
    sheet = np.concatenate((panels[0], separator, panels[1]), axis=1)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return encoded.tobytes() if ok else None


def build_guided_board_endpoint_color_preview(
    frame_bgr: np.ndarray,
    detection: Any,
    step: Any,
) -> bytes | None:
    """Build the saved board endpoint sample without requiring a Sensor pose."""
    board_pin, board = _sample_guided_board_endpoint(
        frame_bgr, detection, step.expected_pin_id,
    )
    board_center = _point(board_pin) if board_pin is not None else None
    if board_center is None:
        return None
    sampling_outline, outward, _direction_source = _board_endpoint_sampling_geometry(
        frame_bgr, detection, board_center,
    )
    saved_outward = board.get("outward_direction")
    if isinstance(saved_outward, list) and len(saved_outward) == 2:
        outward = (float(saved_outward[0]), float(saved_outward[1]))
    board_label = (
        "PI 5"
        if str(getattr(detection, "board_id", "")) == "raspberry-pi-5"
        else "UNO Q"
    )
    return _build_single_endpoint_color_preview(
        frame_bgr,
        board_center,
        sampling_outline,
        getattr(detection, "pins", ()),
        f"{board_label} {getattr(board_pin, 'pin_id', step.expected_pin_id)}",
        outward_override=outward,
        sampling_inner_pitch_scale=_BOARD_ENTRY_INNER_PITCH_SCALE,
        sampling_inner_cap_px=_BOARD_ENTRY_INNER_CAP_PX,
        excluded_colours=(
            _PI5_OVER_PCB_EXCLUDED_COLOURS
            if board.get("direction_source") == "adaptive_360"
            else ()
        ),
    )


def build_guided_component_endpoint_color_preview(
    frame_bgr: np.ndarray,
    component_pose: Any,
    step: Any,
) -> bytes | None:
    """Build the saved Sensor endpoint sample without requiring a UNO Q pose."""
    component_pin, _component = _sample_guided_component_endpoint(
        frame_bgr, component_pose, step.expected_role
    )
    component_center = _point(component_pin) if component_pin is not None else None
    if component_center is None:
        return None
    return _build_single_endpoint_color_preview(
        frame_bgr,
        component_center,
        getattr(component_pose, "outline_px", None),
        getattr(component_pose, "pins", ()),
        f"SENSOR {step.expected_role}",
        outward_override=_component_header_outward(
            getattr(component_pose, "outline_px", None),
            getattr(component_pose, "pins", ()),
        ),
        entry_fan_depth_px=_COMPONENT_CORRIDOR_DEPTH_PX.get(
            getattr(component_pose, "component_id", ""), None,
        ),
    )


def build_guided_endpoint_color_preview(
    frame_bgr: np.ndarray,
    detection: Any,
    component_pose: Any,
    step: Any,
) -> bytes | None:
    """Build a raw-frame plus two highlighted sampling-region JPEG.

    Called only by the manual colour-check endpoint. The image is kept only in
    memory and lets users inspect exactly which pixels informed the local HSV
    result.
    """
    board_pin, board = _sample_guided_board_endpoint(
        frame_bgr, detection, step.expected_pin_id,
    )
    component_pin, _component = _sample_guided_component_endpoint(
        frame_bgr, component_pose, step.expected_role
    )
    board_center = _point(board_pin) if board_pin is not None else None
    component_center = _point(component_pin) if component_pin is not None else None
    if board_center is None or component_center is None:
        return None
    board_outline, board_outward, _direction_source = _board_endpoint_sampling_geometry(
        frame_bgr, detection, board_center,
    )
    saved_outward = board.get("outward_direction")
    if isinstance(saved_outward, list) and len(saved_outward) == 2:
        board_outward = (float(saved_outward[0]), float(saved_outward[1]))
    board_label = (
        "PI 5"
        if str(getattr(detection, "board_id", "")) == "raspberry-pi-5"
        else "UNO Q"
    )
    panels = (
        _preview_panel(frame_bgr, "RAW CAMERA FRAME"),
        _endpoint_sampling_preview(
            frame_bgr,
            board_center,
            board_outline,
            getattr(detection, "pins", ()),
            f"{board_label} {getattr(board_pin, 'pin_id', step.expected_pin_id)}",
            outward_override=board_outward,
            sampling_inner_pitch_scale=_BOARD_ENTRY_INNER_PITCH_SCALE,
            sampling_inner_cap_px=_BOARD_ENTRY_INNER_CAP_PX,
            excluded_colours=(
                _PI5_OVER_PCB_EXCLUDED_COLOURS
                if board.get("direction_source") == "adaptive_360"
                else ()
            ),
        ),
        _endpoint_sampling_preview(
            frame_bgr,
            component_center,
            getattr(component_pose, "outline_px", None),
            getattr(component_pose, "pins", ()),
            f"SENSOR {step.expected_role}",
            outward_override=_component_header_outward(
                getattr(component_pose, "outline_px", None),
                getattr(component_pose, "pins", ()),
            ),
            entry_fan_depth_px=_COMPONENT_CORRIDOR_DEPTH_PX.get(
                getattr(component_pose, "component_id", ""), None,
            ),
        ),
    )
    separator = np.full((340, 12, 3), 12, dtype=np.uint8)
    sheet = np.concatenate((panels[0], separator, panels[1], separator, panels[2]), axis=1)
    ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return encoded.tobytes() if ok else None
