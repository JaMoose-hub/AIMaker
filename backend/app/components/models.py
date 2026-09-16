from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ComponentPin(StrictModel):
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    direction: Literal["input", "output", "bidirectional", "power"]
    required: bool = True
    voltage: float | None = None
    signal_voltage: float | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    required_board_role: str | None = None
    required_rail: str | None = None


class ComponentSpec(StrictModel):
    schema_version: Literal["1.0"]
    id: str = Field(min_length=1)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    name: dict[str, str]
    pins: list[ComponentPin] = Field(min_length=1)

    def pin_by_id(self, pin_id: str) -> ComponentPin | None:
        return next((pin for pin in self.pins if pin.id == pin_id), None)
