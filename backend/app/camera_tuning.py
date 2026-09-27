"""One-shot webcam tuning using raw FrameBus images, not rendered overlays.

No cloud calls, new capture handles, detector thresholds or wiring mutations.
Scores compare a fixed scene/ROI/resolution within ONE run, not recognition accuracy.
"""
from __future__ import annotations

import copy
import logging
import math
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np

from app.capture import control_store

log = logging.getLogger(__name__)
TARGETS = ('raspberry-pi-5', 'hc-sr04', 'mrd-tf240-8p-cs')


class TuneStopped(Exception):
    pass


def observations(state, timestamp: float) -> dict:
    items = []
    board_state = getattr(state, 'detection_state', None)
    if board_state is not None:
        board = board_state.get()
        if board is not None:
            items.append((getattr(board, 'board_id', ''), board))
    component_state = getattr(state, 'component_pose_state', None)
    if component_state is not None:
        items.extend((p.component_id, p) for p in component_state.all())
    return {key: p for key, p in items if key in TARGETS
            and getattr(p, 'tracking', '') == 'locked'
            and 0 <= timestamp - getattr(p, 'ts_ms', 0) <= 500
            and getattr(p, 'outline_px', None) is not None}


def _pi_motion_observation(state, timestamp: float, frame_shape):
    """Use a same-frame display track only as an image-quality ROI, never as pin evidence."""
    motion = getattr(state, 'motion_frame_state', None)
    capture = motion.get_capture() if motion is not None else None
    if capture is None:
        return None
    packet, source = capture
    if (frame_shape is None or source.frame.shape != frame_shape
            or not 0 <= timestamp - source.ts_ms <= 500
            or packet.get('board_id') != 'raspberry-pi-5'
            or packet.get('frame_id') != source.frame_id
            or packet.get('ts_ms') != source.ts_ms):
        return None
    runtime = getattr(state, 'runtime_manager', None)
    if runtime is not None and packet.get('runtime_revision') != runtime.snapshot().runtime_revision:
        return None
    detection = packet.get('detection') or {}
    if (detection.get('board_id') != 'raspberry-pi-5'
            or detection.get('frame_id') != source.frame_id):
        return None
    body = detection.get('body')
    if (isinstance(body, dict) and body.get('frame_id') == source.frame_id
            and not body.get('partial') and isinstance(body.get('confidence'), (int, float))
            and math.isfinite(body['confidence']) and body['confidence'] >= .5):
        try:
            box = np.asarray(body.get('box'), np.float32)
        except (TypeError, ValueError):
            box = np.empty(0)
        if box.shape == (4,) and np.isfinite(box).all() and min(box[2:] - box[:2]) >= 32:
            x0, y0, x1, y1 = box.tolist()
            return SimpleNamespace(tracking='searching', pins=[],
                                   outline_px=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    if detection.get('tracking') == 'locked' and not detection.get('pose_quality', {}).get('outline_only'):
        try:
            outline = np.asarray(detection.get('outline'), np.float32)
        except (TypeError, ValueError):
            return None
        if (outline.shape == (4, 2) and np.isfinite(outline).all()
                and min(outline.max(axis=0) - outline.min(axis=0)) >= 32):
            return SimpleNamespace(tracking='searching', pins=[], outline_px=outline.tolist())
    return None


def pi_tuning_observation(state, timestamp: float, frame_shape=None):
    """Image-only Pi ROI; brief raw-model loss can use a paired display track."""
    board_state = getattr(state, 'detection_state', None)
    board = board_state.get() if board_state is not None else None
    if (board is None or getattr(board, 'board_id', None) != 'raspberry-pi-5'
            or not 0 <= timestamp - getattr(board, 'ts_ms', 0) <= 500):
        return _pi_motion_observation(state, timestamp, frame_shape)
    if getattr(board, 'tracking', None) == 'locked' and getattr(board, 'outline_px', None) is not None:
        return board
    if getattr(board, 'pose_stability_state', None) in ('corner_box_inconsistent', 'pcb_boundary_unverified'):
        return _pi_motion_observation(state, timestamp, frame_shape)
    body = getattr(board, 'body', None)
    if (not isinstance(body, dict) or body.get('partial')
            or not isinstance(body.get('confidence'), (int, float))
            or not math.isfinite(body['confidence']) or body['confidence'] < .5):
        return _pi_motion_observation(state, timestamp, frame_shape)
    try:
        box = np.asarray(body.get('box'), np.float32)
    except (TypeError, ValueError):
        return _pi_motion_observation(state, timestamp, frame_shape)
    if box.shape != (4,) or not np.isfinite(box).all() or box[2] - box[0] < 32 or box[3] - box[1] < 32:
        return _pi_motion_observation(state, timestamp, frame_shape)
    x0, y0, x1, y1 = box.tolist()
    return SimpleNamespace(outline_px=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def fixed_regions(frame, detected: dict) -> dict:
    h, w = frame.shape[:2]
    regions = {}
    for name, detection in detected.items():
        points = np.asarray(detection.outline_px, np.float32)
        if points.shape != (4, 2) or not np.isfinite(points).all():
            continue
        lo = np.maximum(points.min(axis=0) - 6, [0, 0]).astype(int)
        hi = np.minimum(points.max(axis=0) + 7, [w, h]).astype(int)
        if min(hi - lo) >= 32:
            regions[name] = (int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1]))
    # Acquisition must work even when no detector can locate a component yet.
    return regions or {'workspace': (w // 10, h // 10, w * 9 // 10, h * 9 // 10)}


def pi_tuning_regions(frame, observation) -> dict:
    regions = fixed_regions(frame, {'raspberry-pi-5': observation} if observation else {})
    if 'raspberry-pi-5' not in regions or getattr(observation, 'tracking', None) != 'locked':
        return regions
    pins = [(pin.x, pin.y) for pin in getattr(observation, 'pins', ())
            if getattr(pin, 'header', None) == 'J8' and getattr(pin, 'visible', False)
            and math.isfinite(pin.x) and math.isfinite(pin.y)]
    if len(pins) < 8:
        return regions
    h, w = frame.shape[:2]
    points = np.asarray(pins, np.float32)
    lo = np.maximum(points.min(axis=0) - 12, [0, 0]).astype(int)
    hi = np.minimum(points.max(axis=0) + 13, [w, h]).astype(int)
    if min(hi - lo) >= 32:
        regions['raspberry-pi-5-j8'] = (int(lo[0]), int(lo[1]), int(hi[0]), int(hi[1]))
    return regions


def quality(frame, regions: dict) -> tuple[dict, dict]:
    metrics, thumbs = {}, {}
    for name, (x0, y0, x1, y1) in regions.items():
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        scale = min(1., 256 / max(gray.shape))
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        smooth = cv2.GaussianBlur(gray, (3, 3), .7)
        sharpness = float(cv2.Laplacian(smooth, cv2.CV_32F).var())
        highlight = float(np.mean(gray >= 248))
        shadows = float(np.mean(gray <= 12))
        level = float(np.percentile(gray, 75))
        # A dark TFT panel is expected. Never try to make every pixel mid-gray.
        light = min(1., level / 65.) * min(1., max(0., (255 - level) / 35.))
        score = 1.4 * light + .3 * math.log1p(sharpness / 80.) - 2.5 * highlight - 2 * max(0., shadows - .8)
        metrics[name] = dict(score=score, sharpness=sharpness, highlight=highlight, level=level)
        thumbs[name] = gray
    return metrics, thumbs


def image_motion(before, after) -> float:
    points = cv2.goodFeaturesToTrack(before, 80, .03, 5)
    if points is None or len(points) < 6:
        return 0.
    nxt, status, _ = cv2.calcOpticalFlowPyrLK(before, after, points, None)
    if nxt is None or status is None or np.count_nonzero(status) < 6:
        return 0.
    delta = np.linalg.norm((nxt - points).reshape(-1, 2), axis=1)[status.ravel() == 1]
    return float(np.percentile(delta, 75))


def is_better(candidate: dict, baseline: dict) -> bool:
    # Do not improve the large Pi at the expense of a smaller visible module.
    return (candidate['score'] > baseline['score'] + max(.06, abs(baseline['score']) * .035)
            and all(candidate['regions'][k]['score'] >= v['score'] - .10
                    and candidate['regions'][k]['highlight'] <= max(v['highlight'] + .03, .08)
                    and candidate['regions'][k]['sharpness'] >= v['sharpness'] * .82
                    for k, v in baseline['regions'].items())
            and all(candidate['detected'].get(k, 0) >= rate - .3
                    for k, rate in baseline['detected'].items() if rate >= .5))


def snap(prop: dict, value: float) -> int:
    step = max(1, prop['Step'])
    return max(prop['Min'], min(prop['Max'], prop['Min'] + round((value - prop['Min']) / step) * step))


class CameraTuner:
    def __init__(self, state, *, budget_s=75., settle_s=.65, samples=6):
        self.state = state
        self.budget_s, self.settle_s, self.samples = budget_s, settle_s, samples
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._thread = None
        self._closed = False
        self._undo = None
        self._status = dict(state='idle', progress=0, reason=None, before=None, after=None,
                            saved=False, target_id=None)

    def available(self):
        return (getattr(self.state.config.camera, 'source', None) == 'device'
                and bool(getattr(self.state.source, 'supports_live_controls', False)))

    def snapshot(self):
        with self._lock:
            data = copy.deepcopy(self._status)
            data.update(available=self.available(), target_supported=True,
                        busy=bool(self._thread and self._thread.is_alive()),
                        can_restore=bool(self._undo and self.state.source is self._undo['source']))
            return data

    def start(self, restore=False, target_id=None):
        with self._lock:
            if target_id not in (None, 'raspberry-pi-5') or (restore and target_id is not None):
                return {'ok': False, 'reason': 'unsupported'}
            if self._closed or not self.available():
                return {'ok': False, 'reason': 'unsupported'}
            if self._thread and self._thread.is_alive():
                return {'ok': False, 'reason': 'busy'}
            if restore and (not self._undo or self._undo['source'] is not self.state.source):
                return {'ok': False, 'reason': 'no_restore'}
            if not self.state.camera_control_lock.acquire(blocking=False):
                return {'ok': False, 'reason': 'busy'}
            self._cancel.clear()
            self._status = dict(state='restoring' if restore else 'preparing', progress=0,
                                reason=None, before=None, after=None, saved=False, target_id=target_id)
            source = self.state.source
            self._thread = threading.Thread(target=self._run, args=(source, restore, target_id), daemon=True,
                                            name='BoardVision-CameraTuning')
            try:
                self._thread.start()
            except RuntimeError:
                self.state.camera_control_lock.release()
                self._update(state='error', reason='control_failed')
                return {'ok': False, 'reason': 'control_failed'}
            return {'ok': True, **self.snapshot()}

    def cancel(self):
        self._cancel.set()
        return {'ok': True}

    def close(self):
        self._closed = True
        self._cancel.set()
        if self._thread:
            self._thread.join(timeout=30)

    def _update(self, **values):
        with self._lock:
            self._status.update(values)

    def _check(self, source):
        if self._cancel.is_set():
            raise TuneStopped('cancelled')
        if self.state.source is not source or not self.available():
            raise TuneStopped('camera_changed')
        if time.monotonic() > self._deadline:
            raise TuneStopped('timeout')

    def _measure(self, source, regions, shape, exposure=None):
        self._check(source)
        if self._cancel.wait(self.settle_s):
            raise TuneStopped('cancelled')
        rows, seen, previous, motion = [], {}, None, []
        seq = self.state.frame_bus.latest_seq
        for _ in range(self.samples):
            self._check(source)
            slot = self.state.frame_bus.get_latest(.6, newer_than=seq)
            if slot is None or time.monotonic() * 1000 - slot.ts_ms > 700:
                raise TuneStopped('no_frames')
            seq = slot.seq
            if slot.frame.shape != shape:
                raise TuneStopped('camera_changed')
            metrics, thumbs = quality(slot.frame, regions)
            reference = getattr(self, '_scene_reference', None)
            if reference:
                for key in thumbs:
                    # Compare to the same scene, not only adjacent frames: a
                    # hand moving a part BETWEEN candidate batches is not an
                    # improvement caused by changing camera settings.
                    shift, response = cv2.phaseCorrelate(reference[key].astype(np.float32), thumbs[key].astype(np.float32))
                    if response > .25 and np.linalg.norm(shift) > 8:
                        raise TuneStopped('moving')
            if previous:
                motion.extend(image_motion(previous[k], thumbs[k]) for k in thumbs)
            previous = thumbs
            rows.append(metrics)
            observed = observations(self.state, slot.ts_ms)
            for key in observed:
                seen[key] = seen.get(key, 0) + 1
            if (getattr(self, '_target_id', None) == 'raspberry-pi-5'
                    and 'raspberry-pi-5' not in observed
                    and pi_tuning_observation(self.state, slot.ts_ms, slot.frame.shape)):
                seen['raspberry-pi-5'] = seen.get('raspberry-pi-5', 0) + 1
            self._cancel.wait(.10)
        if motion and np.percentile(motion, 80) > 2.5:
            raise TuneStopped('moving')
        if not getattr(self, '_scene_reference', None):
            self._scene_reference = previous
        if getattr(self, '_target_id', None) and seen.get(self._target_id, 0) < math.ceil(self.samples / 2):
            raise TuneStopped('target_not_visible')
        aggregate = {k: {m: float(np.median([row[k][m] for row in rows])) for m in rows[0][k]} for k in regions}
        penalty = max(0, exposure + 5) * .25 if exposure is not None else 0
        return dict(score=float(np.mean([r['score'] for r in aggregate.values()])) - penalty,
                    regions=aggregate, detected={k: seen.get(k, 0) / self.samples for k in TARGETS})

    def _run(self, source, restore, target_id=None):
        original, touched = None, False
        old_saved = control_store.load(source.control_identity)
        self._deadline = time.monotonic() + self.budget_s
        self._scene_reference = None
        self._target_id = target_id
        try:
            props = {p['Name']: p for p in source.read_live_controls()['controls']
                     if p['Name'] in control_store.NAMES and p['Flags'] in (1, 2)}
            original = {k: {'value': p['Value'], 'flags': p['Flags']} for k, p in props.items()}
            if not original:
                raise TuneStopped('unsupported')
            if restore:
                source.apply_live_controls(self._undo['settings'])
                control_store.save(source.control_identity, self._undo['saved'])
                self._undo = None
                self._update(state='restored', progress=100)
                return
            slot = self.state.frame_bus.get_latest(.5)
            if slot is None:
                raise TuneStopped('no_frames')
            if target_id:
                target = pi_tuning_observation(self.state, slot.ts_ms, slot.frame.shape)
                regions = pi_tuning_regions(slot.frame, target)
                if target_id not in regions:
                    raise TuneStopped('target_not_visible')
            else:
                regions = fixed_regions(slot.frame, observations(self.state, slot.ts_ms))
            shape = slot.frame.shape
            original_exposure = original.get('exposure', {}).get('value')
            baseline = self._measure(source, regions, shape, original_exposure)
            self._update(before=baseline, state='adjusting', progress=10)
            best, best_settings = baseline, copy.deepcopy(original)
            # Lock existing auto values for a fair comparison. The saved/undo
            # snapshot retains original modes, not just the numeric values.
            locked = {k: {'value': p['Value'], 'flags': 2} for k, p in props.items() if p['Caps'] & 2}
            touched = True  # also rollback a partially successful batch write
            source.apply_live_controls(locked)
            best_settings = {**original, **locked}

            def trial(changes, progress):
                nonlocal best, best_settings
                self._check(source)
                candidate = {**best_settings, **changes}
                source.apply_live_controls(candidate)
                try:
                    score = self._measure(source, regions, shape, candidate.get('exposure', {}).get('value'))
                except TuneStopped as error:
                    if str(error) != 'target_not_visible':
                        raise
                    # A trial may temporarily hide the Pi. Reject just that
                    # setting; do not abort the whole bounded search.
                    self._check(source)
                    source.apply_live_controls(best_settings)
                    self._update(progress=progress)
                    return
                if is_better(score, best):
                    best, best_settings = score, copy.deepcopy(candidate)
                self._update(progress=progress)

            if 'exposure' in locked:
                p = props['exposure']
                # DirectShow exposure is log2(seconds). Keep shutter <= one
                # 30fps frame (or shorter at higher frame rates) for handheld use.
                limit = min(p['Max'], math.floor(math.log2(1 / max(30, self.state.config.camera.fps))))
                anchor = min(p['Value'], limit)
                values = sorted({snap(p, anchor + delta) for delta in (-2, -1, 0, 1) if anchor + delta <= limit})
                for i, value in enumerate(values):
                    trial({'exposure': {'value': value, 'flags': 2}}, 15 + i * 6)
            if 'gain' in locked:
                p = props['gain']
                step = max(p['Step'], (p['Max'] - p['Min']) // 8)
                # Bounded gain: do not maximize noise to make a dark image bright.
                for i, value in enumerate(sorted({snap(p, p['Value'] - step), snap(p, p['Value'] + step)})):
                    trial({'gain': {'value': value, 'flags': 2}}, 42 + i * 6)
            if 'focus' in locked:
                p = props['focus']
                anchor = p['Value']
                if p['Caps'] & 1:
                    self._check(source)
                    source.apply_live_controls({**best_settings, 'focus': {'value': anchor, 'flags': 1}})
                    self._cancel.wait(1.0)
                    fresh = {v['Name']: v for v in source.read_live_controls()['controls']}
                    anchor = fresh.get('focus', p)['Value']
                for i, value in enumerate(sorted({snap(p, anchor + d * max(1, p['Step'])) for d in (-2, 0, 2)})):
                    trial({'focus': {'value': value, 'flags': 2}}, 55 + i * 6)
            if 'white_balance' in locked and props['white_balance']['Caps'] & 1:
                self._check(source)
                p = props['white_balance']
                source.apply_live_controls({**best_settings, 'white_balance': {'value': p['Value'], 'flags': 1}})
                self._cancel.wait(.8)
                first = {v['Name']: v for v in source.read_live_controls()['controls']}
                self._cancel.wait(.5)
                second = {v['Name']: v for v in source.read_live_controls()['controls']}
                a, b = first.get('white_balance', p)['Value'], second.get('white_balance', p)['Value']
                if abs(a - b) <= max(1, p['Step']) * 2:
                    trial({'white_balance': {'value': snap(p, b), 'flags': 2}}, 80)
            self._update(state='checking', progress=90)
            self._check(source)
            source.apply_live_controls(best_settings)
            final = self._measure(source, regions, shape, best_settings.get('exposure', {}).get('value'))
            if is_better(final, baseline):
                control_store.save(source.control_identity, best_settings)
                with self._lock:
                    self._undo = {'source': source, 'settings': original, 'saved': old_saved}
                self._update(state='improved', progress=100, after=final, saved=True)
            else:
                source.apply_live_controls(original)
                needs_light = any(m['level'] < 45 for m in baseline['regions'].values())
                self._update(state='unchanged', progress=100, after=baseline,
                             reason='needs_light' if needs_light else 'no_improvement')
        except Exception as error:
            reason = str(error) if isinstance(error, TuneStopped) else 'control_failed'
            if not isinstance(error, TuneStopped):
                log.warning('Camera tune failed', exc_info=True)
            if original is not None and (touched or restore):
                try:
                    source.apply_live_controls(original)
                except Exception:
                    reason = 'restore_failed'
                    # Keep an explicit retry path; never claim the old state is restored.
                    self._undo = {'source': source, 'settings': original, 'saved': old_saved}
                    log.error('Camera tune rollback failed', exc_info=True)
            self._update(state='cancelled' if reason == 'cancelled' else 'error', reason=reason, progress=100)
        finally:
            self._target_id = None
            self.state.camera_control_lock.release()
