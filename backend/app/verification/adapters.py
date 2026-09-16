"""Adapters from existing guidance/CV outputs into verification evidence."""
from __future__ import annotations

import math
from typing import Any

from app.verification.models import VerificationEvidence

GEOMETRY_TTL_MS = 1_200.0
VISUAL_TTL_MS = 2_500.0
COMPONENT_MAX_TAIL_EXTRAPOLATION_PITCH = 4.5
COMPONENT_TAIL_POINTS = 18


def _endpoint_outward_direction(
    path_px: list[tuple[float, float]], side: str
) -> tuple[float, float] | None:
    """Fit the visible wire tail and point from insulation toward its plug.

    Colour segmentation ends where the insulated wire enters a black female
    Dupont housing.  The missing housing therefore lies *opposite* the path
    interior.  A small PCA fit is less sensitive to one jagged skeleton pixel
    than using only the final two points.
    """
    if len(path_px) < 5 or side not in {"a", "b"}:
        return None
    tail = (
        list(path_px[:COMPONENT_TAIL_POINTS])
        if side == "a"
        else list(reversed(path_px[-COMPONENT_TAIL_POINTS:]))
    )
    if len(tail) < 5:
        return None
    inside_dx = float(tail[-1][0]) - float(tail[0][0])
    inside_dy = float(tail[-1][1]) - float(tail[0][1])
    if math.hypot(inside_dx, inside_dy) < 6.0:
        return None

    mean_x = sum(float(point[0]) for point in tail) / len(tail)
    mean_y = sum(float(point[1]) for point in tail) / len(tail)
    cov_xx = sum((float(point[0]) - mean_x) ** 2 for point in tail)
    cov_xy = sum(
        (float(point[0]) - mean_x) * (float(point[1]) - mean_y)
        for point in tail
    )
    cov_yy = sum((float(point[1]) - mean_y) ** 2 for point in tail)
    if cov_xx + cov_yy <= 1e-6:
        return None
    angle = 0.5 * math.atan2(2.0 * cov_xy, cov_xx - cov_yy)
    axis_x, axis_y = math.cos(angle), math.sin(angle)
    if axis_x * inside_dx + axis_y * inside_dy < 0.0:
        axis_x, axis_y = -axis_x, -axis_y
    # The fitted axis now points from the observed terminal into the visible
    # wire. The black housing and component pin must be behind that terminal.
    return -axis_x, -axis_y


