from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.vision.interface import DetectionResult, PinDetection
from app.vision.yolo_profile_detector import HybridBoardDetector


def result(state='locked', frame_id=8, ts_ms=1000):
    return DetectionResult(board_id='raspberry-pi-5', frame_id=frame_id,
        ts_ms=ts_ms, tracking=state, confidence=.8,
        pins=[PinDetection('1', 10, 10, .8, True, 'J8', 1)],
        outline_px=[(0, 0), (30, 0), (30, 30), (0, 30)])


def hybrid(primary_result, fallback_result, *, board='raspberry-pi-5', eye=False):
    calls = []
    primary = SimpleNamespace(available=True, _yolo_only=eye,
        detect=lambda *args: primary_result)
    def fallback(*args):
        calls.append(args)
        return fallback_result
    detector = HybridBoardDetector(primary, SimpleNamespace(detect=fallback))
    detector._board_id = board
    detector.fresh_fallback_handoff = True
    return detector, calls


def test_fresh_reference_can_replace_primary_hold_on_same_frame():
    stale = result('stale')
    fresh = result()
    detector, calls = hybrid(stale, fresh)
    output = detector.detect(None, 8, 1000)
    assert output.tracking == 'locked'
    assert output.pose_mode == 'feature_fallback'
    assert len(calls) == 1


@pytest.mark.parametrize('fallback', [result('stale'), result('searching'),
    result(frame_id=7), result(ts_ms=999), replace(result(), pins=[]),
    replace(result(), outline_px=None)])
def test_missing_or_old_reference_must_not_become_new_lock(fallback):
    stale = result('stale')
    detector, calls = hybrid(stale, fallback)
    assert detector.detect(None, 8, 1000) is stale
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['eye', 'other_board', 'primary_locked', 'disabled'])
def test_other_paths_are_unchanged(kind):
    primary = result('locked' if kind == 'primary_locked' else 'stale')
    detector, calls = hybrid(primary, result(),
        board='other' if kind == 'other_board' else 'raspberry-pi-5', eye=kind == 'eye')
    if kind == 'disabled':
        detector.fresh_fallback_handoff = False
    assert detector.detect(None, 8, 1000) is primary
    assert not calls
