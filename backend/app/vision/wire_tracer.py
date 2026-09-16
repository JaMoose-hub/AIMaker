"""Jumper-wire (dupont wire) detection — M15/M16 prototype.

Design doc: docs/wire-recognition-design.md. Stages A-E:
  A. segment_color()   - HSV mask per conventional wire color
  B. skeletonize_mask() - thin to a 1px skeleton (Guo-Hall, no training)
  C. trace_branches()   - walk the skeleton into candidate branches
  D. snap_endpoint()    - resolve a branch endpoint to a known pin, or
                           honestly report it as floating/ambiguous
  E. trace()            - assemble WireInstance/WireTraceResult

Contract: never raise out of trace()/trace_wires() for a well-formed frame;
an empty/no-match result is an empty list, not an exception. Endpoints are
never guessed - see WireEndpoint's `kind` values.

Validated 2026-07-28 against a real captured frame + a real UNO Q + a real
red dupont wire: a wire end actually plugged into the board snapped to
GND_P1 at 15.8px (within the ~8-15px half-pin-pitch radius derived in the
design doc from this board's real geometry); the other end of the same
wire, draped off-frame and not touching the board, correctly reported as
floating (289.6px from the nearest pin, D0) rather than being misassigned.
SNAP_RADIUS_PX below is set from that real-world number, not a guess.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np

# HSV bands per conventional dupont-wire color. Two ranges for red/orange
# because hue wraps at 0/180 in OpenCV's 8-bit HSV. Tuned for a lit indoor
# desk scene; expect to retune once real captures come in (see debug tool).
WIRE_COLOR_BANDS: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    "red": [
        ((0, 90, 60), (8, 255, 255)),
        ((172, 90, 60), (180, 255, 255)),
    ],
    "orange": [((9, 110, 80), (22, 255, 255))],
    # C920-guided colour sample, 2026-08-11: the user's brown Dupont wire
    # measured around H=7/S=55..105/V=80..145 in the actual raw camera
    # frame. The older saved-frame band capped V at 90, which rejected most
    # of that perfectly visible brown insulation. A live UNO Q GND capture on
    # 2026-08-12 measured H=5/S=118/V=188, so retain the same low-saturation
    # brown family up to V=215. This stays below a clean bright-red wire's
    # usual saturation, while endpoint_color resolves the remaining overlap.
    # Keep this range lower-
    # saturation than orange and narrower in hue than red. Any remaining warm
    # overlap is resolved from the full endpoint component's saturation and
    # support in endpoint_color, rather than by a colour-name tie break.
    "brown": [
        ((4, 35, 45), (18, 135, 215)),
        # A second brown family for the user's current C920 Dupont ribbon:
        # dark red-brown insulation measured H=1/S=216/V=85.  It overlaps
        # the red band by design; endpoint_color resolves that overlap from
        # the full component's brightness rather than forcing a hue-only
        # decision.
        ((0, 130, 35), (4, 255, 105)),
    ],
    # Live C920 capture 2026-08-05: the pale yellow jumper's saturation is
    # much lower than the original synthetic/desk tuning (median S=69;
    # substantial visible sections sit below S=90).  H=21..35/S>=70 keeps
    # the full real wire while excluding the low-saturation gray desk and
    # avoids overlapping the green band.  See the yellow-specific close in
    # segment_color(): one 4 px highlight seam still needs reconnecting.
    "yellow": [((21, 70, 70), (35, 255, 255))],
    "green": [((36, 60, 40), (85, 255, 255))],
    # Saturation floor raised 60->100 on 2026-07-29 after live testing showed
    # why the original floor failed: a real blue dupont wire (sampled ~4,800
    # candidate px via the same "S>50 auto-locate" method used for brown; H
    # median 106, S median 144, V median 140) and a desk-scene false positive
    # - a laptop/monitor bezel edge just outside the board, NOT excluded by
    # board_outline - shared almost the same hue (bezel H median 103) and
    # overlapping value, so hue/value alone can't separate them. Saturation
    # is the real separator: at S>=100, 0% of the bezel's false-positive
    # pixels survive (were 100% at the old S>=60 floor) while 68.5% of the
    # real wire's pixels still do - comfortably above MIN_MASK_PIXELS and
    # enough for an unbroken skeleton branch (verified: 369 skeleton pts,
    # one clean branch, on the real test frame). This is the same
    # low-saturation-neutral-object failure mode documented for "black" in
    # DEFAULT_COLORS (wire_worker.py) - fixed here the same way "brown" was
    # fixed (a saturation floor that excludes near-neutral objects), not
    # previously tried for blue because no real blue wire had been sampled
    # yet. NOT re-verified against the earlier-documented board-rim sliver
    # false positive (board wasn't in frame during this test) - if that
    # resurfaces, it should behave the same way since PCB edges are also
    # lower-saturation than a lit dupont wire, but this is an inference, not
    # a re-measurement.
    "blue": [((86, 100, 40), (128, 255, 255))],
    "purple": [((129, 40, 40), (155, 255, 255))],
    "black": [((0, 0, 0), (180, 90, 60))],
    "gray": [((0, 0, 61), (180, 40, 190))],
    "white": [((0, 0, 191), (180, 40, 255))],
}

MIN_MASK_PIXELS = 40  # below this, treat the color as "not present this frame"
# A few antialiased PCB pixels can leak just beyond the projected outline.
# Require a small but real amount of exterior support before preserving a
# component across the board boundary.
MIN_CROSSING_OUTSIDE_PIXELS = max(8, MIN_MASK_PIXELS // 4)
MIN_BRANCH_LENGTH = 25  # skeleton points; filters small-light-source/JPEG-noise fragments
SNAP_RADIUS_PX = 16.0  # half pin-pitch at typical demo distance; see module docstring
# A female Dupont housing is about 9.9 mm long, or 3.9 times the 2.54 mm
# header pitch. Colour segmentation stops at the black housing, so the
# direction-constrained tail-to-header intersection must permit that physical
# gap. Keep a small tolerance for the insulation/housing transition; unlike
# radial snapping this extrapolation still has to hit one projected row and
# one along-row identity cell.
MAX_TAIL_EXTRAPOLATION_PITCH = 4.25
# A dupont wire is thin EVERYWHERE - no interior mask pixel is far from the
# component's edge. Measured live 2026-07-29 via distance transform: a real
# dupont wire's max half-width was 6.4px at typical demo distance, while the
# two lens-vignette corner blobs that flooded the "brown" band the same day
# (the desk surface darkens toward the frame corners, dropping it into
# brown's low-V range) measured 25.7px and 50.5px - a 4-8x separation. 14.0
# sits >2x above the wire with margin below the smallest observed blob. Same
# fixed-diameter-cylinder prior the color-agnostic design doc's ridge stage
# is built on (docs/color-agnostic-wire-and-guidance-design.md §2.1), applied
# here as a cheap filter instead of a detector.
MAX_WIRE_HALF_WIDTH_PX = 14.0

# Stage A' (M20) hue-agnostic channel constants. Calibrated 2026-07-29
# against two SAVED real frames (a C920 720p desk scene with one real blue
# dupont wire + breadboard + clutter, and an iPhone-mirror overhead crop) -
# NOT yet live-verified against a neutral (gray/white/black) wire, which is
# the M20 acceptance gate. See segment_edge_ridge() for what each does.
RIDGE_WIRE_RADIUS_PX = 6    # structuring-element radius ~ wire half-width
RIDGE_SCORE_MIN = 40        # blackhat/tophat response floor (0-255 scale)


def _board_exclusion_mask(shape: tuple[int, int], board_outline: list[tuple[float, float]] | None) -> np.ndarray | None:
    """Return 255 outside the supplied wire-exclusion polygon.

    The live worker passes a polygon projected at the header-pin height.  The
    function still accepts a plain board outline for standalone tools and
    tests, but no longer performs a pixel-space shrink: that old shrink used
    the z=0 PCB silhouette and introduced a large, view-dependent endpoint
    cut under oblique views.
    """
    if not board_outline or len(board_outline) < 3:
        return None
    poly = np.array(board_outline, dtype=np.float32)
    mask = np.full(shape, 255, dtype=np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 0)
    return mask


def _retain_components_touching_exterior(
    mask: np.ndarray,
    exclusion: np.ndarray | None,
) -> np.ndarray:
    """Remove board-only blobs while preserving wires crossing the board.

    A colored wire can lie on top of the PCB before leaving it. Applying the
    board exclusion pixel-by-pixel cuts that wire into a short fragment. A
    PCB trace or logo, in contrast, is normally contained entirely by the
    board polygon. Keep a component only when at least one pixel is outside
    the polygon; the width filter has already removed broad PCB regions.
    """
    if exclusion is None or cv2.countNonZero(mask) == 0:
        return mask
    outside = exclusion != 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    keep = np.zeros_like(mask)
    for label in range(1, n):
        if int(stats[label, cv2.CC_STAT_AREA]) < MIN_MASK_PIXELS:
            continue
        component = labels == label
        outside_pixels = int(np.count_nonzero(component & outside))
        if outside_pixels >= MIN_CROSSING_OUTSIDE_PIXELS:
            keep[component] = 255
    return keep


def segment_color(
    frame_bgr: np.ndarray,
    color: str,
    board_outline: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """Return a cleaned binary mask (uint8, 0/255) for one wire color.

    board_outline (optional): the board's own polygon in this frame (same
    px space as everything else here). Board-contained color blobs are
    excluded, while a thin component that crosses the polygon boundary is
    retained so a wire lying over the PCB is not cut into a non-traceable
    fragment. This preserves PCB suppression without discarding a real
    wire's body before endpoint snapping.
    """
    bands = WIRE_COLOR_BANDS.get(color)
    if not bands:
        raise ValueError(f"unknown wire color: {color!r}")
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lo, hi in bands:
        mask |= cv2.inRange(hsv, lo, hi)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    if color == "yellow":
        # The real pale-yellow insulation has a narrow specular seam that
        # splits one physical wire into two components after thresholding.
        # A 7 px elliptical close bridges that measured ~4 px seam.  It is
        # deliberately color-specific: applying it to every band would make
        # nearby dark/noisy structures more likely to merge.
        close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, close_kernel, iterations=1
        )
    else:
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = _filter_wide_components(mask)
    return _retain_components_touching_exterior(
        mask, _board_exclusion_mask(mask.shape, board_outline)
    )


def _filter_wide_components(mask: np.ndarray) -> np.ndarray:
    """Drop connected components thicker than a dupont wire can be.

    Applied as the last step of segment_color() so every color band (and
    the M15 debug tool, which calls segment_color() directly) sees the
    same filtered mask. Runs before skeletonization on purpose: thinning
    a 33k-px vignette blob is the single most expensive thing the old
    pipeline did with it, and the result was pure noise anyway. Width is
    max distance-transform value per component (= max inscribed half
    -width); see MAX_WIRE_HALF_WIDTH_PX for the measured numbers.
    """
    if cv2.countNonZero(mask) < MIN_MASK_PIXELS:
        return mask
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < MIN_MASK_PIXELS:
            continue  # skeletonize_mask/trace_branches drop these anyway
        # Distance transform on the component cropped to its bbox (cheap;
        # avoids a full-frame pass per component).
        x, y = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP]
        w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        comp = (labels[y : y + h, x : x + w] == i).astype(np.uint8)
        # Zero-pad so the distance transform always has a background pixel
        # to measure against (a component filling its whole bbox would
        # otherwise have no zero pixel in the crop). Edge-touching
        # components get measured conservatively (visible width only),
        # which only errs toward keeping, never wrongly dropping.
        comp = cv2.copyMakeBorder(comp, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        if float(cv2.distanceTransform(comp * 255, cv2.DIST_L2, 3).max()) > MAX_WIRE_HALF_WIDTH_PX:
            mask[y : y + h, x : x + w][labels[y : y + h, x : x + w] == i] = 0
    return mask


def segment_edge_ridge(
    frame_bgr: np.ndarray,
    board_outline: list[tuple[float, float]] | None = None,
) -> np.ndarray:
    """Stage A' (M20): hue-agnostic wire mask from local-contrast shape alone.

    A dupont wire is a fixed-diameter cylinder: at wire scale it is either
    notably DARKER (blackhat) or notably BRIGHTER (tophat) than its local
    surroundings, regardless of hue - so the union of both morphological
    responses on grayscale is a polarity- and color-agnostic wire signal.
    Deliberately NO Frangi/scikit-image (extra dependency for the same
    outcome - design doc §2.1) and NO background subtraction (structurally
    invalid here: boards get moved and hands enter the frame constantly).

    Differences from segment_color(), each deliberate:
    - grayscale, never HSV: hue is exactly what this channel must not need.
    - CLOSE runs 1 iteration (color uses 2): measured 2026-07-29 on a real
      breadboard scene, 2 iterations welded the breadboard's dark hole rows
      into wire-like streaks; at 1 iteration the holes stay discrete dots
      and get dropped by MIN_MASK_PIXELS/MIN_BRANCH_LENGTH. A real wire's
      response is continuous so it survives the weaker closing.
    - output shape/dtype identical to segment_color() so Stages B-E are
      reused verbatim with zero new architecture.

    Honest residual (design doc §2.4): a wire whose luminance matches the
    desk (e.g. black wire on black mat) produces no contrast signal - this
    channel narrows the color gap, it does not close it. Same measured
    example: today's blue wire on the gray desk was only partially masked
    (blue~gray in luminance) - it is the HSV blue band's job there; this
    channel exists for wires no color band covers.
    """
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    d = RIDGE_WIRE_RADIUS_PX * 2 + 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))
    score = cv2.max(
        cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, k),
        cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, k),
    )
    mask = np.where(score >= RIDGE_SCORE_MIN, 255, 0).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = _filter_wide_components(mask)
    return _retain_components_touching_exterior(
        mask, _board_exclusion_mask(mask.shape, board_outline)
    )


# Sentinel color for Stage A' branches: honest "we don't know the hue", not
# a guess. Serialized as-is over WS; the frontend's color->CSS-var lookup
# already falls back to a neutral style for unknown names.
COLOR_UNKNOWN = "unknown"


def skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    """Thin a binary mask to a 1px skeleton (Guo-Hall, no training)."""
    if cv2.countNonZero(mask) < MIN_MASK_PIXELS:
        return np.zeros_like(mask)
    return cv2.ximgproc.thinning(mask, thinningType=cv2.ximgproc.THINNING_GUOHALL)


@dataclass
class SkeletonBranch:
    color: str
    points: list[tuple[int, int]] = field(default_factory=list)  # (x, y), path order
    # A degree>=3 skeleton component has no unique continuation through the
    # junction from a monocular mask. Keep this evidence so downstream code
    # can expose the result as ambiguous instead of guessing a path.
    junction_count: int = 0


def _neighbor_offsets() -> list[tuple[int, int]]:
    return [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def trace_branches(skeleton: np.ndarray, color: str) -> list[SkeletonBranch]:
    """Walk the skeleton's connected components, returning one branch per
    component with terminal-node endpoints ordered along the path.

    This is a deliberately simple degree-based walk (Stage C of the design
    doc): terminal pixels (degree 1) are candidate wire endpoints; junction
    pixels (degree >= 3) are not resolved here (min-curvature continuation
    is a later milestone) - a component containing a junction is still
    returned as one branch (points may not be in a single unambiguous
    order past the junction), so downstream code must not assume M15's
    branches are junction-free.
    """
    ys, xs = np.nonzero(skeleton)
    if len(xs) == 0:
        return []
    pts = set(zip(xs.tolist(), ys.tolist()))

    def degree(p: tuple[int, int]) -> int:
        x, y = p
        return sum((x + dx, y + dy) in pts for dx, dy in _neighbor_offsets())

    junctions = {p for p in pts if degree(p) >= 3}

    visited: set[tuple[int, int]] = set()
    branches: list[SkeletonBranch] = []

    terminals = [p for p in pts if degree(p) == 1]
    starts = terminals if terminals else list(pts)

    for start in starts:
        if start in visited:
            continue
        path = [start]
        visited.add(start)
        current = start
        while True:
            x, y = current
            nxt = None
            for dx, dy in _neighbor_offsets():
                cand = (x + dx, y + dy)
                if cand in pts and cand not in visited:
                    nxt = cand
                    break
            if nxt is None:
                break
            visited.add(nxt)
            path.append(nxt)
            current = nxt
        if len(path) >= MIN_BRANCH_LENGTH:
            branches.append(SkeletonBranch(
                color=color,
                points=path,
                junction_count=sum(1 for p in path if p in junctions),
            ))
        else:
            visited.update(path)  # drop short fragments (LED reflections, JPEG noise), don't leave them "remaining"

    remaining = pts - visited
    if len(remaining) >= MIN_BRANCH_LENGTH:
        branches.append(SkeletonBranch(
            color=color,
            points=list(remaining),
            junction_count=sum(1 for p in remaining if p in junctions),
        ))

    return branches


def trace_wires(
    frame_bgr: np.ndarray,
    colors: list[str] | None = None,
    board_outline: list[tuple[float, float]] | None = None,
    include_edge_agnostic: bool = False,
) -> dict[str, list[SkeletonBranch]]:
    """Run Stages A-C for each requested color (+ optionally the hue-agnostic
    Stage A' channel under the COLOR_UNKNOWN key). Returns {color: branches}."""
    colors = colors or list(WIRE_COLOR_BANDS.keys())
    result: dict[str, list[SkeletonBranch]] = {}
    for color in colors:
        mask = segment_color(frame_bgr, color, board_outline)
        skeleton = skeletonize_mask(mask)
        branches = trace_branches(skeleton, color) if cv2.countNonZero(skeleton) else []
        if branches:
            result[color] = branches
    if include_edge_agnostic:
        mask = segment_edge_ridge(frame_bgr, board_outline)
        skeleton = skeletonize_mask(mask)
        branches = trace_branches(skeleton, COLOR_UNKNOWN) if cv2.countNonZero(skeleton) else []
        if branches:
            result[COLOR_UNKNOWN] = branches
    return result


# ---------------------------------------------------------------------------
# Stage D — endpoint snap-to-pin. Never guesses: an endpoint is "pin" only
# when exactly one known pin is within SNAP_RADIUS_PX; otherwise "floating"
# (nothing close enough) or "ambiguous_tie" (2+ equally-close candidates).
# ---------------------------------------------------------------------------

EndpointKind = Literal["pin", "floating", "ambiguous_tie"]
AttachmentKind = Literal["inserted", "resting", "unknown"]


@dataclass
class WireEndpoint:
    kind: EndpointKind
    px: tuple[float, float]
    pin_id: str | None = None
    candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    # Additive diagnostics for tuning real-camera captures.  These are kept
    # separate from `confidence`: distance/margin are measurable geometry,
    # while confidence also includes the board pin detector's confidence.
    distance_px: float | None = None
    margin_px: float | None = None
    # Name used by the accuracy harness and API contract.  margin_px remains
    # as a backwards-compatible alias for early diagnostic consumers.
    snap_margin_px: float | None = None


@dataclass
class WireInstance:
    wire_id: int
    color: str                      # HSV band name, or COLOR_UNKNOWN for ridge-only
    path_px: list[tuple[float, float]]
    endpoint_a: WireEndpoint
    endpoint_b: WireEndpoint
    confidence: float
    ambiguous: bool
    crossed_junction_count: int = 0
    # Which Stage A channels produced this instance: ["color"], ["edge"], or
    # ["color","edge"] after cross-method merge (M21). Additive field with a
    # default - existing callers/serializers unaffected.
    detection_methods: list[str] = field(default_factory=lambda: ["color"])
    # A single monocular view cannot prove insertion depth.  Live traces use
    # "unknown" until a future multi-view/motion cue proves it; None keeps
    # old injected fixtures backwards-compatible.
    attachment: AttachmentKind | None = None
    attachment_confidence: float = 0.0


@dataclass
class WireTraceResult:
    frame_id: int
    ts_ms: float
    board_tracking: Literal["searching", "locked", "stale"]
    wires: list[WireInstance] = field(default_factory=list)
    # Actual source-frame size.  Kept optional so fixtures and older callers
    # remain compatible; trace() fills it for live results.
    video_size: tuple[int, int] | None = None
    # Scale sanity telemetry: all values are source-frame geometry, never UI
    # pixels.  Optional to preserve older fixtures and injected callers.
    geometry: dict[str, float] | None = None
    # Canonical source-frame positions for resolved pins.  A resolved
    # WireEndpoint keeps its observed skeleton terminal in ``px`` internally
    # because attachment classification needs that raw motion, but API
    # consumers need the live projected pin position for a connection
    # coordinate.  Optional keeps legacy/injected fixtures backwards
    # compatible.
    pin_positions: dict[str, tuple[float, float]] | None = None
    # A runtime safety gate may intentionally publish no wires even while the
    # board pose is locked. Keep the reason explicit so an empty list is not
    # confused with a clean, wire-free scene.
    suppressed_reason: str | None = None


def _row_lattice(pins: list) -> dict[str, tuple[tuple[float, float], float]]:
    """Build projected row direction and pitch from pin metadata.

    A row needs two or more indexed pins. Callers with metadata-free pins
    (debug tools and older tests) transparently use the legacy radial rule.
    """
    rows: dict[str, list[object]] = {}
    for pin in pins:
        header = getattr(pin, "header", None)
        index = getattr(pin, "index", None)
        if header is not None and index is not None:
            rows.setdefault(str(header), []).append(pin)

    result: dict[str, tuple[tuple[float, float], float]] = {}
    for header, row in rows.items():
        row = sorted(row, key=lambda p: int(getattr(p, "index")))
        if len(row) < 2:
            continue
        vectors: list[np.ndarray] = []
        pitches: list[float] = []
        for i, pin in enumerate(row):
            neighbours = []
            if i > 0:
                neighbours.append(row[i - 1])
            if i + 1 < len(row):
                neighbours.append(row[i + 1])
            if not neighbours:
                continue
            if len(neighbours) == 2:
                vec = np.array([neighbours[1].x - neighbours[0].x,
                                neighbours[1].y - neighbours[0].y],
                               dtype=np.float64) * 0.5
            else:
                # Keep the direction consistent with increasing row index.
                # For a two-pin visible row the old expression pointed right
                # for the first pin and left for the second, so the mean
                # direction became (0, 0) and disabled the lattice gate.
                if i + 1 < len(row):
                    neighbour = row[i + 1]
                    vec = np.array([neighbour.x - pin.x,
                                    neighbour.y - pin.y],
                                   dtype=np.float64)
                else:
                    previous = row[i - 1]
                    vec = np.array([pin.x - previous.x,
                                    pin.y - previous.y],
                                   dtype=np.float64)
            length = float(np.linalg.norm(vec))
            if length > 1e-6:
                vectors.append(vec / length)
            for neighbour in neighbours:
                d = math.hypot(neighbour.x - pin.x, neighbour.y - pin.y)
                if d > 1e-6:
                    pitches.append(d)
        if vectors and pitches:
            u = np.mean(np.vstack(vectors), axis=0)
            u /= max(float(np.linalg.norm(u)), 1e-9)
            result[header] = ((float(u[0]), float(u[1])),
                              float(np.median(np.asarray(pitches))))
    return result


def _row_local_pitches(pins: list) -> dict[str, float]:
    """Return the nearest projected neighbour spacing for each pin.

    A single row-level median is a useful fallback, but perspective can make
    the projected pitch change along a header.  Using the nearest local
    spacing keeps the along-row identity cell proportional to the pin being
    snapped.  Taking the *minimum* adjacent spacing is deliberate: a large
    physical gap (for example between the UNO digital-header groups) must not
    widen the cell and make an endpoint in that gap look connected.
    """
    rows: dict[str, list[object]] = {}
    for pin in pins:
        header = getattr(pin, "header", None)
        index = getattr(pin, "index", None)
        if header is not None and index is not None:
            rows.setdefault(str(header), []).append(pin)

    result: dict[str, float] = {}
    for row in rows.values():
        ordered = sorted(row, key=lambda p: int(getattr(p, "index")))
        for i, pin in enumerate(ordered):
            neighbours = []
            if i > 0:
                neighbours.append(ordered[i - 1])
            if i + 1 < len(ordered):
                neighbours.append(ordered[i + 1])
            distances = [
                math.hypot(float(neighbour.x) - float(pin.x),
                           float(neighbour.y) - float(pin.y))
                for neighbour in neighbours
            ]
            distances = [distance for distance in distances if distance > 1e-6]
            if distances:
                result[str(pin.pin_id)] = float(min(distances))
    return result


def snap_endpoint(px: tuple[float, float], pins: list,
                  radius_px: float = SNAP_RADIUS_PX,
                  *, pitch_px: float = 0.0) -> WireEndpoint:
    """Resolve one branch endpoint against projected pin positions.

    When header/index metadata is available, identity is decided in the
    local header lattice: a narrow along-row window prevents a neighbouring
    pin from winning, while a wider cross-row window preserves recall for the
    known perpendicular mask/skeleton error. Metadata-free callers retain the
    old radial behaviour.
    """
    ex, ey = px
    lattice = _row_lattice(pins)
    local_pitches = _row_local_pitches(pins)
    # (ranking score, pixel distance, pin id, pin confidence)
    within: list[tuple[float, float, str, float]] = []
    for p in pins:
        if not getattr(p, "visible", True):
            continue
        dxy = np.array([ex - p.x, ey - p.y], dtype=np.float64)
        row = lattice.get(str(getattr(p, "header", None)))
        if row is not None:
            (ux, uy), pitch = row
            cell_pitch = local_pitches.get(str(p.pin_id), pitch)
            along = abs(float(dxy[0] * ux + dxy[1] * uy))
            cross = abs(float(dxy[0] * (-uy) + dxy[1] * ux))
            # Pin identity is decided along the row. Cross-row tolerance is
            # intentionally wider because the mask/skeleton cut error is
            # predominantly perpendicular to the header.
            along_limit = max(0.5 * cell_pitch, 1.0)
            cross_limit = max(1.5 * cell_pitch, 1.0)
            if along > along_limit or cross > cross_limit:
                continue
            score = (along / along_limit) * 0.7 + (cross / cross_limit) * 0.3
            within.append((score, math.hypot(*dxy), p.pin_id, p.confidence))
        else:
            d = math.hypot(*dxy)
            if d <= radius_px:
                within.append((d / max(radius_px, 1e-6), d,
                               p.pin_id, p.confidence))
    if not within:
        nearest = [
            math.hypot(ex - p.x, ey - p.y)
            for p in pins
            if getattr(p, "visible", True)
        ]
        return WireEndpoint(
            kind="floating",
            px=px,
            confidence=0.0,
            distance_px=min(nearest) if nearest else None,
        )
    within.sort(key=lambda t: (t[0], t[1], t[2]))
    nearest_distance = within[0][1]
    margin = within[1][1] - nearest_distance if len(within) > 1 else None
    # A few pixels of margin is deliberate: deciding between neighbouring
    # pins from floating-point noise is exactly the dangerous failure mode.
    tie_tol = max(2.0, 0.20 * pitch_px) if pitch_px > 0 else max(2.0, 0.20 * radius_px)
    if len(within) > 1 and abs(within[1][1] - within[0][1]) <= tie_tol:
        candidates = [item[2] for item in within
                      if abs(item[1] - within[0][1]) <= tie_tol]
        if len(candidates) > 1:
            return WireEndpoint(kind="ambiguous_tie", px=px,
                                 candidates=candidates,
                                 distance_px=nearest_distance,
                                 margin_px=margin,
                                 snap_margin_px=margin)
    score, _dist, pin_id, pin_conf = within[0]
    endpoint_confidence = pin_conf * max(0.0, 1.0 - min(score, 1.0))
    return WireEndpoint(kind="pin", px=px, pin_id=pin_id,
                        confidence=endpoint_confidence,
                        distance_px=nearest_distance,
                        margin_px=margin,
                        snap_margin_px=margin)


def _median_adjacent_pin_spacing(pins: list) -> float:
    """Return a robust projected pitch in source pixels.

    Pin rows can contain intentional gaps.  The first median rejects those
    gaps with a 1.35x cutoff, then the median is recomputed.  Returning 0 is
    an honest fallback for metadata-free debug callers.
    """
    rows: dict[tuple[str, int], list[object]] = {}
    for pin in pins:
        header = getattr(pin, "header", None)
        index = getattr(pin, "index", None)
        if header is not None and index is not None:
            # Pi J8 physical numbers alternate between two rows. Compare
            # 1->3->5 and 2->4->6, never the across-row 1->2 distance.
            parity = int(index) % 2 if header == "J8" else 0
            rows.setdefault((str(header), parity), []).append(pin)
    distances: list[float] = []
    for row in rows.values():
        ordered = sorted(row, key=lambda p: int(getattr(p, "index")))
        distances.extend(
            math.hypot(ordered[i + 1].x - ordered[i].x,
                       ordered[i + 1].y - ordered[i].y)
            for i in range(len(ordered) - 1)
            if math.hypot(ordered[i + 1].x - ordered[i].x,
                          ordered[i + 1].y - ordered[i].y) > 1e-6
        )
    if not distances:
        return 0.0
    first = float(np.median(np.asarray(distances, dtype=np.float64)))
    filtered = [d for d in distances if d <= 1.35 * first]
    return float(np.median(np.asarray(filtered or distances, dtype=np.float64)))


def projected_pin_pitch(pins: list) -> float:
    """Return the robust adjacent-header pitch in source-frame pixels.

    This small public wrapper lets the detection stream expose the same scale
    measurement as the wire stream without duplicating lattice math in the
    worker layer.  Metadata-free fixtures honestly return 0.
    """
    return _median_adjacent_pin_spacing(pins)


def _refine_endpoint_to_row(path: list[tuple[float, float]], pins: list,
                            *, at_start: bool) -> tuple[float, float] | None:
    """Extrapolate a skeleton tail to a projected header row.

    Color exclusion and skeletonization can stop several pixels before the
    physical pin.  The last tail of a real wire is locally straight, so its
    fitted line can be intersected with the known projected header row.  The
    result is only accepted when it is near a row and near its pin span;
    otherwise callers fall back to the raw skeleton endpoint.
    """
    if len(path) < 5:
        return None
    lattice = _row_lattice(pins)
    if not lattice:
        return None
    tail = path[:min(16, len(path))] if at_start else path[-min(16, len(path)):]
    if not at_start:
        tail = list(reversed(tail))
    pts = np.asarray(tail, dtype=np.float32).reshape(-1, 1, 2)
    try:
        line = cv2.fitLine(pts, cv2.DIST_L2, 0, 0.01, 0.01)
    except cv2.error:
        return None
    dx, dy, x0, y0 = (float(v) for v in line.reshape(4))
    wire_dir = np.array([dx, dy], dtype=np.float64)
    wire_norm = float(np.linalg.norm(wire_dir))
    if wire_norm <= 1e-6:
        return None
    wire_dir /= wire_norm
    # cv2.fitLine may choose either sign for the same undirected line.  Orient
    # it from the observed terminal into the wire so the extrapolation check
    # below has a physical meaning.
    tail_direction = np.asarray(tail[-1], dtype=np.float64) - np.asarray(
        tail[0], dtype=np.float64)
    if float(np.dot(wire_dir, tail_direction)) < 0.0:
        wire_dir = -wire_dir
    raw = np.asarray(path[0] if at_start else path[-1], dtype=np.float64)

    rows: dict[str, list[object]] = {}
    for pin in pins:
        header = getattr(pin, "header", None)
        if header is not None and getattr(pin, "index", None) is not None:
            rows.setdefault(str(header), []).append(pin)

    best: tuple[float, tuple[float, float]] | None = None
    for header, row_pins in rows.items():
        row = lattice.get(header)
        if row is None:
            continue
        (ux, uy), pitch = row
        row_dir = np.array([ux, uy], dtype=np.float64)
        row_base = np.array([row_pins[0].x, row_pins[0].y], dtype=np.float64)
        # Solve raw + t*wire_dir = row_base + s*row_dir.
        cross = wire_dir[0] * row_dir[1] - wire_dir[1] * row_dir[0]
        if abs(float(cross)) < 1e-3:
            continue
        rhs = row_base - raw
        t = (rhs[0] * row_dir[1] - rhs[1] * row_dir[0]) / cross
        # The path starts at the observed terminal and proceeds into the
        # wire.  A missing tail may be extrapolated only behind that terminal
        # (opposite the fitted path direction).  Accepting an intersection
        # in front of it can turn a line that merely crosses the header row
        # into a falsely plugged endpoint.
        if t >= -1.0:
            continue
        intersection = raw + t * wire_dir
        row_min = min(math.hypot(p.x - row_base[0], p.y - row_base[1])
                      for p in row_pins)
        row_max = max(math.hypot(p.x - row_base[0], p.y - row_base[1])
                      for p in row_pins)
        along = float(np.dot(intersection - row_base, row_dir))
        if along < row_min - 1.5 * pitch or along > row_max + 1.5 * pitch:
            continue
        distance = float(np.linalg.norm(intersection - raw))
        if distance > max(MAX_TAIL_EXTRAPOLATION_PITCH * pitch, 12.0):
            continue
        if best is None or distance < best[0]:
            best = (distance, (float(intersection[0]), float(intersection[1])))
    return best[1] if best is not None else None


def _snap_path_endpoint(path: list[tuple[float, float]], pins: list,
                        *, at_start: bool, radius_px: float = SNAP_RADIUS_PX,
                        pitch_px: float = 0.0) -> WireEndpoint:
    raw = path[0] if at_start else path[-1]
    refined = _refine_endpoint_to_row(path, pins, at_start=at_start)
    if refined is not None:
        candidate = snap_endpoint(refined, pins, radius_px, pitch_px=pitch_px)
        if candidate.kind in ("pin", "ambiguous_tie"):
            # Keep the original skeleton px for an ambiguous/floating marker;
            # a resolved pin is rendered from its live projected position.
            return candidate
    return snap_endpoint(raw, pins, radius_px, pitch_px=pitch_px)


def _merge_cross_method_duplicates(wires: list[WireInstance]) -> list[WireInstance]:
    """Stage E extension (M21). Merge a color-band WireInstance with an
    edge-agnostic one iff BOTH endpoints resolved to kind=="pin" and the
    unordered pin pair is identical - the output space is already discrete
    (pin-id pairs), so dedup is a key comparison, not geometric IoU.

    Never merges anything involving floating/ambiguous_tie: a partial
    resolve from one method is not evidence the other method's full resolve
    is wrong, but it's also not proof they're the same wire. Two channels
    agreeing on the same pin pair is MORE trustworthy than either alone -
    confidence gets a small bump, capped at 1.0. Conflicts (same physical
    endpoint, different pin per channel) are deliberately NOT merged - both
    instances stay visible rather than silently picking a winner.

    Known limitation (design doc §2.4): two genuinely distinct physical
    wires plugged into the same pin pair merge into one instance.
    """
    by_key: dict[frozenset[str], list[WireInstance]] = {}
    passthrough: list[WireInstance] = []
    for w in wires:
        if (not w.ambiguous and w.crossed_junction_count == 0
                and w.endpoint_a.kind == "pin"
                and w.endpoint_b.kind == "pin"):
            key = frozenset({w.endpoint_a.pin_id, w.endpoint_b.pin_id})
            by_key.setdefault(key, []).append(w)
        else:
            passthrough.append(w)
    merged: list[WireInstance] = []
    for group in by_key.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        colored = [w for w in group if w.color != COLOR_UNKNOWN]
        base = colored[0] if colored else group[0]
        base.confidence = min(1.0, max(w.confidence for w in group) + 0.1)
        base.detection_methods = sorted({m for w in group for m in w.detection_methods})
        merged.append(base)
    return merged + passthrough


def trace(
    frame_bgr: np.ndarray,
    pins: list,
    frame_id: int,
    ts_ms: float,
    board_tracking: Literal["searching", "locked", "stale"],
    colors: list[str] | None = None,
    board_outline: list[tuple[float, float]] | None = None,
    include_edge_agnostic: bool = False,
    include_floating: bool = False,
) -> WireTraceResult:
    """Full Stage A-E pipeline for one frame. Never raises for a well-formed
    frame; returns an empty `wires` list when tracking=="searching" (no
    known pin candidates to snap against) or nothing is detected.

    board_outline: the board's own outline_px for this frame (same as
    DetectionResult.outline_px) - passed through to segment_color() so the
    board's own surface color never gets mistaken for a wire. Optional
    because callers with no outline (e.g. a test fixture) still get
    correct, just less-filtered, behavior.
    """
    video_size = (int(frame_bgr.shape[1]), int(frame_bgr.shape[0]))
    pitch_px = _median_adjacent_pin_spacing(pins)
    radius_px = float(np.clip(1.55 * pitch_px, 8.0, 26.0)) if pitch_px > 0 else SNAP_RADIUS_PX
    geometry = None
    if pitch_px > 0:
        geometry = {
            "pitch_px": round(pitch_px, 3),
            "px_per_mm": round(pitch_px / 2.54, 4),
            "snap_radius_px": round(radius_px, 3),
            "snap_radius_over_pitch": round(radius_px / pitch_px, 4),
        }
    if board_tracking == "searching" or not pins:
        return WireTraceResult(frame_id=frame_id, ts_ms=ts_ms,
                               board_tracking=board_tracking, wires=[],
                               video_size=video_size, geometry=geometry,
                               pin_positions={
                                   str(pin.pin_id): (float(pin.x), float(pin.y))
                                   for pin in pins
                                   if getattr(pin, "visible", True)
                               })

    branches_by_color = trace_wires(frame_bgr, colors, board_outline, include_edge_agnostic)
    wires: list[WireInstance] = []
    wire_id = 0
    for color, branches in branches_by_color.items():
        for branch in branches:
            path = [(float(x), float(y)) for x, y in branch.points]
            endpoint_a = _snap_path_endpoint(path, pins, at_start=True,
                                              radius_px=radius_px,
                                              pitch_px=pitch_px)
            endpoint_b = _snap_path_endpoint(path, pins, at_start=False,
                                              radius_px=radius_px,
                                              pitch_px=pitch_px)
            if (
                not include_floating
                and endpoint_a.kind == "floating"
                and endpoint_b.kind == "floating"
            ):
                # Neither end touches the board's pin space. This system
                # exists to answer "what is wired to this board" - a
                # detection that never contacts any pin carries no
                # actionable signal for that question, and in live testing
                # (2026-07-29) every false positive that survived to the
                # overlay was exactly this class (vignette-corner streaks
                # with both ends floating at the frame edge). Dropping
                # them is scope filtering, not guessing: a real wire lying
                # on the desk simply isn't reported until one end reaches
                # a pin ("ambiguous_tie" still passes - that's evidence
                # AT the pins, only conflicted). The M15 debug tool still
                # shows raw branches for band tuning.
                continue
            confidences = [c for c in (endpoint_a.confidence, endpoint_b.confidence) if c > 0]
            confidence = sum(confidences) / len(confidences) if confidences else 0.2
            wires.append(
                WireInstance(
                    wire_id=wire_id,
                    color=color,
                    path_px=path,
                    endpoint_a=endpoint_a,
                    endpoint_b=endpoint_b,
                    confidence=confidence,
                    ambiguous=bool(branch.junction_count),
                    crossed_junction_count=int(branch.junction_count),
                    detection_methods=["edge"] if color == COLOR_UNKNOWN else ["color"],
                    attachment="unknown",
                    attachment_confidence=0.0,
                )
            )
            wire_id += 1
    wires = _merge_cross_method_duplicates(wires)
    return WireTraceResult(frame_id=frame_id, ts_ms=ts_ms,
                           board_tracking=board_tracking, wires=wires,
                           video_size=video_size, geometry=geometry,
                           pin_positions={
                               str(pin.pin_id): (float(pin.x), float(pin.y))
                               for pin in pins
                               if getattr(pin, "visible", True)
                           })