def _component_endpoint_assignment(
    px: tuple[float, float],
    component_pose,
    target_pin_id: str,
    *,
    path_px: list[tuple[float, float]] | None = None,
    side: str | None = None,
) -> dict[str, Any]:
    """Assign a wire endpoint to a visible component pin without guessing.

    A close terminal uses the original radial gate.  A terminal hidden by a
    black female Dupont housing may additionally use a direction-constrained
    tail extension: it must point toward exactly one pin, remain within one
    pin lane, and stay inside the physical housing-length bound.
    """
    visible_pins = [pin for pin in component_pose.pins if pin.visible]
    target_pin = next((pin for pin in visible_pins if pin.id == target_pin_id), None)
    if target_pin is None:
        return {"kind": "target_not_visible"}

    pair_distances = [
        math.hypot(left.x - right.x, left.y - right.y)
        for index, left in enumerate(visible_pins)
        for right in visible_pins[index + 1:]
    ]
    pitch_px = min(pair_distances) if pair_distances else 18.0
    radius_px = max(8.0, min(22.0, 0.75 * pitch_px))
    tie_tolerance_px = max(2.0, 0.20 * pitch_px)
    ranked = sorted(
        (
            math.hypot(float(px[0]) - pin.x, float(px[1]) - pin.y),
            pin,
        )
        for pin in visible_pins
    )
    nearest_distance, nearest_pin = ranked[0]
    result = {
        "distance_px": float(nearest_distance),
        "snap_error_px": float(nearest_distance),
        "radius_px": float(radius_px),
        "tolerance_px": float(radius_px),
        "pitch_px": float(pitch_px),
        "actual_pin": str(nearest_pin.id),
        "method": "radial_snap",
    }
    if nearest_distance <= radius_px:
        if (
            len(ranked) > 1
            and ranked[1][0] <= radius_px
            and ranked[1][0] - nearest_distance <= tie_tolerance_px
        ):
            return {
                "kind": "ambiguous",
                "candidates": [str(nearest_pin.id), str(ranked[1][1].id)],
                **result,
            }
        return {
            "kind": "target" if nearest_pin.id == target_pin_id else "other",
            **result,
        }

    outward = _endpoint_outward_direction(path_px or [], side or "")
    if outward is None:
        return {"kind": "none", **result}
    cross_tolerance_px = max(6.0, min(18.0, 0.65 * pitch_px))
    max_extension_px = max(14.0, COMPONENT_MAX_TAIL_EXTRAPOLATION_PITCH * pitch_px)
    directional: list[tuple[float, float, float, Any]] = []
    for pin in visible_pins:
        delta_x = float(pin.x) - float(px[0])
        delta_y = float(pin.y) - float(px[1])
        along = delta_x * outward[0] + delta_y * outward[1]
        cross_track = abs(delta_x * outward[1] - delta_y * outward[0])
        if 0.0 < along <= max_extension_px and cross_track <= cross_tolerance_px:
            observed_distance = math.hypot(delta_x, delta_y)
            directional.append((cross_track, along, observed_distance, pin))
    if not directional:
        return {"kind": "none", **result}

    directional.sort(key=lambda item: (item[0], item[1]))
    cross_track, extension_px, observed_distance, assigned_pin = directional[0]
    directional_result = {
        "distance_px": float(observed_distance),
        "snap_error_px": float(cross_track),
        "radius_px": float(cross_tolerance_px),
        "tolerance_px": float(cross_tolerance_px),
        "pitch_px": float(pitch_px),
        "actual_pin": str(assigned_pin.id),
        "method": "directional_extrapolation",
        "extension_px": float(extension_px),
        "cross_track_px": float(cross_track),
        "max_extension_px": float(max_extension_px),
    }
    if (
        len(directional) > 1
        and directional[1][0] - cross_track <= tie_tolerance_px
    ):
        return {
            "kind": "ambiguous",
            "candidates": [str(assigned_pin.id), str(directional[1][3].id)],
            **directional_result,
        }
    return {
        "kind": "target" if assigned_pin.id == target_pin_id else "other",
        **directional_result,
    }


def _component_pose_quality(component_pose) -> float:
    # The component tracker confidence is a raw small-object YOLO score. Once
    # temporal tracking has locked the homography it is more reliable than the
    # raw number alone, so map a locked observation into a conservative
    # 0.65..1.0 evidence band. Stale/occlusion-held poses remain usable but
    # receive a visible discount.
    raw = max(0.0, min(float(getattr(component_pose, "confidence", 0.0) or 0.0), 1.0))
    quality = 0.65 + 0.35 * raw
    if getattr(component_pose, "tracking", "searching") == "stale":
        quality *= 0.88
    return max(0.0, min(quality, 1.0))


def _board_endpoint_geometry_score(endpoint, trace, detection) -> tuple[float, float]:
    """Score local pin proximity without requiring a high-quality full path."""
    pose_quality = max(
        0.0, min(float(getattr(detection, "confidence", 1.0) or 0.0), 1.0)
    )
    distance = getattr(endpoint, "distance_px", None)
    radius = float((trace.geometry or {}).get("snap_radius_px", 0.0) or 0.0)
    if distance is not None and radius > 0.0:
        proximity = max(0.75, 1.0 - 0.25 * float(distance) / radius)
    else:
        # A uniquely resolved endpoint is already inside the board snap gate.
        # Fixtures and old traces may not carry distance telemetry.
        proximity = max(0.75, min(float(endpoint.confidence), 1.0))
    return min(pose_quality, proximity), pose_quality


