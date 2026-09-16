"""Local Eye cadence waits without changing the Windows process timer period."""
from __future__ import annotations

import time


def wait_eye_deadline(stop, deadline: float, *, clock=time.perf_counter, sleep=time.sleep) -> bool:
    """Wait until a perf_counter deadline; return True if stopping was requested.

    Windows Event.wait() and Python 3.12's monotonic clock have roughly 15.6 ms
    resolution on this host. perf_counter uses QPC and sleep uses a high-
    resolution timer, so the last 50 ms use
    short sleeps and check stop at least every 2 ms of requested sleep. Long
    waits retain Event's immediate wake-on-stop behavior. No global timer or
    webcam scheduling settings are changed.
    """
    while not stop.is_set():
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        if remaining > .050:
            # Leave enough time for Event's coarse Windows tick, then finish
            # against the original deadline instead of accumulating drift.
            if stop.wait(remaining - .020):
                return True
        else:
            sleep(min(.002, remaining))
    return True
