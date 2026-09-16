"""Tests for GET /api/cameras and POST /api/cameras/select
(docs/api-contract.md §7), plus direct unit tests of the
DeviceCameraSource.switch_to() hot-swap contract it depends on.

Uses the same build_app() injection seams as test_backend_core.py. A fake
device-camera source (FakeDeviceSource) implements the surface
app/api/cameras.py actually depends on - `current_index` (property) and
`switch_to(index) -> (ok, width, height)` - plus the plain FrameSource
protocol (open/read/close) so CaptureService can run it for real.

No real webcam is required, and - deliberately - no test in this module ever
calls the real cv2.VideoCapture on a real hardware index: this dev box
genuinely has real camera devices attached (per this session's operating
context, one may already be held open by a separate live demo backend
process on port 8100), so relying on "no camera present" for a test to pass,
or actually opening a real device index from a test process, would be either
flaky or a real risk to that other process's capture thread. Every test that
would otherwise reach cv2.VideoCapture (GET /api/cameras's probing of "other"
indices, and the DeviceCameraSource unit tests below) monkeypatches it with a
fully-synthetic stand-in instead.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

_TESTS = Path(__file__).resolve().parent
for _p in (str(_TESTS.parent), str(_TESTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.config import AppConfig, ComponentVisionConfig
from app.main import build_app

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VIDEO_W, VIDEO_H = 64, 48


# ---------------------------------------------------------------- stubs ----

class FakeDeviceSource:
    """Minimal stand-in for DeviceCameraSource: implements the FrameSource
    protocol (so CaptureService can run it for real, feeding the FrameBus
    app.api.cameras reads for the "current index" thumbnail) plus the two
    members app/api/cameras.py depends on: `current_index` and `switch_to`.
    """

    def __init__(self, index: int = 1, width: int = VIDEO_W, height: int = VIDEO_H,
                 openable: set[int] | None = None) -> None:
        self._index = index
        self._width = width
        self._height = height
        self._openable = openable if openable is not None else set()
        self._frame_id = 0
        self.switch_calls: list[int] = []
        self.opened = False
        self.closed = False

    @property
    def current_index(self) -> int:
        return self._index

    def open(self) -> None:
        self.opened = True

    def read(self):
        time.sleep(0.005)
        self._frame_id += 1
        # Tag the frame with the current index (as a pixel value) so a test
        # can tell, after a switch attempt, which index frames are actually
        # coming from.
        frame = np.full((self._height, self._width, 3), self._index, dtype=np.uint8)
        return frame, self._frame_id, time.monotonic() * 1000.0

    def close(self) -> None:
        self.closed = True

    def switch_to(self, new_index: int):
        self.switch_calls.append(new_index)
        if new_index not in self._openable:
            return False, 0, 0
        self._index = new_index
        return True, self._width, self._height


def make_config(**overrides) -> AppConfig:
    values = dict(
        server={"host": "127.0.0.1", "port": 8100},
        camera={
            "source": "device",
            "device_index": 1,
            "width": VIDEO_W,
            "height": VIDEO_H,
            "fps": 60,
            "max_probe_index": 3,
        },
        detector="mock",
        component_vision=ComponentVisionConfig(),
        board="mini-board",
        profile_dir=FIXTURES,
        frontend_dist=FIXTURES / "no-such-dist",
        default_locale="zh-TW",
        jpeg_quality=70,
        detection_hz=60,
    )
    values.update(overrides)
    return AppConfig(**values)


class _StubDetector:
    def load(self, profile, profile_dir) -> None:
        pass

    def detect(self, frame_bgr, frame_id, ts_ms):
        from app.vision.interface import DetectionResult
        return DetectionResult(
            board_id="mini-board", frame_id=frame_id, ts_ms=ts_ms,
            tracking="searching", confidence=0.0, pins=[],
        )

    def close(self) -> None:
        pass


def make_app(source, **config_overrides):
    return build_app(make_config(**config_overrides), detector=_StubDetector(), source=source)


def _wait_for_frame(app, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while app.state.frame_bus.latest_seq == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert app.state.frame_bus.latest_seq > 0, "no frame arrived in time"


def _patch_fake_cv2_capture(monkeypatch, openable: dict) -> list:
    """Replace cv2.VideoCapture with a fully-synthetic stand-in for the
    duration of one test, so GET /api/cameras's probing of "other" indices
    never touches real hardware.

    This is deliberate, not just a convenience: this dev box has real camera
    devices attached, AND (per this session's operating context) a separate
    live backend process may already hold one of those device indices open
    for a real demo. A test that opens real cv2.VideoCapture handles on
    arbitrary indices could either flake (outcome depends on what hardware
    happens to be plugged in) or contend with that other process's already-
    open capture handle. Mocking removes both risks.

    `openable` maps index -> (width, height) for indices that should report
    as available; any index not in the mapping reports as unavailable.
    Returns the list of indices actually passed to cv2.VideoCapture (append-
    only, in call order) so a test can assert exactly what was/wasn't probed.
    """
    import cv2

    opened_indices: list[int] = []

    class FakeCV2Capture:
        def __init__(self, index, backend):
            opened_indices.append(index)
            self._index = index
            self._ok = index in openable

        def isOpened(self):
            return self._ok

        def set(self, prop, value):
            return True

        def read(self):
            if not self._ok:
                return False, None
            w, h = openable[self._index]
            frame = np.full((h, w, 3), self._index, dtype=np.uint8)
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FakeCV2Capture)
    return opened_indices


# ------------------------------------------------------------ probe shape ----

def test_get_cameras_shape_and_current_index_uses_frame_bus_not_second_capture(monkeypatch):
    """The currently-active index (1) must NEVER be passed to
    cv2.VideoCapture by the probe path - its thumbnail comes from the
    FrameBus. Other indices (0, 2, 3) go through a fully-synthetic
    cv2.VideoCapture stand-in (index 2 "has a camera", 0 and 3 don't)."""
    opened_indices = _patch_fake_cv2_capture(monkeypatch, {2: (VIDEO_W, VIDEO_H)})

    source = FakeDeviceSource(index=1, openable=set())
    app = make_app(source)
    with TestClient(app) as client:
        _wait_for_frame(app)
        r = client.get("/api/cameras")
        assert r.status_code == 200
        body = r.json()

    # index 1 (current) must never have been opened via cv2.VideoCapture.
    assert 1 not in opened_indices
    # every other configured index (0..max_probe_index=3) WAS probed.
    assert set(opened_indices) == {0, 2, 3}

    cameras = {c["index"]: c for c in body["cameras"]}
    assert set(cameras.keys()) == {0, 1, 2, 3}

    current = cameras[1]
    assert current["available"] is True
    assert current["is_current"] is True
    assert current["width"] == VIDEO_W
    assert current["height"] == VIDEO_H
    assert isinstance(current["thumbnail_b64"], str) and len(current["thumbnail_b64"]) > 0

    available_other = cameras[2]
    assert available_other["is_current"] is False
    assert available_other["available"] is True
    assert available_other["width"] == VIDEO_W
    assert available_other["height"] == VIDEO_H
    assert isinstance(available_other["thumbnail_b64"], str) and len(available_other["thumbnail_b64"]) > 0

    for i in (0, 3):
        entry = cameras[i]
        assert entry["is_current"] is False
        assert entry["available"] is False
        assert "thumbnail_b64" not in entry
        assert "width" not in entry


def test_get_cameras_includes_current_index_beyond_max_probe_index(monkeypatch):
    """If the live index is outside the configured probe range, it must
    still show up in the response (never silently dropped)."""
    _patch_fake_cv2_capture(monkeypatch, {})  # no "other" index has a camera

    source = FakeDeviceSource(index=9, openable=set())
    app = make_app(source, camera={"source": "device", "device_index": 9,
                                    "width": VIDEO_W, "height": VIDEO_H,
                                    "fps": 60, "max_probe_index": 2})
    with TestClient(app) as client:
        _wait_for_frame(app)
        r = client.get("/api/cameras")
        assert r.status_code == 200
        body = r.json()

    indices = [c["index"] for c in body["cameras"]]
    assert indices == sorted(indices)
    assert 9 in indices
    current = next(c for c in body["cameras"] if c["index"] == 9)
    assert current["is_current"] is True
    assert current["available"] is True


def test_get_cameras_not_applicable_shape_for_synthetic_source():
    app = build_app(make_config(camera={"source": "synthetic", "device_index": 0,
                                         "width": VIDEO_W, "height": VIDEO_H, "fps": 60}),
                     detector=_StubDetector())
    with TestClient(app) as client:
        r = client.get("/api/cameras")
        assert r.status_code == 200
        assert r.json() == {"cameras": []}


# --------------------------------------------------------------- select ----

def test_select_success_switches_and_downstream_keeps_reading_same_bus():
    source = FakeDeviceSource(index=1, openable={2})
    app = make_app(source)
    with TestClient(app) as client:
        _wait_for_frame(app)
        seq_before = app.state.frame_bus.latest_seq

        r = client.post("/api/cameras/select", json={"index": 2})
        assert r.status_code == 200
        body = r.json()
        assert body == {"ok": True, "index": 2, "width": VIDEO_W, "height": VIDEO_H}

        assert source.switch_calls == [2]
        assert source.current_index == 2

        # CaptureService's read loop (a single thread that keeps calling
        # source.read()) never had to be restarted - it just keeps going,
        # and downstream consumers (MJPEG/VisionWorker/WireTraceWorker) all
        # read the SAME FrameBus, so the switch is visible to them for free.
        # (latest_seq alone isn't a strong enough signal here: the capture
        # loop keeps producing frames continuously, so a handful of already-
        # in-flight index-1 frames may land just after the switch call
        # returns - wait for the frame CONTENT to actually flip to index 2.)
        deadline = time.monotonic() + 2.0
        slot = None
        while time.monotonic() < deadline:
            slot = app.state.frame_bus.get_latest(timeout=0.2)
            if slot is not None and int(slot.frame[0, 0, 0]) == 2:
                break
            slot = None
        assert slot is not None, "frames never switched to the new index"
        assert int(slot.frame[0, 0, 0]) == 2
        assert seq_before < app.state.frame_bus.latest_seq


def test_select_invalid_index_out_of_range():
    source = FakeDeviceSource(index=1, openable={0, 1, 2, 3})
    app = make_app(source)
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={"index": 99})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "invalid_index"
        assert body["error_code"] == "invalid_index"
        assert body["params"] == {}
        assert source.switch_calls == []  # never even attempted


def test_select_negative_index_is_invalid_index():
    source = FakeDeviceSource(index=1, openable={0, 1, 2, 3})
    app = make_app(source)
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={"index": -1})
        assert r.status_code == 200
        assert r.json()["error"] == "invalid_index"
        assert source.switch_calls == []


