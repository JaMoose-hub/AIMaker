"""A paired phone is a FrameSource, not a second desktop vision pipeline."""
from __future__ import annotations

import threading
import time

from fastapi import HTTPException

from .modes import change_mode


class PhoneFrameSource:
    allow_camera_calibration = False

    def __init__(self, session_id, generation, size, *, clock=time.monotonic):
        self.session_id, self.generation = session_id, generation
        self.width, self.height = size
        self.clock = clock
        self._condition = threading.Condition()
        self._latest = None
        self._last_seq = -1
        self._opened = False
        self.error = None
        self.pending_size = None

    def open(self):
        with self._condition:
            self._opened = True
            self._latest = None
            self._last_seq = -1
            self.error = None
            self.pending_size = None

    def close(self):
        with self._condition:
            self._opened = False
            self._latest = None
            self._condition.notify_all()

    def push(self, sid, generation, frame, seq, received):
        if (sid, generation) != (self.session_id, self.generation):
            return False
        with self._condition:
            if not self._opened or seq <= self._last_seq or not 0 <= self.clock()-received < .5:
                return True
            if frame.shape[:2] != (self.height, self.width):
                # Same owner, new native pixels (rotation or encoder adaptation).
                # FrameBus marks a geometry epoch; each inference worker resets
                # its own temporal state, without restarting capture or models.
                self.width, self.height = int(frame.shape[1]), int(frame.shape[0])
            self.error = None
            self.pending_size = None
            self._last_seq = seq
            self._latest = (frame, seq, received * 1000)
            self._condition.notify_all()
        return True

    def read(self):
        with self._condition:
            if self._latest is None and self._opened:
                self._condition.wait(.05)
            item, self._latest = self._latest, None
            if item is None or not 0 <= self.clock()*1000-item[2] < 500:
                return None
            return item


class LiveSourceManager:
    """Uses the existing stop/reset/verify/rollback camera transaction.

    Only the desktop may select a source. Pairing a phone alone never switches
    the desktop, and a lost phone never silently falls back to another camera.
    """
    def __init__(self, state):
        self.state = state
        self.webcam = None
        self.candidate = None

    def phone_source(self, sid, generation):
        for source in (self.candidate, self.state.source):
            if isinstance(source, PhoneFrameSource) and (source.session_id, source.generation) == (sid, generation):
                return source
        return None

    def push(self, sid, generation, frame, seq, received):
        source = self.phone_source(sid, generation)
        return bool(source and source.push(sid, generation, frame, seq, received))

    def snapshot(self):
        state, source = self.state, self.state.source
        phone = isinstance(source, PhoneFrameSource)
        slot = state.frame_bus.get_latest(timeout=0)
        fresh = slot is not None and 0 <= time.monotonic()*1000-slot.ts_ms < 1000
        return dict(kind='phone' if phone else 'webcam',
                    session_id=source.session_id if phone else None,
                    generation=source.generation if phone else None,
                    pending_size=source.pending_size if phone else None,
                    runtime_revision=state.config.runtime_revision,
                    ready=fresh and (not phone or source.error is None), error=source.error if phone else None)

    def select(self, kind, *, phone=None, timeout=6):
        # The route holds camera_control_lock and the photo-session barrier.
        state = self.state
        current = self.snapshot()
        if kind == 'webcam' and current['kind'] == 'webcam':
            return dict(ok=True, **current)
        if state.config.camera.source not in {'device', 'phone'}:
            raise HTTPException(409, 'live_source_not_available')
        debug = getattr(state, 'debug_sessions', None)
        if debug is not None:
            with debug.lock:
                if any(s.get('capture_pending') or s.get('phase') in {
                        'observing_photo', 'observing_tft', 'repair_analysing', 'replying'}
                       for s in debug.sessions.values()):
                    raise HTTPException(409, 'camera_capture_busy')
        if phone and current['kind'] == 'phone' and current['ready'] and not current['error'] and (
                current['session_id'], current['generation']) == (phone.session_id, phone.generation):
            return dict(ok=True, **current)
        if kind == 'phone':
            if phone is None:
                raise HTTPException(409, 'mobile_publisher_not_ready')
            saved = self.webcam or (state.source, state.config.camera.model_copy(deep=True))
            mode = dict(width=phone.width, height=phone.height, fps=30)
            camera = state.config.camera.model_copy(update={**mode, 'source': 'phone',
                'horizontal_fov_deg': None, 'calibration_path': None, 'native_uvc_controls': False})
            replacement = (phone, camera)
            self.candidate = phone
        else:
            if self.webcam is None:
                raise HTTPException(409, 'webcam_restore_unavailable')
            replacement = self.webcam
            camera = replacement[1]
            mode = dict(width=camera.width, height=camera.height, fps=camera.fps)
        try:
            result = change_mode(state, mode, timeout=timeout, replacement=replacement)
            if result['ok']:
                self.webcam = saved if kind == 'phone' else None
            return {**self.snapshot(), **result}
        finally:
            self.candidate = None
