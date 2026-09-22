"""AI jobs are isolated from video/GPIO and never auto-deploy their result."""
import copy
import threading
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.codex_bridge import CodexBridge
from app.designs import CATALOG, AssistantReply, ConversationReply, DesignProposal, GenerateRequest, compile_design, demo_design, proposal_schema
from app.design_prompt import build_design_prompt
from app.ai_costs import estimate_cost, resolve_selection
from app.project_images import ProjectImageStore, build_image_prompt
from app.design_migration import migrate_maker_state

router = APIRouter(prefix="/api", tags=["maker"])


class DesignService:
    def __init__(self, bridge=None, image_store=None):
        self.bridge = bridge or CodexBridge()
        self.images = image_store or ProjectImageStore()
        self.lock = threading.Lock()
        self.jobs = {}
        self.busy = False

    def submit(self, body: GenerateRequest):
        # Resolve once before enqueueing: the estimate and real job use the same explicit settings.
        estimate = self.estimate(body)
        body = body.model_copy(update={"model": estimate["model"], "effort": estimate["effort"]})
        with self.lock:
            if self.busy:
                raise HTTPException(409, "已有設計正在生成，請稍後重試。")
            self.busy = True
            job_id = str(uuid4())
            self.jobs[job_id] = {"id": job_id, "status": "generating", "phase": "design", "design": None, "error": None,
                                 "model": body.model, "effort": body.effort, "estimate": estimate,
                                 "design_mode": body.design_mode,
                                 "persisted": body.generate_image and body.intent in {"design", "auto"}}
            try:
                if self.jobs[job_id]["persisted"]:
                    self.images.save_job(self.jobs[job_id])
            except OSError:
                self.busy = False
                raise HTTPException(503, "無法保存生成工作；未呼叫雲端模型。")
            if len(self.jobs) > 30:
                self.jobs.pop(next(iter(self.jobs)))
        threading.Thread(target=self._generate, args=(job_id, body), daemon=True, name="maker-design").start()
        return {"job_id": job_id}

    def estimate(self, body):
        try:
            model, effort = resolve_selection(self.bridge.models(), body.model, body.effort)
            result = estimate_cost(build_design_prompt(body), proposal_schema(body.intent), model, effort, body.expected_output_tokens)
            result["image_generation"] = {"requested": body.generate_image and body.intent == "design",
                                          "conditional": body.generate_image and body.intent == "auto",
                                          "included_in_estimate": False, "billing_mode": "chatgpt",
                                          "estimated_cost": None}
            return result
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except Exception as error:
            raise HTTPException(503, str(error)) from error

    def _generate(self, job_id, body):
        try:
            prompt = build_design_prompt(body)
            raw = self.bridge.generate(prompt, proposal_schema(body.intent), model=body.model, effort=body.effort)
            if body.intent == "auto":
                reply = ConversationReply.model_validate(raw)
                with self.lock:
                    self.jobs[job_id]["resolved_action"] = reply.action
                if reply.action == "answer":
                    with self.lock:
                        self.jobs[job_id].update(status="completed", answer=reply.answer)
                        if self.jobs[job_id].get("persisted"):
                            self.images.save_job(self.jobs[job_id])
                        self.busy = False
                    return
                body = body.model_copy(update={"intent": "design", "design_mode": "free" if reply.action == "redesign" else "fixed"})
                raw = reply.proposal.model_dump()
                with self.lock:
                    self.jobs[job_id].update(design_mode=body.design_mode, explanation=reply.answer)
            if body.intent == "ask":
                answer = AssistantReply.model_validate(raw).answer
                with self.lock:
                    self.jobs[job_id].update(status="completed", answer=answer)
                    self.busy = False
                return
            proposal = DesignProposal.model_validate(raw)
            if not set(proposal.component_ids).issubset(body.component_ids):
                raise ValueError("AI selected a module outside the available parts")
            design = compile_design(proposal, body.prompt, current=body.current)
            design["generation"] = {"model": body.model, "effort": body.effort, "design_mode": body.design_mode}
            if body.generate_image:
                self._render_image(job_id, design, body.model, body.effort, body.current)
            update = {"status": "completed", "design": design}
        except Exception as error:
            update = {"status": "failed", "error": str(error)[:3000]}
        with self.lock:
            self.jobs[job_id].update(update)
            self.busy = False
            if self.jobs[job_id].get("persisted"):
                try:
                    self.images.save_job(self.jobs[job_id])
                except OSError:
                    self.jobs[job_id].update(status="failed", error="生成工作保存失敗；圖片可能已保存，請檢查磁碟。")

    def _render_image(self, job_id, design, model, effort, current=None):
        design.update(image_required=True, image_job_id=job_id)
        design.pop("image_error", None)
        image_id = uuid4().hex
        try:
            with self.lock:
                self.jobs[job_id].update(phase="image", design=copy.deepcopy(design))
                # Legacy persisted retries keep their original edit semantics.
                mode = self.jobs[job_id].get("design_mode", "fixed")
                if mode == "free":
                    self.jobs[job_id].pop("reference_image", None)
                elif current and current.get("image"):
                    self.jobs[job_id]["reference_image"] = {"id": current["image"].get("id")}
                self.images.save_job(self.jobs[job_id])
                reference_image = self.jobs[job_id].get("reference_image")
            reference = self.images.reference({"image": reference_image})
            image_prompt = build_image_prompt(design, editing=bool(reference), mode=mode)
            self.images.record(image_id, {"status": "generating", "prompt": image_prompt,
                                         "model": model, "effort": effort, "design": design})
            image = self.bridge.generate_image(image_prompt, model=model, effort=effort, reference=reference)
            design["image"] = self.images.save(image, prompt=image_prompt, model=model, effort=effort, image_id=image_id)
        except Exception as error:
            design["image_error"] = str(error)[:1500]
            self.images.record(image_id, {"status": "failed", "error": design["image_error"], "design": design})

    def retry_image(self, previous_id):
        previous = self.get(previous_id)
        design = previous.get("design")
        if not design or not design.get("image_error") or design.get("image"):
            raise HTTPException(409, "這個工作沒有需要重試的圖片。")
        with self.lock:
            if self.busy:
                raise HTTPException(409, "已有生成工作，請稍後。")
            job_id = str(uuid4())
            self.jobs[job_id] = {**previous, "id": job_id, "status": "generating", "phase": "image", "error": None}
            self.images.save_job(self.jobs[job_id])
            self.busy = True
        threading.Thread(target=self._retry_image, args=(job_id, copy.deepcopy(design), previous["model"], previous["effort"]), daemon=True).start()
        return {"job_id": job_id}

    def _retry_image(self, job_id, design, model, effort):
        try:
            self._render_image(job_id, design, model, effort)
            update = {"status": "completed", "design": design}
        except Exception as error:
            update = {"status": "failed", "error": str(error)[:1500]}
        with self.lock:
            self.jobs[job_id].update(update)
            self.busy = False
            try:
                self.images.save_job(self.jobs[job_id])
            except OSError:
                self.jobs[job_id].update(status="failed", error="圖片工作保存失敗；請檢查磁碟。")

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                try:
                    return self.images.load_job(job_id)
                except (OSError, ValueError):
                    raise HTTPException(404, "生成工作不存在或後端已重新啟動；請重試。")
            return copy.deepcopy(self.jobs[job_id])


