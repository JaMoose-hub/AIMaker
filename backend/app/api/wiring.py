"""Safe, pure wiring-plan and observed-connection endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.components.store import ComponentNotFoundError
from app.components.resolver import evaluate_observed_connections, resolve_assignment

router = APIRouter(prefix="/api")


class WiringBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1)
    pin_assignment: dict[str, str] = Field(default_factory=dict)


class ConnectionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_pin: str = Field(min_length=1)
    board_pin: str | None = None
    status: str = "candidate"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class WiringCheckBody(WiringBody):
    observations: list[ConnectionObservation] = Field(default_factory=list)


def _component_store(request: Request):
    return request.app.state.component_store


@router.get("/components")
async def list_components(request: Request) -> dict:
    store = _component_store(request)
    return {
        "components": [
            {
                "id": spec.id,
                "version": spec.version,
                "name": spec.name,
                "pin_ids": [pin.id for pin in spec.pins],
            }
            for spec in store.list()
        ]
    }


@router.get("/components/{component_id}")
async def get_component(component_id: str, request: Request) -> dict:
    try:
        return _component_store(request).raw(component_id)
    except ComponentNotFoundError:
        return {"ok": False, "error": "unknown_component", "component_id": component_id}


@router.post("/wiring/plans")
async def create_wiring_plan(body: WiringBody, request: Request) -> dict:
    try:
        spec = _component_store(request).get(body.component_id)
    except ComponentNotFoundError:
        return {"ok": False, "error": "unknown_component", "component_id": body.component_id}
    return resolve_assignment(request.app.state.profile, spec, body.pin_assignment)


@router.post("/wiring/check")
async def check_wiring(body: WiringCheckBody, request: Request) -> dict:
    try:
        spec = _component_store(request).get(body.component_id)
    except ComponentNotFoundError:
        return {"ok": False, "error": "unknown_component", "component_id": body.component_id}
    return evaluate_observed_connections(
        request.app.state.profile,
        spec,
        body.pin_assignment,
        [item.model_dump() for item in body.observations],
    )
