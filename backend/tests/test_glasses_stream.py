"""Runtime session tests use real FrameBus/CaptureService, never physical cameras."""
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.glasses import router
from app.capture.bus import FrameBus
from app.capture.service import CaptureService
from app.config import load_config
from app.glasses import DEFAULTS, GlassesStreamManager
from app.profiles.store import ProfileStore
from app.runtime import BoardRuntimeManager
from app.vision_worker import DetectionState


class Holder:
    def __init__(self):
        self.clears = 0

    def clear(self):
        self.clears += 1

    def get_step(self):
        return None


class Detector:
    def __init__(self):
        self.resets = []
        self.closed = False
        self.scale_recovery = False

    def reset_for_camera(self, **kwargs):
        self.resets.append(kwargs)

    def close(self):
        self.closed = True

    def set_scale_recovery(self, enabled):
        self.scale_recovery = enabled

    def set_yolo_only(self, enabled):
        self.yolo_only = enabled


class Worker:
    def __init__(self, component_id=None):
        self._thread = None
        self._profile = SimpleNamespace(component_id=component_id)
        self.starts = 0
        self.stops = []
        self.resets = 0
        self.interval = 1 / 30
        self.scale_recovery = False

    def start(self):
        self.starts += 1
        thread = SimpleNamespace(alive=True)
        thread.is_alive = lambda: thread.alive
        self._thread = thread

    def stop(self, **kwargs):
        self.stops.append(kwargs)
        if self._thread is not None:
            self._thread.alive = False
        self._thread = None

    def reset_tracking(self):
        assert self._thread is None
        self.resets += 1

    def set_target_fps(self, hz):
        self.interval = 1 / hz

    def set_scale_recovery(self, enabled):
        assert self._thread is None
        self.scale_recovery = enabled

    def set_yolo_only(self, enabled):
        assert self._thread is None
        self.yolo_only = enabled

    def set_detector(self, detector, **kwargs):
        self.detector = detector
        self.runtime_revision = kwargs["runtime_revision"]

    def set_board_id(self, board_id):
        self.board_id = board_id


class Source:
    owners = set()

    def __init__(self, width=1920, height=1080, fps=30, denoise="clean", reinitialize=False,
                 pixel=2):
        self.settings = dict(width=width, height=height, fps=fps, denoise=denoise)
        self.reinitialize = reinitialize
        self.opens = 0
        self.closes = 0
        self.frame_id = 0
        self.phase = "stopped"
        self.image = np.full((height, width, 3), pixel, np.uint8)

    def open(self):
        assert not self.owners, "two camera owners"
        self.owners.add(self)
        self.opens += 1
        self.phase = "live"

    def close(self):
        self.owners.discard(self)
        self.closes += 1
        self.phase = "stopped"

    def read(self):
        time.sleep(.01)
        self.frame_id += 1
        return self.image, self.frame_id, time.monotonic() * 1000

    def snapshot(self):
        return dict(state=self.phase, actual=self.settings, capture_fps=29.9,
                    processing_fps=29.0, error="unplugged" if self.phase == "error" else None)

    def set_denoise(self, mode):
        self.settings["denoise"] = mode


@pytest.fixture
def session():
    Source.owners.clear()
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    config.board = "raspberry-pi-5"
    config.detector = "hybrid"
    config.camera.source = "device"
    original_camera = config.camera.model_copy(deep=True)
    store = ProfileStore(config.profile_dir)
    bus = FrameBus()
    normal = Source(width=64, height=36, pixel=1)
    messages = []
    state = SimpleNamespace(
        config=config, source=normal, frame_bus=bus,
        detector=Detector(), profile=store.profile(config.board),
        query_service=None, scene=None,
        vision_worker=Worker(), component_worker=None,
        component_workers=[Worker(id) for id in ("hc-sr04", "hw-123", "mrd-tf240-8p-cs")],
        body_worker=Worker(), motion_worker=Worker(),
        wire_worker=Worker(), electrical_worker=Worker(),
        component_segmentation_worker=None, insertion_vlm_worker=None,
        final_wiring_vlm_worker=None, wire_color_vlm_worker=None,
        detection_state=DetectionState(), component_pose_state=Holder(),
        motion_frame_state=Holder(), wire_state=Holder(), guidance_state=Holder(),
        verification_state=Holder(), guidance_color_preview=Holder(),
        broadcaster=SimpleNamespace(publish_threadsafe=messages.append),
    )
    state.runtime_manager = BoardRuntimeManager(
        config=config, profile_store=store,
        detector_builder=lambda *args: Detector(),
    )
    created = []

    def build_source(**settings):
        source = Source(**settings)
        created.append(source)
        return source

    def build_yolo_worker(**kwargs):
        worker = Worker()
        worker.inputs = kwargs
        worker.set_target_fps(kwargs['hz'])
        return worker

    manager = GlassesStreamManager(state, source_factory=build_source,
                                   yolo_worker_factory=build_yolo_worker)
    state.glasses_stream = manager
    for worker in manager._visual_workers() + [state.wire_worker, state.electrical_worker]:
        worker.start()
    state.capture_service = CaptureService(normal, bus)
    state.capture_service.start()
    assert bus.get_latest(timeout=1) is not None
    yield manager, state, normal, created, original_camera
    state.capture_service.stop()
    Source.owners.clear()


