"""Three-layer wiring verification: geometry, visual insertion, electrical."""

from app.verification.fusion import FusionResult, FusionThresholds, fuse_evidence
from app.verification.models import VerificationEvidence
from app.verification.state import VerificationState

__all__ = [
    "FusionResult",
    "FusionThresholds",
    "VerificationEvidence",
    "VerificationState",
    "fuse_evidence",
]
