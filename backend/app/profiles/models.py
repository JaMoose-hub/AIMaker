"""Pydantic models for board profile files (profiles/boards/<id>/board.json).

This module is the runtime source of truth for the profile format.
schemas/board-profile.schema.json mirrors it for documentation/CI validation.

Conventions:
- All human-readable text is an i18n object: {"zh-TW": "...", "en": "..."}.
- Pin positions are 3D millimeters in the board frame:
  origin = top-left corner of the PCB seen from above (USB-C on the left),
  x -> right along the long edge, y -> down, z -> up from the PCB plane
  (header pin openings sit at z = header_top_z_mm, NOT z=0).
- reference.mm_to_px is a 3x3 homography mapping board-mm (x, y, 1) to
  reference-image pixels; for the synthetic orthographic reference it is a
  pure scale, for a real photo it comes from tools/calibrate_reference.py.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

I18nText = dict[str, str]

CapabilityType = Literal[
    "digital_io", "pwm", "adc", "i2c", "spi", "uart",
    "interrupt", "power", "reset", "aref", "boot", "nc",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Capability(StrictModel):
    type: CapabilityType
    role: str | None = None       # e.g. i2c: "sda"/"scl", spi: "mosi"/"miso"/"sck"/"cs", uart: "tx"/"rx"
    bus: str | None = None        # bus id, e.g. "i2c0"
    channel: str | None = None    # adc channel, e.g. "A4"
    rail: str | None = None       # power: "3v3" | "5v" | "gnd" | "vin" | "ioref"
    direction: str | None = None  # power: "input" | "output" | "bidirectional"
    mcu_pin: str | None = None    # e.g. "PC1"
    note: I18nText | None = None


class Electrical(StrictModel):
    voltage: float
    max_current_ma: float | None = None
    five_volt_tolerant: bool | None = None


class PinWarning(StrictModel):
    severity: Literal["info", "warning", "danger"]
    text: I18nText


class Pin(StrictModel):
    id: str                      # unique, e.g. "D3", "A4", "GND_P1"
    silkscreen: str              # label printed on the board, e.g. "~3", "GND"
    header: str                  # header id from BoardProfile.headers
    index: int                   # 0-based position within its header row
    pos_mm: tuple[float, float, float]
    capabilities: list[Capability]
    electrical: Electrical | None = None
    description: I18nText
    usage_examples: list[I18nText] = Field(default_factory=list)
    warnings: list[PinWarning] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Bus(StrictModel):
    id: str                      # "i2c0", "spi0", "uart0"
    type: Literal["i2c", "spi", "uart"]
    pins: list[str]              # pin ids
    note: I18nText | None = None


class HeaderRow(StrictModel):
    id: str                      # e.g. "JDIGITAL_HI", "JANALOG"
    name: I18nText
    side: Literal["top", "bottom", "left", "right"]


class ChipInfo(StrictModel):
    part: str
    core: str | None = None
    max_clock_mhz: float | None = None
    os: str | None = None
    role_note: I18nText | None = None


class BoardInfo(StrictModel):
    id: str                      # "arduino-uno-q" (== profile folder name)
    name: I18nText
    vendor: str
    revision: str | None = None
    mcu: ChipInfo
    mpu: ChipInfo | None = None
    logic_voltage: float
    five_volt_tolerant: bool
    form_factor: str
    outline_mm: tuple[float, float]   # (width_x, height_y) e.g. (68.58, 53.34)
    header_top_z_mm: float            # pin opening height above PCB plane
    docs_url: str | None = None


class ReferenceMeta(StrictModel):
    image: str                   # filename relative to the profile folder
    width_px: int
    height_px: int
    mm_to_px: list[list[float]]  # 3x3 homography board-mm -> reference px
    feature_mask: str | None = None  # optional mask image filename (255 = usable)


class PoseLandmark(StrictModel):
    """Ordered semantic keypoint used by a board-specific pose model."""

    id: str
    role: Literal["board_corner", "header"]
    pos_mm: tuple[float, float, float] | None = None
    pin_id: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "PoseLandmark":
        if (self.pos_mm is None) == (self.pin_id is None):
            raise ValueError("pose landmark requires exactly one of pos_mm or pin_id")
        return self


class BoardProfile(StrictModel):
    schema_version: str
    board: BoardInfo
    reference: ReferenceMeta
    pose_landmarks: list[PoseLandmark] = Field(default_factory=list)
    headers: list[HeaderRow]
    buses: list[Bus] = Field(default_factory=list)
    groups: dict[str, list[str]] = Field(default_factory=dict)  # named pin-id sets
    pins: list[Pin]

    def pin_by_id(self, pin_id: str) -> Pin | None:
        return next((p for p in self.pins if p.id == pin_id), None)

    def pins_with_capability(self, cap_type: str) -> list[Pin]:
        return [p for p in self.pins if any(c.type == cap_type for c in p.capabilities)]

    def bus_by_id(self, bus_id: str) -> Bus | None:
        return next((b for b in self.buses if b.id == bus_id), None)

    def resolved_pose_landmarks(self) -> list[tuple[str, tuple[float, float, float]]]:
        """Resolve ordered keypoints; old profiles retain the four-corner contract."""
        if not self.pose_landmarks:
            width, height = self.board.outline_mm
            return [
                ("board_TL", (0.0, 0.0, 0.0)),
                ("board_TR", (float(width), 0.0, 0.0)),
                ("board_BR", (float(width), float(height), 0.0)),
                ("board_BL", (0.0, float(height), 0.0)),
            ]
        resolved: list[tuple[str, tuple[float, float, float]]] = []
        for landmark in self.pose_landmarks:
            if landmark.pin_id is not None:
                pin = self.pin_by_id(landmark.pin_id)
                if pin is None:
                    raise ValueError(
                        f"pose landmark {landmark.id!r} references unknown pin "
                        f"{landmark.pin_id!r}"
                    )
                position = pin.pos_mm
            else:
                assert landmark.pos_mm is not None
                position = landmark.pos_mm
            resolved.append((landmark.id, tuple(float(v) for v in position)))
        return resolved
