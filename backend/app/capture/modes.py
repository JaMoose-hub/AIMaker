"""Advertised DirectShow MJPEG modes and transactional live resolution changes.

No exposure/focus writes, model reloads, Pi operations or persistent config edits.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import logging
import re
import subprocess
import time

log = logging.getLogger(__name__)


def parse_mjpeg_modes(text: str) -> list[dict]:
    modes = {}
    for line in text.splitlines():
        match = re.search(r"vcodec=mjpeg.*?min s=(\d+)x(\d+) fps=([\d.]+) "
                          r"max s=(\d+)x(\d+) fps=([\d.]+)", line)
        if not match:
            continue
        w, h, low, max_w, max_h, high = map(float, match.groups())
        # Discrete resolutions only; don't invent intermediate sizes/rates.
        if (w, h) != (max_w, max_h) or min(w, h, low, high) <= 0:
            continue
        fps = min(high, 30.0) if low <= 30 else low
        key = (int(w), int(h))
        if key not in modes or modes[key]["fps"] < fps:
            modes[key] = dict(width=key[0], height=key[1], fps=fps)
    return sorted(modes.values(), key=lambda m: (m['width'] * m['height'], m['width']), reverse=True)


@lru_cache(maxsize=8)
def advertised_modes(ffmpeg: str, device: str) -> tuple[dict, ...]:
    result = subprocess.run(
        [ffmpeg, '-hide_banner', '-nostdin', '-list_options', 'true',
         '-f', 'dshow', '-i', f'video={device}'],
        capture_output=True, text=True, errors='replace', timeout=8,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    # FFmpeg list_options deliberately exits nonzero after printing modes.
    modes = parse_mjpeg_modes(result.stderr)
    if not modes:
        raise RuntimeError('camera_modes_unavailable')
    return tuple(modes)


def device_id(source) -> str:
    return hashlib.sha256(f'{source.current_index}:{source.device_name}'.encode()).hexdigest()[:20]


def mode_info(state) -> dict:
    from .sources import FfmpegMjpegCameraSource
    source = state.source
    if state.config.camera.source != 'device' or not isinstance(source, FfmpegMjpegCameraSource):
        return dict(supported=False, device_id=None, name=None, modes=[], current=None, actual=None)
    slot = state.frame_bus.get_latest(timeout=0)
    actual = None
    if slot is not None and time.monotonic() * 1000 - slot.ts_ms < 2000:
        h, w = slot.frame.shape[:2]
        actual = dict(width=w, height=h)
    return dict(supported=True, device_id=device_id(source), name=getattr(source, 'device_display_name', source.device_name),
                modes=list(advertised_modes(source.ffmpeg_path, source.device_name)),
                current=source.capture_mode, actual=actual)


def _workers(state):
    components = list(getattr(state, 'component_workers', []))
    if getattr(state, 'component_worker', None) is not None:
        components.append(state.component_worker)
    visual = [getattr(state, n, None) for n in ('vision_worker', 'motion_worker', 'body_worker')]
    visual.extend(components)
    auxiliary = [getattr(state, n, None) for n in (
        'wire_worker', 'component_segmentation_worker', 'insertion_vlm_worker',
        'final_wiring_vlm_worker', 'wire_color_vlm_worker', 'electrical_worker')]
    # Identity-deduplicate the legacy component alias.
    all_workers = list({id(w): w for w in [*visual, *auxiliary] if w is not None}.values())
    preserve = [*components, getattr(state, 'body_worker', None)]
    return all_workers, [w for w in visual if w is not None], preserve


def _reset_geometry(state, visual):
    state.frame_bus.clear()
    for name in ('detection_state', 'component_pose_state', 'motion_frame_state',
                 'wire_state', 'verification_state', 'guidance_color_preview'):
        holder = getattr(state, name, None)
        if holder is not None and hasattr(holder, 'clear'):
            holder.clear()
    camera = state.config.camera
    state.detection_state.set_video_size((camera.width, camera.height))
    reset = getattr(state.detector, 'reset_for_camera', None)
    if reset:
        reset(horizontal_fov_deg=camera.horizontal_fov_deg,
              camera_calibration_path=camera.calibration_path,
              use_camera_calibration=getattr(state.source, 'allow_camera_calibration', True))
    for worker in visual:
        reset = getattr(worker, 'reset_tracking', None)
        if reset:
            reset()
    state.runtime_manager.camera_changed(state)


def _verify_frames(state, mode, timeout):
    from .sources import frame_has_signal
    deadline = time.monotonic() + timeout
    seq, count, timestamp = state.frame_bus.latest_seq, 0, -1
    while time.monotonic() < deadline:
        slot = state.frame_bus.get_latest(timeout=min(.25, max(0, deadline-time.monotonic())), newer_than=seq)
        if slot is None:
            continue
        seq = slot.seq
        h, w = slot.frame.shape[:2]
        if (w, h) != (mode['width'], mode['height']):
            raise RuntimeError('camera_mode_mismatch')
        if (slot.ts_ms <= timestamp or time.monotonic()*1000 - slot.ts_ms > 2000
                or not frame_has_signal(slot.frame)):
            continue
        timestamp = slot.ts_ms
        count += 1
        if count >= 3:
            return
    raise RuntimeError('camera_mode_no_frames')


def change_mode(state, mode: dict, *, timeout=10.0, replacement=None) -> dict:
    """Caller holds camera_control_lock; all inference pauses before geometry reset."""
    source = state.source
    previous = getattr(source, 'capture_mode', dict(width=state.config.camera.width,
                       height=state.config.camera.height, fps=state.config.camera.fps))
    previous_capture = state.capture_service
    previous_config = state.config.camera.model_copy(deep=True)
    all_workers, visual, preserve = _workers(state)
    running = [w for w in all_workers if getattr(w, '_thread', None) is not None and w._thread.is_alive()]
    stopped = []
    capture_stopped = False
    try:
        state.capture_service.stop()
        capture_stopped = True
        for worker in all_workers:
            thread = getattr(worker, '_thread', None)
            worker.stop(**({'close_models': False} if worker in preserve else {}))
            if thread is not None and thread.is_alive():
                worker._thread = thread
                raise RuntimeError('camera_worker_busy')
            stopped.append(worker)
    except Exception:
        log.exception('Resolution switch could not pause capture/inference')
        if capture_stopped:
            state.capture_service.start()
        for worker in running:
            if worker in stopped:
                worker.start()
        return dict(ok=False, error='camera_worker_busy', restored=False)

    result = dict(ok=True)
    try:
        if replacement is None:
            source.configure_mode(**mode)
            state.config.camera = previous_config.model_copy(update=mode)
        else:
            from .service import CaptureService
            state.source, state.config.camera = replacement
            state.capture_service = CaptureService(state.source, state.frame_bus)
        _reset_geometry(state, visual)
        state.capture_service.start()
        _verify_frames(state, mode, timeout)
    except Exception:
        log.exception('New resolution failed; restoring previous capture mode')
        result = dict(ok=False, error='camera_mode_failed', restored=False)
        try:
            state.capture_service.stop()
            if replacement is None:
                source.configure_mode(**previous)
            else:
                state.source = source
                state.capture_service = previous_capture
            state.config.camera = previous_config
            _reset_geometry(state, visual)
            state.capture_service.start()
            _verify_frames(state, previous, timeout)
            result['restored'] = True
        except Exception:
            log.exception('Camera resolution rollback failed')
            result['error'] = 'camera_restore_failed'
    finally:
        for worker in running:
            worker.start()
    return result
