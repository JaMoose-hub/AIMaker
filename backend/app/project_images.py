"""Persistent, addressable native image artifacts, separate from wiring truth."""
import base64
import hashlib
import json
import os
import re
import struct
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
from app.designs import ROOT, MODULES


class ProjectImageStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT / "runs" / "project-images"

    def path(self, image_id):
        if not isinstance(image_id, str) or not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise ValueError("Invalid image ID")
        path = self.root / f"{image_id}.png"
        if not path.is_file():
            raise FileNotFoundError("作品圖片不存在，請重新生成。")
        return path

    def reference(self, current):
        artifact = (current or {}).get("image")
        return self.path(artifact["id"]) if artifact and artifact.get("id") else None

    def save(self, item, *, prompt, model, effort, image_id=None):
        image_id = image_id or uuid4().hex
        if not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise ValueError("Invalid image ID")
        # Native protocol payload only. Assistant text/URLs are not accepted.
        result = item.get("result", "")
        if result:
            if len(result) > 40_000_000:
                raise ValueError("Image payload too large")
            if result.startswith("data:image/"):
                result = result.split(",", 1)[1]
            content = base64.b64decode(result, validate=True)
        elif item.get("savedPath"):
            path = Path(item["savedPath"]).resolve()
            generated_root = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "generated_images"
            if not path.is_relative_to(generated_root.resolve()) or path.stat().st_size > 30_000_000:
                raise ValueError("Unexpected generated image path")
            content = path.read_bytes()
        else:
            raise ValueError("圖片生成未回傳可保存的圖檔。")
        if len(content) < 24 or content[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Expected a supported PNG image")
        width, height = struct.unpack(">II", content[16:24])
        if width < 1 or height < 1 or width * height > 16_000_000:
            raise ValueError("Unsupported image dimensions")
        decoded = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None or decoded.shape[:2] != (height, width):
            raise ValueError("Invalid PNG image")
        self.root.mkdir(parents=True, exist_ok=True)
        artifact = {"id": image_id, "url": f"/api/design/images/{image_id}", "width": width, "height": height,
                    "provider": "codex-image-generation", "created_at": datetime.now(timezone.utc).isoformat(),
                    "sha256": hashlib.sha256(content).hexdigest()}
        # Unique immutable versions; write metadata only after the image is durable.
        with (self.root / f"{image_id}.png").open("xb") as f:
            f.write(content)
        self.record(image_id, {**artifact, "prompt": prompt, "model": model, "effort": effort,
                               "model_role": "orchestrator", "image_model": "codex-managed",
                               "actual_cost": None, "usage": None, "status": "completed",
                               "revised_prompt": item.get("revisedPrompt")})
        return artifact

    def record(self, image_id, data):
        if not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise ValueError("Invalid image ID")
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{image_id}.json"
        if path.is_file():
            data = {**json.loads(path.read_text(encoding="utf-8")), **data}
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def save_job(self, job):
        if not re.fullmatch(r"[0-9a-f-]{36}", job["id"]):
            raise ValueError("Invalid job ID")
        directory = self.root / "jobs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{job['id']}.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def load_job(self, job_id):
        if not re.fullmatch(r"[0-9a-f-]{36}", job_id):
            raise FileNotFoundError()
        job = json.loads((self.root / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))
        if job["status"] == "generating":
            job.update(status="failed", error="後端已重新啟動，生成中斷；不會自動重試消耗額度。")
        return job


def build_image_prompt(design, *, editing=False, mode="fixed"):
    context = {"request": design["prompt"], "title": design["title"], "summary": design["summary"],
               "modules": ["Raspberry Pi 5"] + [MODULES[c]["name"]["en"] for c in design["component_ids"]],
               "assembly": design.get("assembly"), "preview": design.get("preview")}
    appearance = ""
    if "hc-sr04" in design["component_ids"]:
        appearance += "HC-SR04 is the only module with TWO cylindrical silver ultrasonic transducers on a narrow rectangular PCB.\n"
    continuity = (
        "FREE REDESIGN: Generate a fresh object silhouette and assembly from the latest request. No previous image is an edit target. "
        "Do not carry over a car chassis or wheels unless the requested object calls for them. The object itself must embody the requested shape, not just a label on an old shape.\n"
        if mode == "free" else
        "The attached image is the EDIT TARGET. Preserve its appearance, composition and modules except for requested changes and required module-identity corrections.\n"
        if editing else "Create the initial fixed-version assembly; there is no previous image to preserve.\n"
    )
    return """Use case: product-mockup. Generate exactly one actual raster image with the native image_gen tool.
Asset: BoardVision finished-project modular assembly illustration, not a UI screenshot or circuit diagram.
Render a polished detailed three-quarter product view with the full object visible and a clean studio backdrop.
Show the selected electronic modules recognizably, each exactly once. Open or transparent construction
must make their mounting and relationships visible. Do not hide all the boards inside an opaque enclosure.
Only the modules in the context are allowed. Passive wheels, axles, brass standoffs, screws, acrylic panels
and brackets listed in assembly are allowed. No motors, motor drivers, batteries, servos, LEDs or extra sensors.
This is an illustrative assembly demo, not proof of function, safe wiring, production dimensions or live hardware.
For a car, show passive wheels without implying autonomous motion. No wiring pin numbers or invented measurements.
Display may say DEMO; no fabricated live distance/tilt readings. Keep unnecessary text out of the image.
""" + appearance + continuity + "Design context: " + json.dumps(context, ensure_ascii=False)
