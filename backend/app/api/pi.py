"""MVP Pi connection, deployment and console endpoints."""
from fastapi import APIRouter, Request
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
