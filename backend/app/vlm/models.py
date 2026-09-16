"""Fixed, conservative JSON contract for the optional scene VLM."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NormalizedBox(StrictModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0, le=1.0)
    h: float = Field(ge=0.0, le=1.0)


class SceneBoard(StrictModel):
    type: str | None
    confidence: float = Field(ge=0.0, le=1.0)


class SceneModule(StrictModel):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_norm: NormalizedBox
    pins: list[str] = Field(default_factory=list)


class SceneConnection(StrictModel):
    from_device: str | None
    from_pin: str | None
    to_device: str | None
    to_pin: str | None
    status: Literal["connected", "candidate", "uncertain", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)


class SceneIssue(StrictModel):
    severity: Literal["info", "warning", "danger"]
    type: str = Field(min_length=1)
    message: str = Field(min_length=1)
    related_connection: int | None = Field(default=None, ge=0)


class SceneUncertainItem(StrictModel):
    kind: str = Field(min_length=1)
    message: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SceneUnderstanding(StrictModel):
    schema_version: Literal["1.0"]
    authority: Literal["advisory_only"]
    board: SceneBoard
    modules: list[SceneModule]
    connections: list[SceneConnection]
    issues: list[SceneIssue]
    uncertain_items: list[SceneUncertainItem]
    overall_confidence: float = Field(ge=0.0, le=1.0)


class SceneInput(StrictModel):
    """Structured evidence sent alongside the image to a VLM provider."""

    prompt: str = Field(min_length=1)
    cv: dict = Field(default_factory=dict)
    ocr: list[dict] = Field(default_factory=list)
    board_profile: dict = Field(default_factory=dict)


InsertionState = Literal[
    "inserted_target",
    "inserted_adjacent",
    "empty",
    "occluded",
    "uncertain",
]


class InsertionEndpoint(StrictModel):
    state: InsertionState
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1, max_length=500)


class InsertionUnderstanding(StrictModel):
    """Strict output for two centered endpoint crops.

    This is deliberately narrower than SceneUnderstanding. It cannot claim
    continuity, voltage, or safety and therefore has no electrical fields.
    """

    schema_version: Literal["1.0"]
    authority: Literal["visual_advisory"]
    board_endpoint: InsertionEndpoint
    component_endpoint: InsertionEndpoint
    same_wire: Literal["likely", "unlikely", "uncertain"]
    same_wire_confidence: float = Field(ge=0.0, le=1.0)
    note: str = Field(default="", max_length=500)


class FinalConnectionCheck(StrictModel):
    """Visual-only result for one expected final wiring pair."""

    board_pin: str = Field(min_length=1, max_length=64)
    component_pin: str = Field(min_length=1, max_length=64)
    state: InsertionState
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1, max_length=500)


class FinalWiringUnderstanding(StrictModel):
    """One VLM pass over all expected photoresistor connections."""

    schema_version: Literal["1.0"]
    authority: Literal["visual_advisory"]
    connections: list[FinalConnectionCheck] = Field(min_length=1, max_length=8)
    note: str = Field(default="", max_length=500)


WireColour = Literal[
    "red",
    "orange",
    "brown",
    "yellow",
    "green",
    "blue",
    "purple",
    "unknown",
]


class WireColorUnderstanding(StrictModel):
    """One manual VLM opinion about the insulation at two guided endpoints.

    It deliberately contains no pin-placement, insertion-depth, continuity, or
    voltage claim.  This keeps an optional colour opinion separate from the
    existing visual-insertion and Serial evidence paths.
    """

    schema_version: Literal["1.0"]
    authority: Literal["visual_advisory"]
    board_color: WireColour
    component_color: WireColour
    same_color: Literal["match", "mismatch", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    board_evidence: str = Field(min_length=1, max_length=500)
    component_evidence: str = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=500)
