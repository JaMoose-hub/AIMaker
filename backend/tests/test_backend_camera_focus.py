"""Tests for live focus control + the assisted focus sweep.

- DeviceCameraSource.set_focus / focus_state (no real camera: cv2.VideoCapture
  is monkeypatched, same _FakeCap approach as test_backend_cameras.py)
- the focus value surviving a device reopen (a transient USB reconnect must
  not silently drop a focus lock the accuracy session depends on)
- the /api/camera/focus endpoints, including the sweep's peak selection and
  its peak-at-edge honesty flag, driven by a fake source + fake bus
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.capture.bus import FrameBus
from app.capture.sources import DeviceCameraSource

VIDEO_W, VIDEO_H = 64, 48


class _FocusCap:
    """cv2.VideoCapture stand-in that remembers focus/autofocus writes."""

    reject_focus = False   # make set(CAP_PROP_FOCUS) fail
    raise_on_set = False   # make set() raise

    def __init__(self, index, backend):
        self._index = index
        self.props: dict = {}

    def isOpened(self):
        return True

    def set(self, prop, value):
        import cv2

        if _FocusCap.raise_on_set and prop == cv2.CAP_PROP_FOCUS:
            raise RuntimeError("driver exploded")
        if _FocusCap.reject_focus and prop == cv2.CAP_PROP_FOCUS:
            return False
        self.props[prop] = value
        return True

    def get(self, prop):
        return float(self.props.get(prop, 0.0))

    def read(self):
        return True, np.full((VIDEO_H, VIDEO_W, 3), 7, dtype=np.uint8)

    def release(self):
        pass


@pytest.fixture()
def focus_cap(monkeypatch):
    import cv2

    _FocusCap.reject_focus = False
    _FocusCap.raise_on_set = False
    monkeypatch.setattr(cv2, "VideoCapture", _FocusCap)
    return _FocusCap


def _source() -> DeviceCameraSource:
    return DeviceCameraSource(1, VIDEO_W, VIDEO_H, 30.0, capture_api="dshow")


# ------------------------------------------------------------- set_focus ----

def test_set_focus_disables_autofocus_and_writes_value(focus_cap):
    import cv2

    src = _source()
    src.open()
    accepted, read_back = src.set_focus(10.0)
    assert accepted is True
    assert read_back == 10.0
    assert src._cap.props[cv2.CAP_PROP_AUTOFOCUS] == 0
    assert src._cap.props[cv2.CAP_PROP_FOCUS] == 10.0


def test_set_focus_auto_reenables_autofocus(focus_cap):
    import cv2

    src = _source()
    src.open()
    src.set_focus(10.0)
    accepted, _ = src.set_focus(None)
    assert accepted is True
    assert src._cap.props[cv2.CAP_PROP_AUTOFOCUS] == 1
    assert src.focus_state()["manual"] is False


def test_set_focus_survives_a_device_reopen(focus_cap):
    """A USB reconnect must not drop the lock: _apply_settings reapplies it."""
    import cv2

    src = _source()
    src.open()
    src.set_focus(10.0)
    with src._lock:                 # simulate the reopen path
        src._try_open_locked()
    assert src._cap.props[cv2.CAP_PROP_FOCUS] == 10.0
    assert src._cap.props[cv2.CAP_PROP_AUTOFOCUS] == 0


def test_set_focus_stores_value_even_with_no_open_handle(focus_cap):
    """Storing before touching the handle means the value still applies when
    the camera comes back."""
    src = _source()                  # never opened
    accepted, read_back = src.set_focus(10.0)
    assert (accepted, read_back) == (False, None)
    assert src.focus_state()["configured_focus"] == 10.0
    src.open()
    import cv2
    assert src._cap.props[cv2.CAP_PROP_FOCUS] == 10.0


def test_set_focus_reports_driver_rejection(focus_cap):
    focus_cap.reject_focus = True
    src = _source()
    src.open()
    accepted, _ = src.set_focus(10.0)
    assert accepted is False        # honest: the driver refused


def test_set_focus_never_raises(focus_cap):
    focus_cap.raise_on_set = True
    src = _source()
    src.open()
    assert src.set_focus(10.0) == (False, None)


# ------------------------------------------------------------- endpoints ----

class _FakeSource:
    """Minimal source exposing just the focus surface the API needs."""

    def __init__(self, curve: dict[float, float] | None = None):
        self.focus: float | None = None
        self.calls: list[float | None] = []
        self._curve = curve or {}

    def set_focus(self, value):
        self.focus = value
        self.calls.append(value)
        return True, value

    def focus_state(self):
        return {"manual": self.focus is not None, "configured_focus": self.focus,
                "read_back": self.focus, "autofocus_raw": 0.0, "camera_open": True}

    def sharpness_for(self, value):
        return self._curve.get(value, 0.0)


def _client(source, bus=None, detection_state=None) -> TestClient:
    """A bare app with only the focus router: keeps these tests independent of
    the full build_app lifespan (no camera, no CV, no workers)."""
    from fastapi import FastAPI

    from app.api import camera_focus

    app = FastAPI()
    app.include_router(camera_focus.router)
    app.state.source = source
    app.state.frame_bus = bus
    app.state.detection_state = detection_state
    return TestClient(app)


def test_get_focus_rejects_non_device_source():
    with _client(object()) as client:      # no set_focus attribute
        body = client.get("/api/camera/focus").json()
        assert body["ok"] is False
        assert body["error"] == "not_a_device_camera"


def test_get_and_set_focus():
    src = _FakeSource()
    with _client(src) as client:
        assert client.get("/api/camera/focus").json()["manual"] is False
        body = client.post("/api/camera/focus", json={"value": 10}).json()
        assert body == {"ok": True, "accepted": True, "read_back": 10.0,
                        "mode": "manual", "requested": 10.0}
        assert client.get("/api/camera/focus").json()["configured_focus"] == 10.0


def test_set_focus_auto_mode():
    src = _FakeSource()
    with _client(src) as client:
        body = client.post("/api/camera/focus", json={"auto": True}).json()
        assert body["mode"] == "auto" and body["requested"] is None
        assert src.calls == [None]


def test_set_focus_requires_a_value():
    with _client(_FakeSource()) as client:
        body = client.post("/api/camera/focus", json={}).json()
        assert body["ok"] is False and body["error"] == "no_value"


# ----------------------------------------------------------------- sweep ----

def _sweep_client(curve: dict[float, float], monkeypatch, *, detection=None):
    """Wire the scorer to a synthetic curve keyed by the source's focus, so
    the sweep's search logic is tested without any real optics."""
    from app.api import camera_focus

    src = _FakeSource(curve)
    bus = FrameBus()
    bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 1, 0.0)

    # Every get_latest returns a fresh slot so the sampler never starves.
    def _get_latest(timeout=None, newer_than=None):
        bus.put(np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8), 1, 0.0)
        return FrameBus.get_latest(bus, timeout=0.01, newer_than=None)

    monkeypatch.setattr(bus, "get_latest", _get_latest)
    monkeypatch.setattr(camera_focus, "_SETTLE_S", 0.0)
    monkeypatch.setattr(camera_focus, "_SAMPLES_PER_STEP", 1)
    monkeypatch.setattr(camera_focus, "_score",
                        lambda frame, det: (src.sharpness_for(src.focus), "centre"))

    class _DetState:
        def get(self):
            return detection

    return src, _client(src, bus, _DetState())