def geometry_evidence(
    step, trace, raw_verdict, detection=None, component_pose=None
) -> VerificationEvidence:
    """Verify board and component endpoints independently in one frame.

    The cable curve may be split into multiple HSV/skeleton fragments. For
    guided MVP checks, pin identity therefore comes from two local endpoint
    observations; continuity of the full curve is diagnostic only.
    """
    now_ms = float(trace.ts_ms)
    if trace.board_tracking != "locked":
        return VerificationEvidence.uncertain(
            "geometry",
            "board_not_tracked",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
        )
    if trace.suppressed_reason == "scale_below_minimum":
        return VerificationEvidence.uncertain(
            "geometry",
            "scale_unready",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
            details={
                key: round(float(value), 4)
                for key, value in (trace.geometry or {}).items()
            },
        )

    target_candidates: list[tuple[float, int, str, Any, Any]] = []
    other_candidates: list[tuple[float, str, int, str]] = []
    target_is_ambiguous = False
    for wire in trace.wires:
        for side, endpoint in (("a", wire.endpoint_a), ("b", wire.endpoint_b)):
            if endpoint.kind == "pin" and endpoint.pin_id == step.expected_pin_id:
                target_candidates.append(
                    (
                        float(endpoint.confidence),
                        int(wire.wire_id),
                        side,
                        wire,
                        endpoint,
                    )
                )
            elif endpoint.kind == "pin" and endpoint.pin_id:
                other_candidates.append(
                    (
                        float(endpoint.confidence),
                        str(endpoint.pin_id),
                        int(wire.wire_id),
                        side,
                    )
                )
            elif (
                endpoint.kind == "ambiguous_tie"
                and step.expected_pin_id in endpoint.candidates
            ):
                target_is_ambiguous = True

    requires_component = bool(step.component_id and step.expected_role)
    component_assignments: list[tuple[int, str, dict[str, Any]]] = []
    component_target_matches: list[tuple[int, str, dict[str, Any]]] = []
    if requires_component:
        if (
            component_pose is None
            or component_pose.tracking not in {"locked", "stale"}
            or component_pose.component_id != step.component_id
        ):
            return VerificationEvidence.uncertain(
                "geometry",
                "component_not_tracked",
                as_of_ms=now_ms,
                fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                method="independent_endpoint_snap",
                quality=float(getattr(detection, "confidence", 0.0) or 0.0),
            )
        component_target_visible = any(
            pin.id == step.expected_role and pin.visible
            for pin in component_pose.pins
        )
        if not component_target_visible:
            return VerificationEvidence.uncertain(
                "geometry",
                "component_endpoint_not_visible",
                as_of_ms=now_ms,
                fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                method="independent_endpoint_snap",
                quality=_component_pose_quality(component_pose),
                details={"component_pin": step.expected_role},
            )
        board_target_keys = {
            (wire_id, side)
            for _confidence, wire_id, side, _wire, _endpoint in target_candidates
        }
        for wire in trace.wires:
            for side, endpoint in (("a", wire.endpoint_a), ("b", wire.endpoint_b)):
                key = (int(wire.wire_id), side)
                if key in board_target_keys or endpoint.kind in {"pin", "ambiguous_tie"}:
                    continue
                assignment = _component_endpoint_assignment(
                    endpoint.px,
                    component_pose,
                    str(step.expected_role),
                    path_px=wire.path_px,
                    side=side,
                )
                item = (int(wire.wire_id), side, assignment)
                component_assignments.append(item)
                if assignment["kind"] == "target":
                    component_target_matches.append(item)

    if target_candidates:
        if requires_component:
            if component_target_matches:
                board_scored = [
                    (
                        *_board_endpoint_geometry_score(endpoint, trace, detection),
                        wire_id,
                        side,
                    )
                    for _confidence, wire_id, side, _wire, endpoint in target_candidates
                ]
                board_score, board_quality, board_wire_id, board_side = max(
                    board_scored, key=lambda item: item[0]
                )
                component_wire_id, component_side, assignment = min(
                    component_target_matches,
                    key=lambda item: item[2].get(
                        "snap_error_px", item[2]["distance_px"]
                    ),
                )
                component_quality = _component_pose_quality(component_pose)
                distance_ratio = assignment.get(
                    "snap_error_px", assignment["distance_px"]
                ) / max(
                    assignment.get("tolerance_px", assignment["radius_px"]),
                    1e-6,
                )
                proximity_score = max(0.75, 1.0 - 0.25 * distance_ratio)
                score = min(board_score, component_quality, proximity_score)
                return VerificationEvidence(
                    source="geometry",
                    status="pass",
                    score=score,
                    quality=min(board_quality, component_quality),
                    reason="both_endpoints_near_targets",
                    as_of_ms=now_ms,
                    fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                    method="independent_endpoint_snap",
                    details={
                        "board_pin": step.expected_pin_id,
                        "component_pin": step.expected_role,
                        "board_wire_id": board_wire_id,
                        "board_endpoint": board_side,
                        "component_wire_id": component_wire_id,
                        "component_endpoint": component_side,
                        "same_wire_fragment": board_wire_id == component_wire_id,
                        "component_distance_px": round(assignment["distance_px"], 2),
                        "component_snap_radius_px": round(assignment["radius_px"], 2),
                        "component_assignment_method": assignment.get("method"),
                        "component_extension_px": round(
                            float(assignment.get("extension_px", 0.0)), 2
                        ),
                        "component_cross_track_px": round(
                            float(assignment.get("cross_track_px", assignment.get("snap_error_px", 0.0))),
                            2,
                        ),
                        "scope": "independent_endpoints",
                    },
                )
            ambiguous = next(
                (item for item in component_assignments if item[2]["kind"] == "ambiguous"),
                None,
            )
            if ambiguous is not None:
                wire_id, side, assignment = ambiguous
                return VerificationEvidence.uncertain(
                    "geometry",
                    "component_endpoint_ambiguous",
                    as_of_ms=now_ms,
                    fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                    method="independent_endpoint_snap",
                    quality=_component_pose_quality(component_pose),
                    details={
                        "component_pin": step.expected_role,
                        "candidates": assignment["candidates"],
                        "wire_id": wire_id,
                        "component_endpoint": side,
                        "component_assignment_method": assignment.get("method"),
                    },
                )
            other = next(
                (item for item in component_assignments if item[2]["kind"] == "other"),
                None,
            )
            if other is not None:
                wire_id, side, assignment = other
                return VerificationEvidence.uncertain(
                    "geometry",
                    "component_endpoint_near_other_pin",
                    as_of_ms=now_ms,
                    fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                    method="independent_endpoint_snap",
                    quality=_component_pose_quality(component_pose),
                    details={
                        "expected_pin": step.expected_role,
                        "actual_pin": assignment["actual_pin"],
                        "wire_id": wire_id,
                        "component_endpoint": side,
                        "component_assignment_method": assignment.get("method"),
                    },
                )
            return VerificationEvidence.uncertain(
                "geometry",
                "waiting_for_component_endpoint",
                as_of_ms=now_ms,
                fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
                method="independent_endpoint_snap",
                quality=_component_pose_quality(component_pose),
                details={
                    "board_pin": step.expected_pin_id,
                    "component_pin": step.expected_role,
                },
            )

        confidence, wire_id, side, _wire, _endpoint = max(
            target_candidates, key=lambda item: item[0]
        )
        pose_quality = float(getattr(detection, "confidence", 1.0) or 0.0)
        quality = max(0.0, min(pose_quality, 1.0))
        score = min(max(0.0, confidence), quality) if detection is not None else confidence
        return VerificationEvidence(
            source="geometry",
            status="pass",
            score=score,
            quality=quality,
            reason="target_endpoint_near_pin",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
            details={
                "board_pin": step.expected_pin_id,
                "wire_id": wire_id,
                "endpoint": side,
                "scope": "board_endpoint",
            },
        )

    if raw_verdict.status == "wrong_pin" and raw_verdict.actual_pin_id:
        return VerificationEvidence(
            source="geometry",
            status="fail",
            score=float(raw_verdict.confidence),
            quality=float(getattr(detection, "confidence", 1.0) or 0.0),
            reason="wrong_pin",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
            details={
                "expected_pin": step.expected_pin_id,
                "actual_pin": raw_verdict.actual_pin_id,
            },
        )
    if target_is_ambiguous:
        return VerificationEvidence.uncertain(
            "geometry",
            "endpoint_ambiguous",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
            quality=float(getattr(detection, "confidence", 0.0) or 0.0),
        )
    if other_candidates:
        confidence, actual_pin, wire_id, side = max(
            other_candidates, key=lambda item: item[0]
        )
        return VerificationEvidence.uncertain(
            "geometry",
            "endpoint_near_other_pin",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="wire_endpoint_snap",
            quality=float(getattr(detection, "confidence", 0.0) or 0.0),
            details={
                "expected_pin": step.expected_pin_id,
                "actual_pin": actual_pin,
                "candidate_confidence": round(confidence, 3),
                "wire_id": wire_id,
                "endpoint": side,
            },
        )
    if requires_component and component_target_matches:
        component_wire_id, component_side, assignment = min(
            component_target_matches,
            key=lambda item: item[2].get(
                "snap_error_px", item[2]["distance_px"]
            ),
        )
        return VerificationEvidence.uncertain(
            "geometry",
            "waiting_for_board_endpoint",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
            method="independent_endpoint_snap",
            quality=_component_pose_quality(component_pose),
            details={
                "board_pin": step.expected_pin_id,
                "component_pin": step.expected_role,
                "component_wire_id": component_wire_id,
                "component_endpoint": component_side,
                "component_distance_px": round(assignment["distance_px"], 2),
                "component_assignment_method": assignment.get("method"),
            },
        )
    reason = raw_verdict.reason or "waiting_for_target_endpoint"
    return VerificationEvidence.uncertain(
        "geometry",
        reason,
        as_of_ms=now_ms,
        fresh_until_ms=now_ms + GEOMETRY_TTL_MS,
        method="wire_endpoint_snap",
        quality=float(getattr(detection, "confidence", 0.0) or 0.0),
    )


