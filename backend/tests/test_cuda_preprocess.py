"""Real CUDA parity; skips honestly when the optional runtime/device is absent."""
import cv2
import numpy as np
import pytest

from app.vision.cuda_preprocess import CudaPreprocessor
from app.vision.yolo_pose import _letterbox


@pytest.fixture(scope='module')
def cuda_device():
    cp = pytest.importorskip('cupy')
    try:
        count = cp.cuda.runtime.getDeviceCount()
    except Exception as exc:
        pytest.skip(f'CUDA driver unavailable: {exc}')
    if not count:
        pytest.skip('No CUDA device')
    return 0


@pytest.mark.parametrize('size', [768, 960, 1280])
def test_current_camera_preprocessing_is_pixel_identical(cuda_device, size):
    frame = np.random.default_rng(408).integers(0, 256, (1080, 1920, 3), dtype=np.uint8)
    processor = CudaPreprocessor(size, cuda_device)
    image, scale, left, top = _letterbox(frame, size)
    expected = cv2.dnn.blobFromImage(image, scalefactor=1/255., swapRB=True)
    actual, gs, gl, gt = processor.prepare(frame)
    assert (gs, gl, gt) == (scale, left, top)
    np.testing.assert_allclose(actual.get(), expected, atol=1e-7, rtol=0)


@pytest.mark.parametrize('shape', [(73, 131), (151, 59), (32, 32), (1, 57), (59, 1)])
def test_letterbox_odd_sizes_portrait_and_reused_buffers(cuda_device, shape):
    processor = CudaPreprocessor(128, cuda_device)
    for h, w in (shape, shape[::-1]):
        frame = np.random.default_rng(23).integers(0, 256, (h, w, 3), dtype=np.uint8)
        frame = frame[:, ::-1]  # non-contiguous camera/mirror input
        expected, scale, left, top = _letterbox(frame, 128)
        blob = cv2.dnn.blobFromImage(expected, scalefactor=1/255., swapRB=True)
        actual, gs, gl, gt = processor.prepare(frame)
        assert (gs, gl, gt) == (scale, left, top)
        # OpenCV has platform-specific SIMD tails for unusual dimensions.
        assert np.max(np.abs(actual.get() - blob)) <= 1/255. + 1e-7