def test_sweep_finds_the_peak_and_applies_it(monkeypatch):
    curve = {0.0: 300.0, 5.0: 560.0, 10.0: 1067.0, 15.0: 886.0, 20.0: 638.0}
    src, client = _sweep_client(curve, monkeypatch)
    with client:
        body = client.post("/api/camera/focus/sweep",
                           json={"start": 0, "end": 20, "step": 5}).json()
    assert body["ok"] is True
    assert body["best_focus"] == 10.0
    assert body["best_sharpness"] == 1067.0
    assert body["peak_at_edge"] is False
    assert body["applied_focus"] == 10.0
    assert src.focus == 10.0                       # camera left at the peak
    assert [p["focus"] for p in body["curve"]] == [0.0, 5.0, 10.0, 15.0, 20.0]


def test_sweep_flags_a_peak_at_the_range_edge(monkeypatch):
    """Monotonic rise to the last step: the true optimum may be outside the
    swept range, and saying so is more useful than returning the endpoint."""
    curve = {0.0: 100.0, 5.0: 300.0, 10.0: 900.0}
    _, client = _sweep_client(curve, monkeypatch)
    with client:
        body = client.post("/api/camera/focus/sweep",
                           json={"start": 0, "end": 10, "step": 5}).json()
    assert body["best_focus"] == 10.0
    assert body["peak_at_edge"] is True


def test_sweep_can_restore_instead_of_applying(monkeypatch):
    curve = {0.0: 100.0, 5.0: 900.0, 10.0: 200.0}
    src, client = _sweep_client(curve, monkeypatch)
    src.focus = 42.0                                # pre-existing manual lock
    with client:
        body = client.post("/api/camera/focus/sweep",
                           json={"start": 0, "end": 10, "step": 5,
                                 "apply_best": False}).json()
    assert body["best_focus"] == 5.0
    assert body["applied_focus"] is None
    assert src.focus == 42.0                        # restored, not left at 10


def test_sweep_rejects_a_degenerate_range(monkeypatch):
    _, client = _sweep_client({0.0: 1.0}, monkeypatch)
    with client:
        body = client.post("/api/camera/focus/sweep",
                           json={"start": 10, "end": 10, "step": 5}).json()
    assert body["ok"] is False and body["error"] == "bad_range"

    with client:
        body = client.post("/api/camera/focus/sweep",
                           json={"start": 30, "end": 10, "step": 5}).json()
    assert body["ok"] is False and body["error"] == "bad_range"


def test_sweep_uses_the_board_roi_when_tracked(monkeypatch):
    """The score must come from the board, not the featureless desk."""
    from app.api import camera_focus

    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    class _Det:
        outline_px = [(20.0, 20.0), (180.0, 20.0), (180.0, 180.0), (20.0, 180.0)]

    roi, kind = camera_focus._sharpness_roi(frame, _Det())
    assert kind == "board"
    assert roi.shape[:2] == (160, 160)

    roi, kind = camera_focus._sharpness_roi(frame, None)
    assert kind == "centre"          # no tracking -> centre third fallback


def test_sharpness_roi_ignores_a_degenerate_outline():
    """A tiny/offscreen outline must not produce a useless 2px ROI."""
    from app.api import camera_focus

    frame = np.zeros((200, 200, 3), dtype=np.uint8)

    class _Det:
        outline_px = [(5.0, 5.0), (8.0, 5.0), (8.0, 8.0), (5.0, 8.0)]

    _, kind = camera_focus._sharpness_roi(frame, _Det())
    assert kind == "centre"