def visual_evidence(visual_check: dict[str, Any] | None, *, now_ms: float) -> VerificationEvidence:
    """Keep guided ROI advisory; only a manual VLM request may pass appearance."""
    if visual_check is None:
        return VerificationEvidence.uncertain(
            "visual",
            "visual_check_unavailable",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + VISUAL_TTL_MS,
            method="guided_roi",
        )
    status = str(visual_check.get("status", "uncertain"))
    reason = str(visual_check.get("reason", "visual_check_unavailable"))
    details = {
        key: value
        for key, value in visual_check.items()
        if key not in {"status", "reason"}
    }
    if status == "candidate":
        raw_score = max(0.0, min(float(visual_check.get("confidence", 0.0) or 0.0), 1.0))
        return VerificationEvidence.uncertain(
            "visual",
            "awaiting_manual_vlm",
            as_of_ms=now_ms,
            fresh_until_ms=now_ms + VISUAL_TTL_MS,
            method="guided_roi",
            quality=0.85,
            details={"raw_change_confidence": round(raw_score, 3), **details},
        )
    return VerificationEvidence.uncertain(
        "visual",
        reason,
        as_of_ms=now_ms,
        fresh_until_ms=now_ms + VISUAL_TTL_MS,
        method="guided_roi",
        quality=0.0 if status == "uncertain" else 0.5,
        details=details,
    )
