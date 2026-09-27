"""Isolated synthetic AI Debug UI on http://127.0.0.1:18765/.

Run from backend: .venv/Scripts/python.exe -m tests.ai_debug_preview
No real webcam, SSH, GPIO, Codex, or external model is opened. The fixture uses
the real session routes/state machine with a test-only mock-webcam facade.
RGB uses 2 seconds per synthetic phase, code 3 seconds, and trial about 3 seconds.
These timings and generated observations are UI fixtures, never hardware proof.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import MethodType, SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute

from app.component_testing import ComponentTests
from app.debug_capture import current_debug_camera
from app.debug_sessions import DebugSessions
from app.debugging import DebugCases
from app.integration_trials import IntegrationTrials


TEMP = tempfile.TemporaryDirectory(prefix="boardvision-ai-debug-ui-")


def _temporary_constructor(cls, filename, *, no_worker=False):
    original = cls.__init__
    def initialize(self, *args, **kwargs):
        # Redirect even build_app's initial managers before reusing the preview
        # stack. In particular DebugSessions.__init__ immediately saves its file.
        import inspect
        bound = inspect.signature(original).bind_partial(self, *args, **kwargs)
        bound.arguments["store"] = Path(TEMP.name) / filename
        if no_worker:
            bound.arguments["autostart"] = False
        return original(*bound.args, **bound.kwargs)
    return initialize


with ExitStack() as patches:
    for cls, filename in ((ComponentTests, "components.json"), (DebugCases, "cases.json"),
                          (IntegrationTrials, "trials.json"), (DebugSessions, "initial-sessions.json")):
        patches.enter_context(patch.object(cls, "__init__", _temporary_constructor(
            cls, filename, no_worker=cls is DebugSessions)))
    from tests.component_test_preview import app, pi, ROOT, Source, demo_design

app.state.debug_sessions.close()
pi._set(program="stopped", pid=None, invocation_id=None, host="synthetic-preview.invalid")
pi.preview_frames = {}
pi.preview_phase = None
pi.preview_started = None
pi.preview_run = None
_fake_pi_run = pi._run


def _image(target, *, phase=None, text=None):
    frame = np.full((480, 800, 3), (30, 24, 18), np.uint8)
    cv2.putText(frame, "SYNTHETIC UI PREVIEW - NO HARDWARE / NO AI", (15, 35),
                cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 210, 255), 2)
    cv2.putText(frame, target, (25, 85), cv2.FONT_HERSHEY_SIMPLEX, .9, (220, 220, 220), 2)
    colors = {"display_red": (0, 0, 255), "display_lime": (0, 255, 0), "display_blue": (255, 0, 0)}
    if target == "tft_screen":
        cv2.rectangle(frame, (240, 110), (550, 450), colors.get(phase, (40, 60, 50)), -1)
        cv2.rectangle(frame, (255, 145), (520, 235), (0, 0, 0), -1)
        cv2.putText(frame, text or "TFT", (270, 210), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
    else:
        cv2.circle(frame, (270, 280), 65, (180, 180, 180), 4)
        cv2.circle(frame, (445, 280), 65, (180, 180, 180), 4)
        cv2.putText(frame, "SIMULATED HC TARGET", (160, 410), cv2.FONT_HERSHEY_SIMPLEX, .8, (240, 210, 120), 2)
    ok, image = cv2.imencode(".jpg", frame)
    assert ok
    raw = image.tobytes()
    now = time.monotonic()*1000
    metadata = dict(source="device", synthetic_only=True, target=target,
        camera_id=current_debug_camera(fixture_state),
        runtime_revision=app.state.runtime_manager.snapshot().runtime_revision,
        frame_id=int(now), seq=int(now), ts_ms=now, capture_ts_ms=now,
        captured_at=datetime.now(timezone.utc).isoformat(), size=[800, 480],
        sha256=hashlib.sha256(raw).hexdigest(), quality=dict(score=5., warnings=[], framing_ready=True),
        stability=dict(stable=True, heuristic=True), visibility_verified=False, electrical_verified=False)
    return {"overview": raw}, metadata


def fake_capture(state, target="overview", **kwargs):
    return _image(target)


def _fake_phase():
    if not pi.preview_started or not pi.preview_run:
        return
    elapsed = time.monotonic()-pi.preview_started
    if elapsed >= 9:
        pi.result.update(phase="finished", outcome="awaiting_confirmation", heartbeat_at=time.time())
        pi.raw = "LoadState=loaded\nActiveState=inactive\nMainPID=0\nExecMainStatus=0"
        return
    sequence = min(4, int(elapsed//2)+1)
    phase = {1: "display_red", 2: "display_lime", 3: "display_blue", 4: "display_code"}[sequence]
    stage = dict(seq=sequence, phase=phase, committed_at=time.time(), post_display=True)
    pi.result.update(phase=phase, outcome="running", heartbeat_at=time.time(),
                     last_progress_at=time.time(), camera_phase=stage)
    pi.raw = "LoadState=loaded\nActiveState=active\nMainPID=10\nExecMainStatus=0"
    if phase != pi.preview_phase:
        pi.preview_phase = phase
        text = pi.current["camera_markers"][str(sequence)] if sequence < 4 else pi.current["visual_code"]
        images, metadata = _image("tft_screen", phase=phase, text=text)
        metadata.update(run_id=pi.preview_run, phase_seq=sequence, phase=phase,
            phase_association="candidate_requires_marker", human_confirmation_required=True,
            phase_evidence=dict(run_id=pi.preview_run, seq=sequence, phase=phase,
                committed_at=stage["committed_at"], post_display=True,
                received_monotonic_ms=metadata["ts_ms"]-200))
        pi.preview_frames.setdefault(pi.preview_run, []).append((images, metadata))


def simulated_run(self, command, timeout=20):
    if ("show boardvision-test-" in command and "show boardvision-test-trial-" not in command
            and self.preview_run and self.preview_run in command):
        _fake_phase()
    response = _fake_pi_run(command, timeout)
    if command.startswith("systemd-run"):
        if self.current.get("component_id") == "mrd-tf240-8p-cs" and self.current.get("camera_assisted"):
            self.preview_run, self.preview_started = self.current["run_id"], time.monotonic()
            self.preview_phase = None
            _fake_phase()
        else:
            self.preview_started = None
            self.preview_run = None
    return response


pi._run = MethodType(simulated_run, pi)


class PreviewBridge:
    """Expected observations are scripted here; this is not model evaluation."""
    def status(self):
        return dict(available=True, logged_in=True, busy=False, error=None, synthetic_only=True)

    def models(self, refresh=False):
        return dict(models=[dict(id="synthetic-preview", name="SIMULATED AI — NO CLOUD",
            description="Local scripted model fixture for UI testing; no model inference or billing.",
            input_modalities=["text", "image"], efforts=["low"], default_effort="low", is_default=True,
            excluded_efforts=[], notice="合成 UI 預覽：固定模擬回覆，未呼叫真實 AI。")],
            default_model="synthetic-preview", billing_mode="synthetic", synthetic_only=True)

    def generate(self, prompt, schema, **kwargs):
        fields = schema.get("properties", {})
        if "stage1_text" in fields:
            answer = {"visibility": "clear"}
            for index, color in enumerate(("red", "green", "blue", "black"), 1):
                answer[f"stage{index}_color"] = color
                answer[f"stage{index}_text"] = (pi.current["camera_markers"][str(index)]
                                                 if index < 4 else pi.current["visual_code"])
            return answer
        if "seen" in fields:
            tft = "Component: mrd-tf240-8p-cs" in prompt
            return dict(seen="合成 UI 測試圖；沒有實體硬體或真實 AI 判讀。", visibility="clear",
                        suggested_action="test_tft" if tft else "test_hc",
                        explanation="固定 fixture 回覆，用於驗證畫面、路由與人工確認流程。")
        return dict(facts="Synthetic UI fixture, no hardware facts.", possible_causes="Scripted preview.",
                    next_step="Review the UI only.", logic=demo_design()["logic"])

    def close(self): pass
    def login(self): return self.status()


class PreviewSampler:
    def __init__(self, run_id): self.run_id = run_id
    def stop(self): return deepcopy(pi.preview_frames.get(self.run_id, []))
    def snapshot(self): return self.stop()


class PreviewSessions(DebugSessions):
    def _ensure_sampler(self, sid, run):
        if sid not in self.samplers and run.get("reserved") and run["phase"] != "awaiting_visual":
            self.samplers[sid] = PreviewSampler(run["id"])


bridge = PreviewBridge()
app.state.design_service.bridge = bridge
app.state.debug_cases.bridge = bridge
# This facade is intentionally exclusive to a localhost test fixture. The real
# capture service keeps its synthetic source, and production guards are unchanged.
mock_config = app.state.config.model_copy(deep=True)
mock_config.camera.source = "device"
fixture_state = SimpleNamespace(**{**app.state._state, "config": mock_config})
app.state.debug_sessions = PreviewSessions(fixture_state, Path(TEMP.name)/"sessions.json", capture=fake_capture)


@app.middleware("http")
async def block_real_camera_controls(request, call_next):
    # UI camera controls cannot escape this fixture into device probing/switching.
    if request.url.path.startswith(("/api/camera", "/api/cameras", "/api/glasses")):
        return JSONResponse({"synthetic_only": True, "detail": "Camera controls are disabled in this synthetic UI preview."}, status_code=409)
    return await call_next(request)


from app.api.routes import get_config as production_config


async def fixture_config(request: Request):
    config = await production_config(request)
    config.update(camera_source="device", synthetic_only=True, preview="ai-debug-ui")
    return config


async def fixture_info():
    return dict(synthetic_only=True, no_hardware=True, no_cloud=True, store=TEMP.name,
        timing="RGB 2s per phase; code 3s; trial approximately 3s",
        sessions=app.state.debug_sessions.active(), tests=app.state.component_tests.snapshot(),
        displayed_code=getattr(pi, "current", {}).get("visual_code"))


async def index():
    project = demo_design()
    project["id"], project["title"] = "ai-debug-preview", "SYNTHETIC AI DEBUG — NO HARDWARE"
    confirmed = {w["id"]: dict(signature="|".join([w["componentId"], w["componentPin"], w["boardPin"], w["connectionKind"]]),
                              mode="camera", at=datetime.now(timezone.utc).isoformat()) for w in project["wiring"]}
    seed = dict(stage="debug", design=project, selected=project["component_ids"], code=project["code"],
                aiModel="synthetic-preview", aiEffort="low", guide=dict(confirmed=confirmed))
    script = ("<script>if(!localStorage.getItem('ai-debug-preview-v1')){localStorage.setItem('boardvision.maker.v1',"
              + json.dumps(json.dumps(seed)) + ");localStorage.removeItem('boardvision.ai-debug-session.v1');"
              "localStorage.setItem('ai-debug-preview-v1','1');}</script>")
    banner = ('<div style="position:sticky;top:0;z-index:99999;padding:10px;background:#ffd64a;color:#17120a;'
              'font:700 16px sans-serif;text-align:center">SYNTHETIC UI PREVIEW · 模擬鏡頭 / Pi / AI · '
              '非真實硬體驗收 · RGB 2 秒 / 試跑約 3 秒</div>')
    html = (ROOT/"frontend/dist/index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("</head>", script+"</head>").replace("<body>", "<body>"+banner))


# Test-only routes precede production routes and the SPA catch-all on this origin.
app.router.routes[0:0] = [APIRoute("/", index, methods=["GET"]),
                         APIRoute("/api/config", fixture_config, methods=["GET"]),
                         APIRoute("/__test/info", fixture_info, methods=["GET"])]


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18765, timeout_graceful_shutdown=1, access_log=False)
