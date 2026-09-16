"""Backend core tests: config, capture bus, profile store, query service,
REST endpoints, WS hello + detection broadcast, MJPEG stream.

These tests never import app.vision.factory / app.vision.synthetic (built by
another agent in parallel): a local stub detector + stub frame source are
injected through the same build_app() seams that app.main uses at runtime.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture.bus import FrameBus
from app.config import AppConfig, ComponentVisionConfig, load_config
from app.main import build_app
from app.profiles.store import (
    ProfileNotFoundError,
    ProfileStore,
    ProfileValidationError,
)
from app.query.service import QueryService
from app.vision.interface import DetectionResult, PinDetection
from app.vision_worker import DetectionState, VisionWorker, detection_message

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MINI_BOARD_JSON = FIXTURES / "mini-board" / "board.json"
VIDEO_W, VIDEO_H = 64, 48


# ---------------------------------------------------------------- stubs ----

class StubFrameSource:
    """Implements the FrameSource protocol; emits small frames at ~100 fps."""

    def __init__(self, width: int = VIDEO_W, height: int = VIDEO_H) -> None:
        self._w, self._h = width, height
        self._frame_id = 0
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self):
        time.sleep(0.01)
        self._frame_id += 1
        frame = np.full((self._h, self._w, 3), 32, dtype=np.uint8)
        return frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        self.closed = True


_NATIVE_JPEG = b"\xff\xd8board-vision-native-mjpeg\xff\xd9"


class NativeJpegStubFrameSource(StubFrameSource):
    """Frame source that exercises native MJPEG passthrough end to end."""

    def read(self):
        frame, frame_id, ts_ms = super().read()
        return frame, frame_id, ts_ms, _NATIVE_JPEG


class StubDetector:
    """Implements the BoardDetector protocol locally (no app.vision.factory)."""

    def __init__(self, board_id: str = "mini-board") -> None:
        self._board_id = board_id
        self.loaded = False
        self.closed = False

    def load(self, profile, profile_dir: Path) -> None:
        self.loaded = True

    def detect(self, frame_bgr, frame_id: int, ts_ms: float) -> DetectionResult:
        return DetectionResult(
            board_id=self._board_id,
            frame_id=frame_id,
            ts_ms=ts_ms,
            tracking="locked",
            confidence=0.9,
            pins=[PinDetection(pin_id="D3", x=10.0, y=5.0, confidence=0.97, visible=True)],
            outline_px=[(0.0, 0.0), (64.0, 0.0), (64.0, 48.0), (0.0, 48.0)],
        )

    def close(self) -> None:
        self.closed = True


class FailingDetector(StubDetector):
    def detect(self, frame_bgr, frame_id: int, ts_ms: float) -> DetectionResult:
        raise RuntimeError("boom")


def make_config(**overrides) -> AppConfig:
    values = dict(
        server={"host": "127.0.0.1", "port": 8100},
        camera={
            "source": "synthetic",
            "device_index": 0,
            "width": VIDEO_W,
            "height": VIDEO_H,
            "fps": 60,
        },
        detector="mock",
        # Unit-test stubs must not start the production component models.
        component_vision=ComponentVisionConfig(),
        board="mini-board",
        profile_dir=FIXTURES,
        frontend_dist=FIXTURES / "no-such-dist",
        default_locale="zh-TW",
        jpeg_quality=70,
        detection_hz=60,
        # Keep this unit-test fixture independent from a developer machine's
        # BOARDVISION_VLM__* launch environment.
        vlm={"enabled": False, "provider": "none", "timeout_s": 8.0},
    )
    values.update(overrides)
    return AppConfig(**values)


def make_app(detector=None, source=None):
    return build_app(
        make_config(),
        detector=detector or StubDetector(),
        source=source or StubFrameSource(),
    )


# --------------------------------------------------------------- config ----

def test_config_loads_yaml_relative_to_backend_dir():
    cfg = load_config()
    assert cfg.server.port == 8100
    # device, not synthetic: the real C920 is the active rig while wiring up
    # Pi 5 parity with arduino-uno-q (config.yaml's own comment explains the
    # override knob back to synthetic for CI/demo-without-hardware use).
    assert cfg.camera.source == "device"
    # FFmpeg explicitly selects the C920's native MJPEG mode; unlike OpenCV
    # DSHOW/YUY2 this delivers the configured 1080p30 stream.
    assert cfg.camera.width == 1920 and cfg.camera.height == 1080
    assert cfg.camera.capture_backend == "ffmpeg"
    assert cfg.camera.ffmpeg_device_name == "HD Pro Webcam C920"
    assert cfg.camera.capture_api == "dshow"
    assert cfg.camera.horizontal_fov_deg == pytest.approx(70.42)
    assert cfg.detector == "hybrid"
    # raspberry-pi-5, not arduino-uno-q: config.yaml's active board while its
    # calibration is being brought to parity with the already-working UNO Q.
    assert cfg.board == "raspberry-pi-5"
    assert cfg.detection_hz == 30
    assert cfg.jpeg_quality == 80
    # paths resolved to absolute, relative to config.yaml's directory
    assert cfg.profile_dir.is_absolute() and cfg.profile_dir.name == "profiles"
    assert cfg.frontend_dist.is_absolute() and cfg.frontend_dist.name == "dist"
    assert (
        cfg.yolo_pose.model_path_for("raspberry-pi-5").name
        == "board-pose-pi5-handheld-v2.onnx"
    )
    assert cfg.yolo_pose.keypoint_count_for("raspberry-pi-5") == 4
    assert cfg.yolo_pose.model_path_for("arduino-uno-q").name == "board-pose.onnx"
    assert cfg.yolo_pose.confidence_threshold_for("raspberry-pi-5") == pytest.approx(0.30)
    assert cfg.yolo_pose.confidence_threshold_for("arduino-uno-q") == pytest.approx(0.45)
    assert cfg.video_size == (1920, 1080)


def test_config_env_overrides_yaml(monkeypatch):
    monkeypatch.setenv("BOARDVISION_DETECTOR", "pipeline")
    monkeypatch.setenv("BOARDVISION_CAMERA__DEVICE_INDEX", "5")
    monkeypatch.setenv("BOARDVISION_CAMERA__SOURCE", "device")
    cfg = load_config()
    assert cfg.detector == "pipeline"
    assert cfg.camera.device_index == 5
    assert cfg.camera.source == "device"
    # untouched values still come from the YAML
    assert cfg.server.port == 8100


def test_default_config_enables_both_component_models(monkeypatch):
    import os

    from app.component_worker import ComponentVisionProfile

    for name in os.environ:
        if name.startswith("BOARDVISION_COMPONENT_VISION"):
            monkeypatch.delenv(name)
    cfg = load_config()
    assert cfg.component_vision.enabled is True
    assert cfg.component_vision.primary_component_id == "mrd-tf240-8p-cs"
    targets = cfg.component_vision.components
    assert [target.id for target in targets] == [
        "hc-sr04", "mrd-tf240-8p-cs",
    ]
    assert [target.model_path.name for target in targets] == [
        "hc-sr04-corner-pose-v3-robust.onnx",
        "mrd-tf240-8p-cs-pose.onnx",
    ]
    assert [target.input_size for target in targets] == [768, 1280]
    assert [target.confidence_threshold for target in targets] == [0.25, 0.20]
    assert [target.keypoint_threshold for target in targets] == [0.20, 0.15]
    assert [target.reacquire_min_visible_fraction for target in targets] == [0.25, 0.08]
    for target in targets:
        assert target.model_path.is_absolute() and target.model_path.is_file()
        assert target.profile_path.is_absolute() and target.profile_path.is_file()
        assert ComponentVisionProfile.load(target.profile_path).component_id == target.id


def test_app_starts_and_stops_every_configured_component_worker(monkeypatch):
    workers = []

    class StubComponentWorker:
        def __init__(self, component_id):
            self.component_id = component_id
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    def build_component_worker(**kwargs):
        worker = StubComponentWorker(kwargs["target"].id)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.main._build_component_pose_worker", build_component_worker)
    config = make_config(component_vision=load_config().component_vision)
    app = build_app(config, detector=StubDetector(), source=StubFrameSource())
    with TestClient(app) as client:
        assert [worker.component_id for worker in workers] == [
            "hc-sr04", "mrd-tf240-8p-cs",
        ]
        assert all(worker.started and not worker.stopped for worker in workers)
        runtime = client.get("/api/config").json()["component_vision"]
        assert runtime["enabled"] is True
        assert [target["id"] for target in runtime["components"]] == [
            worker.component_id for worker in workers
        ]
    assert all(worker.stopped for worker in workers)


def test_hardware_free_launch_can_explicitly_disable_component_workers(monkeypatch):
    monkeypatch.setenv("BOARDVISION_COMPONENT_VISION__ENABLED", "false")
    config = make_config(component_vision=load_config().component_vision)
    app = build_app(config, detector=StubDetector(), source=StubFrameSource())
    with TestClient(app):
        assert config.component_vision.enabled is False
        assert app.state.component_workers == []


def test_profile_quality_accepts_runtime_scale_thresholds():
    from app.vision.profile_quality import inspect_profile_quality

    cfg = make_config(
        wire_trace={"min_pin_pitch_px": 9.0, "min_px_per_mm": 3.5}
    )
    app = build_app(cfg, detector=StubDetector(), source=StubFrameSource())
    report = inspect_profile_quality(
        app.state.profile,
        app.state.profile_store.board_dir(cfg.board),
        min_pin_pitch_px=cfg.wire_trace.min_pin_pitch_px,
        min_px_per_mm=cfg.wire_trace.min_px_per_mm,
    )

    assert report["min_pitch_px"] == 9.0
    assert report["min_px_per_mm"] == 3.5
    assert report["pitch_px"] >= report["min_pitch_px"]


# ------------------------------------------------------------- FrameBus ----

def test_frame_bus_latest_wins_and_timeout():
    bus = FrameBus()
    assert bus.get_latest(timeout=0.02) is None
    f1 = np.zeros((2, 2, 3), np.uint8)
    f2 = np.ones((2, 2, 3), np.uint8)
    bus.put(f1, 1, 100.0)
    bus.put(f2, 2, 200.0)
    slot = bus.get_latest(timeout=0.1)
    assert slot is not None and slot.frame_id == 2 and slot.ts_ms == 200.0
    # nothing newer than the latest seq -> timeout
    assert bus.get_latest(timeout=0.05, newer_than=slot.seq) is None
    bus.put(f1, 3, 300.0)
    slot2 = bus.get_latest(timeout=0.1, newer_than=slot.seq)
    assert slot2 is not None and slot2.frame_id == 3


def test_frame_bus_preserves_native_jpeg():
    bus = FrameBus()
    frame = np.zeros((2, 2, 3), np.uint8)
    bus.put(frame, 1, 100.0, jpeg=_NATIVE_JPEG)
    slot = bus.get_latest(timeout=0.1)
    assert slot is not None and slot.jpeg == _NATIVE_JPEG


# -------------------------------------------------------- profile store ----

def test_profile_store_loads_valid_profile():
    store = ProfileStore(FIXTURES)
    profile = store.profile("mini-board")
    raw = store.raw("mini-board")
    assert profile.board.id == "mini-board"
    assert [p.id for p in profile.pins] == ["D3", "A4", "A5", "GND_P1"]
    assert raw["board"]["id"] == "mini-board"
    assert profile.bus_by_id("i2c0") is not None
    assert store.has("mini-board")


def test_profile_store_unknown_board():
    store = ProfileStore(FIXTURES)
    with pytest.raises(ProfileNotFoundError):
        store.load("no-such-board")
    assert not store.has("no-such-board")


def test_profile_store_schema_error_names_pin(tmp_path):
    raw = json.loads(MINI_BOARD_JSON.read_text(encoding="utf-8"))
    bad = copy.deepcopy(raw)
    bad["pins"][0]["id"] = "D9"
    bad["pins"][0]["capabilities"][0]["type"] = "bogus-capability"
    board_dir = tmp_path / "bad-board"
    board_dir.mkdir()
    (board_dir / "board.json").write_text(json.dumps(bad), encoding="utf-8")

    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileValidationError) as excinfo:
        store.load("bad-board")
    message = str(excinfo.value)
    assert "board.json" in message
    assert "D9" in message  # error names the offending pin


def test_profile_store_model_error_is_readable(tmp_path):
    raw = json.loads(MINI_BOARD_JSON.read_text(encoding="utf-8"))
    bad = copy.deepcopy(raw)
    # passes jsonschema (type is just "string") but fails the pydantic Literal
    bad["headers"][0]["side"] = "top"
    bad["schema_version"] = "1.0"
    bad["pins"][1]["pos_mm"] = [1.0, 2.0, "not-a-number"]
    board_dir = tmp_path / "bad-board2"
    board_dir.mkdir()
    (board_dir / "board.json").write_text(json.dumps(bad), encoding="utf-8")

    store = ProfileStore(tmp_path)
    with pytest.raises(ProfileValidationError) as excinfo:
        store.load("bad-board2")
    message = str(excinfo.value)
    assert "board.json" in message
    assert "A4" in message  # pins[1] is A4


# -------------------------------------------------------- query service ----

@pytest.fixture(scope="module")
def query_service() -> QueryService:
    profile = ProfileStore(FIXTURES).profile("mini-board")
    return QueryService(profile, default_locale="zh-TW")


def test_query_servo_zh(query_service):
    res = query_service.answer("哪支腳可以接 servo?", "zh-TW")
    assert res["matched"] is True
    assert res["pin_ids"] == ["D3"]  # derived from profile pwm capability
    assert res["group"] is None
    assert "PWM" in res["answer"]
    assert "3.3" in res["answer"]  # 3.3V logic reminder for I/O intents


def test_query_i2c_en(query_service):
    res = query_service.answer("Where do I connect the I2C temperature sensor?", "en")
    assert res["matched"] is True
    assert res["pin_ids"] == ["A4", "A5"]  # derived from bus i2c0
    assert res["group"] == "i2c0"
    # silkscreen == pin id on mini-board, so names appear once, no parens
    assert "A4" in res["answer"] and "A5" in res["answer"]
    assert "(" not in res["answer"].replace("(bus i2c0)", "")
    assert "3.3" in res["answer"]


def test_query_i2c_zh_synonym(query_service):
    res = query_service.answer("溫濕度感測器要接哪裡?", None)  # locale fallback zh-TW
    assert res["matched"] is True
    assert res["group"] == "i2c0"
    assert res["pin_ids"] == ["A4", "A5"]


def test_query_power_zh(query_service):
    res = query_service.answer("電源腳位在哪?", "zh-TW")
    assert res["matched"] is True
    assert res["group"] == "power_rails"  # from profile groups
    assert res["pin_ids"] == ["GND_P1"]
    assert "邏輯" not in res["answer"]  # power is not an I/O intent -> no reminder


def test_query_nonsense(query_service):
    res = query_service.answer("今天天氣如何?", "zh-TW")
    assert res["matched"] is False
    assert res["pin_ids"] == []
    assert res["group"] is None
    assert "servo" in res["answer"].lower()  # suggestion lists example queries


def test_query_interrupt_button_en(query_service):
    res = query_service.answer("which pin for a push button interrupt?", "en")
    assert res["matched"] is True
    assert res["pin_ids"] == ["D3"]


# ------------------------------------------------------------ REST API ----

def _poison_vision_imports(monkeypatch):
    """Make any attempt to import the parallel-built vision modules fail
    loudly for the duration of a test: proves the backend seams (injection +
    lazy imports) never touch app.vision.factory / app.vision.synthetic."""
    monkeypatch.setitem(sys.modules, "app.vision.factory", None)
    monkeypatch.setitem(sys.modules, "app.vision.synthetic", None)


def test_rest_endpoints(monkeypatch):
    _poison_vision_imports(monkeypatch)
    detector = StubDetector()
    source = StubFrameSource()
    app = make_app(detector=detector, source=source)

    with TestClient(app) as client:
        assert detector.loaded is True  # backend called load() before detect()

        r = client.get("/api/config")
        assert r.status_code == 200
        assert r.json() == {
            "board_id": "mini-board",
            "runtime_revision": 1,
            "default_locale": "zh-TW",
            "video_size": [VIDEO_W, VIDEO_H],
                "detector": "mock",
                "camera_source": "synthetic",
                "camera_capture_backend": "ffmpeg",
                "realtime_tracking": False,
                "accuracy": {
                "status": "warning",
                "physical_gate_ready": False,
                "pitch_px": pytest.approx(50.0, abs=0.01),
                "px_per_mm": pytest.approx(10.0, abs=0.01),
                "min_pitch_px": 18.0,
                "min_px_per_mm": 8.0,
                "camera_calibrated": False,
                "camera_quality_ok": False,
                "camera_quality_status": None,
                "camera_rms_reprojection_error_px": None,
                "camera_max_view_rms_px": None,
                "camera_coverage_fraction": None,
                "feature_count": 0,
                "warnings": [
                    "camera.json is absent; pose uses the FOV fallback",
                    "feature cache is missing or too small (0 features)",
                ],
            },
            "verification_runtime": {
                "vlm_enabled": False,
                "vlm_provider": "none",
                "vlm_model": "qwen3-vl:8b",
                "vlm_insertion_enabled": True,
                "vlm_timeout_s": 8.0,
                "vlm_worker": None,
                "electrical_enabled": False,
            },
            "component_vision": {
                "enabled": False,
                "primary_component_id": None,
                "components": [],
            },
        }

        r = client.get("/api/boards/mini-board")
        assert r.status_code == 200
        body = r.json()
        assert body["board"]["id"] == "mini-board"
        assert len(body["pins"]) == 4
        assert body["groups"]["power_rails"] == ["GND_P1"]

        r = client.get("/api/boards/no-such-board")
        assert r.status_code == 404
        assert r.json() == {
            "error_code": "profile_not_found",
            "params": {"board_id": "no-such-board"},
        }

        r = client.get("/api/boards/mini-board/pins/D3")
        assert r.status_code == 200
        pin = r.json()
        assert pin["id"] == "D3" and pin["silkscreen"] == "~3"

        r = client.get("/api/boards/mini-board/pins/NOPE")
        assert r.status_code == 404
        assert r.json() == {
            "error_code": "resource_not_found",
            "params": {"detail": "unknown pin 'NOPE' on board 'mini-board'"},
        }

        r = client.post("/api/query", json={"text": "哪支腳可以接 servo?", "locale": "zh-TW"})
        assert r.status_code == 200
        body = r.json()
        assert body["matched"] is True and body["pin_ids"] == ["D3"]
        assert set(body.keys()) == {"answer", "pin_ids", "group", "matched"}

        # frontend dist missing -> info page, API still up
        r = client.get("/")
        assert r.status_code == 200
        assert "not built" in r.text.lower()

    # clean shutdown
    assert detector.closed is True
    assert source.closed is True


# ------------------------------------------------------------ WebSocket ----

def test_ws_hello_and_detection_broadcast(monkeypatch):
    _poison_vision_imports(monkeypatch)
    app = make_app()
    with TestClient(app) as client:
        with client.websocket_connect("/ws/detections") as ws:
            hello = ws.receive_json()
            assert hello == {
                "type": "hello",
                "board_id": "mini-board",
                "runtime_revision": 1,
                "video_size": [VIDEO_W, VIDEO_H],
            }
            msg = ws.receive_json()
            assert msg["type"] == "detection"
            assert msg["board_id"] == "mini-board"
            assert msg["tracking"] == "locked"
            assert msg["confidence"] == 0.9
            assert msg["video_size"] == [VIDEO_W, VIDEO_H]
            assert isinstance(msg["frame_id"], int)
            assert isinstance(msg["ts_ms"], (int, float))
            assert msg["outline"] == [[0.0, 0.0], [64.0, 0.0], [64.0, 48.0], [0.0, 48.0]]
            assert len(msg["pins"]) == 1
            pin = msg["pins"][0]
            assert set(pin.keys()) == {"id", "x", "y", "c", "v"}  # contract field names
            assert pin["id"] == "D3" and pin["x"] == 10.0 and pin["y"] == 5.0
            assert pin["c"] == 0.97 and pin["v"] is True


def test_detection_message_exposes_live_projected_pin_scale():
    result = DetectionResult(
        board_id="mini-board",
        frame_id=4,
        ts_ms=400.0,
        tracking="locked",
        confidence=0.9,
        pins=[
            PinDetection("D3", 20.0, 30.0, 1.0, header="J", index=0),
            PinDetection("D4", 30.0, 30.0, 1.0, header="J", index=1),
            PinDetection("D5", 40.0, 30.0, 1.0, header="J", index=2),
        ],
    )

    message = detection_message(result, (100, 100))

    assert message["geometry"] == {"pitch_px": 10.0, "px_per_mm": 3.937}


def test_detection_message_exposes_pose_quality_separately_from_confidence():
    result = DetectionResult(
        board_id="mini-board", frame_id=5, ts_ms=500.0,
        tracking="locked", confidence=0.91, pins=[],
        pose_path="track", pose_inliers=42, pose_reproj_px=0.8432,
        pose_inlier_board_area_frac=0.12345,
    )

    message = detection_message(result, (100, 100))

    assert message["pose_quality"] == {
        "path": "track",
        "inliers": 42,
        "reproj_px": 0.843,
        "inlier_board_area_frac": 0.1235,
    }


# ----------------------------------------------------------------- MJPEG ----

def test_latest_frame_jpeg_returns_finite_native_frame():
    with TestClient(make_app(source=NativeJpegStubFrameSource())) as client:
        deadline = time.monotonic() + 2.0
        response = client.get("/frame.jpg")
        while response.status_code == 503 and time.monotonic() < deadline:
            time.sleep(0.01)
            response = client.get("/frame.jpg")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"].startswith("no-store")
    assert int(response.headers["x-frame-id"]) >= 1
    assert int(response.headers["x-frame-seq"]) >= 1
    assert response.content == _NATIVE_JPEG


def test_mjpeg_stream_content_type_and_first_frame():
    """Streams from a real uvicorn server on an ephemeral port: starlette's
    TestClient buffers whole responses, so an endless MJPEG stream can only be
    exercised over an actual socket."""
    import httpx
    import threading
    import uvicorn

    app = make_app(source=NativeJpegStubFrameSource())
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, "uvicorn did not start"
        port = server.servers[0].sockets[0].getsockname()[1]

        with httpx.stream(
            "GET", f"http://127.0.0.1:{port}/video", timeout=httpx.Timeout(5.0)
        ) as response:
            assert response.status_code == 200
            content_type = response.headers["content-type"]
            assert content_type.startswith("multipart/x-mixed-replace")
            assert "boundary=frame" in content_type

            buf = b""
            for chunk in response.iter_bytes():
                buf += chunk
                if b"\xff\xd8" in buf:  # JPEG SOI marker seen
                    break
            assert buf.startswith(b"--frame\r\n")
            assert b"Content-Type: image/jpeg" in buf
            assert b"Content-Length: " in buf
            assert _NATIVE_JPEG in buf
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)
        assert not thread.is_alive(), "uvicorn did not shut down cleanly"


# -------------------------------------- actual frame size on the wire ----

def test_vision_worker_publishes_actual_frame_size():
    """Device cameras may deliver a different resolution than configured:
    the wire message must carry the ACTUAL frame size."""
    bus = FrameBus()
    state = DetectionState()
    published: list[dict] = []
    worker = VisionWorker(
        bus=bus,
        detector=StubDetector(),
        state=state,
        board_id="mini-board",
        video_size=(VIDEO_W, VIDEO_H),  # configured size (wrong on purpose)
        detection_hz=100,
        publish=published.append,
    )
    worker.start()
    try:
        assert state.get_video_size() is None  # nothing seen yet
        actual_w, actual_h = 2 * VIDEO_W, 2 * VIDEO_H
        frame = np.zeros((actual_h, actual_w, 3), np.uint8)
        bus.put(frame, 1, 123.0)
        deadline = time.monotonic() + 2.0
        while not published and time.monotonic() < deadline:
            time.sleep(0.01)
        assert published, "worker did not publish"
        assert published[-1]["video_size"] == [actual_w, actual_h]
        assert state.get_video_size() == (actual_w, actual_h)
    finally:
        worker.stop()


def test_ws_uses_actual_frame_size_when_camera_disagrees(monkeypatch):
    _poison_vision_imports(monkeypatch)
    actual_w, actual_h = 2 * VIDEO_W, 2 * VIDEO_H
    app = make_app(source=StubFrameSource(width=actual_w, height=actual_h))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/detections") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            msg = ws.receive_json()
            assert msg["type"] == "detection"
            assert msg["video_size"] == [actual_w, actual_h]
        # A detection was broadcast, so the actual size is known: a new
        # client's hello must report it (not the configured size).
        with client.websocket_connect("/ws/detections") as ws:
            hello = ws.receive_json()
            assert hello["video_size"] == [actual_w, actual_h]


# -------------------------------------------------- worker error handling ----

def test_vision_worker_survives_detector_exception():
    bus = FrameBus()
    state = DetectionState()
    published: list[dict] = []
    worker = VisionWorker(
        bus=bus,
        detector=FailingDetector(),
        state=state,
        board_id="mini-board",
        video_size=(VIDEO_W, VIDEO_H),
        detection_hz=100,
        publish=published.append,
    )
    worker.start()
    try:
        frame = np.zeros((VIDEO_H, VIDEO_W, 3), np.uint8)
        bus.put(frame, 1, 123.0)
        deadline = time.monotonic() + 2.0
        while state.get() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        result = state.get()
        assert result is not None, "worker did not emit a result"
        assert result.tracking == "searching"
        assert result.confidence == 0.0
        assert result.pins == []
        assert result.frame_id == 1 and result.ts_ms == 123.0

        # worker is still alive: feed another frame, get another result
        bus.put(frame, 2, 456.0)
        deadline = time.monotonic() + 2.0
        while (state.get() is None or state.get().frame_id != 2) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert state.get().frame_id == 2
        assert published and published[-1]["tracking"] == "searching"
    finally:
        worker.stop()
