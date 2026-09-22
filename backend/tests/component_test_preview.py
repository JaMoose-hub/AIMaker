"""Isolated UI acceptance on :18763. Mock SSH, synthetic frames, no hardware.

python -m tests.component_test_preview
Uses actual APIs, manager, React UI and guide state, but simulated remote output.
Never import from production. Different origin preserves the user's real draft.
"""
import json
import tempfile
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import cv2
import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from app.component_testing import ComponentTests
from app.pi_execution import PiExecution
from app.integration_trials import IntegrationTrials
from app.debugging import DebugCases
from app.designs import demo_design
from tests.test_pi_execution import QueuePi
from tests.wiring_guide_preview import app, Source, MODULES, ROOT

MODULES.pop("hw-123", None)


class SimulatedPi(QueuePi):
    @contextmanager
    def _sftp(self):
        yield self

    def file(self, path, mode):
        if path not in self.files:
            raise FileNotFoundError(path)
        return BytesIO(self.files[path].encode())

    def version_evidence(self):
        return self.snapshot()

    def connect(self):
        self._set(connected=True, connection_error=None)
        return {"ok": True, "status": self.snapshot()}

    def _run(self, command, timeout=20):
        if "show boardvision-test-trial-" in command and getattr(self,"trial_started",None) and time.time()-self.trial_started>3:
            self.raw = "LoadState=loaded\nActiveState=inactive\nExecMainStatus=0"
            self.files[self.trial_directory+"/runtime.json"] = json.dumps(dict(run_id=self.current["run_id"], code_hash=self.current["code_hash"],
                phase="finished", program_ok=True, structured=True, sample_seq=30, display_seq=15, distances=[10,20,30],
                latest_valid_at=time.time(), last_display_at=time.time(), heartbeat_at=time.time(), exit_code=0))
        response = super()._run(command, timeout)
        if command.startswith("systemd-run"):
            self.current = json.loads(next(reversed([value for key,value in self.files.items() if key.endswith("config.json")])))
            if "component_id" not in self.current:
                self.trial_started=time.time()
                self.trial_directory=next(reversed([key.rsplit("/",1)[0] for key in self.files if key.endswith("run-config.json")]))
                self.raw="LoadState=loaded\nActiveState=active\nMainPID=10\nExecMainStatus=0"
                return response
            self.result = dict(run_id=self.current["run_id"], phase="awaiting_near", heartbeat_at=time.time(), samples={})
            self.raw = "LoadState=loaded\nActiveState=active\nMainPID=10\nExecMainStatus=0"
            if self.current["component_id"] != "hc-sr04":
                self.result.update(phase="finished",outcome="awaiting_confirmation")
                self.raw = "LoadState=loaded\nActiveState=inactive\nMainPID=0\nExecMainStatus=0"
        return response

    def _write(self, path, contents):
        super()._write(path, contents)
        if path.endswith("command.json"):
            action = json.loads(contents)["action"]
            self.result.update(heartbeat_at=time.time())
            if action == "near":
                self.result.update(phase="awaiting_far",samples={"near":{"count":12,"median_cm":15}})
            else:
                self.result.update(phase="finished",outcome="passed",samples={"near":{"count":12,"median_cm":15},"far":{"count":12,"median_cm":30}})
                self.raw = "LoadState=loaded\nActiveState=inactive\nMainPID=0\nExecMainStatus=0"


class SimulatedTests(ComponentTests):
    def _read_result(self, directory):
        if self.pi.result:
            self.pi.result["heartbeat_at"] = time.time()
        return self.pi.result


temp = tempfile.TemporaryDirectory(prefix="boardvision-component-ui-")
pi = SimulatedPi()
pi._set(program="running", host="simulated-pi.invalid")
app.state.pi_execution.close()
app.state.component_tests.close()
app.state.integration_trials.close()
app.state.pi_deployer.close()
app.state.pi_deployer = pi
app.state.component_tests = SimulatedTests(pi, Path(temp.name) / "tests.json")
app.state.integration_trials = IntegrationTrials(pi, Path(temp.name) / "trials.json")
app.state.pi_execution = PiExecution(pi, app.state.component_tests, app.state.integration_trials)


class PreviewAgent:
    def generate(self, *args, **kwargs):
        return dict(facts="模擬診斷；不是硬體證據。", possible_causes="用於測試候選邏輯流程。", next_step="確認差異後試跑。",
                    logic=demo_design()["logic"].replace('return f"distance_cm=', 'return f"Distance: '))


app.state.debug_cases = DebugCases(pi, app.state.component_tests, app.state.integration_trials, app.state.pi_execution, PreviewAgent(), Path(temp.name) / "debug.json")
original_read = Source.read


def simulated_screen(self):
    frame, seq, ts = original_read(self)
    if hasattr(pi,"current") and pi.current.get("component_id") == "mrd-tf240-8p-cs":
        cv2.putText(frame, "SIMULATED SCREEN: " + pi.current["visual_code"], (120, 650),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (90, 240, 230), 3)
    return frame, seq, ts


Source.read = simulated_screen


async def index():
    project = demo_design()
    project["id"], project["title"] = "simulated-component-test", "SIMULATED FUNCTION TEST — NOT HARDWARE"
    seed = dict(stage="guide",design=project,selected=project["component_ids"],code=project["code"],guide={"confirmed":{}})
    script = "<script>if(!localStorage.getItem('component-preview-seeded')){localStorage.setItem('boardvision.maker.v1'," + json.dumps(json.dumps(seed)) + ");localStorage.setItem('component-preview-seeded','1');}</script>"
    return HTMLResponse((ROOT / "frontend/dist/index.html").read_text(encoding="utf-8").replace("</head>",script+"</head>"))


app.router.routes.insert(0,APIRoute("/",index,methods=["GET"]))

if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=18763,timeout_graceful_shutdown=1,access_log=False)
