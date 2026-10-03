"""Phone images use stateless YOLO observations and the existing photo geometry.

No camera, FrameBus, live tracker reset, or camera calibration is used here.
Borrowed model owners serialize inference/close; this service owns geometry only.
"""
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import cv2
import numpy as np
from fastapi import HTTPException

from app.component_worker import (ComponentPoseResult, ComponentVisionProfile,
    component_pose_message, project_component_outline, project_component_pins)
from app.designs import CATALOG, profile_versions, wiring_for
from app.photo_geometry import PhotoGeometry
from app.vision.body_tracking import body_observation
from app.vision.interface import DetectionResult
from app.vision.yolo_pose import create_yolo_pose_locator
from app.vision.yolo_profile_detector import (_canonical_reference_board,
    _ordered_quad_ok, _pi_corner_box_consistent, _project_profile_on_observed_quad,
    _correct_pi5_j8_from_image, _anchor_profile_header_from_landmarks)
from app.vision.reference_recovery import ReferencePoseRecovery
from app.vision_worker import detection_message
from app.wiring_capture import image_quality

COMPONENTS = ("hc-sr04", "mrd-tf240-8p-cs")


class MobilePhotoAnalyzer:
    def __init__(self, state, *, contexts=None, geometry_factory=PhotoGeometry):
        self.state = state
        self.lock = threading.RLock()
        self.contexts = contexts
        self.geometry_factory = geometry_factory
        self.geometries = {}
        self.owned_models = []
        self._owned_contexts = {}
        self._model_contexts = None
        self._live_signature = None

    def _models(self):
        if self.contexts is not None:
            return self.contexts
        primary = getattr(self.state.detector, "primary", self.state.detector)
        workers = list(getattr(self.state, "component_workers", []))
        legacy = getattr(self.state, "component_worker", None)
        if legacy is not None:
            workers.append(legacy)
        signature = (id(getattr(primary, "_locator", None)),
            tuple((getattr(getattr(w, "_profile", None), "component_id", None), id(getattr(w, "_locator", None))) for w in workers))
        if self._model_contexts is not None and signature == self._live_signature:
            return self._model_contexts
        store = self.state.profile_store
        profile = store.profile("raspberry-pi-5")
        folder = store.board_dir("raspberry-pi-5")
        cfg = self.state.config
        locator = getattr(primary, "_locator", None)
        if getattr(getattr(primary, "_profile", None), "board", None) != profile.board:
            locator = None
        if locator is None:
            owned = self._owned_contexts.get("raspberry-pi-5")
            if owned is None:
                y = cfg.yolo_pose
                locator = create_yolo_pose_locator(y.model_path_for("raspberry-pi-5"),
                    runtime_backend=y.runtime_backend, cuda_device_id=y.cuda_device_id,
                    directml_device_id=y.directml_device_id, input_size=y.input_size,
                    confidence_threshold=y.confidence_threshold_for("raspberry-pi-5"),
                    keypoint_threshold=y.keypoint_threshold, nms_iou_threshold=y.nms_iou_threshold,
                    keypoint_count=y.keypoint_count_for("raspberry-pi-5"))
                self.owned_models.append(locator)
                self._owned_contexts["raspberry-pi-5"] = SimpleNamespace(_locator=locator)
            else:
                locator = owned._locator
        result = {"raspberry-pi-5": SimpleNamespace(_profile=profile, _profile_dir=folder,
            _reference_board_bgr=_canonical_reference_board(profile, folder), _locator=locator)}
        for cid in COMPONENTS:
            worker = next((w for w in workers if getattr(getattr(w, "_profile", None), "component_id", None) == cid), None)
            if worker is not None:
                result[cid] = SimpleNamespace(_profile=worker._profile, _locator=worker._locator,
                    _reference_recovery=getattr(worker, "_reference_recovery", None))
                continue
            if cid in self._owned_contexts:
                result[cid] = self._owned_contexts[cid]
                continue
            target = next((t for t in cfg.component_vision.components if t.id == cid), None)
            if target is None:
                continue
            p = ComponentVisionProfile.load(target.profile_path)
            c = cfg.component_vision
            locator = create_yolo_pose_locator(target.model_path, runtime_backend=c.runtime_backend,
                cuda_device_id=c.cuda_device_id, directml_device_id=c.directml_device_id,
                input_size=target.input_size or c.input_size,
                confidence_threshold=target.confidence_threshold if target.confidence_threshold is not None else c.confidence_threshold,
                keypoint_threshold=target.keypoint_threshold if target.keypoint_threshold is not None else c.keypoint_threshold,
                nms_iou_threshold=target.nms_iou_threshold if target.nms_iou_threshold is not None else c.nms_iou_threshold,
                keypoint_count=p.keypoint_count)
            self.owned_models.append(locator)
            result[cid] = SimpleNamespace(_profile=p, _locator=locator,
                _reference_recovery=ReferencePoseRecovery.from_component_profile(target.profile_path))
            self._owned_contexts[cid] = result[cid]
        self._model_contexts = result
        self._live_signature = signature
        return result

    @staticmethod
    def _design(context):
        design = context.get("design") or {}
        return design.get("current") or {}

    def _component_ids(self, context):
        design = self._design(context)
        ids = design.get("component_ids") or (context.get("design") or {}).get("component_ids") or list(COMPONENTS)
        return [cid for cid in ids if cid in COMPONENTS]

    @staticmethod
    def _identity(identity):
        return int(identity.get("sample_seq", identity.get("seq", 0))), float(identity.get("ts_ms", time.time()*1000))

    def _observe(self, frame, context, identity, *, project_live_pins=False):
        models = self._models()
        fid, ts = self._identity(identity)
        size = (frame.shape[1], frame.shape[0])
        model = models["raspberry-pi-5"]
        observation = model._locator.locate(frame)
        board = DetectionResult("raspberry-pi-5", fid, ts, "searching", 0., pose_path="mobile_yolo")
        if observation is not None:
            board = DetectionResult("raspberry-pi-5", fid, ts, "locked", float(observation.confidence),
                outline_px=np.asarray(observation.corners_px).tolist(),
                body=body_observation(observation, size), pose_path="mobile_yolo")
            if project_live_pins:
                from app.vision.eye_geometry import clipped_corners
                corners = np.asarray(observation.corners_px, np.float32)
                profile = getattr(model, "_profile", None)
                # Same current-observation geometry gates as the webcam. Never
                # borrow its temporal tracker, calibration or display offsets.
                if (not _ordered_quad_ok(corners, size) or not _pi_corner_box_consistent(observation)
                        or clipped_corners(corners, size, observation.box_xyxy)):
                    board = replace(board, tracking="searching", pins=[], outline_px=None)
                elif profile is not None:
                    pins, outline = _project_profile_on_observed_quad(profile, corners, size, observation.confidence)
                    threshold = getattr(getattr(getattr(self.state, "config", None), "yolo_pose", None), "keypoint_threshold", .4)
                    pins = _anchor_profile_header_from_landmarks(profile, pins, observation, size, keypoint_threshold=threshold)
                    pins = _correct_pi5_j8_from_image(frame, profile, pins, size)
                    if all(np.isfinite([pin.x, pin.y]).all() for pin in pins):
                        board = replace(board, pins=pins, outline_px=outline)
        components = []
        for cid in self._component_ids(context):
            model = models.get(cid)
            observation = model._locator.locate(frame) if model is not None else None
            result = ComponentPoseResult(cid, fid, ts, "searching", 0., size, None, (), "mobile_yolo")
            if observation is not None:
                corners = np.asarray(observation.corners_px, np.float32)
                if corners.shape == (4, 2) and np.isfinite(corners).all() and cv2.isContourConvex(corners):
                    confidence = float(observation.confidence)
                    result = ComponentPoseResult(cid, fid, ts, "locked", confidence, size,
                        project_component_outline(model._profile, corners),
                        project_component_pins(model._profile, corners, confidence, size), "mobile_yolo",
                        body=body_observation(observation, size), model_confidence=confidence)
            components.append(result)
        return board, components, models

    @staticmethod
    def _object(frame, cid, outline, confidence):
        if outline is None:
            return None
        points = np.asarray(outline, np.float32)
        h, w = frame.shape[:2]
        if points.shape != (4, 2) or not np.isfinite(points).all() or not cv2.isContourConvex(points):
            return None
        framed = bool(np.all(points >= 2) and np.all(points < [w-2, h-2]))
        x0, y0 = np.maximum(np.floor(points.min(axis=0)).astype(int), 0)
        x1, y1 = np.minimum(np.ceil(points.max(axis=0)).astype(int), [w, h])
        roi = frame[y0:y1, x0:x1]
        if not roi.size:
            return None
        quality = image_quality(roi)
        return dict(id=cid, outline_px=points.tolist(), confidence=float(confidence),
            framed=framed, area_fraction=abs(float(cv2.contourArea(points)))/(w*h), quality=quality)

    def preview(self, frame, context, identity):
        with self.lock:
            board, components, models = self._observe(frame, context, identity, project_live_pins=True)
            packet = dict(detection=detection_message(board, (frame.shape[1], frame.shape[0]), int(identity.get('generation', 0))),
                          components=[{**component_pose_message(c), 'runtime_revision': int(identity.get('generation', 0))} for c in components])
            return self.preview_packet(frame, context, identity, packet,
                model_runtime={cid: self._runtime(model._locator) for cid, model in models.items()})

    def preview_packet(self, frame, context, identity, packet, model_runtime=None):
        """Framing feedback from an already synchronized live result, no YOLO rerun."""
        board, components = packet['detection'], packet['components']
        objects = [self._object(frame, 'raspberry-pi-5',
            board.get('outline') if board.get('tracking') == 'locked' else None, board.get('confidence', 0))]
        objects += [self._object(frame, c['component_id'],
            c.get('outline') if c.get('tracking') == 'locked' else None, c.get('confidence', 0)) for c in components]
        objects = [obj for obj in objects if obj is not None]
        target = ((context.get("context") or {}).get("debug_context") or {}).get("wiring_target") or {}
        target_id = target.get("component_id") or next(iter(self._component_ids(context)), None)
        required = ["raspberry-pi-5"] + ([target_id] if target_id else [])
        found = {obj["id"]: obj for obj in objects}
        selected = [found[cid] for cid in required if cid in found]
        present = all(cid in found for cid in required)
        framed = present and all(obj["framed"] for obj in selected)
        sharp = present and all(not obj["quality"]["warnings"] for obj in selected)
        big = "raspberry-pi-5" in found and found["raspberry-pi-5"]["area_fraction"] >= .025
        reason = ("find_board" if "raspberry-pi-5" not in found else
            "find_target_component" if target_id is not None and target_id not in found else
            "keep_targets_in_frame" if not framed else "move_closer" if not big else
            "improve_focus_or_light" if not sharp else "ready")
        return dict(objects=objects, board_present="raspberry-pi-5" in found,
            target_present=target_id is None or target_id in found, target_id=target_id,
            sharp=sharp, framed=bool(framed and big), reason=reason,
            quality={obj["id"]: obj["quality"] for obj in selected}, model_runtime=model_runtime or {},
            outline_px=found.get("raspberry-pi-5", {}).get("outline_px"),
            recognition=dict(source="phone", session_id=identity.get("session_id"),
                generation=int(identity.get("generation", 0)), context_id=context.get("context_id"),
                frame_seq=identity['sample_seq'], video_size=[frame.shape[1], frame.shape[0]],
                coordinates_are_hints_only=True,
                detection={**board, 'runtime_revision': int(identity.get('generation', 0)), 'frame_id': identity['sample_seq']},
                components=[{**c, 'runtime_revision': int(identity.get('generation', 0)), 'frame_id': identity['sample_seq']} for c in components]))

    @staticmethod
    def _runtime(locator):
        diagnostic = getattr(locator, "diagnostics", None)
        if callable(diagnostic):
            return diagnostic()
        session = getattr(locator, "_session", None)
        return dict(runtime=type(locator).__name__, available=bool(getattr(locator, "available", False)),
            providers=session.get_providers() if session is not None else [])

    def analyze(self, asset, context, session):
        path = Path(asset["analysis_path"])
        image = path.read_bytes()
        frame = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if frame is None or frame.nbytes > 64*1024*1024:
            raise HTTPException(422, "Invalid normalized photograph")
        with self.lock:
            capture_id = uuid4().hex
            generation = int(session.get("generation", session.get("stream", {}).get("generation", 0)))
            identity = dict(sample_seq=int(time.time()*1000), ts_ms=time.time()*1000)
            board, components, models = self._observe(frame, context, identity)
            # Each capture starts with entirely fresh current-photo evidence.
            geometry = self.geometry_factory()
            board, local = geometry.board(frame, board, models["raspberry-pi-5"])
            size = (frame.shape[1], frame.shape[0])
            packet = dict(capture_id=capture_id, session_id=session["session_id"], source="mobile",
                asset_id=asset["id"], image_url=f"/api/mobile/assets/{asset['id']}/file",
                image_sha256=hashlib.sha256(image).hexdigest(), video_size=list(size),
                frame_id=identity["sample_seq"], seq=identity["sample_seq"], capture_ts_ms=identity["ts_ms"],
                captured_at=datetime.now(timezone.utc).isoformat(), runtime_revision=generation,
                camera_id=session["session_id"], detection=detection_message(board, size, generation),
                components=[], localization=[local], quality=image_quality(frame), same_frame=True,
                capture_skew_ms=0, coordinates_are_hints_only=True, continuous_inference=False,
                electrical_verified=False, stale=False, component_ids=self._component_ids(context))
            for component in components:
                model = models.get(component.component_id)
                if model is None:
                    local = dict(object_id=component.component_id, status="not_found", reason="model_unavailable",
                        evidence={"pin_geometry_verified": False}, candidate_pins=[])
                else:
                    component, local = geometry.component(frame, component, model)
                packet["components"].append({**component_pose_message(component), "runtime_revision": generation})
                packet["localization"].append(local)
            design = self._design(context)
            wires = design.get("wiring") or wiring_for(packet["component_ids"])
            packet.update(project_id=design.get("id") or context.get("conversation_id", "mobile-project"),
                project_revision=design.get("revision", 1), catalog_version=design.get("catalog_version", CATALOG["version"]),
                profile_versions=design.get("profile_versions") or profile_versions(packet["component_ids"]),
                wires=[dict(wire_id=w.get("wire_id", w.get("id")),
                    component_id=w.get("component_id", w.get("componentId")),
                    board_pin=w.get("board_pin", w.get("boardPin")),
                    component_pin=w.get("component_pin", w.get("componentPin")),
                    connection_kind=w.get("connection_kind", w.get("connectionKind", "direct"))) for w in wires])
            return packet

    def release(self, session_id):
        with self.lock:
            self.geometries.pop(session_id, None)

    def close(self):
        with self.lock:
            for locator in self.owned_models:
                locator.close()
            self.owned_models.clear()
            self._owned_contexts.clear()
            self._model_contexts = None
