"""Independent fast display tracking. Does not mutate verification states."""
from __future__ import annotations

import base64
from copy import deepcopy
import logging
import math
import threading
import time

import cv2

from app.component_worker import component_pose_message, ComponentPoseTracker
from app.vision.component_identity import hc_tft_conflict
from app.vision.motion_tracking import MotionTrack, warm_motion_runtime
from app.vision.body_tracking import BodyTrack
from app.vision.tracking_diagnostics import TrackingDiagnostics
from app.vision.display_prediction import DisplayPrediction
from app.vision.background_recovery import BackgroundRecovery
from app.vision_worker import detection_message

log = logging.getLogger(__name__)

# Each supported component owns its template, loss state and semantic lease.
TRACKED_COMPONENT_IDS = ('hc-sr04', 'mrd-tf240-8p-cs')
PREDICTED_COMPONENT_IDS = ('hc-sr04', 'mrd-tf240-8p-cs')


def tracking_gray(frame):
    scale = min(1.0, 960.0 / frame.shape[1])
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
    return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), scale


def absent(message: dict, frame_id: int, ts_ms: float) -> dict:
    result = deepcopy(message)
    result.update(frame_id=frame_id, ts_ms=ts_ms, tracking='searching',
                  confidence=0, outline=None, pins=[])
    result.pop('diagnostic', None)
    result.pop('geometry', None)
    result.pop('body', None)
    result['pose_quality'] = {'stability': 'flow_lost'}
    return result


class MotionFrameState:
    def __init__(self):
        self._condition = threading.Condition()
        self._packet = None
        self._source = None
        self._requested = 0.0

    def requested(self):
        with self._condition:
            return time.monotonic() - self._requested < 2.0

    def set(self, packet, source=None):
        with self._condition:
            self._packet = packet
            self._source = source
            self._condition.notify_all()

    def clear(self):
        with self._condition:
            self._packet = None
            self._source = None
            self._condition.notify_all()

    def get_capture(self):
        """One atomic raw source/pose pair, never serialized into the UI packet.

        FrameBus frames are immutable after publication. Retain only the latest
        slot, not a continuous full-resolution recording or a per-frame copy.
        """
        with self._condition:
            self._requested = time.monotonic()
            packet, source = self._packet, self._source
            if packet is None or source is None:
                return None
            if (packet['frame_id'], packet['seq'], packet['ts_ms']) != (source.frame_id, source.seq, source.ts_ms):
                return None
            if not 0 <= time.monotonic()*1000 - source.ts_ms < 500:
                return None
            return packet, source

    def get(self, after=-1, timeout=0.25):
        with self._condition:
            self._requested = time.monotonic()
            ready = self._condition.wait_for(
                lambda: self._packet is not None and self._packet['seq'] > after
                and time.monotonic() * 1000 - self._packet['ts_ms'] < 500,
                timeout=timeout,
            )
            return self._packet if ready else None


