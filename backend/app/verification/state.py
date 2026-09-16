"""Thread-safe latest-state holder for one guided verification step."""
from __future__ import annotations

import threading
import time
from collections import Counter
from dataclasses import dataclass, replace
from typing import Iterable

from app.verification.fusion import FusionResult, fuse_evidence
from app.verification.models import EvidenceSource, VerificationEvidence


_FINAL_VLM_METHOD = "vlm_final_wiring"
_FINAL_CONNECTION_PAIRS = (
    ("3V3", "VCC"),
    ("GND", "GND"),
    ("A0", "AO"),
)

@dataclass(frozen=True)
class VerificationTarget:
    step_id: str
    board_pin: str
    component_pin: str | None
    component_id: str | None
    geometry_requested: bool = False
    geometry_complete: bool = False
    geometry_generation: int = 0
    electrical_supported: bool = False
    electrical_requested: bool = False
    electrical_generation: int = 0


class VerificationState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._target: VerificationTarget | None = None
        self._evidence: dict[EvidenceSource, VerificationEvidence] = {}
        self._fusion: FusionResult | None = None
        self._geometry_samples: list[VerificationEvidence] = []
        self._geometry_frame_ids: set[int] = set()

    @staticmethod
    def _now_ms() -> float:
        return time.monotonic() * 1000.0

    def set_step(
        self,
        step_id: str,
        board_pin: str,
        component_pin: str | None = None,
        component_id: str | None = None,
        *,
        electrical_available: bool = False,
        electrical_unavailable_reason: str = "electrical_not_configured",
    ) -> None:
        now_ms = self._now_ms()
        evidence: dict[EvidenceSource, VerificationEvidence] = {
            "geometry": VerificationEvidence.unavailable(
                "geometry",
                "geometry_skipped_for_vlm",
            ),
            "visual": VerificationEvidence.uncertain(
                "visual", "awaiting_manual_vlm", as_of_ms=now_ms, method="vlm_insertion"
            ),
            "electrical": (
                VerificationEvidence.uncertain(
                    "electrical",
                    "awaiting_electrical_start",
                    as_of_ms=now_ms,
                    method="serial_a0_response",
                )
                if electrical_available
                else VerificationEvidence.unavailable(
                    "electrical", electrical_unavailable_reason
                )
            ),
        }
        with self._lock:
            self._target = VerificationTarget(
                step_id,
                board_pin,
                component_pin,
                component_id,
                electrical_supported=electrical_available,
            )
            self._evidence = evidence
            self._fusion = fuse_evidence(evidence, now_ms=now_ms)
            self._geometry_samples = []
            self._geometry_frame_ids = set()

    def request_geometry(self, step_id: str) -> bool:
        """Start/restart a five-frame manual dual-endpoint geometry check."""
        now_ms = self._now_ms()
        with self._lock:
            target = self._target
            if target is None or target.step_id != step_id:
                return False
            self._target = replace(
                target,
                geometry_requested=True,
                geometry_complete=False,
                geometry_generation=target.geometry_generation + 1,
            )
            self._geometry_samples = []
            self._geometry_frame_ids = set()
            self._evidence["geometry"] = VerificationEvidence.uncertain(
                "geometry",
                "collecting_geometry_samples",
                as_of_ms=now_ms,
                method="manual_dual_endpoint_consensus",
                details={
                    "sample_count": 0,
                    "sample_target": 5,
                    "required_agreement": 3,
                    "frozen": False,
                },
            )
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    @staticmethod
    def _geometry_signature(item: VerificationEvidence) -> str:
        actual_pin = str((item.details or {}).get("actual_pin", ""))
        return f"{item.status}:{item.reason}:{actual_pin}"

    @classmethod
    def _fuse_geometry_samples(
        cls, samples: list[VerificationEvidence], *, now_ms: float
    ) -> VerificationEvidence:
        signatures = Counter(cls._geometry_signature(item) for item in samples)
        pass_items = [item for item in samples if item.status == "pass"]
        common_signature, common_count = signatures.most_common(1)[0]
        representative = next(
            item for item in samples if cls._geometry_signature(item) == common_signature
        )
        counts = {
            signature: count for signature, count in sorted(signatures.items())
        }
        consensus_details = {
            **(representative.details or {}),
            "sample_count": len(samples),
            "sample_target": 5,
            "required_agreement": 3,
            "pass_count": len(pass_items),
            "outcome_counts": counts,
            "frozen": True,
        }
        if len(pass_items) >= 3:
            return VerificationEvidence(
                source="geometry",
                status="pass",
                score=sum(item.score for item in pass_items) / len(pass_items),
                quality=sum(item.quality for item in pass_items) / len(pass_items),
                reason="both_endpoints_near_targets",
                as_of_ms=now_ms,
                method="manual_dual_endpoint_consensus",
                details=consensus_details,
            )
        if common_count >= 3:
            matching = [
                item
                for item in samples
                if cls._geometry_signature(item) == common_signature
            ]
            return VerificationEvidence(
                source="geometry",
                status="fail" if representative.status == "fail" else "uncertain",
                score=(
                    sum(item.score for item in matching) / len(matching)
                    if representative.status == "fail"
                    else 0.0
                ),
                quality=sum(item.quality for item in matching) / len(matching),
                reason=representative.reason,
                as_of_ms=now_ms,
                method="manual_dual_endpoint_consensus",
                details=consensus_details,
            )
        return VerificationEvidence.uncertain(
            "geometry",
            "geometry_no_consensus",
            as_of_ms=now_ms,
            method="manual_dual_endpoint_consensus",
            quality=sum(item.quality for item in samples) / len(samples),
            details=consensus_details,
        )

    def add_geometry_sample(
        self,
        step_id: str,
        item: VerificationEvidence,
        *,
        frame_id: int,
        now_ms: float,
    ) -> bool:
        """Collect one unique wire-trace tick; freeze after five observations."""
        if item.source != "geometry":
            return False
        with self._lock:
            target = self._target
            if (
                target is None
                or target.step_id != step_id
                or not target.geometry_requested
                or target.geometry_complete
                or frame_id in self._geometry_frame_ids
            ):
                return False
            self._geometry_frame_ids.add(int(frame_id))
            self._geometry_samples.append(item)
            if len(self._geometry_samples) >= 5:
                self._evidence["geometry"] = self._fuse_geometry_samples(
                    self._geometry_samples[:5], now_ms=now_ms
                )
                self._target = replace(target, geometry_complete=True)
            else:
                self._evidence["geometry"] = VerificationEvidence.uncertain(
                    "geometry",
                    "collecting_geometry_samples",
                    as_of_ms=now_ms,
                    method="manual_dual_endpoint_consensus",
                    details={
                        "sample_count": len(self._geometry_samples),
                        "sample_target": 5,
                        "required_agreement": 3,
                        "pass_count": sum(
                            sample.status == "pass"
                            for sample in self._geometry_samples
                        ),
                        "frozen": False,
                    },
                )
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    def request_electrical(self, step_id: str) -> bool:
        """Start or restart the explicit final A0 challenge for one step."""
        now_ms = self._now_ms()
        with self._lock:
            target = self._target
            if (
                target is None
                or target.step_id != step_id
                or not target.electrical_supported
            ):
                return False
            self._target = replace(
                target,
                electrical_requested=True,
                electrical_generation=target.electrical_generation + 1,
            )
            self._evidence["electrical"] = VerificationEvidence.uncertain(
                "electrical",
                "collecting_a0_baseline",
                as_of_ms=now_ms,
                method="serial_a0_response",
            )
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    def set_final_visual_pending(self, step_id: str, *, now_ms: float) -> bool:
        """Mark the one-shot complete-wiring VLM request as in progress."""
        with self._lock:
            if self._target is None or self._target.step_id != step_id:
                return False
            self._evidence["visual"] = VerificationEvidence.uncertain(
                "visual",
                "vlm_final_checking",
                as_of_ms=now_ms,
                method=_FINAL_VLM_METHOD,
                details={"expected_connections": len(_FINAL_CONNECTION_PAIRS)},
            )
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    @staticmethod
    def _normalise_final_pin(value: object) -> str:
        return str(value or "").upper().replace("_P1", "")

    def set_final_visual_result(
        self,
        step_id: str,
        connections: Iterable[dict],
        *,
        note: str = "",
        now_ms: float,
    ) -> bool:
        """Store the final VLM result as the authoritative visual evidence."""
        by_pair: dict[tuple[str, str], dict] = {}
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            pair = (
                self._normalise_final_pin(connection.get("board_pin")),
                self._normalise_final_pin(connection.get("component_pin")),
            )
            by_pair[pair] = connection

        rows: list[dict[str, object]] = []
        for board_pin, component_pin in _FINAL_CONNECTION_PAIRS:
            item = by_pair.get((board_pin, component_pin))
            if item is None:
                rows.append({
                    "board_pin": board_pin,
                    "component_pin": component_pin,
                    "state": "uncertain",
                    "confidence": 0.0,
                    "evidence": "VLM did not return this expected connection",
                })
                continue
            try:
                confidence = max(0.0, min(float(item.get("confidence", 0.0)), 1.0))
            except (TypeError, ValueError):
                confidence = 0.0
            rows.append({
                "board_pin": board_pin,
                "component_pin": component_pin,
                "state": str(item.get("state", "uncertain")),
                "confidence": round(confidence, 3),
                "evidence": str(item.get("evidence", "")),
            })

        states = [str(row["state"]) for row in rows]
        confidences = [float(row["confidence"]) for row in rows]
        partial_points = [
            confidence if row["state"] == "inserted_target" else
            0.50 if row["state"] == "inserted_adjacent" else
            0.0
            for row, confidence in zip(rows, confidences)
        ]
        adjacent = [
            float(row["confidence"])
            for row in rows
            if row["state"] == "inserted_adjacent"
        ]
        empty = [
            float(row["confidence"])
            for row in rows
            if row["state"] == "empty"
        ]
        if all(state == "inserted_target" for state in states):
            status = "pass"
            score = min(confidences, default=0.0)
            reason = "final_wiring_visual_confirmed"
        elif adjacent:
            # An adjacent result is not correct, but it is useful partial
            # evidence: the other seated endpoints still contribute and the
            # near-miss gets half credit. Keep it uncertain so it can never
            # unlock completion by itself.
            status = "uncertain"
            score = sum(partial_points) / len(partial_points) if partial_points else 0.0
            reason = "final_wiring_adjacent_pin"
        elif empty:
            status = "fail"
            score = max(empty)
            reason = "final_wiring_connector_missing"
        else:
            status = "uncertain"
            score = 0.0
            reason = "final_wiring_visual_uncertain"

        evidence = VerificationEvidence(
            source="visual",
            status=status,
            score=score,
            quality=sum(confidences) / len(confidences) if confidences else 0.0,
            reason=reason,
            as_of_ms=now_ms,
            # Final VLM evidence is latched until the user explicitly runs the
            # final check again or changes guidance step.
            fresh_until_ms=0.0,
            method=_FINAL_VLM_METHOD,
            details={
                "connections": rows,
                "note": note,
                "partial": bool(adjacent) and status == "uncertain",
                "partial_score": round(score, 3),
                "target_count": states.count("inserted_target"),
                "adjacent_count": states.count("inserted_adjacent"),
            },
        )
        with self._lock:
            if self._target is None or self._target.step_id != step_id:
                return False
            self._evidence["visual"] = evidence
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    def set_final_visual_error(
        self,
        step_id: str,
        *,
        error: str,
        now_ms: float,
    ) -> bool:
        """Keep final-check failures visible without turning them into a pass."""
        with self._lock:
            if self._target is None or self._target.step_id != step_id:
                return False
            self._evidence["visual"] = VerificationEvidence.uncertain(
                "visual",
                "vlm_final_error",
                as_of_ms=now_ms,
                method=_FINAL_VLM_METHOD,
                details={"error": error},
            )
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    def clear(self) -> None:
        with self._lock:
            self._target = None
            self._evidence = {}
            self._fusion = None
            self._geometry_samples = []
            self._geometry_frame_ids = set()

    def target(self) -> VerificationTarget | None:
        with self._lock:
            return self._target

    def update(self, step_id: str, items: Iterable[VerificationEvidence], *, now_ms: float) -> bool:
        with self._lock:
            if self._target is None or self._target.step_id != step_id:
                return False
            for item in items:
                existing = self._evidence.get(item.source)
                keep_final_vlm = (
                    item.source == "visual"
                    and existing is not None
                    and existing.method == _FINAL_VLM_METHOD
                    and item.method == "guided_roi"
                )
                keep_manual_vlm = (
                    item.source == "visual"
                    and existing is not None
                    and existing.method == "vlm_insertion"
                    and item.method == "guided_roi"
                )
                if keep_final_vlm or keep_manual_vlm:
                    # Explicit VLM evidence belongs to the captured frame. Live
                    # ROI/HSV guidance must not alter it when pose tracking
                    # drops, the board moves, or a hand enters the scene.
                    continue
                self._evidence[item.source] = item
            self._fusion = fuse_evidence(self._evidence, now_ms=now_ms)
            return True

    def snapshot(self, now_ms: float | None = None) -> dict:
        current_ms = self._now_ms() if now_ms is None else float(now_ms)
        with self._lock:
            if self._target is None:
                return {"active": False, "target": None, "evidence": None, "fusion": None}
            fusion = fuse_evidence(self._evidence, now_ms=current_ms)
            return {
                "active": True,
                "target": {
                    "step_id": self._target.step_id,
                    "board_pin": self._target.board_pin,
                    "component_pin": self._target.component_pin,
                    "component_id": self._target.component_id,
                    "geometry_requested": self._target.geometry_requested,
                    "geometry_complete": self._target.geometry_complete,
                    "geometry_generation": self._target.geometry_generation,
                    "electrical_supported": self._target.electrical_supported,
                    "electrical_requested": self._target.electrical_requested,
                    "electrical_generation": self._target.electrical_generation,
                },
                "evidence": {
                    source: self._evidence[source].as_dict(current_ms)
                    for source in ("geometry", "visual", "electrical")
                    if source in self._evidence
                },
                "fusion": fusion.as_dict(),
            }

    def message(self, board_id: str, frame_id: int, ts_ms: float) -> dict | None:
        snapshot = self.snapshot(ts_ms)
        if not snapshot["active"]:
            return None
        return {
            "type": "verification_update",
            "board_id": board_id,
            "frame_id": int(frame_id),
            "ts_ms": float(ts_ms),
            **snapshot,
        }
