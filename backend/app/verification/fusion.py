"""Conservative fusion for correlated camera evidence plus electrical proof."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from app.verification.models import EvidenceSource, VerificationEvidence

VerificationLevel = Literal["none", "geometry", "visual", "electrical"]
VerificationVerdict = Literal[
    "unverified",
    "position_matched",
    "visual_verified",
    "verified",
    "wrong_pin",
    "not_inserted",
    "electrical_mismatch",
    "evidence_conflict",
    "evidence_incomplete",
    "uncertain",
]


@dataclass(frozen=True)
class FusionThresholds:
    geometry_pass: float = 0.70
    visual_pass: float = 0.75
    electrical_pass: float = 0.85
    geometry_fail: float = 0.75
    visual_fail: float = 0.75
    electrical_fail: float = 0.85


@dataclass(frozen=True)
class FusionResult:
    verdict: VerificationVerdict
    verification_level: VerificationLevel
    overall_confidence: int
    verdict_confidence: int
    score_cap: int
    reason: str

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "verification_level": self.verification_level,
            "overall_confidence": self.overall_confidence,
            "verdict_confidence": self.verdict_confidence,
            "score_cap": self.score_cap,
            "reason": self.reason,
        }


def _harmonic(left: float, right: float) -> float:
    total = left + right
    return 0.0 if total <= 0.0 else (2.0 * left * right) / total


def _score(value: float, cap: int) -> int:
    return min(cap, max(0, round(100.0 * value)))


def _failure(
    verdict: VerificationVerdict,
    reason: str,
    confidence: float,
    *,
    conflict: bool = False,
) -> FusionResult:
    # ``overall_confidence`` always means confidence that the wiring is
    # correct.  A highly certain failure therefore produces a low number;
    # ``verdict_confidence`` separately says how strongly the failure is known.
    correctness = min(20, max(0, round(100.0 * (1.0 - confidence))))
    return FusionResult(
        verdict="evidence_conflict" if conflict else verdict,
        verification_level="electrical" if verdict == "electrical_mismatch" or conflict else "visual",
        overall_confidence=correctness,
        verdict_confidence=max(0, min(99, round(100.0 * confidence))),
        score_cap=20,
        reason=reason,
    )


def fuse_evidence(
    evidence: Mapping[EvidenceSource, VerificationEvidence],
    *,
    now_ms: float,
    thresholds: FusionThresholds | None = None,
) -> FusionResult:
    """Fuse one active step. Hard contradictions are resolved before scoring."""
    limits = thresholds or FusionThresholds()
    geometry = evidence.get("geometry", VerificationEvidence.unavailable("geometry")).effective(now_ms)
    visual = evidence.get("visual", VerificationEvidence.unavailable("visual")).effective(now_ms)
    electrical = evidence.get("electrical", VerificationEvidence.unavailable("electrical")).effective(now_ms)

    # Guided POC mode skips wire-endpoint geometry. Board and component poses
    # may still place the VLM crops, but they are not evidence that can block
    # the wiring step.
    geometry_skipped = (
        geometry.status == "unavailable"
        and geometry.reason == "geometry_skipped_for_vlm"
    )

    g_pass = geometry.status == "pass" and geometry.score >= limits.geometry_pass
    v_pass = visual.status == "pass" and visual.score >= limits.visual_pass
    v_partial = (
        visual.status == "uncertain"
        and visual.method == "vlm_final_wiring"
        and bool((visual.details or {}).get("partial"))
        and visual.score > 0.0
    )
    e_pass = electrical.status == "pass" and electrical.score >= limits.electrical_pass
    g_fail = geometry.status == "fail" and geometry.score >= limits.geometry_fail
    v_fail = visual.status == "fail" and visual.score >= limits.visual_fail
    e_fail = electrical.status == "fail" and electrical.score >= limits.electrical_fail

    # Electrical disagreement with a strong camera claim must stay visible as
    # a conflict; averaging these values would hide the most useful diagnosis.
    if e_fail:
        return _failure(
            "electrical_mismatch",
            electrical.reason,
            electrical.score,
            conflict=g_pass and v_pass,
        )
    if e_pass and (g_fail or v_fail):
        failed = geometry if g_fail else visual
        return _failure(
            "evidence_conflict",
            f"electrical_pass_but_{failed.source}_failed",
            # Electrical proof confirms a signal response, but it cannot make
            # a visually misplaced connector correct. Keep the score tied to
            # the failing camera evidence so a successful Serial check does
            # not look like a penalty (20 remains the safety cap here).
            failed.score,
            conflict=True,
        )
    if g_fail:
        return _failure("wrong_pin", geometry.reason, geometry.score)
    if v_fail:
        return _failure("not_inserted", visual.reason, visual.score)

    # Serial may still contain a valid previous A0 response, but it cannot
    # keep the complete guided result green after the camera loses focus on
    # either endpoint. Return to zero until VLM is run again.
    if geometry_skipped and e_pass and not v_pass and not v_partial:
        return FusionResult(
            verdict="evidence_incomplete",
            verification_level="electrical",
            overall_confidence=0,
            verdict_confidence=_score(electrical.score, 99),
            score_cap=0,
            reason=(
                "visual_focus_lost"
                if visual.reason in {
                    "board_not_tracked",
                    "component_not_tracked",
                    "endpoint_not_visible",
                    "lighting_unready",
                    "hand_occlusion",
                    "scene_moving",
                    "baseline_rebased",
                }
                else "visual_check_incomplete"
            ),
        )

    if g_pass and v_pass:
        camera_score = _harmonic(geometry.score, visual.score)
        if e_pass:
            combined = 0.35 * camera_score + 0.65 * electrical.score
            return FusionResult(
                verdict="verified",
                verification_level="electrical",
                overall_confidence=_score(combined, 99),
                verdict_confidence=_score(min(camera_score, electrical.score), 99),
                score_cap=99,
                reason="all_layers_passed",
            )
        return FusionResult(
            verdict="visual_verified",
            verification_level="visual",
            overall_confidence=_score(camera_score, 79),
            verdict_confidence=_score(min(geometry.score, visual.score), 99),
            score_cap=79,
            reason=(
                "electrical_not_available"
                if electrical.status == "unavailable"
                else "electrical_not_confirmed"
            ),
        )

    # In the guided VLM + Serial flow, the final AO step is complete when the
    # visual connector check and the A0 response both pass. Geometry is only a
    # locator for the crops and is intentionally absent from this verdict.
    if geometry_skipped and v_pass and e_pass:
        combined = _harmonic(visual.score, electrical.score)
        return FusionResult(
            verdict="verified",
            verification_level="electrical",
            overall_confidence=_score(combined, 95),
            verdict_confidence=_score(min(visual.score, electrical.score), 99),
            score_cap=95,
            reason="visual_and_electrical_passed_geometry_skipped",
        )

    if e_pass:
        # A pin-specific electrical result is strong, but the requested full
        # three-layer story is incomplete until both camera layers are usable.
        available_camera = max(
            geometry.score if geometry.status == "pass" else 0.0,
            visual.score if visual.status == "pass" or v_partial else 0.0,
        )
        combined = 0.75 * electrical.score + 0.25 * available_camera
        partial_cap = 79 if v_partial else 89
        return FusionResult(
            verdict="evidence_incomplete",
            verification_level="electrical",
            overall_confidence=_score(combined, partial_cap),
            verdict_confidence=_score(electrical.score, 99),
            score_cap=partial_cap,
            reason=(
                "electrical_pass_visual_partial"
                if v_partial
                else "electrical_pass_visual_incomplete"
            ),
        )

    if geometry_skipped and v_partial:
        return FusionResult(
            verdict="evidence_incomplete",
            verification_level="visual",
            overall_confidence=_score(visual.score, 59),
            verdict_confidence=_score(visual.score, 99),
            score_cap=59,
            reason="visual_partial_adjacent_pin",
        )

    if g_pass:
        return FusionResult(
            verdict="position_matched",
            verification_level="geometry",
            overall_confidence=_score(geometry.score, 49),
            verdict_confidence=_score(geometry.score, 99),
            score_cap=49,
            reason="awaiting_visual_insertion",
        )

    if v_pass:
        # Appearance alone is useful evidence (especially when guidance was
        # started after a cable was already present), but it cannot name a
        # GPIO safely. Show that progress instead of a misleading 0 while
        # keeping it below the geometry-only cap.
        if geometry_skipped:
            return FusionResult(
                verdict="visual_verified",
                verification_level="visual",
                overall_confidence=_score(visual.score, 79),
                verdict_confidence=_score(visual.score, 99),
                score_cap=79,
                reason=(
                    "electrical_not_available"
                    if electrical.status == "unavailable"
                    else "electrical_not_confirmed"
                ),
            )
        return FusionResult(
            verdict="evidence_incomplete",
            verification_level="visual",
            overall_confidence=_score(visual.score, 39),
            verdict_confidence=_score(visual.score, 99),
            score_cap=39,
            reason="visual_pass_geometry_incomplete",
        )

    has_attempt = any(item.status != "unavailable" for item in (geometry, visual, electrical))
    return FusionResult(
        verdict="uncertain" if has_attempt else "unverified",
        verification_level="none",
        overall_confidence=0,
        verdict_confidence=0,
        score_cap=0,
        reason=(
            next(
                (
                    item.reason
                    for item in (geometry, visual, electrical)
                    if item.status == "uncertain" and item.reason != "not_evaluated"
                ),
                "awaiting_evidence",
            )
            if has_attempt
            else "no_evidence"
        ),
    )
