"""Deterministic deadlines and stop handling; no machine timer assumptions."""
import pytest

from app.eye_timing import wait_eye_deadline


class Clock:
    def __init__(self):
        self.now = 10.
        self.sleeps = []
        self.overshoot = 0.
        self.after_sleep = None

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds + self.overshoot
        if self.after_sleep:
            self.after_sleep()


class Stop:
    def __init__(self, clock):
        self.clock = clock
        self.set = False
        self.waits = []
        self.stop_on_wait = False

    def is_set(self):
        return self.set

    def wait(self, seconds):
        self.waits.append(seconds)
        if self.stop_on_wait:
            self.set = True
            return True
        # Simulate a coarse Windows event wake rather than an exact sleep.
        self.clock.now += seconds + .015
        return False


def wait(stop, deadline):
    return wait_eye_deadline(stop, deadline, clock=stop.clock.read, sleep=stop.clock.sleep)


def test_short_deadline_uses_no_coarse_event_wait_and_does_not_accumulate_drift():
    clock = Clock()
    stop = Stop(clock)
    deadline = clock.now + .007
    assert wait(stop, deadline) is False
    assert stop.waits == []
    assert all(0 < seconds <= .002 for seconds in clock.sleeps)
    assert clock.now == pytest.approx(deadline)


def test_oversleep_never_adds_another_delay_after_deadline():
    clock = Clock()
    clock.overshoot = .020
    stop = Stop(clock)
    assert wait(stop, clock.now + .003) is False
    assert clock.sleeps == [.002]
    assert stop.waits == []


@pytest.mark.parametrize('already_stopped', [False, True])
def test_stop_is_checked_before_and_between_short_sleeps(already_stopped):
    clock = Clock()
    stop = Stop(clock)
    stop.set = already_stopped
    clock.after_sleep = lambda: setattr(stop, 'set', True)
    assert wait(stop, clock.now + .030) is True
    assert len(clock.sleeps) == (0 if already_stopped else 1)
    assert stop.waits == []


def test_long_wait_retains_event_wakeup_then_finishes_against_original_deadline():
    clock = Clock()
    stop = Stop(clock)
    deadline = clock.now + .500
    assert wait(stop, deadline) is False
    assert stop.waits == pytest.approx([.480])
    assert all(0 < seconds <= .002 for seconds in clock.sleeps)
    assert clock.now == pytest.approx(deadline)


def test_stop_interrupts_long_event_wait_without_followup_sleep():
    clock = Clock()
    stop = Stop(clock)
    stop.stop_on_wait = True
    assert wait(stop, clock.now + 1.) is True
    assert len(stop.waits) == 1 and clock.sleeps == []


def test_expired_deadline_returns_immediately():
    clock = Clock()
    stop = Stop(clock)
    assert wait(stop, clock.now - 1.) is False
    assert stop.waits == [] and clock.sleeps == []
