"""Unit tests for the searching/locked/stale state machine."""
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.vision.pose_tracker import TrackerStateMachine


def make():
    return TrackerStateMachine(lock_after_good=3, search_after_bad=15)


def test_starts_searching():
    assert make().state == "searching"


def test_locks_after_three_consecutive_good():
    sm = make()
    assert sm.update(True) == "searching"
    assert sm.update(True) == "searching"
    assert sm.update(True) == "locked"


def test_good_streak_resets_on_bad():
    sm = make()
    sm.update(True)
    sm.update(True)
    assert sm.update(False) == "searching"
    sm.update(True)
    sm.update(True)
    assert sm.state == "searching"  # streak restarted, only 2 good so far
    assert sm.update(True) == "locked"


def test_locked_goes_stale_on_single_bad():
    sm = make()
    for _ in range(3):
        sm.update(True)
    assert sm.update(False) == "stale"


def test_stale_relocks_on_single_good():
    sm = make()
    for _ in range(3):
        sm.update(True)
    sm.update(False)
    assert sm.update(True) == "locked"


def test_stale_falls_back_to_searching_after_15_bad():
    sm = make()
    for _ in range(3):
        sm.update(True)
    states = [sm.update(False) for _ in range(15)]
    assert states[:14] == ["stale"] * 14
    assert states[14] == "searching"


def test_five_bad_frames_stay_stale():
    sm = make()
    for _ in range(3):
        sm.update(True)
    states = [sm.update(False) for _ in range(5)]
    assert states == ["stale"] * 5


def test_after_searching_fallback_needs_three_good_again():
    sm = make()
    for _ in range(3):
        sm.update(True)
    for _ in range(15):
        sm.update(False)
    assert sm.state == "searching"
    assert sm.update(True) == "searching"
    assert sm.update(True) == "searching"
    assert sm.update(True) == "locked"


def test_reset():
    sm = make()
    for _ in range(3):
        sm.update(True)
    sm.reset()
    assert sm.state == "searching"
    sm.update(True)
    sm.update(True)
    assert sm.state == "searching"
