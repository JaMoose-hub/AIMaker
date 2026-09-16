"""Replay a wire-truth session without opening a camera or starting FastAPI.

This is intentionally a geometry-first MVP harness.  It uses the clicked
projected pin lattice from ``pin_truth.json`` and the saved JPEG burst, then
reports assignment, endpoint error, empty-scene false positives, and temporal
flips.  It does not use the declared pin IDs to pair observations; pairing is
strictly by source-image distance so a wrong pin cannot hide as an unmatched
false positive.

Pose modes are intentionally separate:

* ``truth-pins``: clicked projected pins; geometry-only lower bound;
* ``recorded``: frozen detector pose from ``pose.jsonl``; primary regression gate;
* ``sequential``: one stateful ``PipelineDetector`` over the burst;
* ``perframe``: a fresh detector per JPEG; pose-noise diagnostic only.

Usage::

    backend\\.venv\\Scripts\\python.exe tools\\replay_accuracy.py \
      --dataset datasets\\wire-truth\\s01 --json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from app.profiles.models import BoardProfile  # noqa: E402
from app.vision.interface import PinDetection  # noqa: E402
from app.vision.factory import create_detector  # noqa: E402
from app.vision.temporal import AttachmentClassifier, WireTraceStabilizer  # noqa: E402
from app.vision.wire_tracer import WireTraceResult, trace  # noqa: E402


def _percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=np.float64), percent))


def _load_pins(profile_path: Path, truth: dict[str, Any]) -> list[PinDetection]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    projected = truth.get("pins_px", {})
    pins: list[PinDetection] = []
    for pin in profile["pins"]:
        point = projected.get(pin["id"])
        if point is None:
            continue
        pins.append(PinDetection(
            pin_id=pin["id"], x=float(point[0]), y=float(point[1]), confidence=1.0,
            visible=True, header=pin["header"], index=int(pin["index"]),
        ))
    return pins


def _load_profile(profile_path: Path) -> BoardProfile:
    """Load the captured profile snapshot for detector-backed replay modes.

    A capture stores a flat ``<dataset>/profile`` snapshot rather than the
    normal ``profiles/boards/<id>`` tree.  Pydantic validation is sufficient
    here because the snapshot was produced from a profile already validated by
    ``ProfileStore``; the detector only needs the typed runtime model and the
    snapshot directory for its image/cache assets.
    """
    try:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        return BoardProfile.model_validate(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"could not load profile snapshot {profile_path}: {exc}") from exc


def _truth_endpoints(truth: dict[str, Any]) -> list[dict[str, Any]]:
    positions = truth.get("pins_px", {})
    endpoints: list[dict[str, Any]] = []
    for connection in truth.get("connections", []):
        for endpoint in connection.get("endpoints", []):
            pin_id = endpoint.get("pin_id")
            if pin_id in positions:
                endpoints.append({"pin_id": pin_id, "px": tuple(float(v) for v in positions[pin_id])})
    return endpoints


def _load_pose_records(config_dir: Path) -> dict[str, dict[str, Any]]:
    """Load pose records keyed by JPEG filename.

    ``capture_groundtruth.py`` records one line per frame.  Older datasets
    may contain ``tracking=not_recorded``; those are intentionally rejected
    by recorded mode instead of silently falling back to clicked pin truth.
    """
    path = config_dir / "pose.jsonl"
    if not path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid pose.jsonl line {line_no} in {path}: {exc}") from exc
        source = record.get("source")
        if isinstance(source, str):
            records[source] = record
    return records


def _pins_from_pose_record(record: dict[str, Any], reference_pins: list[PinDetection]) -> list[PinDetection]:
    """Convert a recorded detector message into wire-tracer pin inputs."""
    metadata = {pin.pin_id: pin for pin in reference_pins}
    pins: list[PinDetection] = []
    for raw in record.get("pins", []):
        pin_id = raw.get("id")
        if not isinstance(pin_id, str):
            continue
        try:
            base = metadata[pin_id]
            pins.append(PinDetection(
                pin_id=pin_id,
                x=float(raw["x"]),
                y=float(raw["y"]),
                confidence=float(raw.get("c", 0.0)),
                visible=bool(raw.get("v", True)),
                header=raw.get("header", base.header),
                index=raw.get("index", base.index),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return pins


def _pose_projection_errors(
    record: dict[str, Any], truth: dict[str, Any]
) -> list[float]:
    """Compare recorded projected pins with independently clicked pin truth."""
    truth_positions = truth.get("pins_px", {})
    errors: list[float] = []
    for raw in record.get("pins", []):
        pin_id = raw.get("id")
        expected = truth_positions.get(pin_id)
        if expected is None or not raw.get("v", True):
            continue
        try:
            errors.append(float(np.linalg.norm(
                np.asarray([float(raw["x"]), float(raw["y"])])
                - np.asarray(expected, dtype=np.float64)
            )))
        except (KeyError, TypeError, ValueError):
            continue
    return errors


def _result_projection_errors(result: Any, truth: dict[str, Any]) -> list[float]:
    """Compare a live detector result with the independently clicked truth."""
    truth_positions = truth.get("pins_px", {})
    errors: list[float] = []
    for pin in getattr(result, "pins", []):
        expected = truth_positions.get(pin.pin_id)
        if expected is None or not getattr(pin, "visible", True):
            continue
        errors.append(float(np.linalg.norm(
            np.asarray([float(pin.x), float(pin.y)])
            - np.asarray(expected, dtype=np.float64)
        )))
    return errors


def _observed_endpoints(result: Any) -> list[dict[str, Any]]:
    """Serialize endpoints in the coordinate space used by replay matching.

    A resolved endpoint keeps its raw skeleton terminal internally because
    attachment classification needs that motion signal.  Accuracy matching,
    however, compares against the annotated projected pin center, so use the
    trace's canonical ``pin_positions`` for resolved pins.  Unresolved
    endpoints have no canonical pin center and intentionally keep their raw
    observed pixels.
    """
    endpoints: list[dict[str, Any]] = []
    pin_positions = getattr(result, "pin_positions", None) or {}
    for wire in result.wires:
        for endpoint in (wire.endpoint_a, wire.endpoint_b):
            canonical = None
            if endpoint.kind == "pin" and endpoint.pin_id:
                canonical = pin_positions.get(endpoint.pin_id)
            observed_px = canonical if canonical is not None else endpoint.px
            endpoints.append({
                "kind": endpoint.kind,
                "pin_id": endpoint.pin_id,
                "px": tuple(float(v) for v in observed_px),
                # Keep the actual skeleton terminal as a separate diagnostic
                # coordinate.  ``px`` intentionally remains canonical for
                # assignment matching, while raw_px exposes ferrule/cut and
                # segmentation error instead of hiding it in a zero-distance
                # canonical match.
                "raw_px": tuple(float(v) for v in endpoint.px),
            })
    return endpoints


def _match(truth: list[dict[str, Any]], observed: list[dict[str, Any]], max_distance: float) -> list[tuple[dict[str, Any], dict[str, Any], float]]:
    candidates: list[tuple[float, int, int]] = []
    for truth_index, expected in enumerate(truth):
        for observed_index, actual in enumerate(observed):
            distance = float(np.linalg.norm(np.asarray(expected["px"]) - np.asarray(actual["px"])))
            if distance <= max_distance:
                candidates.append((distance, truth_index, observed_index))
    matches: list[tuple[dict[str, Any], dict[str, Any], float]] = []
    used_truth: set[int] = set()
    used_observed: set[int] = set()
    for distance, truth_index, observed_index in sorted(candidates):
        if truth_index in used_truth or observed_index in used_observed:
            continue
        used_truth.add(truth_index)
        used_observed.add(observed_index)
        matches.append((truth[truth_index], observed[observed_index], distance))
    return matches


def _replay_config(
    config_dir: Path,
    pins: list[PinDetection],
    truth: dict[str, Any],
    colors: list[str] | None,
    include_edge: bool,
    pose_mode: str,
    wire_interval_s: float,
    *,
    profile: BoardProfile | None = None,
    profile_dir: Path | None = None,
    horizontal_fov_deg: float | None = 70.42,
) -> dict[str, Any]:
    """Replay one burst using an explicitly selected pose pipeline.

    ``truth-pins`` is the geometry-only lower bound.  ``recorded`` consumes
    the frozen detector output captured beside each JPEG.  ``sequential``
    keeps one PipelineDetector alive across the burst so LK/One-Euro state is
    exercised.  ``perframe`` creates a fresh detector for every JPEG and is a
    diagnostic upper bound for pose noise, not a release gate.
    """
    valid_modes = {"truth-pins", "recorded", "sequential", "perframe"}
    if pose_mode not in valid_modes:
        raise ValueError(f"unknown pose mode {pose_mode!r}")
    if pose_mode in {"sequential", "perframe"} and (profile is None or profile_dir is None):
        raise RuntimeError(
            f"{pose_mode} replay requires a validated profile snapshot and profile directory"
        )

    truth_endpoints = _truth_endpoints(truth)
    pitch = float(truth.get("pitch_px") or 0.0)
    match_radius = max(2.0 * pitch, 12.0)
    all_errors: list[float] = []
    raw_errors: list[float] = []
    correct = 0
    matched_truth = 0
    unmatched_truth = 0
    unmatched_observed = 0
    empty_fp = 0
    projection_errors: list[float] = []
    pitch_errors: list[float] = []
    raw_pitch_errors: list[float] = []
    same_row_neighbour_errors = 0
    wrong_pin_matches = 0
    observed_total = 0
    endpoint_positions: dict[str, list[tuple[float, float]]] = {
        endpoint["pin_id"]: [] for endpoint in truth_endpoints
    }
    endpoint_pin_ids: dict[str, list[str]] = {
        endpoint["pin_id"]: [] for endpoint in truth_endpoints
    }
    draped_pin_ids: set[str] = set()
    for item in truth.get("draped", []):
        for raw_endpoint in item.get("endpoints", []):
            if raw_endpoint.get("pin_id"):
                draped_pin_ids.add(str(raw_endpoint["pin_id"]))
        for pin_id in item.get("near_pins", []):
            if pin_id:
                draped_pin_ids.add(str(pin_id))
    phantom_from_drape = 0
    flips_by_pin: dict[str, list[str | None]] = {endpoint["pin_id"]: [] for endpoint in truth_endpoints}
    geometry: dict[str, float] | None = None
    frame_count = 0
    recorded = _load_pose_records(config_dir) if pose_mode == "recorded" else {}
    metadata = {pin.pin_id: pin for pin in pins}
    if pose_mode == "recorded" and not recorded:
        raise RuntimeError(f"recorded pose requested but pose.jsonl is missing/empty: {config_dir}")
    stabilizer = WireTraceStabilizer()
    attachment_classifier = AttachmentClassifier()
    detector = None
    if pose_mode == "sequential":
        detector = create_detector(
            "pipeline", profile, profile_dir,
            horizontal_fov_deg=horizontal_fov_deg,
        )
    try:
        for frame_path in sorted(config_dir.glob("f*.jpg")):
            frame = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            if frame is None:
                raise RuntimeError(f"could not read {frame_path}")
            frame_index = frame_count
            frame_count += 1
            frame_pins = pins
            tracking = "locked"
            board_outline = None
            ts_ms = float(frame_index * max(wire_interval_s, 0.0) * 1000.0)

            if pose_mode == "recorded":
                record = recorded.get(frame_path.name)
                if record is None:
                    raise RuntimeError(f"pose.jsonl has no record for {frame_path.name}")
                if record.get("tracking") == "not_recorded" or record.get("pose_mode") != "recorded":
                    raise RuntimeError(
                        f"{config_dir}: {frame_path.name} has no recorded detector pose; "
                        "recapture without --no-record-pose"
                    )
                frame_pins = _pins_from_pose_record(record, pins)
                tracking = record.get("tracking", "searching")
                if tracking not in {"searching", "locked", "stale"}:
                    tracking = "searching"
                board_outline = record.get("wire_exclusion") or record.get("outline")
                ts_ms = float(record.get("ts_ms", ts_ms))
                projection_errors.extend(_pose_projection_errors(record, truth))
            elif pose_mode in {"sequential", "perframe"}:
                frame_detector = detector
                if pose_mode == "perframe":
                    frame_detector = create_detector(
                        "pipeline", profile, profile_dir,
                        horizontal_fov_deg=horizontal_fov_deg,
                    )
                try:
                    detection = frame_detector.detect(frame, frame_index, ts_ms)
                finally:
                    if pose_mode == "perframe":
                        frame_detector.close()
                frame_pins = detection.pins
                tracking = detection.tracking
                board_outline = detection.wire_exclusion_px or detection.outline_px
                projection_errors.extend(_result_projection_errors(detection, truth))

            if tracking != "locked":
                stabilizer.reset()
                attachment_classifier.reset()
                result = WireTraceResult(
                    frame_id=frame_index,
                    ts_ms=ts_ms,
                    board_tracking=tracking,
                    wires=[],
                    video_size=(int(frame.shape[1]), int(frame.shape[0])),
                )
            else:
                result = trace(
                    frame,
                    frame_pins,
                    frame_index,
                    ts_ms,
                    tracking,
                    colors=colors,
                    board_outline=board_outline,
                    include_edge_agnostic=include_edge,
                )
                result = stabilizer.update(result)
                result = attachment_classifier.update(result, frame_pins)

            geometry = result.geometry or geometry
            observed = _observed_endpoints(result)
            observed_total += len(observed)
            matches = _match(truth_endpoints, observed, match_radius)
            matched_truth += len(matches)
            unmatched_truth += len(truth_endpoints) - len(matches)
            unmatched_observed += len(observed) - len(matches)
            if truth.get("empty_scene"):
                empty_fp += len(result.wires)
            if draped_pin_ids:
                if any(
                    wire.attachment != "inserted"
                    and any(
                        endpoint.kind == "pin" and endpoint.pin_id in draped_pin_ids
                        for endpoint in (wire.endpoint_a, wire.endpoint_b)
                    )
                    for wire in result.wires
                ):
                    phantom_from_drape += 1
            for expected, actual, distance in matches:
                all_errors.append(distance)
                raw_distance = float(np.linalg.norm(
                    np.asarray(expected["px"], dtype=np.float64)
                    - np.asarray(actual.get("raw_px", actual["px"]), dtype=np.float64)
                ))
                raw_errors.append(raw_distance)
                expected_id = str(expected["pin_id"])
                endpoint_positions.setdefault(expected_id, []).append(actual["px"])
                endpoint_pin_ids.setdefault(expected_id, []).append(
                    str(actual["pin_id"]) if actual["kind"] == "pin" else "<unresolved>"
                )
                if pitch > 0:
                    pitch_errors.append(distance / pitch)
                    raw_pitch_errors.append(raw_distance / pitch)
                if actual["kind"] == "pin" and actual["pin_id"] == expected["pin_id"]:
                    correct += 1
                elif actual["kind"] == "pin":
                    wrong_pin_matches += 1
                    expected_pin = metadata.get(expected["pin_id"])
                    actual_pin = metadata.get(actual["pin_id"])
                    if (expected_pin is not None and actual_pin is not None
                            and expected_pin.header == actual_pin.header
                            and expected_pin.index is not None
                            and actual_pin.index is not None
                            and abs(expected_pin.index - actual_pin.index) == 1):
                        same_row_neighbour_errors += 1
                flips_by_pin.setdefault(expected_id, []).append(
                    actual["pin_id"] if actual["kind"] == "pin" else None
                )
    finally:
        if detector is not None:
            detector.close()

    endpoint_stddevs: list[float] = []
    pin_id_unique_counts: list[float] = []
    pin_id_entropies: list[float] = []
    for expected_id, positions in endpoint_positions.items():
        if len(positions) > 1:
            array = np.asarray(positions, dtype=np.float64)
            center = np.mean(array, axis=0)
            radial_stddev = float(np.sqrt(np.mean(np.sum((array - center) ** 2, axis=1))))
            endpoint_stddevs.append(radial_stddev / pitch if pitch > 0 else radial_stddev)
        identities = endpoint_pin_ids.get(expected_id, [])
        if identities:
            counts = Counter(identities)
            pin_id_unique_counts.append(float(len(counts)))
            total = float(len(identities))
            pin_id_entropies.append(float(-sum(
                (count / total) * math.log2(count / total)
                for count in counts.values()
            )))
    flips = 0
    observations = 0
    for values in flips_by_pin.values():
        previous: str | None = None
        for value in values:
            if value is None:
                continue
            observations += 1
            if previous is not None and previous != value:
                flips += 1
            previous = value
    return {
        "config": config_dir.name,
        "pose_mode": pose_mode,
        "wire_interval_s": float(wire_interval_s),
        "frames": frame_count,
        "truth_pin_endpoints": len(truth_endpoints) * frame_count,
        "matched_truth_endpoints": matched_truth,
        "unmatched_truth_endpoints": unmatched_truth,
        "unmatched_observed_endpoints": unmatched_observed,
        "observed_endpoints": observed_total,
        "correct_pin_assignments": correct,
        "pin_assignment_accuracy": (correct / matched_truth) if matched_truth else None,
        "wire_recall": (matched_truth / (len(truth_endpoints) * frame_count))
        if truth_endpoints and frame_count else None,
        "wire_precision": (matched_truth / observed_total) if observed_total else None,
        "endpoint_error_px_median": float(median(all_errors)) if all_errors else None,
        "endpoint_error_px_p95": _percentile(all_errors, 95),
        "endpoint_error_pitch_median": float(median(pitch_errors)) if pitch_errors else None,
        "endpoint_error_pitch_p95": _percentile(pitch_errors, 95),
        "raw_endpoint_error_px_median": float(median(raw_errors)) if raw_errors else None,
        "raw_endpoint_error_px_p95": _percentile(raw_errors, 95),
        "raw_endpoint_error_pitch_median": (
            float(median(raw_pitch_errors)) if raw_pitch_errors else None
        ),
        "raw_endpoint_error_pitch_p95": _percentile(raw_pitch_errors, 95),
        "endpoint_stddev_pitch_median": float(median(endpoint_stddevs)) if endpoint_stddevs else None,
        "endpoint_stddev_pitch_p95": _percentile(endpoint_stddevs, 95),
        "pin_id_unique_median": float(median(pin_id_unique_counts)) if pin_id_unique_counts else None,
        "pin_id_entropy_bits_median": float(median(pin_id_entropies)) if pin_id_entropies else None,
        "pin_projection_error_px_median": float(median(projection_errors)) if projection_errors else None,
        "pin_projection_error_px_p95": _percentile(projection_errors, 95),
        "same_row_neighbour_error_rate": (
            same_row_neighbour_errors / wrong_pin_matches
            if wrong_pin_matches else None
        ),
        "same_row_neighbour_errors": same_row_neighbour_errors,
        "wrong_pin_matches": wrong_pin_matches,
        "empty_scene_wire_fp_total": empty_fp,
        "empty_scene_fp_per_frame": (empty_fp / frame_count) if frame_count else None,
        "phantom_from_drape": phantom_from_drape,
        "flips": flips,
        "observations_for_flip_metric": observations,
        "flip_transitions": max(frame_count - 1, 1),
        "flips_per_minute": (
            flips / max(frame_count - 1, 1) * 60.0 / max(wire_interval_s, 1e-9)
        ),
        "geometry": geometry,
    }


def _aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate counts before calculating accuracy; never average ratios."""
    truth = sum(int(report["truth_pin_endpoints"]) for report in reports)
    matched = sum(int(report["matched_truth_endpoints"]) for report in reports)
    correct = sum(int(report["correct_pin_assignments"]) for report in reports)
    errors = [
        float(report["endpoint_error_px_median"])
        for report in reports
        if report["endpoint_error_px_median"] is not None
    ]
    pitch_errors = [
        float(report["endpoint_error_pitch_median"])
        for report in reports
        if report["endpoint_error_pitch_median"] is not None
    ]
    raw_errors = [
        float(report["raw_endpoint_error_px_median"])
        for report in reports
        if report.get("raw_endpoint_error_px_median") is not None
    ]
    raw_pitch_errors = [
        float(report["raw_endpoint_error_pitch_median"])
        for report in reports
        if report.get("raw_endpoint_error_pitch_median") is not None
    ]
    endpoint_stddevs = [
        float(report["endpoint_stddev_pitch_median"])
        for report in reports
        if report.get("endpoint_stddev_pitch_median") is not None
    ]
    pin_id_unique = [
        float(report["pin_id_unique_median"])
        for report in reports
        if report.get("pin_id_unique_median") is not None
    ]
    pin_id_entropy = [
        float(report["pin_id_entropy_bits_median"])
        for report in reports
        if report.get("pin_id_entropy_bits_median") is not None
    ]
    projection_errors = [
        float(report["pin_projection_error_px_median"])
        for report in reports
        if report["pin_projection_error_px_median"] is not None
    ]
    return {
        "configs": len(reports),
        "frames": sum(int(report["frames"]) for report in reports),
        "truth_pin_endpoints": truth,
        "matched_truth_endpoints": matched,
        "unmatched_truth_endpoints": sum(int(report["unmatched_truth_endpoints"]) for report in reports),
        "unmatched_observed_endpoints": sum(int(report["unmatched_observed_endpoints"]) for report in reports),
        "observed_endpoints": sum(int(report.get("observed_endpoints", 0)) for report in reports),
        "correct_pin_assignments": correct,
        "pin_assignment_accuracy": (correct / matched) if matched else None,
        "wire_recall": (matched / truth) if truth else None,
        "wire_precision": (
            matched / sum(int(report.get("observed_endpoints", 0)) for report in reports)
            if sum(int(report.get("observed_endpoints", 0)) for report in reports) else None
        ),
        "endpoint_error_median_of_config_medians_px": float(median(errors)) if errors else None,
        "endpoint_error_pitch_median_of_config_medians": float(median(pitch_errors)) if pitch_errors else None,
        "raw_endpoint_error_median_of_config_medians_px": (
            float(median(raw_errors)) if raw_errors else None
        ),
        "raw_endpoint_error_pitch_median_of_config_medians": (
            float(median(raw_pitch_errors)) if raw_pitch_errors else None
        ),
        "endpoint_stddev_pitch_median_of_config_medians": float(median(endpoint_stddevs)) if endpoint_stddevs else None,
        "pin_id_unique_median_of_config_medians": float(median(pin_id_unique)) if pin_id_unique else None,
        "pin_id_entropy_bits_median_of_config_medians": float(median(pin_id_entropy)) if pin_id_entropy else None,
        "pin_projection_error_median_of_config_medians_px": float(median(projection_errors)) if projection_errors else None,
        "same_row_neighbour_error_rate": (
            sum(int(report.get("same_row_neighbour_errors", 0)) for report in reports)
            / max(sum(int(report.get("wrong_pin_matches", 0)) for report in reports), 1)
        ),
        "empty_scene_wire_fp_total": sum(int(report["empty_scene_wire_fp_total"]) for report in reports),
        "empty_scene_fp_per_frame": (
            sum(int(report["empty_scene_wire_fp_total"]) for report in reports)
            / max(sum(int(report["frames"]) for report in reports), 1)
        ),
        "phantom_from_drape": sum(int(report.get("phantom_from_drape", 0)) for report in reports),
        "flips": sum(int(report["flips"]) for report in reports),
        "flips_per_minute": (
            sum(int(report["flips"]) for report in reports)
            / max(sum(int(report.get("flip_transitions", 1)) for report in reports), 1)
            * 60.0
            / max(float(reports[0].get("wire_interval_s", 0.5)) if reports else 0.5, 1e-9)
        ),
    }