def test_select_same_as_current_does_not_attempt_switch():
    source = FakeDeviceSource(index=1, openable={0, 1, 2, 3})
    app = make_app(source)
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={"index": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "same_as_current"
        assert body["error_code"] == "same_as_current"
        assert body["params"] == {}
        assert source.switch_calls == []


def test_select_open_failed_rolls_back_and_keeps_serving_original_index():
    """new_index is NOT in `openable` -> switch_to() reports failure and
    (per FakeDeviceSource, mirroring the real DeviceCameraSource.switch_to
    contract) never mutates current_index. The source must keep serving
    frames from the ORIGINAL index the whole time."""
    source = FakeDeviceSource(index=1, openable={5})  # 2 is not openable
    app = make_app(source)
    with TestClient(app) as client:
        _wait_for_frame(app)

        r = client.post("/api/cameras/select", json={"index": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "open_failed"
        assert body["error_code"] == "open_failed"
        assert body["params"] == {}

        assert source.switch_calls == [2]
        assert source.current_index == 1  # rolled back / never changed

        # capture loop is still alive and still serving the ORIGINAL index.
        slot_before = app.state.frame_bus.get_latest(timeout=1.0)
        assert slot_before is not None
        time.sleep(0.05)
        slot_after = app.state.frame_bus.get_latest(timeout=1.0, newer_than=slot_before.seq)
        assert slot_after is not None
        assert int(slot_after.frame[0, 0, 0]) == 1  # still tagged with the original index


def test_select_not_applicable_for_synthetic_source():
    app = build_app(make_config(camera={"source": "synthetic", "device_index": 0,
                                         "width": VIDEO_W, "height": VIDEO_H, "fps": 60}),
                     detector=_StubDetector())
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={"index": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "not_applicable"
        assert body["error_code"] == "not_applicable"
        assert body["params"] == {}


# -------------------------------------------------------------- malformed ----

def test_select_missing_field_is_422():
    source = FakeDeviceSource(index=1, openable={0, 1, 2, 3})
    app = make_app(source)
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={})
        assert r.status_code == 422


def test_select_non_integer_index_is_422():
    source = FakeDeviceSource(index=1, openable={0, 1, 2, 3})
    app = make_app(source)
    with TestClient(app) as client:
        r = client.post("/api/cameras/select", json={"index": "not-a-number"})
        assert r.status_code == 422


# --------------------------------------- DeviceCameraSource.switch_to() ----
# Direct unit tests of the real class the API layer above calls into,
# independent of the FastAPI app - covers the actual open/rollback contract.

class _FakeCap:
    """Fully-synthetic stand-in for a single cv2.VideoCapture handle."""

    _registry: dict = {}    # index -> opens successfully at all
    _warmup: dict = {}      # index -> initial successful black reads
    _no_frame: set = set()  # indices that open fine but yield no frame
    _black: set = set()     # indices return a successful but all-zero frame
    log: list = []          # ("open"|"release", index), in call order
    set_calls: list = []    # (index, property, value)

    def __init__(self, index, backend):
        self._index = index
        self._ok = _FakeCap._registry.get(index, False)
        self._read_count = 0
        _FakeCap.log.append(("open", index))

    def isOpened(self):
        return self._ok

    def set(self, prop, value):
        _FakeCap.set_calls.append((self._index, prop, value))
        return True

    def read(self):
        self._read_count += 1
        if not self._ok or self._index in _FakeCap._no_frame:
            return False, None
        if self._read_count <= _FakeCap._warmup.get(self._index, 0):
            return True, np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
        if self._index in _FakeCap._black:
            return True, np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
        frame = np.full((VIDEO_H, VIDEO_W, 3), self._index, dtype=np.uint8)
        if self._index == 0:
            # Keep the index tag at [0, 0] while making the synthetic frame
            # meaningfully non-black so it exercises the real signal guard.
            # A single bright pixel is intentionally no longer sufficient:
            # the real C920 can return that kind of near-black sensor noise.
            frame[1:9, 1:9] = 255
        return True, frame

    def release(self):
        _FakeCap.log.append(("release", self._index))


@pytest.fixture()
def fake_cap(monkeypatch):
    import cv2
    _FakeCap._registry = {}
    _FakeCap._warmup = {}
    _FakeCap._no_frame = set()
    _FakeCap._black = set()
    _FakeCap.log = []
    _FakeCap.set_calls = []
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCap)
    return _FakeCap


def test_device_camera_source_switch_to_success(fake_cap):
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {0: True, 1: True}
    src = DeviceCameraSource(0, VIDEO_W, VIDEO_H, 30.0)
    src.open()
    assert src.current_index == 0
    frame, _, _ = src.read()
    assert int(frame[0, 0, 0]) == 0

    ok, w, h = src.switch_to(1)
    assert (ok, w, h) == (True, VIDEO_W, VIDEO_H)
    assert src.current_index == 1

    frame, _, _ = src.read()
    assert int(frame[0, 0, 0]) == 1


def test_device_camera_source_applies_optional_manual_image_controls(fake_cap):
    import cv2
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {1: True}
    src = DeviceCameraSource(
        1, VIDEO_W, VIDEO_H, 30.0,
        lock_auto_focus=True,
        focus=17.0,
        lock_auto_exposure=True,
        lock_auto_white_balance=True,
        exposure=-6.0,
        gain=4.0,
        white_balance_temperature=4500.0,
    )
    src.open()

    props = {(prop, value) for _index, prop, value in fake_cap.set_calls}
    assert (cv2.CAP_PROP_AUTOFOCUS, 0) in props
    assert (cv2.CAP_PROP_FOCUS, 17.0) in props
    assert (cv2.CAP_PROP_AUTO_EXPOSURE, 0.25) in props
    assert (cv2.CAP_PROP_EXPOSURE, -6.0) in props
    assert (cv2.CAP_PROP_GAIN, 4.0) in props
    if hasattr(cv2, "CAP_PROP_AUTO_WB"):
        assert (cv2.CAP_PROP_AUTO_WB, 0) in props
    if hasattr(cv2, "CAP_PROP_WB_TEMPERATURE"):
        assert (cv2.CAP_PROP_WB_TEMPERATURE, 4500.0) in props


def test_device_camera_leaves_autofocus_enabled_by_default(fake_cap):
    import cv2
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {1: True}
    src = DeviceCameraSource(1, VIDEO_W, VIDEO_H, 30.0)
    src.open()

    assert not any(prop == cv2.CAP_PROP_AUTOFOCUS
                   for _index, prop, _value in fake_cap.set_calls)
    src.close()


def test_device_camera_source_selects_mjpg_before_resolution_requests(fake_cap):
    """DirectShow cameras may expose 1080p only after MJPG negotiation."""
    import cv2
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {1: True}
    src = DeviceCameraSource(1, 1920, 1080, 30.0)
    src.open()

    calls = [
        (prop, value)
        for _index, prop, value in fake_cap.set_calls
    ]
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    assert calls.index((cv2.CAP_PROP_FOURCC, fourcc)) < calls.index(
        (cv2.CAP_PROP_FRAME_WIDTH, 1920)
    )
    assert calls.index((cv2.CAP_PROP_FRAME_WIDTH, 1920)) < calls.index(
        (cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    )


def test_device_camera_requests_a_low_latency_driver_buffer(fake_cap):
    import cv2
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {1: True}
    src = DeviceCameraSource(1, VIDEO_W, VIDEO_H, 30.0, buffer_size=1)
    src.open()

    if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
        assert any(prop == cv2.CAP_PROP_BUFFERSIZE and value == 1
                   for _index, prop, value in fake_cap.set_calls)
    src.close()


def test_camera_probe_uses_the_same_mjpg_negotiation_order(fake_cap):
    import cv2
    from app.api.cameras import _probe_other_index

    fake_cap._registry = {2: True}
    result = _probe_other_index(2, 1920, 1080)

    assert result["available"] is True
    calls = [call[1:] for call in fake_cap.set_calls]
    fourcc = (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    assert fourcc in calls
    assert calls.index(fourcc) < calls.index(
        (cv2.CAP_PROP_FRAME_WIDTH, 1920)
    )


def test_camera_probe_rejects_successful_but_black_frame(fake_cap):
    from app.api.cameras import _probe_other_index

    fake_cap._registry = {2: True}
    fake_cap._black = {2}

    result = _probe_other_index(2, 1920, 1080)

    assert result == {
        "index": 2,
        "available": False,
        "is_current": False,
        "signal_status": "black",
    }


def test_camera_probe_allows_short_uvc_warmup(fake_cap):
    from app.api.cameras import _probe_other_index

    fake_cap._registry = {2: True}
    fake_cap._warmup = {2: 1}

    result = _probe_other_index(2, 1920, 1080)

    assert result["available"] is True
    assert result["width"] == VIDEO_W
    assert result["height"] == VIDEO_H


def test_device_camera_switch_rejects_black_frame_and_keeps_original(fake_cap):
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {0: True, 1: True}
    fake_cap._black = {1}
    src = DeviceCameraSource(0, VIDEO_W, VIDEO_H, 30.0)
    src.open()

    ok, width, height = src.switch_to(1)

    assert (ok, width, height) == (False, 0, 0)
    assert src.current_index == 0
    frame, _, _ = src.read()
    assert int(frame[0, 0, 0]) == 0


def test_device_camera_read_drops_black_frame(fake_cap):
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {1: True}
    fake_cap._black = {1}
    src = DeviceCameraSource(1, VIDEO_W, VIDEO_H, 30.0)
    src.open()

    assert src.read() is None
    src.close()


def test_frame_signal_guard_rejects_sparse_near_black_noise():
    from app.capture.sources import frame_has_signal

    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    frame[0, 0, 0] = 255

    assert frame_has_signal(frame) is False


def test_frame_signal_guard_accepts_a_dim_but_usable_frame():
    from app.capture.sources import frame_has_signal

    frame = np.full((48, 64, 3), 2, dtype=np.uint8)

    assert frame_has_signal(frame) is True


def test_device_camera_falls_back_to_driver_default_after_black_codecs(monkeypatch):
    import cv2
    from app.capture.sources import DeviceCameraSource

    opened: list[object] = []
    mjpg = cv2.VideoWriter_fourcc(*"MJPG")
    yuy2 = cv2.VideoWriter_fourcc(*"YUY2")

    class FormatCap:
        def __init__(self, _index, _backend):
            self.codec = None
            opened.append(self)

        def isOpened(self):
            return True

        def set(self, prop, value):
            if prop == cv2.CAP_PROP_FOURCC:
                self.codec = value
            return True

        def read(self):
            if self.codec in (mjpg, yuy2):
                return True, np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
            frame = np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
            frame[1:9, 1:9] = 255
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", FormatCap)
    src = DeviceCameraSource(1, 1920, 1080, 30.0)
    src.open()

    got = src.read()

    assert got is not None
    assert len(opened) == 3
    src.close()


def test_device_camera_probe_allows_short_uvc_warmup(monkeypatch):
    """A transient first black frame must not force a lower-quality fallback."""
    import cv2
    from app.capture.sources import DeviceCameraSource

    opened: list[object] = []
    class WarmupCap:
        def __init__(self, _index, _backend):
            self.codec = None
            self.read_count = 0
            opened.append(self)

        def isOpened(self):
            return True

        def set(self, prop, value):
            if prop == cv2.CAP_PROP_FOURCC:
                self.codec = value
            return True

        def read(self):
            self.read_count += 1
            if self.read_count == 1:
                return True, np.zeros((VIDEO_H, VIDEO_W, 3), dtype=np.uint8)
            frame = np.full((VIDEO_H, VIDEO_W, 3), 32, dtype=np.uint8)
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", WarmupCap)
    src = DeviceCameraSource(1, 1920, 1080, 30.0)
    src.open()

    got = src.read()

    assert got is not None
    assert len(opened) == 1
    assert opened[0].read_count == 3  # one probe frame + one live read
    src.close()


def test_device_camera_source_switch_to_open_failure_rolls_back(fake_cap):
    """new_index fails cv2.VideoCapture.isOpened() -> failure reported,
    original device left completely untouched."""
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {0: True, 1: False}
    src = DeviceCameraSource(0, VIDEO_W, VIDEO_H, 30.0)
    src.open()

    ok, w, h = src.switch_to(1)
    assert (ok, w, h) == (False, 0, 0)
    assert src.current_index == 0  # unchanged

    frame, _, _ = src.read()  # original capture still serving frames
    assert int(frame[0, 0, 0]) == 0


def test_device_camera_source_switch_to_no_frame_rolls_back(fake_cap):
    """new_index opens (isOpened() True) but read() never yields a frame -
    also a failure, also rolled back (not just the "won't open at all" case)."""
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {0: True, 1: True}
    fake_cap._no_frame = {1}
    src = DeviceCameraSource(0, VIDEO_W, VIDEO_H, 30.0)
    src.open()

    ok, w, h = src.switch_to(1)
    assert (ok, w, h) == (False, 0, 0)
    assert src.current_index == 0

    frame, _, _ = src.read()
    assert int(frame[0, 0, 0]) == 0


def test_device_camera_source_switch_to_never_releases_old_handle_before_new_succeeds(fake_cap):
    """The previous capture handle must only be release()d AFTER a new one
    is confirmed open-and-producing-frames - never eagerly, and never at all
    across repeated failures."""
    from app.capture.sources import DeviceCameraSource

    fake_cap._registry = {0: True, 1: False}
    src = DeviceCameraSource(0, VIDEO_W, VIDEO_H, 30.0)
    src.open()
    fake_cap.log.clear()

    src.switch_to(1)  # fails to open
    assert 0 not in [i for (op, i) in fake_cap.log if op == "release"]

    src.switch_to(1)  # fails again - still must not touch index 0's handle
    assert 0 not in [i for (op, i) in fake_cap.log if op == "release"]

    fake_cap._registry[1] = True
    ok, _, _ = src.switch_to(1)  # now it succeeds
    assert ok is True
    assert 0 in [i for (op, i) in fake_cap.log if op == "release"]  # only now


# ------------------------------------------------------- window source ----

def test_camera_config_accepts_window_source():
    from app.config import CameraConfig

    cfg = CameraConfig(source="window", window_title="iPhone")
    assert cfg.source == "window"
    assert cfg.window_title == "iPhone"


def test_ffmpeg_mjpeg_parser_returns_complete_frames_and_keeps_tail():
    from app.capture.sources import extract_complete_mjpeg_frames

    frame_1 = b"\xff\xd8first\xff\xd9"
    frame_2 = b"\xff\xd8second\xff\xd9"
    partial = b"\xff\xd8third"
    buffer = bytearray(b"pipe-noise" + frame_1 + frame_2 + partial)

    assert extract_complete_mjpeg_frames(buffer) == [frame_1, frame_2]
    assert bytes(buffer) == partial
    buffer.extend(b"-done\xff\xd9")
    assert extract_complete_mjpeg_frames(buffer) == [partial + b"-done\xff\xd9"]
    assert not buffer


def test_ffmpeg_camera_command_selects_native_1080p30_mjpeg():
    from app.capture.sources import FfmpegMjpegCameraSource

    source = FfmpegMjpegCameraSource(
        1, "HD Pro Webcam C920", 1920, 1080, 30.0,
    )
    command = source.command()

    assert command[0] == "ffmpeg"
    assert command[command.index("-video_size") + 1] == "1920x1080"
    assert command[command.index("-framerate") + 1] == "30"
    assert command[command.index("-vcodec") + 1] == "mjpeg"
    assert command[command.index("-i") + 1] == "video=HD Pro Webcam C920"
    assert command[command.index("-c:v") + 1] == "copy"


def test_create_frame_source_builds_ffmpeg_device_source():
    from app.capture.sources import FfmpegMjpegCameraSource, create_frame_source
    from app.config import AppConfig, CameraConfig

    cfg = AppConfig(camera=CameraConfig(
        source="device",
        device_index=1,
        capture_backend="ffmpeg",
        ffmpeg_device_name="HD Pro Webcam C920",
        width=1920,
        height=1080,
        fps=30,
    ))
    source, scene = create_frame_source(cfg)

    assert isinstance(source, FfmpegMjpegCameraSource)
    assert source.current_index == 1
    assert scene is None


def test_create_frame_source_builds_window_capture_source():
    from app.capture.sources import WindowCaptureSource, create_frame_source
    from app.config import AppConfig, CameraConfig

    cfg = AppConfig(camera=CameraConfig(source="window", window_title="zz-nope"))
    source, scene = create_frame_source(cfg)
    assert isinstance(source, WindowCaptureSource)
    assert scene is None


def test_window_capture_source_missing_window_never_raises():
    """FrameSource contract: read() must never raise on transient failure.
    A title that matches no window is the 'camera unplugged' equivalent."""
    from app.capture.sources import WindowCaptureSource

    src = WindowCaptureSource("zz-no-such-window-title-zz", fps=60.0)
    src.open()          # window not found - must not raise
    for _ in range(3):
        assert src.read() is None  # no window -> None, still no raise
    src.close()
