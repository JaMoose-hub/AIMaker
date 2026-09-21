"""MVP Pi connection, deployment and console endpoints."""
from fastapi import APIRouter, Request, HTTPException
from typing import Literal
from pydantic import BaseModel, Field
from app.designs import CATALOG, MODULES, ComponentId, profile_versions, wiring_for

router = APIRouter(prefix="/api/pi", tags=["pi"])


class ProjectContext(BaseModel):
    component_ids: list[ComponentId] = Field(min_length=1, max_length=2)
    catalog_version: str
    profile_versions: dict | None = None


class DeployRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200_000)
    project: ProjectContext | None = None


# Sync endpoints run in FastAPI's worker pool, independent of MJPEG/WS.
@router.post("/connect")
def connect(request: Request):
    return request.app.state.pi_deployer.connect()


@router.post("/deploy")
def deploy(body: DeployRequest, request: Request):
    if body.project:
        errors = [MODULES[cid]["runtime"]["reason"] for cid in body.project.component_ids if not MODULES[cid]["runtime"]["supported"]]
        if body.project.catalog_version != CATALOG["version"]:
            errors.append("零件目錄已更新，請重新產生作品。")
        if body.project.profile_versions and body.project.profile_versions != profile_versions(body.project.component_ids):
            errors.append("硬體 Profile 已更新，請重新產生作品並核對接線。")
        try:
            wiring_for(body.project.component_ids)
        except ValueError as error:
            errors.append(str(error))
        if errors:
            return {"ok": False, "error": "\n".join(errors), "status": request.app.state.pi_deployer.snapshot()}
        imports = sorted({i for cid in body.project.component_ids for i in MODULES[cid]["runtime"]["imports"]})
        devices = sorted({d for cid in body.project.component_ids for d in MODULES[cid]["runtime"]["devices"]})
        return request.app.state.pi_deployer.deploy(body.code, imports=imports, devices=devices)
    return request.app.state.pi_deployer.deploy(body.code)


@router.get("/status")
def status(request: Request):
    return request.app.state.pi_deployer.status()


class TestWire(BaseModel):
    componentId: ComponentId
    componentPin: str = Field(max_length=40)
    boardPin: str = Field(max_length=40)
    connectionKind: str = Field(max_length=40)


class ComponentTestRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=150)
    revision: int = Field(ge=0)
    component_id: ComponentId
    catalog_version: str = Field(max_length=50)
    profile_versions: dict
    guide_key: str = Field(min_length=1, max_length=8192)
    wires: list[TestWire] = Field(min_length=1, max_length=12)


class TestAction(BaseModel):
    action: Literal["stop", "invalidate", "stop_project", "near", "far", "visual"]
    guide_key: str = Field(default="", max_length=8192)
    code: str | None = Field(default=None, pattern=r"^\d{4}$")
    appearance: Literal["normal", "black", "white", "abnormal"] | None = None


@router.get("/component-tests")
def component_tests(request: Request, project_id: str | None = None):
    return request.app.state.component_tests.status(project_id)


@router.post("/component-tests")
def start_component_test(body: ComponentTestRequest, request: Request):
    try:
        return request.app.state.component_tests.start(body.model_dump())
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/component-tests/{run_id}/action")
def component_test_action(run_id: str, body: TestAction, request: Request):
    try:
        return request.app.state.component_tests.action(run_id, **body.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
