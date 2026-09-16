"""One runtime camera session; the normal source is restored when Eye exits."""
from __future__ import annotations

import logging
import threading

from app.capture.service import CaptureService
from app.config import CameraConfig

log = logging.getLogger(__name__)
DEFAULTS = {"width": 1920, "height": 1080, "fps": 30, "denoise": "clean"}
MODES = {
    "resolutions": [{"width": w, "height": h} for w, h in
                    ((1920, 1080), (2048, 1512), (1080, 1920), (720, 1280))],
    "fps": [30, 60], "denoise": ["original", "clean", "strong"],
}
AUXILIARY = (
    "wire_worker", "component_segmentation_worker", "insertion_vlm_worker",
    "final_wiring_vlm_worker", "wire_color_vlm_worker", "electrical_worker",
)


def _eye_source(**settings):
    from app.capture.xreal import XrealEyeSource
    return XrealEyeSource(**settings)


class GlassesStreamManager:
    def __init__(self, state, *, source_factory=None, yolo_worker_factory=None):
        self.state = state
        self._source_factory = source_factory or _eye_source
        if yolo_worker_factory is None:
            from app.eye_yolo_worker import EyeYoloWorker
            yolo_worker_factory = EyeYoloWorker
        self._yolo_worker_factory = yolo_worker_factory
        self._yolo_worker = None
        self._lock = threading.RLock()
        self._saved = None
        self._eye = None
        self._error = None
        self._phase = "stopped"
        self._requested = dict(DEFAULTS)

    def _components(self):
        workers = list(self.state.component_workers)
        legacy = self.state.component_worker
        if legacy is not None:
            workers.append(legacy)
        return workers

    def _visual_workers(self):
        return [w for w in (
            self.state.vision_worker, self.state.motion_worker,
            self.state.body_worker, *self._components(),
        ) if w is not None]

    @staticmethod
    def _running(worker):
        thread = getattr(worker, "_thread", None)
        return thread is not None and thread.is_alive()

    def _stop_visual(self):
        # A completed stop is required before resetting model/tracker state.
        self.stop_yolo_worker()
        for worker in self._visual_workers():
            if worker is self.state.body_worker or worker in self._components():
                worker.stop(close_models=False)
            else:
                worker.stop()

    def stop_yolo_worker(self):
        if self._yolo_worker is not None:
            self._yolo_worker.stop()
            self._yolo_worker = None

    @staticmethod
    def _stop_auxiliary(worker):
        thread = getattr(worker, "_thread", None)
        worker.stop()
        if thread is not None and thread.is_alive():
            # Older workers discard the handle even after a timed-out join.
            # Retain it so a retry joins that worker instead of duplicating it.
            worker._thread = thread
            raise RuntimeError("Background worker is still stopping; apply again shortly")

    def _reset(self):
        state = self.state
        state.frame_bus.clear()
        for name in ("detection_state", "component_pose_state", "motion_frame_state",
                     "wire_state", "verification_state", "guidance_color_preview"):
            holder = getattr(state, name, None)
            if holder is not None and hasattr(holder, "clear"):
                holder.clear()
        state.detection_state.set_video_size((state.config.camera.width, state.config.camera.height))
        reset = getattr(state.detector, "reset_for_camera", None)
        if reset is not None:
            camera = state.config.camera
            reset(horizontal_fov_deg=camera.horizontal_fov_deg,
                  camera_calibration_path=camera.calibration_path,
                  use_camera_calibration=camera.source != "xreal")
        recover_board_scale = getattr(state.detector, "set_scale_recovery", None)
        if recover_board_scale is not None:
            recover_board_scale(state.config.camera.source == "xreal")
        set_yolo_only = getattr(state.detector, "set_yolo_only", None)
        if set_yolo_only is not None:
            set_yolo_only(state.config.camera.source == "xreal")
        for worker in self._visual_workers():
            reset = getattr(worker, "reset_tracking", None)
            if reset is not None:
                reset()
        for worker in self._components():
            recover_scale = getattr(worker, "set_scale_recovery", None)
            if recover_scale is not None:
                recover_scale(state.config.camera.source == "xreal")
            set_yolo_only = getattr(worker, "set_yolo_only", None)
            if set_yolo_only is not None:
                set_yolo_only(state.config.camera.source == "xreal")
        state.runtime_manager.camera_changed(state)

    def _start_eye_vision(self):
        state = self.state
        # Use the existing YOLO sessions, and project all GPIO/Pin on one image.
        # The normal feature/consensus/flow workers stay stopped during Eye.
        if state.motion_worker is not None:
            state.motion_worker.set_target_fps(self._requested["fps"])
        detector = getattr(state.detector, "primary", state.detector)
        if not hasattr(detector, "set_yolo_only"):
            raise RuntimeError("Eye needs a loaded YOLO detector")
        self._yolo_worker = self._yolo_worker_factory(
            bus=state.frame_bus, detection_state=state.detection_state,
            component_state=state.component_pose_state,
            runtime_manager=state.runtime_manager, motion_frame_state=state.motion_frame_state,
            detector=detector,
            component_workers=[w for w in self._components() if w in self._saved["visual"]],
            # Eye sends the image and all poses together through tracking/frame.
            # Runtime-change events keep their own broadcaster; normal workers
            # retain their publishers when restored.
            hz=self._requested["fps"],
        )
        self._yolo_worker.start()

    def configure(self, settings):
        with self._lock:
            state = self.state
            previous = dict(self._requested)
            failed = self._error is not None or (
                self._eye is not None and self._eye.snapshot().get("state") == "error"
            )
            self._requested = dict(settings)
            self._error = None
            if self._eye is not None and not failed and all(
                previous[k] == settings[k] for k in ("width", "height", "fps")
            ):
                self._eye.set_denoise(settings["denoise"])
                return self.snapshot()
            self._phase = "starting" if self._saved is None else "switching"
            try:
                if self._saved is None:
                    self._saved = {
                        "source": state.source,
                        "camera": state.config.camera.model_copy(deep=True),
                        "visual": [w for w in self._visual_workers() if self._running(w)],
                        "auxiliary": [w for name in AUXILIARY
                                      if (w := getattr(state, name, None)) is not None and self._running(w)],
                        "motion_fps": (1 / state.motion_worker.interval
                                       if state.motion_worker is not None else 30),
                    }
                for worker in self._saved["auxiliary"]:
                    self._stop_auxiliary(worker)
                state.capture_service.stop()
                self._stop_visual()
                self._eye = None
                state.config.camera = CameraConfig(
                    source="xreal", width=settings["width"], height=settings["height"],
                    fps=settings["fps"], capture_api="msmf", horizontal_fov_deg=None,
                    calibration_path=None,
                )
                self._reset()
                self._eye = self._source_factory(**settings, reinitialize=failed)
                state.source = self._eye
                state.capture_service = CaptureService(self._eye, state.frame_bus)
                state.capture_service.start()
                self._start_eye_vision()
                self._phase = "starting"
            except Exception as exc:
                log.exception("Eye stream configuration failed")
                self._error = str(exc)
                self._phase = "error"
            return self.snapshot()

    def restore(self):
        with self._lock:
            if self._saved is None:
                return self.snapshot()
            state, saved = self.state, self._saved
            self._phase, self._error = "stopping", None
            try:
                for worker in saved["auxiliary"]:
                    self._stop_auxiliary(worker)
                state.capture_service.stop()
                self._stop_visual()
                self._eye = None
                state.config.camera = saved["camera"]
                self._reset()
                if state.motion_worker is not None:
                    state.motion_worker.set_target_fps(saved["motion_fps"])
                state.source = saved["source"]
                state.capture_service = CaptureService(state.source, state.frame_bus)
                state.capture_service.start()
                for worker in saved["visual"]:
                    worker.start()
                for worker in saved["auxiliary"]:
                    worker.start()
                self._saved = None
                self._phase = "stopped"
            except Exception as exc:
                log.exception("Original camera restore failed")
                self._error, self._phase = str(exc), "error"
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            info = self._eye.snapshot() if self._eye is not None else {}
            phase = info.get("state", self._phase)
            if phase == "live":
                phase = "running"
            actual = info.get("actual") or {}
            return {
                "active": self._saved is not None,
                "state": "error" if self._error else phase,
                "error": self._error or info.get("error"),
                "requested": dict(self._requested),
                "actual": {"width": actual.get("width"), "height": actual.get("height")},
                "capture_fps": info.get("capture_fps", 0),
                "processing_fps": info.get("processing_fps", 0),
                "denoise_backend": info.get("denoise_backend"),
                "denoise_fallback_reason": info.get("denoise_fallback_reason"),
                "inference": (self._yolo_worker.snapshot()
                              if self._yolo_worker is not None and hasattr(self._yolo_worker, 'snapshot')
                              else None),
                "runtime_revision": self.state.runtime_manager.runtime_revision,
                "modes": MODES,
            }
