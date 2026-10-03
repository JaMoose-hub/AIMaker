"""Isolated QA server: actual assistant/design persistence with a fake model.

Run from backend: .venv/Scripts/python -m uvicorn tests.assistant_preview:app ...
No main application, camera, SSH, Pi or Codex is instantiated.
"""
import base64
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from app.api.assistant import router
from app.api.design import DesignService
from app.assistant import AssistantService, builtin_checklist
from app.designs import DesignProposal, demo_design
from app.project_images import ProjectImageStore


class PreviewModel:
    def __init__(self):
        self.calls = []; self.image_calls = 0

    def models(self, refresh=False):
        return {"models": [{"id": "gpt-6-luna", "name": "QA fake model", "efforts": ["low"], "default_effort": "low"}], "default_model": "gpt-6-luna", "billing_mode": "fake"}

    def generate(self, prompt, schema, **options):
        self.calls.append({"schema": schema.get("title"), "model": options.get("model")})
        time.sleep(.2)
        if schema.get("title") == "PlanningReply":
            checklist = builtin_checklist("en" if "Reply entirely in English" in prompt else "zh-TW")
            checklist["requirements"].append("QA changed requirement")
            return {"answer": "QA fake planning reply — no image generated.", "checklist": checklist}
        if schema.get("title") == "RoutedReply":
            return {"capability": "answer", "answer": "QA fake reply — no hardware or paid model was used."}
        if schema.get("title") == "AssistantReply":
            return {"answer": "QA fake advisory reply."}
        design = demo_design()
        proposal = {key: design.get(key) for key in DesignProposal.model_fields}
        proposal.update(assembly={"description": "QA fixture", "parts": builtin_checklist("en")["structure"]}, concept_only_parts=builtin_checklist("en")["concept_only"])
        if schema.get("title") == "ConversationReply":
            return {"action": "redesign", "answer": "QA fake preview ready.", "proposal": proposal}
        return proposal

    def generate_image(self, *args, **kwargs):
        self.image_calls += 1
        sample = Path(__file__).resolve().parents[2] / "frontend/public/demo/distance-monitor-three-wheel-motors-v2.png"
        return {"result": base64.b64encode(sample.read_bytes()).decode()}


app = FastAPI()
root = Path(tempfile.mkdtemp(prefix="tinkro-assistant-qa-"))
bridge = PreviewModel()
app.state.design_service = DesignService(bridge, ProjectImageStore(root / "images"))
app.state.assistant = AssistantService(app.state, root / "conversations")
app.include_router(router)


@app.get("/api/assistant-qa")
def stats():
    return {"fake": True, "model_calls": bridge.calls, "image_calls": bridge.image_calls}


@app.get("/api/design/images/{image_id}")
def image(image_id: str):
    from fastapi.responses import FileResponse
    return FileResponse(app.state.design_service.images.path(image_id))
