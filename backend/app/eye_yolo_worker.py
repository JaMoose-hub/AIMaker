"""Same-frame Eye preview using YOLO and local image-corrected GPIO projection.

The caller supplies the YOLO-only board detector and stopped component workers.
Their model sessions remain loaded. The detectors may correct current-frame
J8/contact or mounting-hole geometry without another AI model. This loop does
not invoke optical flow, feature recovery or verification workers. A small
display correction smooths fresh geometry; missing results clear immediately.
"""
from __future__ import annotations

import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
import math
import threading
import time

import cv2

from app.component_worker import ComponentPoseResult, component_pose_message
from app.vision.interface import DetectionResult
from app.vision_worker import detection_message
from app.eye_timing import wait_eye_deadline
from app.eye_display_stabilizer import EyeYoloDisplayStabilizer

log = logging.getLogger(__name__)


def _box(result):
    body = result.body
    if body is None:
        return None
    values = body.get("box")
    if not isinstance(values, (tuple, list)) or len(values) != 4:
        return None
    values = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in values):
        return None
    return values


def _iou(first, second):
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0., x2 - x1) * max(0., y2 - y1)
    area_a = max(0., first[2] - first[0]) * max(0., first[3] - first[1])
    area_b = max(0., second[2] - second[0]) * max(0., second[3] - second[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.


def suppress_overlapping_classes(board_result, component_results, threshold=0.5):
    """Standard confidence-ordered NMS across these independent YOLO classes."""
    results = [board_result, *component_results]
    candidates = [(index, _box(result)) for index, result in enumerate(results)]
    candidates = [(index, box) for index, box in candidates if box is not None]
    candidates.sort(key=lambda item: float(results[item[0]].body["confidence"]), reverse=True)
    kept, suppressed = [], set()
    for index, box in candidates:
        if any(_iou(box, existing) > threshold for existing in kept):
            suppressed.add(index)
        else:
            kept.append(box)
    for index in suppressed:
        result = results[index]
        if index == 0:
            results[index] = replace(result, tracking="searching", confidence=0.,
                pins=[], outline_px=None, body=None, motion_outline_px=None,
                wire_exclusion_px=None, pose_stability_state="yolo_direct", pose_path="yolo_nms")
        else:
            results[index] = replace(result, tracking="searching", confidence=0.,
                pins=(), outline_px=None, body=None, motion_outline_px=None,
                diagnostic_pins=(), diagnostic_box_px=None, diagnostic_reason=None,
                stability="yolo_direct", tracking_reason="yolo_nms")
    return results[0], results[1:]


def _current_body(body, slot):
    """Represent a fresh YOLO box in the existing preview-outline wire shape."""
    if body is None:
        return None
    x1, y1, x2, y2 = body["box"]
    return {**body, "outline": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "frame_id": slot.frame_id, "source_frame_id": slot.frame_id,
            "age_ms": 0., "partial": bool(body.get('partial', False)), "display_only": True}


class EyeYoloWorker:
    def __init__(self, bus, detection_state, component_state, runtime_manager,
                 motion_frame_state, detector, component_workers, hz=30, publish=None):
        self.bus, self.detection_state = bus, detection_state
        self.component_state, self.runtime_manager = component_state, runtime_manager
        self.state, self.detector = motion_frame_state, detector
        self.component_workers = tuple(component_workers)
        self.publish = publish
        self.set_target_fps(hz)
        self._stop = threading.Event()
        self._thread = None
        self._executor = None
        self._process_lock = threading.Lock()
        self._display_stabilizer = EyeYoloDisplayStabilizer()
        self._display_context = None
        self._last_seq = -1
        self._statistics_lock = threading.Lock()
        self._processed = 0
        self._rates = deque()
        self._processing_ms = 0.
        self._bus_wait_ms = 0.
        self._postprocessing_ms = 0.
        self._error = None

    def set_target_fps(self, hz):
        hz = float(hz)
        if not math.isfinite(hz) or not 1 <= hz <= 60:
            raise ValueError("Eye display FPS must be between 1 and 60")
        self.target_fps, self.interval = hz, 1 / hz

    def snapshot(self):
        from app.vision.inference_status import locator_status
        detector = getattr(self.detector, 'primary', self.detector)
        board_id = self.runtime_manager.snapshot().board_id
        entries = [(board_id, getattr(detector, '_locator', None))]
        recovery = getattr(detector, '_reference_recovery', None)
        if recovery is not None:
            entries.append((board_id + '-roi', getattr(recovery, 'roi_locator', None)))
        entries.extend((worker._profile.component_id, getattr(worker, '_locator', None))
                       for worker in self.component_workers)
        models = [{**locator_status(locator, 'cuda'), 'id': identifier}
                  for identifier, locator in entries]
        with self._statistics_lock:
            fps = 0.
            fresh = bool(self._rates and time.monotonic() - self._rates[-1][0] <= .6)
            if fresh and len(self._rates) >= 2 and self._rates[-1][0] > self._rates[0][0]:
                fps = (self._rates[-1][1] - self._rates[0][1]) / (self._rates[-1][0] - self._rates[0][0])
            return {"target_fps": self.target_fps, "processing_fps": fps,
                    "processing_ms": self._processing_ms if fresh else 0., "processed_frames": self._processed,
                    "bus_wait_ms": self._bus_wait_ms if fresh else 0.,
                    "postprocessing_ms": self._postprocessing_ms if fresh else 0.,
                    "error": self._error, "models": models}

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="eye-yolo", daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("Eye YOLO worker did not stop")
            self._thread = None
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None
        self._display_stabilizer.reset()
        self._display_context = None
        self.state.clear()

    def reset_tracking(self):
        """Reset source bookkeeping while stopped, retaining every YOLO session."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Stop Eye YOLO worker before changing the camera")
        self._last_seq = -1
        self._display_stabilizer.reset()
        self._display_context = None
        with self._statistics_lock:
            self._processed = 0
            self._rates.clear()
            self._processing_ms = 0.
            self._bus_wait_ms = 0.
            self._postprocessing_ms = 0.
            self._error = None
        self.state.clear()
        self.detection_state.clear()
        self.component_state.clear()

    def process(self, slot):
        # Each loaded locator owns mutable CUDA input buffers. Independent
        # models run together; a second frame never enters the same group.
        with self._process_lock:
            try:
                return self._process(slot)
            except Exception:
                self._display_stabilizer.reset()
                self._display_context = None
                raise

    def _board(self, slot, runtime):
        started = time.perf_counter()
        error = None
        try:
            result = self.detector.detect(slot.frame, slot.frame_id, slot.ts_ms)
            if result is None:
                raise ValueError('YOLO board detector returned no DetectionResult')
            if (result.frame_id, result.ts_ms, result.board_id) != (slot.frame_id, slot.ts_ms, runtime.board_id):
                raise ValueError('YOLO board result does not match the source frame')
        except Exception as exc:
            log.exception('Eye board YOLO failed for frame %s', slot.frame_id)
            error = str(exc)
            result = DetectionResult(runtime.board_id, slot.frame_id, slot.ts_ms,
                'searching', 0., pose_path='yolo_error', pose_stability_state='yolo_direct')
        return result, round((time.perf_counter()-started)*1000, 2), error

    def _component(self, worker, slot, size):
        started = time.perf_counter()
        component_id, error = worker._profile.component_id, None
        try:
            result = worker.detect_yolo_frame(slot)
            if (result.frame_id, result.ts_ms, result.component_id) != (slot.frame_id, slot.ts_ms, component_id):
                raise ValueError('Component YOLO result does not match the source frame')
        except Exception as exc:
            log.exception('Eye component YOLO %s failed for frame %s', component_id, slot.frame_id)
            error = str(exc)
            result = ComponentPoseResult(component_id, slot.frame_id, slot.ts_ms,
                'searching', 0., size, None, (), 'yolo_direct', tracking_reason='yolo_error')
        return result, round((time.perf_counter()-started)*1000, 2), error

    def _process(self, slot):
        """Infer and publish one image/YOLO group without borrowing old results."""
        if self._stop.is_set() or slot.seq <= self._last_seq:
            return None
        runtime = self.runtime_manager.snapshot()
        started = time.perf_counter()
        size = (int(slot.frame.shape[1]), int(slot.frame.shape[0]))
        object_ms = {}
        model_errors = {}
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1+len(self.component_workers),
                                                thread_name_prefix='eye-yolo-model')
        board_future = self._executor.submit(self._board, slot, runtime)
        futures = [self._executor.submit(self._component, worker, slot, size)
                   for worker in self.component_workers]
        board_result, object_ms['board'], error = board_future.result()
        if error:
            model_errors[runtime.board_id] = error
        component_results = []
        # Drain every model even if stop/revision changed; shared locators must
        # finish before webcam restoration is allowed to reuse them.
        for worker, future in zip(self.component_workers, futures):
            component_id = worker._profile.component_id
            result, object_ms[component_id], error = future.result()
            if error:
                model_errors[component_id] = error
            component_results.append(result)
        if self._stop.is_set():
            return None
        board_result, component_results = suppress_overlapping_classes(board_result, component_results)
        smoothing_started = time.perf_counter()
        display_context = (runtime.board_id, runtime.runtime_revision, size)
        if display_context != self._display_context:
            self._display_stabilizer.reset()
            self._display_context = display_context
        # NMS/error/missing results reach the helper too, clearing the matching
        # object immediately. Body-only ROI results stay body-only; this layer
        # never turns unverified model corners into GPIO or revives old pins.
        board_result = self._display_stabilizer.apply(board_result,
            video_size=size, runtime_revision=runtime.runtime_revision)
        component_results = [self._display_stabilizer.apply(result,
            video_size=size, runtime_revision=runtime.runtime_revision)
            for result in component_results]
        smoothing_ms = (time.perf_counter() - smoothing_started) * 1000
        # Every outcome belongs to this exact image, including absent/NMS/error
        # results. Keep the direct-frame marker so clients never smooth old pins
        # into a fresh missing detection; explanatory reasons remain separate.
        board_result = replace(board_result, pose_stability_state="yolo_direct")
        component_results = [replace(result, stability="yolo_direct") for result in component_results]
        detection = detection_message(board_result, size, runtime.runtime_revision)
        detection["body"] = _current_body(detection.get("body"), slot)
        components = []
        for result in component_results:
            message = component_pose_message(result)
            message["body"] = _current_body(message.get("body"), slot)
            components.append(message)
        jpeg_started = time.perf_counter()
        jpeg = slot.jpeg
        if jpeg is None:
            ok, buffer = cv2.imencode(".jpg", slot.frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise RuntimeError("Could not encode the Eye YOLO preview")
            jpeg = buffer.tobytes()
        packet = {"seq": slot.seq, "frame_id": slot.frame_id, "ts_ms": slot.ts_ms,
                  "runtime_revision": runtime.runtime_revision, "board_id": runtime.board_id,
                  "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii"),
                  "detection": detection, "components": components, "display_only": True,
                  "mode": "yolo_only",
                  "inference_execution": "parallel",
                  "display_stabilization": self._display_stabilizer.diagnostics(),
                  "timing_ms": {"objects": object_ms,
                                "display_stabilization": round(smoothing_ms, 2),
                                "jpeg": round((time.perf_counter() - jpeg_started) * 1000, 2)},
                  "processing_ms": round((time.perf_counter() - started) * 1000, 2),
                  "recovery_searches": 0, "recovery_deferred": []}
        if model_errors:
            packet["model_errors"] = model_errors
        current = self.runtime_manager.snapshot()
        if self._stop.is_set() or (runtime.board_id, runtime.runtime_revision) != (
                current.board_id, current.runtime_revision):
            self._display_stabilizer.reset()
            self._display_context = None
            return None
        self._last_seq = slot.seq
        self.detection_state.set_video_size(size)
        self.detection_state.set(board_result, slot)
        for result in component_results:
            self.component_state.set(result, slot)
        now = time.monotonic()
        with self._statistics_lock:
            self._processed += 1
            self._rates.append((now, self._processed))
            while len(self._rates) > 2 and self._rates[0][0] < now - 3:
                self._rates.popleft()
            self._processing_ms = packet["processing_ms"]
            self._error = None
        self.state.set(packet, slot)
        if self.publish is not None:
            try:
                self.publish(detection)
                for component in components:
                    self.publish(component)
            except Exception:
                log.exception("Eye YOLO websocket publication failed")
        return packet

    def _run(self):
        while not self._stop.is_set():
            waiting = time.perf_counter()
            slot = self.bus.get_latest(timeout=0.1, newer_than=self._last_seq)
            if slot is None:
                continue
            started = time.perf_counter()
            bus_wait_ms = (started - waiting) * 1000
            try:
                packet = self.process(slot)
                if packet is not None:
                    with self._statistics_lock:
                        self._bus_wait_ms = bus_wait_ms
                        self._postprocessing_ms = max(0.,
                            (time.perf_counter() - started) * 1000 - packet['processing_ms'])
            except Exception as exc:
                self._last_seq = slot.seq
                self.state.clear()
                with self._statistics_lock:
                    self._error = str(exc)
                log.exception("Eye YOLO preview failed for frame %s", slot.frame_id)
            wait_eye_deadline(self._stop, started + self.interval)
