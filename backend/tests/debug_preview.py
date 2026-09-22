"""Dedicated synthetic Debug UI acceptance. No SSH or real Agent calls."""
import json
import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from tests.component_test_preview import app, pi, ROOT, demo_design


async def index():
    project = demo_design()
    project["id"], project["title"] = "debug-preview", "SIMULATED DEBUG — NOT HARDWARE"
    confirmed = {w["id"]:dict(signature="|".join([w["componentId"],w["componentPin"],w["boardPin"],w["connectionKind"]]),mode="camera",at="2026-09-21T00:00:00Z") for w in project["wiring"]}
    seed = dict(stage="debug",design=project,selected=project["component_ids"],code=project["code"],guide={"confirmed":confirmed})
    script = "<script>if(!localStorage.getItem('debug-preview-seeded')){localStorage.setItem('boardvision.maker.v1'," + json.dumps(json.dumps(seed)) + ");localStorage.setItem('debug-preview-seeded','1');}</script>"
    return HTMLResponse((ROOT / "frontend/dist/index.html").read_text(encoding="utf-8").replace("</head>",script+"</head>"))


app.router.routes.insert(0, APIRoute("/",index,methods=["GET"]))
if __name__ == "__main__":
    uvicorn.run(app,host="127.0.0.1",port=18764,timeout_graceful_shutdown=1,access_log=False)