class MotionOverlayWorker:
    def __init__(self, bus, detection_state, component_state, runtime_manager, state, hz=30, body_state=None, background_recovery_enabled=False):
        self.bus, self.detection_state = bus, detection_state
        self.component_state, self.runtime_manager = component_state, runtime_manager
        self.state = state
        self.body_state = body_state
        self.set_target_fps(hz)
        self._stop = threading.Event()
        self._thread = None
        self.tracks: dict[str, MotionTrack] = {}
        self.body_tracks: dict[str, BodyTrack] = {}
        self.context = None
        self.previous_seq = -1
        self.previous_frame_id = -1
        self.search_turn = 0
        self.diagnostics = TrackingDiagnostics()
        self.prediction = DisplayPrediction()
        self.component_predictions = {key: DisplayPrediction() for key in PREDICTED_COMPONENT_IDS}
        self.background_recovery = None
        self.background_recovery_enabled = background_recovery_enabled

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.background_recovery = BackgroundRecovery() if self.background_recovery_enabled else None
        self._thread = threading.Thread(target=self._run, name='motion-overlay', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError('motion worker did not stop')
            self._thread = None
        if self.background_recovery is not None:
            self.background_recovery.close()
            self.background_recovery = None

    def set_target_fps(self, hz):
        hz = float(hz)
        if not math.isfinite(hz) or not 1 <= hz <= 60:
            raise ValueError('display FPS must be between 1 and 60')
        self.interval = 1 / hz

    def reset_tracking(self):
        """Call while stopped; keep the shared bus sequence monotonic."""
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError('stop motion worker before resetting tracking')
        self.tracks.clear()
        self.body_tracks.clear()
        self.context = None
        self.previous_seq = -1
        self.previous_frame_id = -1
        self.search_turn = 0
        self.state.clear()
        self.diagnostics = TrackingDiagnostics()
        self.prediction = DisplayPrediction()
        self.component_predictions = {key: DisplayPrediction() for key in PREDICTED_COMPONENT_IDS}

    def process(self, slot):
        started = time.perf_counter()
        runtime = self.runtime_manager.snapshot()
        context = (runtime.board_id, runtime.runtime_revision, slot.frame.shape)
        if self.context != context or slot.seq <= self.previous_seq or slot.frame_id <= self.previous_frame_id:
            self.tracks.clear()
            self.body_tracks.clear()
            self.context = context
            self.search_turn = 0
            self.diagnostics = TrackingDiagnostics()
            self.prediction = DisplayPrediction()
            self.component_predictions = {key: DisplayPrediction() for key in PREDICTED_COMPONENT_IDS}
        self.previous_seq = slot.seq
        self.previous_frame_id = slot.frame_id
        if runtime.board_id != 'raspberry-pi-5':
            return None
        gray, scale = tracking_gray(slot.frame)
        gray_ms = (time.perf_counter() - started) * 1000
        gray_cache = {(slot.frame_id, slot.seq): (gray, scale)}
        width, height = slot.frame.shape[1], slot.frame.shape[0]
        detection = {
            'type': 'detection', 'board_id': runtime.board_id,
            'runtime_revision': runtime.runtime_revision, 'frame_id': slot.frame_id,
            'ts_ms': slot.ts_ms, 'video_size': [width, height], 'tracking': 'searching',
            'confidence': 0, 'outline': None, 'pins': [],
        }
        board_pair = self.detection_state.get_synchronized()
        seeds = []
        if board_pair is not None:
            source, result = board_pair
            if result.board_id == runtime.board_id and source.frame.shape == slot.frame.shape:
                detection = detection_message(result, (width, height), runtime.runtime_revision)
                detection['motion_outline'] = result.motion_outline_px
                seeds.append(('board', source, detection))
        component_results = {r.component_id: r for r in self.component_state.all()}
        templates = {'board': detection}
        components = []
        for component_id in TRACKED_COMPONENT_IDS:
            if component_id in component_results:
                templates[component_id] = component_pose_message(component_results[component_id])
            component_pair = self.component_state.get_synchronized(component_id)
            if component_pair is None:
                continue
            source, result = component_pair
            if source.frame.shape == slot.frame.shape:
                message = component_pose_message(result)
                message['motion_outline'] = (
                    result.motion_outline_px.tolist() if result.motion_outline_px is not None else None
                )
                seeds.append((component_id, source, message))
                templates[component_id] = message
        seed_map = {key: (source, message) for key, source, message in seeds}
        body_seed_map = dict(seed_map)
        if self.body_state is not None:
            pair = self.body_state.get_synchronized()
            if pair is not None:
                body_source, body_message = pair
                if (body_source.frame.shape == slot.frame.shape
                        and body_message['board_id'] == runtime.board_id
                        and body_message['runtime_revision'] == runtime.runtime_revision):
                    body_seed_map['board'] = pair
        # One expensive recovery search per displayed frame. Rotating priority
        # prevents a repeatedly hidden Pi from starving another component.
        search_count = 0
        def claim_search():
            nonlocal search_count
            if search_count >= 1:
                return False
            search_count += 1
            return True
        keys = list(templates)
        offset = self.search_turn % len(keys)
        self.search_turn += 1
        outputs, object_ms, deferred = {}, {}, []
        for key in keys[offset:] + keys[:offset]:
            template = templates[key]
            object_started = time.perf_counter()
            track = self.tracks.setdefault(key, MotionTrack())
            track.fresh_recovery_enabled = key == 'board' or key in PREDICTED_COMPONENT_IDS
            seed = seed_map.get(key)
            if seed is not None:
                source, message = seed
                # No template from an earlier camera session or an old frame.
                if 0 <= slot.ts_ms - source.ts_ms <= 750:
                    if source.frame_id > track.seen_seed:
                        cache_key = (source.frame_id, source.seq)
                        if not track.needs_source_image(message):
                            # Normal corroboration never reads these pixels.
                            # A guarded rebase MUST use its paired source below.
                            source_gray, source_scale = gray, scale
                        elif cache_key not in gray_cache:
                            gray_cache[cache_key] = tracking_gray(source.frame)
                            source_gray, source_scale = gray_cache[cache_key]
                        else:
                            source_gray, source_scale = gray_cache[cache_key]
                        track.observe(message, source_gray, source_scale)
            if key == 'board':
                track.flow.background_recovery = self.background_recovery
            tracked = track.update(gray, slot.frame_id, slot.ts_ms, search_budget=claim_search)
            if track.flow.search_deferred:
                deferred.append(key)
            if tracked is None:
                # Diagnostics expose short recovery without presenting old
                # geometry as current. Both original WS and wiring stay intact.
                tracked = absent(template, slot.frame_id, slot.ts_ms)
                tracked['pose_quality'].update(
                    recovering=track.recovering,
                    interrupted=track.ever_locked,
                    reason=track.failure_reason or 'awaiting_model_lock',
                )
            if key == 'board':
                if (self.background_recovery is not None and tracked.get('tracking') == 'locked'
                        and not tracked.get('pose_quality', {}).get('partial')):
                    self.background_recovery.observe(track.flow, slot.ts_ms)
                tracked = self.prediction.apply(tracked)
            elif key in self.component_predictions:
                tracked = self.component_predictions[key].apply(tracked)
            outputs[key] = tracked
            # Keep upstream evidence alongside the display decision. A lost
            # flow template alone cannot explain why no fresh seed arrived.
            source_info = {'paired': seed is not None}
            if seed is not None:
                source, message = seed
                source_info.update(
                    frame_id=source.frame_id,
                    age_ms=round(slot.ts_ms - source.ts_ms, 2),
                    tracking=message.get('tracking'),
                    quality=deepcopy(message.get('pose_quality', {})),
                    consumed_frame_id=track.seen_seed,
                )
            tracked.setdefault('pose_quality', {})['model_source'] = source_info
            # Object identity/box transport is independent of semantic pin
            # orientation. Always use the detector's actual paired pixels.
            body_track = self.body_tracks.setdefault(key, BodyTrack())
            body_seed = body_seed_map.get(key)
            if body_seed is not None:
                body_source, body_message = body_seed
                if (0 <= slot.ts_ms - body_source.ts_ms <= 650
                        and body_message.get('body') is not None
                        and body_source.frame_id > body_track.seen_frame):
                    cache_key = (body_source.frame_id, body_source.seq)
                    if cache_key not in gray_cache:
                        gray_cache[cache_key] = tracking_gray(body_source.frame)
                    body_gray, body_scale = gray_cache[cache_key]
                    body_track.observe(body_message, body_gray, body_scale)
            # Never inherit a body stamped with an older source frame.
            tracked['body'] = body_track.update(gray, slot.frame_id, slot.ts_ms)
            if (seed is not None and 0 <= slot.ts_ms - source.ts_ms <= 750
                    and message.get('pose_quality', {}).get('reason') == 'pin_orientation_unverified'):
                # Surface the current candidate status, not a generic missing
                # object message or a retained pin order from an older frame.
                tracked['tracking'] = 'searching'
                tracked['outline'] = None
                tracked['pins'] = []
                tracked['pose_quality']['reason'] = 'pin_orientation_unverified'
            object_ms[key] = round((time.perf_counter()-object_started)*1000, 2)
        self._resolve_component_identities(outputs, slot, seed_map)
        detection = outputs['board']
        components = [outputs[key] for key in keys if key != 'board']
        # Non-trial modules retain their old low-rate detector path. Mark
        # them stale in this synchronized view, never pretend they were tracked.
        for result in component_results.values():
            if result.component_id not in TRACKED_COMPONENT_IDS:
                message = component_pose_message(result)
                if slot.ts_ms - result.ts_ms > 750:
                    message = absent(message, slot.frame_id, slot.ts_ms)
                elif message['tracking'] == 'locked':
                    message['tracking'] = 'stale'
                components.append(message)
        detection.pop('motion_outline', None)
        for component in components:
            component.pop('motion_outline', None)
        jpeg_started = time.perf_counter()
        jpeg = slot.jpeg
        if jpeg is None:
            ok, buffer = cv2.imencode('.jpg', slot.frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                return None
            jpeg = buffer.tobytes()
        image = 'data:image/jpeg;base64,' + base64.b64encode(jpeg).decode('ascii')
        return {
            'seq': slot.seq, 'frame_id': slot.frame_id, 'ts_ms': slot.ts_ms,
            'runtime_revision': runtime.runtime_revision, 'board_id': runtime.board_id,
            'image': image,
            'detection': detection, 'components': components,
            'display_only': True,
            'timing_ms': {'gray': round(gray_ms, 2), 'objects': object_ms,
                          'jpeg': round((time.perf_counter()-jpeg_started)*1000, 2)},
            'recovery_searches': search_count, 'recovery_deferred': deferred,
            'pi_recovery_mode': 'background_predicted_roi' if self.background_recovery is not None else 'synchronous',
            'pi_fresh_source_recovery': True,
            'component_prediction_ids': list(PREDICTED_COMPONENT_IDS),
        }

    def _resolve_component_identities(self, outputs, slot, seed_map):
        hc, tft = outputs.get('hc-sr04'), outputs.get('mrd-tf240-8p-cs')
        if hc is None:
            return
        evidence = None
        pair = seed_map.get('hc-sr04')
        source_quality = {}
        if pair is not None and 0 <= slot.ts_ms - pair[0].ts_ms <= 750:
            source_quality = pair[1].get('pose_quality', {})
            if source_quality.get('reason') == 'component_identity_conflict':
                evidence = source_quality.get('identity_check')
        # Both tracked outlines are projected into THIS image. Never compare
        # independently timed raw boxes, nor let a prediction veto a detector.
        if evidence is None and tft is not None and tft.get('tracking') == 'locked':
            reference = source_quality.get('reference_recovery', {})
            evidence = hc_tft_conflict(slot.frame, hc.get('outline'), tft.get('outline'),
                hc_visible=ComponentPoseTracker._hc_transducers_visible,
                reference_confirmed=bool(reference.get('accepted')
                    and reference.get('frame_id') == slot.frame_id))
        if evidence is None:
            return
        rejected = absent(hc, slot.frame_id, slot.ts_ms)
        rejected['pose_quality'].update(reason='component_identity_conflict',
            identity_check=dict(evidence), model_source=hc.get('pose_quality', {}).get('model_source'))
        outputs['hc-sr04'] = rejected
        # Clearing the display template/prediction prevents an old false HC
        # from returning for its semantic lease after the TFT moves or vanishes.
        self.tracks.pop('hc-sr04', None)
        self.body_tracks.pop('hc-sr04', None)
        self.component_predictions['hc-sr04'] = DisplayPrediction()

    def _run(self):
        try:
            warm_motion_runtime()
        except Exception:
            # Warm-up failure is not a camera failure; the normal guarded
            # path can retry the underlying operation when actually needed.
            log.exception('motion runtime warm-up failed')
        last_seq = -1
        while not self._stop.is_set():
            if not self.state.requested():
                self.tracks.clear()
                self.body_tracks.clear()
                self._stop.wait(0.1)
                continue
            slot = self.bus.get_latest(timeout=0.1, newer_than=last_seq)
            if slot is None:
                continue
            last_seq = slot.seq
            started = time.monotonic()
            try:
                packet = self.process(slot)
                if packet is not None:
                    packet['processing_ms'] = round((time.monotonic() - started) * 1000, 2)
                    packet['tracking_diagnostics'] = self.diagnostics.record(
                        packet, packet['processing_ms'], self.interval * 1000,
                    )
                    self.state.set(packet, slot)
            except Exception:
                self.tracks.clear()
                self.body_tracks.clear()
                log.exception('motion display failed for frame %s', slot.frame_id)
            self._stop.wait(max(0, self.interval - (time.monotonic() - started)))