def test_enter_reconfigure_denoise_and_restore(session):
    manager, state, normal, created, original = session
    detector = state.detector
    initial_seq = state.frame_bus.latest_seq
    result = manager.configure(dict(DEFAULTS))
    assert result["active"] and result["error"] is None
    assert normal.closes == 1
    assert state.config.camera.source == "xreal"
    assert state.config.camera.focus is None
    assert state.config.camera.native_uvc_controls is False
    assert state.wire_worker._thread is None and state.electrical_worker._thread is None
    slot = state.frame_bus.get_latest(timeout=1, newer_than=initial_seq)
    assert slot is not None and slot.frame[0, 0, 0] == 2
    assert slot.frame.shape == (1080, 1920, 3)
    revision = result["runtime_revision"]
    assert state.detector is detector and not detector.closed
    assert detector.resets[-1]["use_camera_calibration"] is False
    assert detector.scale_recovery is True
    assert detector.yolo_only is True
    assert manager._yolo_worker._thread.is_alive()
    assert state.vision_worker._thread is None and state.motion_worker._thread is None
    assert all(w._thread is None and w.yolo_only for w in state.component_workers)
    assert all(w.scale_recovery for w in state.component_workers)
    manager.configure({**DEFAULTS, "denoise": "strong"})
    assert len(created) == 1
    assert manager.snapshot()["runtime_revision"] == revision
    assert created[0].settings["denoise"] == "strong"
    manager.configure({**DEFAULTS, "width": 2048, "height": 1512, "fps": 60})
    assert len(created) == 2 and created[0].closes == 1
    assert manager.snapshot()["runtime_revision"] > revision
    assert state.motion_worker.interval == 1 / 60
    assert state.detector is detector
    assert all(w.stops[-1] == {"close_models": False} for w in state.component_workers)
    result = manager.restore()
    assert result["active"] is False and result["state"] == "stopped"
    assert state.source is normal and normal.opens == 2
    assert state.config.camera == original
    assert all(not w.scale_recovery for w in state.component_workers)
    assert detector.resets[-1]["use_camera_calibration"] is True
    assert detector.scale_recovery is False
    assert detector.yolo_only is False
    assert manager._yolo_worker is None
    assert state.motion_worker.interval == 1 / 30
    assert state.wire_worker._thread is not None and state.electrical_worker._thread is not None
    assert manager.restore()["runtime_revision"] == result["runtime_revision"]


def test_same_size_retry_after_disconnect_clears_context(session):
    manager, state, normal, created, _ = session
    manager.configure(dict(DEFAULTS))
    revision = manager.snapshot()["runtime_revision"]
    created[0].phase = "error"
    assert manager.snapshot()["error"] == "unplugged"
    manager.configure(dict(DEFAULTS))
    assert len(created) == 2 and created[1].reinitialize
    assert manager.snapshot()["runtime_revision"] > revision
    assert state.component_pose_state.clears == 2
    assert state.motion_frame_state.clears == 2
    assert all(w.resets == 2 for w in state.component_workers)


