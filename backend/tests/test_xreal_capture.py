"""Hardware-free coverage of the actual Eye adapter and image processing path."""
from queue import Queue
import threading
import time

import cv2
import numpy as np
import pytest

from app.capture.xreal import CAMERA_FPS, RESOLUTIONS, XrealEyeSource
from app.capture.xreal import source as source_module
from app.capture.xreal.control import make_frame, parse_frame
from app.capture.xreal.quality import RgbDenoiser


class FakeQueue(Queue):
    def close(self):
        self.closed = True

    def cancel_join_thread(self):
        pass


class FakeProcess:
    def __init__(self, *, target, args, name, daemon):
        self.args = args
        self.alive = False
        self.stuck = False
        self.terminated = False
        self.closed = False
        self.join_timeouts = []

    def start(self):
        self.alive = True
        self.args[5].put({"stage": "waiting", "driver_reported": dict(self.args[0])})

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.join_timeouts.append(timeout)
        if not self.stuck and self.args[4].is_set():
            self.alive = False

    def terminate(self):
        self.terminated = True
        self.alive = False

    def kill(self):
        self.alive = False

    def close(self):
        assert not self.alive
        self.closed = True


class FakeContext:
    RawArray = staticmethod(lambda kind, size: (kind * size)())
    Lock = staticmethod(threading.Lock)
    Event = staticmethod(threading.Event)
    Queue = staticmethod(FakeQueue)

    def __init__(self):
        self.processes = []

    def Process(self, **kwargs):
        process = FakeProcess(**kwargs)
        self.processes.append(process)
        return process


class FakeEyeDenoiser(RgbDenoiser):
    """Exercise source lifecycle with the real CPU filter and no CUDA import."""

    def __init__(self, mode):
        super().__init__(mode)
        self.backend = "none" if mode == "original" else "cpu"
        self.fallback_reason = None
        self.closed = False

    def close(self):
        self.closed = True
        self.reset()


@pytest.fixture
def fake_context(monkeypatch):
    context = FakeContext()
    monkeypatch.setattr(source_module.mp, "get_context", lambda method: context)
    monkeypatch.setattr(source_module, "create_eye_denoiser", FakeEyeDenoiser)
    return context


def publish(source, frame, sequence=1, stamp=None):
    stamp = time.monotonic_ns() if stamp is None else stamp
    with source._frame_lock:
        np.frombuffer(source._pixels, dtype=np.uint8)[:frame.nbytes] = frame.reshape(-1)
        source._metadata[:] = (sequence, frame.shape[1], frame.shape[0], stamp)
    return stamp


@pytest.mark.parametrize("width,height", RESOLUTIONS)
def test_native_resolution_color_timestamp_and_jpeg_preserved(fake_context, width, height):
    source = XrealEyeSource(width, height, 60, "original")
    source.open()
    try:
        frame = np.full((height, width, 3), (32, 96, 180), dtype=np.uint8)
        stamp = publish(source, frame)
        result, frame_id, ts_ms, jpeg = source.read()
        assert result.shape == frame.shape
        assert np.array_equal(result, frame)
        assert frame_id > 0
        assert ts_ms == pytest.approx(stamp / 1e6)
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape == frame.shape
        assert np.max(np.abs(decoded.astype(float) - frame)) <= 2
        snapshot = source.snapshot()
        assert snapshot["state"] == "live"
        assert snapshot["actual"] == {"width": width, "height": height, "fps": 60}
        assert snapshot["requested"]["denoise"] == "original"
        assert snapshot["denoise_backend"] == "none"
        assert snapshot["denoise_fallback_reason"] is None
    finally:
        source.close()
    assert fake_context.processes[0].closed


def test_denoise_change_resets_history_without_reopening_camera(fake_context):
    source = XrealEyeSource(denoise="clean")
    source.open()
    try:
        frame = np.full((48, 64, 3), 120, dtype=np.uint8)
        publish(source, frame)
        source.read()
        previous = source._denoiser
        source.set_denoise("strong")
        publish(source, frame, 2)
        source.read()
        assert source._denoiser is not previous
        assert previous.closed and previous.history is None
        assert source._denoiser.mode == "strong"
        assert source.snapshot()["requested"]["denoise"] == "strong"
        assert len(fake_context.processes) == 1
    finally:
        active = source._denoiser
        source.close()
    assert active.closed and source._denoiser is None


