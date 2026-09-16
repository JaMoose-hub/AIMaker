"""Offline capture contracts. No synthetic image is a wiring accuracy claim."""
from copy import deepcopy
from types import SimpleNamespace as NS
import time

import cv2
import numpy as np
import pytest

from app.capture.bus import FrameSlot
from app.motion_worker import MotionFrameState
from app.cloud_wiring import capture_images, locate_capture
from app.cloud_connector_inspection import endpoint_image_names, endpoint_prompt
from app.wiring_capture import capture_best_images, image_quality
from test_cloud_wiring import setup


class Clock:
    def __init__(self):
        self.now = time.monotonic()
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


def test_atomic_raw_pair_never_uses_display_jpeg_and_png_preserves_pixels():
    body, packet, state, _, _ = setup()
    raw = np.random.default_rng(3).integers(0, 256, (600, 1000, 3), dtype=np.uint8)
    packet['seq'] = 23
    packet['image'] = 'deliberately not an image'
    store = MotionFrameState()
    slot = FrameSlot(raw, 23, packet['ts_ms'], 23)
    store.set(packet, slot)
    state.motion_frame_state = store
    images, metadata = capture_images(state, body)
    assert metadata['locator'] == 'same_frame_raw_tracking'
    assert 'source' not in store.get(timeout=0)
    for view in metadata['views']:
        if not view['name'].endswith('_pins'):
            continue
        assert images[view['name']].startswith(bytes.fromhex('89504e47'))
        x0, y0, x1, y1 = view['crop']
        decoded = cv2.imdecode(np.frombuffer(images[view['name']], np.uint8), 1)
        np.testing.assert_array_equal(decoded, raw[y0:y1, x0:x1])


@pytest.mark.parametrize('change', ['frame_id', 'seq', 'ts_ms', 'expired', 'missing'])
def test_raw_pair_rejects_mismatch_and_expiry(change):
    store = MotionFrameState()
    now = time.monotonic()*1000
    packet = {'frame_id': 2, 'seq': 2, 'ts_ms': now}
    args = dict(frame_id=2, seq=2, ts_ms=now)
    if change in args:
        args[change] += 1
    if change == 'expired':
        packet['ts_ms'] = args['ts_ms'] = now-1000
    source = FrameSlot(np.zeros((10, 10, 3), np.uint8), **args)
    store.set(packet, None if change == 'missing' else source)
    assert store.get_capture() is None


def test_header_context_preserves_pin1_beyond_old_target_square():
    body, packet, state, _, _ = setup()
    packet['detection']['pins'].append({'id': '3V3_P1', 'x': 240, 'y': 30, 'v': True})
    _, metadata = capture_images(state, body)
    view = next(v for v in metadata['views'] if v['name'] == 'pi_pins')
    assert view['crop'][1] == 0
    assert any(p['id'] == '3V3_P1' for p in view['pin_hints'])
    assert view['context'] == 'visible_header_and_wire_exit'


def candidates(monkeypatch, *, stale=False, only_overview=False):
    body, packet, state, _, _ = setup()
    clock = Clock()
    start = clock()
    rng = np.random.default_rng(5)
    sharp = cv2.GaussianBlur(rng.integers(25, 225, (600, 1000, 3), dtype=np.uint8), (3, 3), 0)
    blurred = cv2.GaussianBlur(sharp, (25, 25), 0)
    calls = []
    def locate(*_):
        if only_overview:
            raise ValueError('no locator')
        i = len(calls)
        calls.append(i)
        frame = sharp if i == 3 else blurred
        ts = (start-1 if stale else clock())*1000
        pi, module = deepcopy(packet['detection']), deepcopy(packet['components'][0])
        pi['frame_id'] = module['frame_id'] = i
        return [(frame, pi, i, ts), (frame, module, i, ts)], state.runtime_manager.snapshot(), 'test_raw'
    def overview(*_):
        ts = (start-1 if stale else clock())*1000
        return FrameSlot(sharp, len(calls), ts, len(calls)), state.runtime_manager.snapshot()
    monkeypatch.setattr('app.cloud_wiring.locate_capture', locate)
    monkeypatch.setattr('app.cloud_wiring._overview_source', overview)
    return body, state, clock, calls


