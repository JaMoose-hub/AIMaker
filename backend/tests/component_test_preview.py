"""Isolated UI acceptance on :18763. Mock SSH, synthetic frames, no hardware.

python -m tests.component_test_preview
Uses actual APIs, manager, React UI and guide state, but simulated remote output.
Never import from production. Different origin preserves the user's real draft.
"""
import json
import tempfile
import time
from pathlib import Path

import cv2
import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute

from app.component_testing import ComponentTests
from app.designs import demo_design
from tests.test_component_testing import FakePi
from tests.wiring_guide_preview import app, Source, MODULES, ROOT

MODULES.pop("hw-123", None)


class SimulatedPi(FakePi):
    def _run(self, command, timeout=20):
        response = super()._run(command, timeout)
        if command.startswith("systemd-run"):
            self.current = json.loads(next(reversed([value for key,value in self.files.items() if key.endswith("config.json")])))
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
app.state.component_tests.close()
app.state.pi_deployer.close()
app.state.pi_deployer = pi
app.state.component_tests = SimulatedTests(pi, Path(temp.name) / "tests.json")
original_read = Source.read


def simulated_screen(self):
    frame, seq, ts = original_read(self)
    if hasattr(pi,"current") and pi.current["component_id"] != "hc-sr04":
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