def test_repeated_eye_cycles_restore_all_webcam_workers_and_controls(session):
    manager, state, normal, _, original_camera = session
    detector = state.detector
    visual = tuple(manager._visual_workers())
    component_config = state.config.component_vision.model_dump()
    model_config = state.config.yolo_pose.model_dump()
    initial_revision = state.runtime_manager.runtime_revision
    for cycle, settings in enumerate((dict(DEFAULTS),
            {**DEFAULTS, "width": 2048, "height": 1512, "fps": 60, "denoise": "strong"},
            {**DEFAULTS, "width": 1080, "height": 1920, "denoise": "original"}), start=1):
        entered = manager.configure(settings)
        assert entered["active"] and entered["error"] is None
        assert all(not manager._running(worker) for worker in visual)
        assert detector.yolo_only and detector.scale_recovery
        assert all(worker.yolo_only and worker.scale_recovery for worker in state.component_workers)
        eye_worker = manager._yolo_worker
        frame_before_restore = state.frame_bus.latest_seq

        restored = manager.restore()
        assert not restored["active"] and restored["error"] is None
        assert not manager._running(eye_worker) and manager._yolo_worker is None
        assert state.source is normal and state.config.camera == original_camera
        assert state.detector is detector and not detector.closed
        assert not detector.yolo_only and not detector.scale_recovery
        assert detector.resets[-1] == {
            "horizontal_fov_deg": original_camera.horizontal_fov_deg,
            "camera_calibration_path": original_camera.calibration_path,
            "use_camera_calibration": True,
        }
        assert all(not worker.yolo_only and not worker.scale_recovery for worker in state.component_workers)
        assert all(manager._running(worker) and worker.starts == cycle + 1 for worker in visual)
        assert state.motion_worker.interval == 1 / 30
        assert state.config.component_vision.model_dump() == component_config
        assert state.config.yolo_pose.model_dump() == model_config
        assert state.runtime_manager.runtime_revision == initial_revision + 2 * cycle
        assert state.component_pose_state.clears == 2 * cycle
        assert state.motion_frame_state.clears == 2 * cycle
        assert all(worker.resets == 2 * cycle for worker in state.component_workers)
        frame = state.frame_bus.get_latest(timeout=1, newer_than=frame_before_restore)
        assert frame is not None and frame.frame[0, 0, 0] == 1  # Original source, never Eye.


def test_current_wiring_board_and_model_are_never_replaced(session):
    manager, state, _, _, _ = session
    state.runtime_manager.select("arduino-uno-q", state)
    detector = state.detector
    component_config = state.config.component_vision
    yolo_config = state.config.yolo_pose.model_dump()
    state.config.detector = "pipeline"
    state.config.realtime_tracking = False
    manager.configure(dict(DEFAULTS))
    assert state.runtime_manager.board_id == "arduino-uno-q"
    assert state.detector is detector and not detector.closed
    assert state.config.detector == "pipeline"
    assert state.config.component_vision is component_config
    assert state.config.yolo_pose.model_dump() == yolo_config
    assert state.config.realtime_tracking is False
    manager.restore()
    assert state.runtime_manager.board_id == "arduino-uno-q"
    assert state.detector is detector and not detector.closed


def test_eye_reuses_all_active_wiring_targets_without_enabling_others(session):
    manager, state, _, _, _ = session
    configured_extra = Worker("photoresistor-module")
    configured_extra.start()
    inactive = Worker("another-configured-target")
    state.component_workers.extend([configured_extra, inactive])
    workers = tuple(state.component_workers)
    targets = state.config.component_vision.model_dump()
    manager.configure(dict(DEFAULTS))
    assert tuple(state.component_workers) == workers
    assert configured_extra.starts == 1
    assert configured_extra in manager._yolo_worker.inputs['component_workers']
    assert inactive not in manager._yolo_worker.inputs['component_workers']
    assert inactive.starts == 0
    assert state.config.component_vision.model_dump() == targets
    manager.configure({**DEFAULTS, "fps": 60})
    assert configured_extra.starts == 1
    assert inactive.starts == 0
    manager.restore()
    assert configured_extra.starts == 2
    assert inactive.starts == 0


def test_api_readback_and_invalid_modes_never_open_camera(session):
    manager, state, _, created, _ = session
    app = FastAPI()
    app.state.glasses_stream = manager
    app.include_router(router)
    with TestClient(app) as client:
        assert client.get("/api/glasses/stream").json()["active"] is False
        for change in ({"fps": 25}, {"width": 2016}, {"denoise": "unknown"}):
            assert client.put("/api/glasses/stream", json={**DEFAULTS, **change}).status_code == 422
        assert not created
        response = client.put("/api/glasses/stream", json=DEFAULTS)
        assert response.status_code == 200
        assert response.json()["requested"] == DEFAULTS
        assert response.json()["modes"]["fps"] == [30, 60]
        assert client.delete("/api/glasses/stream").json()["active"] is False


def test_bus_clear_preserves_sequence():
    bus = FrameBus()
    image = np.zeros((2, 3, 3), np.uint8)
    bus.put(image, 10, 1)
    seq = bus.latest_seq
    bus.clear()
    assert bus.get_latest(timeout=.01) is None
    bus.put(image, 1, 2)
    assert bus.get_latest(timeout=.01, newer_than=seq).seq == seq + 1


def test_slow_background_worker_is_joined_before_camera_swap(session):
    manager, state, normal, created, _ = session
    worker = state.wire_worker
    old_stop = worker.stop
    thread = worker._thread
    worker.stop = lambda: setattr(worker, "_thread", None)
    result = manager.configure(dict(DEFAULTS))
    assert result["state"] == "error"
    assert worker._thread is thread and thread.is_alive()
    assert not created and normal.closes == 0
    worker.stop = old_stop
    result = manager.configure(dict(DEFAULTS))
    assert result["error"] is None and len(created) == 1
