"""Temporal stabilization for already-detected wire candidates.

This module deliberately does not discover wires.  It only stabilizes the
discrete endpoint identities produced by ``wire_tracer``.  A short spatial
match keeps a wire's track when one frame assigns a nearby pin differently;
the endpoint voter then publishes a pin only when the recent evidence has a
clear winner.  Conflicted evidence becomes ``ambiguous_tie`` instead of being
converted into a confident wrong pin.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field, replace
import math

from app.vision.wire_tracer import WireEndpoint, WireInstance, WireTraceResult

__all__ = ["WireTraceStabilizer", "AttachmentClassifier"]


@dataclass
class _WireTrack:
    track_id: int
    last: WireInstance
    history: deque[WireInstance] = field(default_factory=lambda: deque(maxlen=6))
    seen: deque[bool] = field(default_factory=lambda: deque(maxlen=3))
    missing: int = 0

    def observe(self, wire: WireInstance) -> None:
        self.last = wire
        self.history.append(wire)
        self.seen.append(True)
        self.missing = 0

    def miss(self) -> None:
        self.seen.append(False)
        self.missing += 1


@dataclass
class _AttachmentTrack:
    """Motion evidence for one resolved wire endpoint.

    ``endpoint_px`` is deliberately the raw skeleton endpoint, not the
    refined/snap point.  The latter is calculated from the *current* pin
    lattice and would make a resting ferrule appear to move with the board.
    """

    pin_id: str
    endpoint_px: tuple[float, float]
    pin_px: tuple[float, float]
    votes: deque[str] = field(default_factory=lambda: deque(maxlen=4))
    qualities: deque[float] = field(default_factory=lambda: deque(maxlen=4))


def _path_endpoints(wire: WireInstance) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if not wire.path_px:
        return None
    a = wire.path_px[0]
    b = wire.path_px[-1]
    return (a, b)


def _wire_distance(a: WireInstance, b: WireInstance) -> float:
    """Endpoint geometry distance used only for track association."""
    if a.color != b.color and a.color != "unknown" and b.color != "unknown":
        return float("inf")
    ea = _path_endpoints(a)
    eb = _path_endpoints(b)
    if ea is None or eb is None:
        return float("inf")

    def d(p: tuple[float, float], q: tuple[float, float]) -> float:
        return math.hypot(p[0] - q[0], p[1] - q[1])

    same = d(ea[0], eb[0]) + d(ea[1], eb[1])
    reverse = d(ea[0], eb[1]) + d(ea[1], eb[0])
    return min(same, reverse) * 0.5


def _orient_like_reference(reference: WireInstance,
                           wire: WireInstance) -> WireInstance:
    """Keep endpoint A/B stable when skeleton traversal reverses direction.

    ``_find_track`` intentionally accepts either path orientation, but the
    endpoint voter is side-specific. Normalize the incoming observation to
    the previous track orientation before appending it to history; otherwise
    a harmless path reversal looks like both pins swapped in one frame.
    """
    ref_ends = _path_endpoints(reference)
    wire_ends = _path_endpoints(wire)
    if ref_ends is None or wire_ends is None:
        return wire

    def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
        return math.hypot(float(a[0]) - float(b[0]),
                          float(a[1]) - float(b[1]))

    same = distance(ref_ends[0], wire_ends[0]) + distance(ref_ends[1], wire_ends[1])
    reverse = distance(ref_ends[0], wire_ends[1]) + distance(ref_ends[1], wire_ends[0])
    if reverse < same:
        return replace(
            wire,
            path_px=list(reversed(wire.path_px)),
            endpoint_a=wire.endpoint_b,
            endpoint_b=wire.endpoint_a,
        )
    return wire


def _resolved_pin_ids(wire: WireInstance) -> frozenset[str]:
    """Return resolved endpoint identities for track association.

    Geometry alone is too permissive when two same-colour wires cross. A
    matching pin pair is stronger evidence than a short pixel distance, so
    the stabilizer prefers identity before falling back to path geometry.
    Ambiguous and floating endpoints intentionally contribute nothing.
    """
    return frozenset(
        ep.pin_id
        for ep in (wire.endpoint_a, wire.endpoint_b)
        if ep.kind == "pin" and ep.pin_id
    )


def _endpoint_key(endpoint: WireEndpoint) -> tuple[str, object]:
    if endpoint.kind == "pin":
        return ("pin", endpoint.pin_id or "")
    if endpoint.kind == "ambiguous_tie":
        return ("ambiguous", tuple(sorted(endpoint.candidates)))
    return ("floating", "")


def _stable_endpoint(history: list[WireInstance], side: str,
                     min_share: float) -> tuple[WireEndpoint, float]:
    endpoints = [getattr(w, side) for w in history]
    keys = [_endpoint_key(ep) for ep in endpoints]
    counts = Counter(keys)
    winner, count = counts.most_common(1)[0]
    share = count / max(len(keys), 1)

    # A current ambiguous observation is fresh conflicting evidence. Do not
    # let an older majority pin hide it for one render tick; that would turn
    # an endpoint sitting between pins into a falsely resolved connection.
    if endpoints[-1].kind == "ambiguous_tie":
        return replace(endpoints[-1], pin_id=None, confidence=0.0), share

    # A current floating observation is also fresh negative evidence. Do not
    # keep publishing an old pin while the wire terminal has disappeared or
    # become occluded; the conservative result is floating until the pin is
    # observed again and wins a new vote window.
    if endpoints[-1].kind == "floating":
        return replace(endpoints[-1], pin_id=None, confidence=0.0), share

    # Mixed pin identities are unsafe even if no exact tie exists.  The
    # candidates are the observed concrete pins; floating is not silently
    # converted into a pin.
    if share < min_share:
        candidates = sorted({str(key[1]) for key in keys if key[0] == "pin"})
        if len(candidates) >= 2:
            latest = endpoints[-1]
            return replace(latest, kind="ambiguous_tie", pin_id=None,
                           candidates=candidates, confidence=0.0), share
        return replace(endpoints[-1], confidence=0.0), share

    for endpoint in reversed(endpoints):
        if _endpoint_key(endpoint) == winner:
            return replace(endpoint), share
    return replace(endpoints[-1]), share


class WireTraceStabilizer:
    """M-of-N wire confirmation plus endpoint voting.

    A new wire needs two observations in the latest three ticks before it is
    published.  A missing observation does not immediately destroy its track,
    but it is not rendered while missing; this prevents unplugged wires from
    remaining falsely visible during a coasting window.  Tracks are retained
    briefly only so a single segmentation miss can reconnect to the same
    history.
    """

    def __init__(self, *, confirm_hits: int = 2,
                 confirm_window: int = 3,
                 vote_window: int = 6,
                 vote_share: float = 0.70,
                 match_radius_px: float = 48.0,
                 match_radius_over_pitch: float = 4.75,
                 min_match_radius_px: float = 24.0,
                 max_match_radius_px: float = 96.0,
                 coast_ticks: int = 3) -> None:
        self.confirm_hits = int(confirm_hits)
        self.confirm_window = int(confirm_window)
        self.vote_window = int(vote_window)
        self.vote_share = float(vote_share)
        self.match_radius_px = float(match_radius_px)
        self.match_radius_over_pitch = max(0.0, float(match_radius_over_pitch))
        self.min_match_radius_px = max(1.0, float(min_match_radius_px))
        self.max_match_radius_px = max(self.min_match_radius_px,
                                       float(max_match_radius_px))
        self.coast_ticks = int(coast_ticks)
        self._tracks: list[_WireTrack] = []
        self._next_track_id = 0

    def _new_track(self, wire: WireInstance) -> _WireTrack:
        """Create a track whose evidence buffers honor the configured windows."""
        return _WireTrack(
            track_id=self._next_track_id,
            last=wire,
            history=deque(maxlen=max(1, self.vote_window)),
            seen=deque(maxlen=max(1, self.confirm_window)),
        )

    def reset(self) -> None:
        self._tracks.clear()

    def _effective_match_radius(self, pitch_px: float) -> float:
        if pitch_px > 0.0 and self.match_radius_over_pitch > 0.0:
            return min(
                self.max_match_radius_px,
                max(self.min_match_radius_px,
                    self.match_radius_over_pitch * pitch_px),
            )
        return self.match_radius_px

    def _find_track(self, wire: WireInstance, used: set[int],
                    match_radius_px: float | None = None) -> _WireTrack | None:
        current_pins = _resolved_pin_ids(wire)
        if current_pins:
            identity_matches: list[tuple[float, _WireTrack]] = []
            for track in self._tracks:
                if track.track_id in used:
                    continue
                if (track.last.color != wire.color
                        and track.last.color != "unknown"
                        and wire.color != "unknown"):
                    continue
                previous_pins = _resolved_pin_ids(track.last)
                if previous_pins and previous_pins == current_pins:
                    identity_matches.append((_wire_distance(track.last, wire), track))
            if identity_matches:
                identity_matches.sort(key=lambda item: (item[0], item[1].track_id))
                return identity_matches[0][1]

        best: tuple[float, _WireTrack] | None = None
        for track in self._tracks:
            if track.track_id in used:
                continue
            distance = _wire_distance(track.last, wire)
            if distance > (self.match_radius_px if match_radius_px is None
                           else match_radius_px):
                continue
            if best is None or distance < best[0]:
                best = (distance, track)
        return best[1] if best is not None else None

    def _stable_wire(self, track: _WireTrack) -> WireInstance | None:
        if sum(track.seen) < self.confirm_hits:
            return None
        history = list(track.history)[-self.vote_window:]
        endpoint_a, share_a = _stable_endpoint(history, "endpoint_a",
                                                self.vote_share)
        endpoint_b, share_b = _stable_endpoint(history, "endpoint_b",
                                                self.vote_share)
        latest = track.last
        ambiguous = (latest.ambiguous
                     or endpoint_a.kind == "ambiguous_tie"
                     or endpoint_b.kind == "ambiguous_tie")
        confidence = float(latest.confidence) * min(share_a, share_b)
        methods = sorted({method for wire in history
                          for method in wire.detection_methods})
        return replace(
            latest,
            wire_id=track.track_id,
            endpoint_a=endpoint_a,
            endpoint_b=endpoint_b,
            ambiguous=ambiguous,
            confidence=confidence,
            detection_methods=methods or list(latest.detection_methods),
        )

    def update(self, result: WireTraceResult) -> WireTraceResult:
        if result.board_tracking == "searching":
            self.reset()
            return result

        used: set[int] = set()
        pitch_px = float((result.geometry or {}).get("pitch_px", 0.0))
        match_radius_px = self._effective_match_radius(pitch_px)
        for wire in result.wires:
            track = self._find_track(wire, used, match_radius_px)
            if track is None:
                track = self._new_track(wire)
                self._next_track_id += 1
                self._tracks.append(track)
            else:
                wire = _orient_like_reference(track.last, wire)
            track.observe(wire)
            used.add(track.track_id)

        for track in self._tracks:
            if track.track_id not in used:
                track.miss()

        self._tracks = [track for track in self._tracks
                        if track.missing <= self.coast_ticks]
        stable = []
        for track in self._tracks:
            if track.track_id not in used:
                continue
            wire = self._stable_wire(track)
            if wire is not None:
                stable.append(wire)
        stable.sort(key=lambda wire: wire.wire_id)
        return replace(result, wires=stable)


def _raw_endpoint_px(wire: WireInstance, endpoint: WireEndpoint) -> tuple[float, float]:
    """Choose the raw path end belonging to an endpoint.

    Skeleton walking can return either direction, and resolved endpoint ``px``
    may be a row extrapolation rather than the observed pixel.  The nearest
    raw end is therefore safer than assuming ``path[0]`` is endpoint A.
    """
    if not wire.path_px:
        return endpoint.px
    candidates = [wire.path_px[0], wire.path_px[-1]]
    return min(candidates, key=lambda p: math.hypot(
        float(p[0]) - endpoint.px[0], float(p[1]) - endpoint.px[1]))


class AttachmentClassifier:
    """Classify physical attachment only when board motion supplies evidence.

    A single camera cannot distinguish an inserted ferrule from a resting tip
    in one static frame.  This classifier uses the board's projected pin and
    the *raw* wire endpoint across motion:

    - ``inserted``: endpoint and pin move together, keeping their relative
      image offset stable;
    - ``resting``: endpoint remains approximately still while the pin moves;
    - ``unknown``: insufficient motion, conflicting evidence, or ambiguous
      geometry.

    It never promotes from one frame.  A fresh non-matching motion sample also
    hides an older verdict until the evidence becomes consistent again.
    """

    def __init__(self, *, vote_window: int = 4, min_votes: int = 3,
                 min_motion_px: float = 2.0) -> None:
        self.vote_window = max(2, int(vote_window))
        self.min_votes = max(2, int(min_votes))
        self.min_motion_px = max(0.5, float(min_motion_px))
        self._tracks: dict[tuple[int, str], _AttachmentTrack] = {}

    def reset(self) -> None:
        self._tracks.clear()

    def _state(self, key: tuple[int, str], pin_id: str,
               endpoint_px: tuple[float, float],
               pin_px: tuple[float, float]) -> _AttachmentTrack:
        previous = self._tracks.get(key)
        if previous is None or previous.pin_id != pin_id:
            previous = _AttachmentTrack(pin_id, endpoint_px, pin_px)
            self._tracks[key] = previous
        return previous

    def _observe(self, state: _AttachmentTrack,
                 endpoint_px: tuple[float, float],
                 pin_px: tuple[float, float], pitch_px: float) -> None:
        pin_dx = pin_px[0] - state.pin_px[0]
        pin_dy = pin_px[1] - state.pin_px[1]
        endpoint_dx = endpoint_px[0] - state.endpoint_px[0]
        endpoint_dy = endpoint_px[1] - state.endpoint_px[1]
        pin_motion = math.hypot(pin_dx, pin_dy)
        if pin_motion >= max(self.min_motion_px, 0.25 * pitch_px):
            old_rel = (state.endpoint_px[0] - state.pin_px[0],
                       state.endpoint_px[1] - state.pin_px[1])
            new_rel = (endpoint_px[0] - pin_px[0],
                       endpoint_px[1] - pin_px[1])
            relative_shift = math.hypot(new_rel[0] - old_rel[0],
                                        new_rel[1] - old_rel[1])
            endpoint_motion = math.hypot(endpoint_dx, endpoint_dy)
            follow_tolerance = max(2.0, 0.25 * pitch_px,
                                   0.35 * pin_motion)

            if relative_shift <= follow_tolerance:
                vote = "inserted"
                quality = max(0.0, 1.0 - relative_shift /
                              max(follow_tolerance, 1e-6))
            elif (endpoint_motion <= 0.35 * pin_motion
                  and relative_shift >= 0.65 * pin_motion):
                vote = "resting"
                quality = max(0.0, 1.0 - endpoint_motion /
                              max(0.35 * pin_motion, 1e-6))
            else:
                vote = "unknown"
                quality = 0.0
            state.votes.append(vote)
            state.qualities.append(float(quality))

        state.endpoint_px = endpoint_px
        state.pin_px = pin_px

    def _verdict(self, state: _AttachmentTrack) -> tuple[str, float]:
        votes = list(state.votes)
        if len(votes) < self.min_votes:
            return "unknown", 0.0
        winner = max(("inserted", "resting"),
                     key=lambda value: votes.count(value))
        count = votes.count(winner)
        share = count / len(votes)
        # A fresh unknown/conflicting sample must not be hidden by an older
        # majority; this mirrors the endpoint stabilizer's safety rule.
        if count < self.min_votes or share < 0.75 or votes[-1] != winner:
            return "unknown", 0.0
        qualities = list(state.qualities)[-len(votes):]
        quality = (sum(qualities) / len(qualities)
                   if qualities else 0.0)
        return winner, float(max(0.0, min(1.0, 0.5 * share + 0.5 * quality)))

    def update(self, result: WireTraceResult, pins: list) -> WireTraceResult:
        """Add motion evidence and annotate live ``unknown`` attachments."""
        if result.board_tracking != "locked":
            self.reset()
            return result
        if not result.wires:
            # Require consecutive visible observations.  An occlusion or a
            # lost segmentation must not let an old verdict leak to a new
            # physical wire reappearance.
            self.reset()
            return result

        pitch_px = float((result.geometry or {}).get("pitch_px", 0.0))
        pin_map = {
            str(getattr(pin, "pin_id")): pin
            for pin in pins
            if getattr(pin, "visible", True)
        }
        active: set[tuple[int, str]] = set()
        per_wire: dict[int, list[tuple[str, float]]] = {}
        for wire in result.wires:
            if wire.attachment != "unknown":
                continue
            for side, endpoint in (("a", wire.endpoint_a),
                                   ("b", wire.endpoint_b)):
                if endpoint.kind != "pin" or not endpoint.pin_id:
                    continue
                pin = pin_map.get(str(endpoint.pin_id))
                if pin is None:
                    continue
                key = (int(wire.wire_id), side)
                active.add(key)
                endpoint_px = _raw_endpoint_px(wire, endpoint)
                pin_px = (float(pin.x), float(pin.y))
                state = self._state(key, str(endpoint.pin_id),
                                    endpoint_px, pin_px)
                self._observe(state, endpoint_px, pin_px, pitch_px)
                per_wire.setdefault(int(wire.wire_id), []).append(
                    self._verdict(state))

        self._tracks = {key: value for key, value in self._tracks.items()
                        if key in active}
        annotated = []
        for wire in result.wires:
            # Injected/legacy fixtures use None to mean "attachment was not
            # part of that caller's contract". Preserve it rather than
            # rewriting it as a live unknown value.
            if wire.attachment != "unknown":
                annotated.append(wire)
                continue
            verdicts = per_wire.get(int(wire.wire_id), [])
            attachment = "unknown"
            confidence = 0.0
            if verdicts:
                # A resting endpoint is a hard safety veto.  Otherwise one
                # confirmed inserted board endpoint is enough to establish
                # the board-side attachment of a wire to a module/off-frame.
                resting = [v for v in verdicts if v[0] == "resting"]
                inserted = [v for v in verdicts if v[0] == "inserted"]
                if resting:
                    attachment, confidence = "resting", min(v[1] for v in resting)
                elif inserted:
                    attachment, confidence = "inserted", max(v[1] for v in inserted)
            annotated.append(replace(
                wire, attachment=attachment,
                attachment_confidence=float(confidence)))
        return replace(result, wires=annotated)
