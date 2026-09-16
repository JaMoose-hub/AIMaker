"""Bounded, on-demand image-quality selection, not local wiring recognition."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import time

import cv2


def image_quality(frame):
    """Relative focus/exposure heuristic. No claim of contact visibility.

    Noise, textured hands and backgrounds can also have strong edges. Keep the
    measurements in capture diagnostics, never convert them to a wiring verdict.
    """
    scale = min(1., 256 / max(frame.shape[:2]))
    small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    focus = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    dark = float((gray < 12).mean())
    bright = float((gray > 245).mean())
    clipped = dark + bright
    score = math.log1p(focus) * (1 - min(.95, clipped))
    return {'score': round(score, 4), 'laplacian_variance': round(focus, 2),
            'dark_fraction': round(dark, 4), 'bright_fraction': round(bright, 4),
            'warnings': (['low_edge_detail'] if focus < 8 else []) +
                        (['exposure_clipping'] if clipped > .6 else []),
            'contact_visibility_verified': False}


def _quality_sources(sources, targets):
    from app.cloud_wiring import _fresh_pose
    reports = []
    for (frame, message, frame_id, _), target in zip(sources, targets):
        pin, _ = _fresh_pose(message, target, frame_id, frame.shape)
        x, y = int(pin['x']), int(pin['y'])
        # Focus score uses local source pixels, not the textured whole desk.
        roi = frame[max(0, y-96):min(frame.shape[0], y+97),
                    max(0, x-96):min(frame.shape[1], x+97)]
        reports.append(image_quality(roi))
    return reports


def capture_best_images(state, body, *, seconds=.65, clock=time.monotonic, sleep=time.sleep):
    """Sample at most nine candidates after the request; encode only the winner.

    Hold only the current winner plus current candidate. Never mix endpoints
    from independently selected moments or use a pre-request sharper frame.
    The synchronized-detector fallback still declares its <=250ms skew.
    """
    from app.cloud_wiring import (capture_images, locate_capture, _overview_source,
                                  _capture_located_images, _jpeg)
    if seconds <= 0:
        return capture_images(state, body)
    started = clock()
    duration = min(float(seconds), 1.)
    revision = state.runtime_manager.snapshot().runtime_revision
    best = None
    seen = set()
    diagnostics = []
    for index in range(9):
        sleep(max(0., started + duration * index / 8 - clock()))
        if state.runtime_manager.snapshot().runtime_revision != revision:
            raise ValueError('控制器已切換，請重新拍攝。')
        located = None
        try:
            located = locate_capture(state, body)
            if min(s[3] for s in located[0]) < started*1000:
                located = None
        except (ValueError, KeyError):
            pass
        if located is not None:
            sources, runtime, _ = located
            key = ('pins',) + tuple((s[2], s[3]) for s in sources)
            reports = _quality_sources(sources, (body.board_pin, body.component_pin))
            payload = located
        else:
            try:
                slot, runtime = _overview_source(state)
            except ValueError:
                continue
            if slot.ts_ms < started*1000:
                continue
            key = ('overview', slot.frame_id, slot.ts_ms)
            reports = [image_quality(slot.frame)]
            payload = (slot, runtime)
        if runtime.runtime_revision != revision:
            raise ValueError('控制器已切換，請重新拍攝。')
        if key in seen:
            continue
        seen.add(key)
        # Crops include the overview as well. Prefer this richer evidence set;
        # compare focus using the weaker endpoint so one sharp end cannot hide
        # a blurred second end. This does NOT establish visibility or insertion.
        score = min(r['score'] for r in reports)
        rank = (located is not None, score)
        diagnostics.append({'frame_ids': [s[2] for s in located[0]] if located else [payload[0].frame_id],
                            'mode': 'pin_crops' if located else 'overview', 'quality': reports})
        if best is None or rank >= best[0]:
            best = (rank, payload, len(diagnostics)-1)
    if best is None:
        raise ValueError('按下檢查後沒有取得新的相機影格，請確認相機串流後重試。')
    rank, payload, selected = best
    if rank[0]:
        images, metadata = _capture_located_images(state, body, payload)
    else:
        slot, runtime = payload
        height, width = slot.frame.shape[:2]
        images = {'pi_overview': _jpeg(slot.frame)}
        metadata = {'mode': 'overview', 'locator': 'camera_overview', 'same_frame': True,
                    'views': [{'name': 'pi_overview', 'frame_id': slot.frame_id, 'ts_ms': slot.ts_ms, 'size': [width, height]}],
                    'capture_skew_ms': 0, 'runtime_revision': runtime.runtime_revision, 'anchors': {},
                    'captured_at': datetime.now(timezone.utc).isoformat(), 'capture_ts_ms': slot.ts_ms,
                    'coordinates_are_hints_only': True}
    if state.runtime_manager.snapshot().runtime_revision != revision:
        raise ValueError('控制器已切換，請重新拍攝。')
    metadata['selection'] = {'method': 'post_request_burst_v1', 'requested_ts_ms': started*1000,
                             'window_ms': round(duration*1000), 'candidate_count': len(diagnostics),
                             'selected_index': selected, 'candidates': diagnostics,
                             'visibility_verified': False, 'wiring_verified': False}
    return images, metadata