@router.get("/ai/status")
def ai_status(request: Request):
    return request.app.state.design_service.bridge.status()


@router.post("/ai/login")
def ai_login(request: Request):
    try:
        return request.app.state.design_service.bridge.login()
    except Exception as error:
        raise HTTPException(503, str(error)) from error


@router.get("/ai/models")
def models(request: Request, refresh: bool = False):
    try:
        return request.app.state.design_service.bridge.models(refresh=refresh)
    except Exception as error:
        raise HTTPException(503, str(error)) from error


@router.post("/ai/estimate")
def estimate(body: GenerateRequest, request: Request):
    return request.app.state.design_service.estimate(body)


@router.post("/design/generate", status_code=202)
def generate(body: GenerateRequest, request: Request):
    return request.app.state.design_service.submit(body)


@router.get("/design/jobs/{job_id}")
def job(job_id: str, request: Request):
    return request.app.state.design_service.get(job_id)


@router.get("/design/images/{image_id}")
def project_image(image_id: str, request: Request):
    try:
        path = request.app.state.design_service.images.path(image_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(404, "作品圖片不存在，請重新生成。")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=31536000, immutable"})


@router.post("/design/jobs/{job_id}/retry-image", status_code=202)
def retry_image(job_id: str, request: Request):
    return request.app.state.design_service.retry_image(job_id)


@router.get("/design/catalog")
def catalog():
    return CATALOG


@router.get("/design/demo")
def demo(sensor_only: bool = False):
    return demo_design(["hc-sr04"] if sensor_only else None)


@router.post("/design/migrate-retired")
@router.post("/design/migrate-catalog")
def migrate_retired(body: dict):
    try:
        return migrate_maker_state(body)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(422, "舊作品轉換失敗；原始草稿已保留，請勿清除瀏覽器資料。") from error
