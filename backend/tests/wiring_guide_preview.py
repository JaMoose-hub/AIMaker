"""Isolated UI fixture: python -m tests.wiring_guide_preview (localhost:18761).

No camera, model, GPIO or serial device is opened. The picture and all poses
are synthetic; manual confirmations in this server are UI tests, not evidence.
POST /__test/scenario/{locked,stale,missing,silent} changes only this fixture.
Never import this module from the production application.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import uvicorn
from fastapi.routing import APIRoute

from app.component_worker import ComponentPinPosition, ComponentPoseResult, component_pose_message
from app.config import (
    AppConfig, CameraConfig, ComponentSegmentationConfig, ComponentVisionConfig,
    ElectricalVerificationConfig, VlmConfig, WireTraceConfig,
)
from app.main import build_app
from app.vision.interface import DetectionResult, PinDetection

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "hc-sr04": ("VCC", "TRIG", "ECHO", "GND"),
    "hw-123": ("VCC", "GND", "SCL", "SDA", "XDA", "XCL", "AD0", "INT"),
    "mrd-tf240-8p-cs": ("GND", "VCC", "SCL", "SDA", "RES", "DC", "CS", "BLK"),
}


class Source:
    def open(self):
        self.seq = 0

    def read(self):
        time.sleep(0.08)
        self.seq += 1
        frame = np.full((720, 1280, 3), (30, 24, 18), dtype=np.uint8)
        cv2.putText(frame, "SYNTHETIC UI TEST - NOT REAL WIRING", (32, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (70, 190, 250), 2)
        cv2.rectangle(frame, (70, 170), (570, 580), (55, 100, 50), 2)
        cv2.putText(frame, "Pi 5", (100, 220), cv2.FONT_HERSHEY_SIMPLEX, 1, (180, 220, 180), 2)
        for i, (module, pins) in enumerate(MODULES.items()):
            y = 170 + i * 160
            cv2.rectangle(frame, (700, y), (1220, y + 105), (130, 110, 50), 2)
            cv2.putText(frame, module, (725, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 1)
            for j, pin in enumerate(pins):
                cv2.circle(frame, (730 + j * 62, y + 80), 5, (240, 230, 180), -1)
        return frame, self.seq, time.monotonic() * 1000

    def close(self):
        pass


class Detector:
    mode = "locked"
    state = None

    def load(self, profile, profile_dir):
        self.pins = profile.pins

    def detect(self, frame, frame_id, ts_ms):
        tracking = "stale" if self.mode == "stale" else "locked"
        for i, (module, names) in enumerate(MODULES.items()):
            if self.mode == "silent":
                continue
            y = 170 + i * 160
            result = ComponentPoseResult(
                component_id=module, frame_id=frame_id, ts_ms=ts_ms,
                tracking="searching" if self.mode == "missing" and module == "hc-sr04" else "locked",
                confidence=0.99, video_size=(1280, 720),
                outline_px=np.array([[700, y], [1220, y], [1220, y + 105], [700, y + 105]]),
                pins=tuple(ComponentPinPosition(name, 730 + j * 62, y + 80, 0.99) for j, name in enumerate(names)),
                stability="tracking",
            )
            self.state.component_pose_state.set(result)
            self.state.broadcaster.publish_threadsafe(component_pose_message(result))
        return DetectionResult(
            board_id="raspberry-pi-5", frame_id=frame_id, ts_ms=ts_ms,
            tracking=tracking, confidence=0.99,
            pins=[PinDetection(pin.id, 110 + (i // 2) * 22, 280 + (i % 2) * 48, 0.99)
                  for i, pin in enumerate(self.pins)],
            outline_px=[(70, 170), (570, 170), (570, 580), (70, 580)],
        )

    def close(self):
        pass


detector = Detector()
app = build_app(
    AppConfig(
        board="raspberry-pi-5", detector="mock", profile_dir=ROOT / "profiles",
        frontend_dist=ROOT / "frontend" / "dist", detection_hz=10,
        camera=CameraConfig(source="synthetic", width=1280, height=720, fps=10),
        component_vision=ComponentVisionConfig(enabled=False),
        component_segmentation=ComponentSegmentationConfig(enabled=False),
        wire_trace=WireTraceConfig(enabled=False), vlm=VlmConfig(enabled=False),
        electrical_verification=ElectricalVerificationConfig(enabled=False),
    ), detector=detector, source=Source(), scene=object(),
)
detector.state = app.state


async def scenario(mode: Literal["locked", "stale", "missing", "silent"]):
    detector.mode = mode
    return {"synthetic_only": True, "scenario": mode}


# Before the SPA catch-all; this test-only endpoint never exists on port 8100.
app.router.routes.insert(0, APIRoute("/__test/scenario/{mode}", scenario, methods=["POST"]))

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18761, timeout_graceful_shutdown=1)
