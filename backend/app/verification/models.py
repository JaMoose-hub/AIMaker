"""Typed evidence shared by all wiring-verification providers."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

EvidenceSource = Literal["geometry", "visual", "electrical"]
EvidenceStatus = Literal["pass", "fail", "uncertain", "unavailable"]


def _unit(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


@dataclass(frozen=True)
class VerificationEvidence:
    """One provider's latest statement about the active wiring step.

    ``score`` is confidence in ``status`` rather than an independently
    calibrated probability that the complete circuit is correct.  The fusion
    layer converts pass/fail evidence conservatively and keeps unavailable or
    stale evidence explicit.
    """

    source: EvidenceSource
    status: EvidenceStatus
    score: float = 0.0
    quality: float = 0.0
    reason: str = "not_evaluated"
    as_of_ms: float = 0.0
    fresh_until_ms: float = 0.0
    method: str = "none"
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _unit(self.score))
        object.__setattr__(self, "quality", _unit(self.quality))
        object.__setattr__(self, "details", dict(self.details))

    @classmethod
    def unavailable(cls, source: EvidenceSource, reason: str = "not_configured") -> "VerificationEvidence":
        return cls(source=source, status="unavailable", reason=reason)

    @classmethod
    def uncertain(
        cls,
        source: EvidenceSource,
        reason: str,
        *,
        as_of_ms: float = 0.0,
        fresh_until_ms: float = 0.0,
        method: str = "none",
        quality: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> "VerificationEvidence":
        return cls(
            source=source,
            status="uncertain",
            reason=reason,
            as_of_ms=as_of_ms,
            fresh_until_ms=fresh_until_ms,
            method=method,
            quality=quality,
            details=details or {},
        )

    def effective(self, now_ms: float) -> "VerificationEvidence":
        if (
            self.status not in {"unavailable", "uncertain"}
            and self.fresh_until_ms > 0.0
            and now_ms > self.fresh_until_ms
        ):
            return replace(
                self,
                status="uncertain",
                score=0.0,
                reason="stale_evidence",
                details={**self.details, "previous_status": self.status},
            )
        return self

    def as_dict(self, now_ms: float | None = None) -> dict[str, Any]:
        item = self.effective(now_ms) if now_ms is not None else self
        result: dict[str, Any] = {
            "status": item.status,
            "score": round(item.score, 3),
            "quality": round(item.quality, 3),
            "reason": item.reason,
            "method": item.method,
            "as_of_ms": round(float(item.as_of_ms), 3),
            "fresh_until_ms": round(float(item.fresh_until_ms), 3),
        }
        if item.details:
            result["details"] = dict(item.details)
        return result