def test_source_reports_denoise_fallback_and_resets_after_stall(fake_context, monkeypatch):
    def fallback_filter(mode):
        denoiser = FakeEyeDenoiser(mode)
        denoiser.fallback_reason = "RuntimeError: test CUDA failure"
        return denoiser

    monkeypatch.setattr(source_module, "create_eye_denoiser", fallback_filter)
    source = XrealEyeSource(denoise="clean")
    source.open()
    try:
        before = np.full((48, 64, 3), 120, np.uint8)
        publish(source, before)
        source.read()
        active = source._denoiser
        assert source.snapshot()["denoise_backend"] == "cpu"
        assert "CUDA failure" in source.snapshot()["denoise_fallback_reason"]
        source._last_processed_at = time.monotonic() - 1.0
        after = np.full_like(before, 122)
        publish(source, after, 2)
        result = source.read()[0]
        np.testing.assert_array_equal(result, RgbDenoiser("clean").process(after))
        assert source._denoiser is active
    finally:
        source.close()
    assert active.closed


def test_hot_change_discards_inflight_frame_before_using_new_filter(fake_context, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    created = []

    class WaitingDenoiser(FakeEyeDenoiser):
        def __init__(self, mode):
            super().__init__(mode)
            created.append(self)

        def process(self, frame):
            if self.mode == "clean":
                entered.set()
                assert release.wait(2)
            return super().process(frame)

    monkeypatch.setattr(source_module, "create_eye_denoiser", WaitingDenoiser)
    source = XrealEyeSource(denoise="clean")
    source.open()
    results = []
    try:
        frame = np.full((48, 64, 3), 120, np.uint8)
        publish(source, frame)
        reader = threading.Thread(target=lambda: results.append(source.read()))
        reader.start()
        assert entered.wait(2)
        source.set_denoise("original")
        release.set()
        reader.join(2)
        assert not reader.is_alive() and results == [None]
        publish(source, frame, 2)
        np.testing.assert_array_equal(source.read()[0], frame)
        assert created[0].closed and created[1].mode == "original"
        assert source.snapshot()["denoise_backend"] == "none"
        assert source.snapshot()["processed_frames"] == 1
    finally:
        release.set()
        source.close()


def test_capture_failure_remains_visible_and_releases_process(fake_context):
    source = XrealEyeSource()
    source.open()
    process = fake_context.processes[0]
    source._messages.put({"error": "device disconnected"})
    assert source.read() is None
    assert source.snapshot()["state"] == "error"
    assert source.snapshot()["error"] == "device disconnected"
    assert process.closed
    assert source.read() is None
    assert len(fake_context.processes) == 1
    source.close()


def test_close_terminates_stuck_reader_with_bounded_joins(fake_context):
    source = XrealEyeSource()
    source.open()
    process = fake_context.processes[0]
    process.stuck = True
    source.close()
    assert process.terminated and process.closed
    assert process.join_timeouts == [1.5, 1.5]
    assert source.snapshot()["state"] == "stopped"


def test_actual_rate_uses_capture_counter_including_skipped_frames(fake_context):
    source = XrealEyeSource(denoise="original")
    source.open()
    try:
        frame = np.zeros((48, 64, 3), np.uint8)
        first_stamp = time.monotonic_ns()
        publish(source, frame, 1, first_stamp)
        source.read()
        publish(source, frame, 31, first_stamp + 1_000_000_000)
        source.read()
        assert source.snapshot()["capture_fps"] == pytest.approx(30.0)
        assert source.snapshot()["processed_frames"] == 2
    finally:
        source.close()


def test_eye_cadence_uses_high_resolution_clock_without_changing_timestamp_domain(fake_context, monkeypatch):
    source = XrealEyeSource(denoise="original")
    source.open()
    clock = {"perf": 100.}
    waits = []

    def perf_counter():
        value = clock["perf"]
        clock["perf"] += .001
        return value

    def wait_deadline(stop, deadline):
        assert 100. <= deadline < 101.  # Never a monotonic-domain timestamp.
        waits.append(deadline)
        clock["perf"] = max(clock["perf"], deadline)
        return stop.is_set()

    try:
        with monkeypatch.context() as patch:
            patch.setattr(source_module.time, "monotonic", lambda: 1000.)
            patch.setattr(source_module.time, "perf_counter", perf_counter)
            patch.setattr(source_module, "wait_eye_deadline", wait_deadline)
            source._next_due = 100.020
            frame = np.zeros((48, 64, 3), np.uint8)
            for sequence in (1, 2):
                publish(source, frame, sequence, stamp=1_000_000_000_000)
                output = source.read()
                assert output is not None
                assert output[2] == 1_000_000.  # Existing monotonic milliseconds.
                assert 100. <= source._next_due < 101.
            assert waits and source.snapshot()["frame_age_seconds"] == 0.
    finally:
        source.close()


@pytest.mark.parametrize("mode", RgbDenoiser.MODES)
def test_denoise_keeps_shape_and_uint8(mode):
    frame = np.random.default_rng(10).integers(0, 256, (72, 96, 3), dtype=np.uint8)
    result = RgbDenoiser(mode).process(frame)
    assert result.shape == frame.shape
    assert result.dtype == np.uint8


def test_temporal_denoise_reduces_static_noise_and_resets_on_shape_change():
    random = np.random.default_rng(10)
    denoiser = RgbDenoiser("clean")
    for _ in range(6):
        raw = np.clip(128 + random.normal(0, 7, (72, 96, 3)), 0, 255).astype(np.uint8)
        output = denoiser.process(raw)
    assert np.std(output.astype(float)) < np.std(raw.astype(float)) * 0.65
    different_shape = np.full((96, 72, 3), 170, dtype=np.uint8)
    assert np.array_equal(denoiser.process(different_shape), RgbDenoiser("clean").process(different_shape))
    denoiser.reset()
    assert denoiser.history is None and denoiser.previous_chroma is None
    assert denoiser.last_motion_fraction == 0


def test_motion_gate_does_not_mix_old_color_into_new_scene():
    denoiser = RgbDenoiser("strong")
    denoiser.process(np.full((72, 96, 3), (0, 0, 240), np.uint8))
    moved = np.full((72, 96, 3), (240, 0, 0), np.uint8)
    result = denoiser.process(moved)
    assert np.array_equal(result, RgbDenoiser("strong").process(moved))
    assert denoiser.last_motion_fraction == 1


def test_clean_preserves_a_subtly_translated_thin_edge_without_old_pixels():
    before = np.full((96, 128, 3), 100, np.uint8)
    before[20:76, 42:46] = 112
    after = np.full_like(before, 100)
    after[20:76, 44:48] = 112
    denoiser = RgbDenoiser("clean")
    for _ in range(5):
        denoiser.process(before)
    moved = denoiser.process(after)
    fresh = RgbDenoiser("clean").process(after)
    # A two-pixel movement of a low-contrast thin feature must not leave the
    # previous feature behind or blend its leading edge into an older frame.
    np.testing.assert_array_equal(moved[24:72, 40:50], fresh[24:72, 40:50])
    assert np.max(moved[24:72, 42:44]) <= 101
    assert np.min(moved[24:72, 45:47]) >= 110


def test_clean_motion_gate_uses_chroma_for_equal_luminance_color_changes():
    before = np.full((96, 128, 3), (20, 30, 180), np.uint8)
    after = np.full((96, 128, 3), (20, 110, 20), np.uint8)
    gray_before = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    gray_after = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    assert abs(int(gray_before[0, 0]) - int(gray_after[0, 0])) <= 2
    denoiser = RgbDenoiser("clean")
    for _ in range(5):
        denoiser.process(before)
    np.testing.assert_array_equal(denoiser.process(after), RgbDenoiser("clean").process(after))
    assert denoiser.last_motion_fraction == 1


def test_clean_reset_discards_old_scene_and_does_not_mutate_retained_frames():
    denoiser = RgbDenoiser("clean")
    before = np.full((72, 96, 3), (40, 80, 120), np.uint8)
    retained = denoiser.process(before)
    saved = retained.copy()
    after = np.full_like(before, (42, 82, 122))
    for _ in range(5):
        denoiser.process(after)
    np.testing.assert_array_equal(retained, saved)
    denoiser.reset()
    np.testing.assert_array_equal(denoiser.process(after), RgbDenoiser("clean").process(after))


def test_original_mode_is_pixel_exact_passthrough():
    frame = np.random.default_rng(11).integers(0, 256, (72, 96, 3), dtype=np.uint8)
    assert RgbDenoiser("original").process(frame) is frame


def test_known_enable_packet_and_crc_validation():
    frame = make_frame(0xD3, bytes.fromhex("45100100"))
    assert parse_frame(frame) == (0xD3, bytes.fromhex("45100100"))
    corrupted = bytearray(frame)
    corrupted[-1] ^= 1
    with pytest.raises(ValueError, match="CRC"):
        parse_frame(bytes(corrupted))


def test_unsupported_25_fps_excluded():
    assert CAMERA_FPS == (30, 60)
    with pytest.raises(ValueError):
        XrealEyeSource(fps=25)
