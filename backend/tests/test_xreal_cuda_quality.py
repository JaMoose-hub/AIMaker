"""CPU-only fallback tests, plus explicitly requested CUDA image checks."""
import os

import numpy as np
import pytest

from app.capture.xreal import cuda_quality
from app.capture.xreal.cuda_quality import EyeDenoiser
from app.capture.xreal.quality import RgbDenoiser


def test_cuda_initialization_is_lazy_and_failure_only_attempted_once(monkeypatch):
    calls = []

    def unavailable(**_):
        calls.append(True)
        raise ImportError("CuPy is not installed")

    monkeypatch.setattr(cuda_quality, "CudaFastClean", unavailable)
    denoiser = EyeDenoiser("clean")
    assert calls == [] and denoiser.backend == "pending"
    frame = np.full((48, 64, 3), (80, 110, 140), np.uint8)
    reference = RgbDenoiser("clean")
    for _ in range(3):
        np.testing.assert_array_equal(denoiser.process(frame), reference.process(frame))
    assert calls == [True]
    assert denoiser.backend == "cpu"
    assert denoiser.fallback_reason == "ImportError: CuPy is not installed"
    denoiser.reset()
    denoiser.process(frame)
    assert calls == [True]


@pytest.mark.parametrize("mode", ["original", "strong"])
def test_other_modes_never_initialize_cuda_and_keep_existing_pixels(monkeypatch, mode):
    def forbidden():
        pytest.fail("Only Eye CLEAN may initialize CUDA")

    monkeypatch.setattr(cuda_quality, "CudaFastClean", forbidden)
    denoiser, reference = EyeDenoiser(mode), RgbDenoiser(mode)
    random = np.random.default_rng(39)
    for _ in range(3):
        frame = random.integers(0, 256, (48, 64, 3), np.uint8)
        output = denoiser.process(frame)
        np.testing.assert_array_equal(output, reference.process(frame))
        if mode == "original":
            assert output is frame
    assert denoiser.backend == ("none" if mode == "original" else "cpu")
    assert denoiser.fallback_reason is None


def test_runtime_cuda_failure_reprocesses_current_frame_without_old_history(monkeypatch):
    instances = []

    class FailingCuda:
        def __init__(self, **_):
            self.frames = 0
            self.closed = False
            self.last_motion_fraction = 0.
            instances.append(self)

        def process(self, frame):
            self.frames += 1
            if self.frames == 2:
                raise RuntimeError("test CUDA device failure")
            return frame.copy()

        def close(self):
            self.closed = True

    monkeypatch.setattr(cuda_quality, "CudaFastClean", FailingCuda)
    denoiser = EyeDenoiser("clean")
    old = np.full((48, 64, 3), 120, np.uint8)
    retained = denoiser.process(old)
    saved = retained.copy()
    assert denoiser.backend == "cuda"
    # This small change would blend with old history if it survived fallback.
    current = np.full_like(old, 122)
    expected = RgbDenoiser("clean").process(current)
    np.testing.assert_array_equal(denoiser.process(current), expected)
    np.testing.assert_array_equal(retained, saved)
    assert denoiser.backend == "cpu" and "device failure" in denoiser.fallback_reason
    assert instances[0].closed
    denoiser.process(current)
    assert len(instances) == 1 and instances[0].frames == 2


def test_reset_and_close_release_only_the_owned_filter(monkeypatch):
    instances = []

    class FakeCuda:
        last_motion_fraction = .3

        def __init__(self, **_):
            self.resets = self.closes = 0
            instances.append(self)

        def process(self, frame):
            return frame.copy()

        def reset(self):
            self.resets += 1

        def close(self):
            self.closes += 1

    monkeypatch.setattr(cuda_quality, "CudaFastClean", FakeCuda)
    first, other = EyeDenoiser(), EyeDenoiser()
    frame = np.zeros((48, 64, 3), np.uint8)
    first.process(frame)
    other.process(frame)
    assert first.last_motion_fraction == .3
    first.reset()
    assert first.last_motion_fraction == 0
    assert instances[0].resets == 1 and instances[1].resets == 0
    first.close()
    first.close()
    assert instances[0].closes == 1 and instances[1].closes == 0
    other.process(frame)
    other.close()
    with pytest.raises(RuntimeError, match="closed"):
        first.process(frame)


def test_production_factory_skips_unused_diagnostic_and_keeps_cpu_fallback_history(monkeypatch):
    options = []

    def unavailable(**kwargs):
        options.append(kwargs)
        raise ImportError("test CUDA unavailable")

    monkeypatch.setattr(cuda_quality, "CudaFastClean", unavailable)
    production = cuda_quality.create_eye_denoiser("clean")
    diagnostic = EyeDenoiser("clean")
    assert production.last_motion_fraction is None
    assert diagnostic.last_motion_fraction == 0
    before = np.full((72, 96, 3), 100, np.uint8)
    before[20:52, 40:44] = 112
    after = np.roll(before, 2, axis=1)
    for frame in [before, before, after, np.full_like(before, (20, 110, 20))]:
        np.testing.assert_array_equal(production.process(frame), diagnostic.process(frame))
        assert production.last_motion_fraction is None
        assert isinstance(diagnostic.last_motion_fraction, float)
    assert options == [{"collect_motion_fraction": False}, {"collect_motion_fraction": True}]
    production.reset()
    diagnostic.reset()
    assert production.last_motion_fraction is None
    np.testing.assert_array_equal(production.process(after), diagnostic.process(after))
    assert production.backend == "cpu" and production.fallback_reason == "ImportError: test CUDA unavailable"