def test_burst_picks_sharper_post_request_frame_not_latest(monkeypatch):
    body, state, clock, calls = candidates(monkeypatch)
    images, capture = capture_best_images(state, body, clock=clock, sleep=clock.sleep)
    selection = capture['selection']
    assert len(calls) == selection['candidate_count'] == 9
    assert selection['selected_index'] == 3
    assert capture['capture_ts_ms'] >= selection['requested_ts_ms']
    assert {v['frame_id'] for v in capture['views']} == {3}
    assert not selection['visibility_verified'] and not selection['wiring_verified']
    assert set(images) == {'pi_overview', 'pi_pins', 'component_pins'}


def test_burst_rejects_all_pre_request_frames(monkeypatch):
    body, state, clock, _ = candidates(monkeypatch, stale=True)
    with pytest.raises(ValueError, match='沒有取得新的'):
        capture_best_images(state, body, clock=clock, sleep=clock.sleep)


def test_burst_retains_no_locator_overview_flow(monkeypatch):
    body, state, clock, _ = candidates(monkeypatch, only_overview=True)
    images, capture = capture_best_images(state, body, clock=clock, sleep=clock.sleep)
    assert list(images) == ['pi_overview'] and capture['mode'] == 'overview'
    assert capture['capture_ts_ms'] >= capture['selection']['requested_ts_ms']


def test_runtime_change_during_burst_is_not_silently_accepted(monkeypatch):
    body, state, clock, _ = candidates(monkeypatch)
    start = clock()
    state.runtime_manager.snapshot = lambda: NS(board_id='raspberry-pi-5', runtime_revision=7 if clock()-start < .2 else 8)
    with pytest.raises(ValueError, match='控制器已切換'):
        capture_best_images(state, body, clock=clock, sleep=clock.sleep)


def test_quality_does_not_claim_visibility_or_insertion():
    report = image_quality(np.full((200, 200, 3), 255, np.uint8))
    assert report['score'] == 0 and not report['contact_visibility_verified']
    assert set(report['warnings']) == {'low_edge_detail', 'exposure_clipping'}


def test_burst_does_not_count_repeated_frame_as_nine_candidates(monkeypatch):
    body, state, clock, _ = candidates(monkeypatch, only_overview=True)
    fixed = FrameSlot(np.full((60, 100, 3), 100, np.uint8), 1, clock()*1000, 1)
    monkeypatch.setattr('app.cloud_wiring._overview_source', lambda *_: (fixed, state.runtime_manager.snapshot()))
    _, capture = capture_best_images(state, body, clock=clock, sleep=clock.sleep)
    assert capture['selection']['candidate_count'] == 1


def test_raw_state_replacement_drops_previous_source():
    store = MotionFrameState()
    ts = time.monotonic()*1000
    source = FrameSlot(np.zeros((10, 10, 3), np.uint8), 1, ts, 1)
    store.set({'seq': 1, 'frame_id': 1, 'ts_ms': ts}, source)
    assert store.get_capture()[1] is source
    store.set({'seq': 2, 'frame_id': 2, 'ts_ms': ts})
    assert store.get_capture() is None


def test_both_endpoints_receive_context_and_actionable_prompt():
    body, _, _, _, _ = setup()
    images = {'pi_overview': b'', 'component_reading': b'', 'component_contact': b''}
    assert endpoint_image_names('component', images)[-1] == 'pi_overview'
    images['component_overview'] = b''
    assert endpoint_image_names('component', images)[-1] == 'component_overview'
    prompt = endpoint_prompt(body, 'component', list(images))
    assert 'only then compare' in prompt and 'one useful next photo' in prompt
    assert 'NOT proof' in prompt and 'edge of a crop' in prompt