def _read_baseline(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload.get("aggregate"), dict):
        return payload["aggregate"]
    if isinstance(payload.get("metrics"), dict):
        return payload["metrics"]
    return payload


def _check_baseline(actual: dict[str, Any], baseline: dict[str, Any], tolerance: float) -> list[str]:
    """Return regressions against a recorded baseline.

    Accuracy is higher-is-better.  Error, missing truth, false positives, and
    flips are lower-is-better.  A zero baseline is strict: any positive
    regression is reported instead of being hidden by a relative tolerance.
    """
    higher = {"pin_assignment_accuracy", "wire_precision"}
    lower = {
        "unmatched_truth_endpoints",
        "unmatched_observed_endpoints",
        "endpoint_error_median_of_config_medians_px",
        "endpoint_error_pitch_median_of_config_medians",
        "endpoint_stddev_pitch_median_of_config_medians",
        "pin_id_entropy_bits_median_of_config_medians",
        "pin_projection_error_median_of_config_medians_px",
        "same_row_neighbour_error_rate",
        "empty_scene_wire_fp_total",
        "empty_scene_fp_per_frame",
        "phantom_from_drape",
        "flips",
        "flips_per_minute",
    }
    failures: list[str] = []
    for key in sorted(higher | lower):
        old = baseline.get(key)
        new = actual.get(key)
        if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
            continue
        if key in higher:
            if new + max(abs(float(old)) * tolerance, 1e-12) < old:
                failures.append(f"{key}: {new:.6g} < baseline {old:.6g}")
        elif old == 0:
            if new > 0:
                failures.append(f"{key}: {new:.6g} > baseline 0")
        elif new > old * (1.0 + tolerance):
            failures.append(f"{key}: {new:.6g} > baseline {old:.6g}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scene", default=None, help="replay one scene; default: all scenes")
    parser.add_argument("--profile", default=None, help="profile snapshot board.json; default: <dataset>/profile/board.json")
    parser.add_argument("--colors", default=None, help="comma-separated colors; default: all configured bands")
    parser.add_argument("--include-edge", action="store_true")
    parser.add_argument(
        "--pose-mode", choices=("truth-pins", "recorded", "sequential", "perframe"),
        default="truth-pins",
        help=(
            "pose source: clicked truth (geometry lower bound), frozen pose.jsonl, "
            "one stateful PipelineDetector, or fresh detector per frame"
        ),
    )
    parser.add_argument(
        "--horizontal-fov-deg", type=float, default=70.42,
        help="fallback horizontal FOV for sequential/perframe pose replay (default: C920 70.42)",
    )
    parser.add_argument(
        "--wire-interval-s", type=float, default=0.5,
        help="worker tick interval used to normalize flips/min (default: 0.5)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--baseline-out", default=None, help="write aggregate metrics to this new JSON file")
    parser.add_argument("--fail-under", default=None, help="fail when metrics regress against this baseline JSON")
    parser.add_argument("--tolerance", type=float, default=0.05, help="relative regression tolerance for --fail-under (default: 0.05)")
    args = parser.parse_args()
    if args.tolerance < 0:
        parser.error("--tolerance must be >= 0")

    dataset = Path(args.dataset).resolve()
    profile = Path(args.profile).resolve() if args.profile else dataset / "profile" / "board.json"
    if not profile.exists():
        raise SystemExit(f"profile snapshot not found: {profile}")
    detector_profile = _load_profile(profile) if args.pose_mode in {"sequential", "perframe"} else None
    detector_profile_dir = profile.parent if detector_profile is not None else None
    scene_dirs = sorted(dataset.glob("scene-*"))
    if args.scene:
        scene_dirs = [dataset / args.scene]
    colors = [color.strip() for color in args.colors.split(",") if color.strip()] if args.colors else None
    reports: list[dict[str, Any]] = []
    for scene_dir in scene_dirs:
        truth_path = scene_dir / "pin_truth.json"
        if not truth_path.exists():
            continue
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        pins = _load_pins(profile, truth)
        for config_dir in sorted(scene_dir.glob("cfg-*")):
            declaration = json.loads((config_dir / "truth.json").read_text(encoding="utf-8"))
            reports.append({
                "scene": scene_dir.name,
                **_replay_config(
                    config_dir, pins, declaration | truth, colors,
                    args.include_edge, args.pose_mode, args.wire_interval_s,
                    profile=detector_profile,
                    profile_dir=detector_profile_dir,
                    horizontal_fov_deg=args.horizontal_fov_deg,
                ),
            })
    aggregate = _aggregate(reports)
    output = {"dataset": str(dataset), "aggregate": aggregate, "reports": reports}
    if args.baseline_out:
        baseline_path = Path(args.baseline_out).resolve()
        if baseline_path.exists():
            raise SystemExit(f"refusing to overwrite baseline: {baseline_path}")
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures: list[str] = []
    if args.fail_under:
        baseline_path = Path(args.fail_under).resolve()
        if not baseline_path.exists():
            raise SystemExit(f"baseline not found: {baseline_path}")
        failures = _check_baseline(aggregate, _read_baseline(baseline_path), args.tolerance)
    if args.as_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"dataset: {dataset}")
        print(f"aggregate: {json.dumps(aggregate, ensure_ascii=False)}")
        for report in reports:
            print(
                f"{report['scene']}/{report['config']}: frames={report['frames']} "
                f"accuracy={report['pin_assignment_accuracy']} "
                f"endpoint_median_px={report['endpoint_error_px_median']} "
                f"unmatched={report['unmatched_truth_endpoints']} "
                f"flips={report['flips']}"
            )
        if failures:
            print("REGRESSION:")
            for failure in failures:
                print(f"  {failure}")
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