@pytest.mark.skipif(os.environ.get("BOARD_VISION_TEST_CUDA") != "1",
                    reason="Opt-in CUDA check; ordinary tests never initialize GPU")
def test_production_cuda_without_motion_diagnostic_has_exact_pixels_and_temporal_history(monkeypatch):
    diagnostic = cuda_quality.CudaFastClean()
    production = cuda_quality.CudaFastClean(collect_motion_fraction=False)
    try:
        random = np.random.default_rng(705)
        retained = None
        for height, width in ((1080, 1920), (1512, 2048), (72, 96)):
            # Static noise, subtle feature movement, a chroma scene change and
            # explicit reset cover every branch of temporal history handling.
            base = np.full((height, width, 3), 100, np.uint8)
            base[height // 4:3 * height // 4, width // 2:width // 2 + 4] = 112
            noisy = np.clip(base.astype(np.int16) + random.integers(-2, 3, base.shape), 0, 255).astype(np.uint8)
            for frame in [base, noisy, np.roll(base, 2, axis=1), np.full_like(base, (20, 110, 20))]:
                expected = diagnostic.process(frame)
                with monkeypatch.context() as patch:
                    def forbidden_reduction(*_, **__):
                        pytest.fail("Production Eye must not launch the unused motion reduction")
                    patch.setattr(production.cp, "count_nonzero", forbidden_reduction)
                    actual = production.process(frame)
                np.testing.assert_array_equal(actual, expected)
                for name in ("history", "current", "previous"):
                    np.testing.assert_array_equal(getattr(production, name).get(), getattr(diagnostic, name).get())
                assert production.first == diagnostic.first
                assert production.last_motion_fraction is None
                if retained is not None:
                    np.testing.assert_array_equal(retained[0], retained[1])
                retained = (actual, actual.copy())
            diagnostic.reset()
            production.reset()
            assert production.last_motion_fraction is None and production.first
            np.testing.assert_array_equal(production.process(base), diagnostic.process(base))
    finally:
        production.close()
        diagnostic.close()


@pytest.mark.skipif(os.environ.get("BOARD_VISION_TEST_CUDA") != "1",
                    reason="Opt-in CUDA check; ordinary tests never initialize GPU")
def test_cuda_preserves_native_frames_motion_reset_noise_and_cpu_parity():
    denoiser = cuda_quality.CudaFastClean()
    try:
        random = np.random.default_rng(40)
        # Native resolutions and shape changes exercise device buffer ownership.
        for height, width in ((1080, 1920), (1512, 2048)):
            frame = random.integers(0, 256, (height, width, 3), np.uint8)
            actual = denoiser.process(frame)
            expected = RgbDenoiser("clean").process(frame)
            assert actual.shape == frame.shape and actual.dtype == np.uint8
            assert np.max(np.abs(actual.astype(np.int16) - expected.astype(np.int16))) <= 2
            assert denoiser.last_motion_fraction == 0

        reference = RgbDenoiser("clean")
        denoiser.reset()
        for _ in range(6):
            raw = np.clip(128 + random.normal(0, 7, (72, 96, 3)), 0, 255).astype(np.uint8)
            output, cpu = denoiser.process(raw), reference.process(raw)
            assert np.max(np.abs(output.astype(np.int16) - cpu.astype(np.int16))) <= 2
            assert denoiser.last_motion_fraction == reference.last_motion_fraction
        assert np.std(output.astype(float)) < np.std(raw.astype(float)) * .65

        before = np.full((96, 128, 3), 100, np.uint8)
        before[20:76, 42:46] = 112
        for _ in range(5):
            retained = denoiser.process(before)
        saved = retained.copy()
        after = np.full_like(before, 100)
        after[20:76, 44:48] = 112
        moved = denoiser.process(after)
        denoiser.reset()
        fresh = denoiser.process(after)
        np.testing.assert_array_equal(moved[24:72, 40:50], fresh[24:72, 40:50])
        np.testing.assert_array_equal(retained, saved)
        assert np.max(moved[24:72, 42:44]) <= 101
        assert np.min(moved[24:72, 45:47]) >= 110

        before = np.full((96, 128, 3), (20, 30, 180), np.uint8)
        after = np.full_like(before, (20, 110, 20))
        denoiser.reset()
        denoiser.process(before)
        moved = denoiser.process(after)
        assert denoiser.last_motion_fraction == 1
        denoiser.reset()
        np.testing.assert_array_equal(moved, denoiser.process(after))
        private_pool = denoiser.pool
    finally:
        denoiser.close()
    assert private_pool.total_bytes() == 0
    denoiser.close()
