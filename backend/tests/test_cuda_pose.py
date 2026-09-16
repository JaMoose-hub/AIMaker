from types import SimpleNamespace
import sys

import numpy as np
import pytest

from app.config import YoloPoseConfig, ComponentVisionConfig
from app.vision import cuda_pose
from app.vision.yolo_pose import create_yolo_pose_locator


def test_windows_cudnn_extra_dll_is_loaded_from_wheel_once(monkeypatch, tmp_path):
    dll = tmp_path / 'cudnn_engines_tensor_ir64_9.dll'
    dll.touch()
    loaded = []
    monkeypatch.setattr(cuda_pose.sys, 'platform', 'win32')
    monkeypatch.setattr(cuda_pose, '_extra_dlls', {})
    monkeypatch.setattr(cuda_pose, 'distribution', lambda name: SimpleNamespace(locate_file=lambda _: dll))
    monkeypatch.setattr(cuda_pose.ctypes, 'CDLL', lambda path: loaded.append(path))
    cuda_pose._preload_cudnn_tensor_ir()
    cuda_pose._preload_cudnn_tensor_ir()
    assert loaded == [str(dll)]


class CpuStub:
    available = True
    def __init__(self, *a, **kw):
        self.calls = 0
    def locate(self, image):
        self.calls += 1
        return 'cpu-result'
    def close(self):
        self.available = False


def fake_ort(monkeypatch, *, providers=None, actual=None, fail_at=None):
    calls = {}
    class Session:
        def __init__(self, path, sess_options, providers):
            calls.update(options=sess_options, providers=providers, runs=0)
        def get_providers(self):
            return actual if actual is not None else ['CUDAExecutionProvider','CPUExecutionProvider']
        def disable_fallback(self):
            calls['fallback_disabled'] = True
        def get_inputs(self):
            return [SimpleNamespace(name='images')]
        def run(self, _, inputs):
            calls['runs'] += 1
            if calls['runs'] == fail_at:
                raise RuntimeError('GPU out of memory')
            calls['blob'] = inputs['images']
            return [np.zeros((1,17,1), np.float32)]
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(
        get_available_providers=lambda: providers if providers is not None else ['CUDAExecutionProvider','CPUExecutionProvider'],
        preload_dlls=lambda **kw: calls.update(preloaded=True), SessionOptions=SimpleNamespace,
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL=99), InferenceSession=Session,
    ))
    monkeypatch.setattr(cuda_pose, 'OpenCvYoloPoseLocator', CpuStub)
    monkeypatch.setattr(cuda_pose, '_preload_cudnn_tensor_ir', lambda: None)
    # Unit tests must not initialize the host GPU. Dedicated integration tests
    # exercise the real kernel, including CPU-only environments that skip it.
    def no_preprocessor(*args):
        raise RuntimeError('test preprocessing unavailable')
    monkeypatch.setattr(cuda_pose, 'CudaPreprocessor', no_preprocessor)
    return calls


def test_cuda_provider_is_selected_and_warmed_before_ready(monkeypatch):
    calls = fake_ort(monkeypatch)
    locator = create_yolo_pose_locator('test.onnx', runtime_backend='cuda', cuda_device_id=2, input_size=320)
    assert locator.available and calls['preloaded']
    assert calls['providers'][0][0] == 'CUDAExecutionProvider'
    assert calls['providers'][0][1]['device_id'] == 2
    assert calls['providers'][0][1]['use_tf32'] == '0'
    assert calls['fallback_disabled'] and calls['runs'] == 1
    assert locator.diagnostics()['inference_count'] == 0
    # A valid empty detection is NOT a GPU failure and must not fall back.
    assert locator.locate(np.zeros((240,320,3),np.uint8)) is None
    assert locator.diagnostics()['actual_backend'] == 'cuda'
    assert locator.diagnostics()['inference_count'] == 1
    locator.close()
    assert not locator.available


@pytest.mark.parametrize('options', [
    {'providers':['CPUExecutionProvider']},
    {'actual':['CPUExecutionProvider']},
    {'fail_at':1},
])
def test_cuda_unavailable_is_explicit_cpu_fallback(monkeypatch, options):
    fake_ort(monkeypatch, **options)
    locator = cuda_pose.CudaYoloPoseLocator('test.onnx',input_size=320)
    status = locator.diagnostics()
    assert status['requested_backend'] == 'cuda' and status['actual_backend'] == 'opencv'
    assert status['fallback_reason'] and status['providers'] == []
    assert locator.locate(np.zeros((240,320,3),np.uint8)) == 'cpu-result'


def test_runtime_cuda_failure_falls_back_once_and_reports_actual_backend(monkeypatch):
    calls = fake_ort(monkeypatch, fail_at=2)
    locator = cuda_pose.CudaYoloPoseLocator('test.onnx',input_size=320)
    frame = np.zeros((240,320,3),np.uint8)
    assert locator.locate(frame) == 'cpu-result'
    assert locator.locate(frame) == 'cpu-result'
    assert calls['runs'] == 2 and locator._fallback.calls == 2
    assert locator.diagnostics()['fallback_reason'] == 'GPU out of memory'


def test_cuda_config_device_is_separate_from_directml():
    for cls in (YoloPoseConfig, ComponentVisionConfig):
        cfg = cls(runtime_backend='cuda', cuda_device_id=0, directml_device_id=1)
        assert cfg.cuda_device_id == 0 and cfg.directml_device_id == 1
        with pytest.raises(ValueError):
            cls(runtime_backend='cuda', cuda_device_id=-1)


def test_preprocessor_failure_keeps_cuda_model_and_reports_separate_reason(monkeypatch):
    calls = fake_ort(monkeypatch)
    locator = cuda_pose.CudaYoloPoseLocator('test.onnx', input_size=320)
    locator.locate(np.zeros((240, 320, 3), np.uint8))
    status = locator.diagnostics()
    assert status['actual_backend'] == 'cuda' and status['fallback_reason'] is None
    assert status['preprocessing_backend'] == 'opencv'
    assert status['preprocessing_fallback_reason'] == 'test preprocessing unavailable'
    assert calls['runs'] == 2


def test_iobinding_uses_cuda_buffer_and_recovers_input_path_once(monkeypatch):
    calls = fake_ort(monkeypatch)
    class Preprocessor:
        def __init__(self, size, device):
            self.size, self.device, self.calls = size, device, 0
        def prepare(self, frame):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError('input transfer failed')
            return SimpleNamespace(shape=(1,3,self.size,self.size), data=SimpleNamespace(ptr=1234)), 1., 0., 0.
    class Binding:
        def bind_input(self, *args):
            calls['bound_input'] = args
        def bind_output(self, *args):
            calls['bound_output'] = args
        def copy_outputs_to_cpu(self):
            return [np.zeros((1,17,1), np.float32)]
    session = sys.modules['onnxruntime'].InferenceSession
    monkeypatch.setattr(session, 'io_binding', lambda _: Binding(), raising=False)
    monkeypatch.setattr(session, 'get_outputs', lambda _: [SimpleNamespace(name='output0')], raising=False)
    monkeypatch.setattr(session, 'run_with_iobinding', lambda *_: calls.update(bound=True), raising=False)
    monkeypatch.setattr(cuda_pose, 'CudaPreprocessor', Preprocessor)
    locator = cuda_pose.CudaYoloPoseLocator('test.onnx', input_size=320, device_id=2)
    assert locator.diagnostics()['preprocessing_backend'] == 'cuda'
    assert calls['bound_input'] == ('images', 'cuda', 2, np.float32, (1,3,320,320), 1234)
    assert calls['bound_output'] == ('output0', 'cpu')
    frame = np.zeros((240,320,3), np.uint8)
    assert locator.locate(frame) is None
    assert calls['runs'] == 1  # only the original model warmup uses host input
    assert locator.locate(frame) is None  # third prep fails, retry same CUDA model
    assert locator.locate(frame) is None
    assert calls['runs'] == 3
    assert locator.diagnostics()['actual_backend'] == 'cuda'
    assert locator.diagnostics()['preprocessing_fallback_reason'] == 'input transfer failed'


def test_opencv_pool_is_bounded_and_configurable():
    from app.config import AppConfig
    assert AppConfig().opencv_num_threads == 2
    assert AppConfig(opencv_num_threads=4).opencv_num_threads == 4
    with pytest.raises(ValueError):
        AppConfig(opencv_num_threads=0)


def test_inference_status_reports_real_fallback_not_just_requested_config(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes import router
    fake_ort(monkeypatch, providers=['CPUExecutionProvider'])
    locator = cuda_pose.CudaYoloPoseLocator('test.onnx',input_size=320)
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(yolo_pose=SimpleNamespace(runtime_backend='cuda'),
                                       component_vision=SimpleNamespace(runtime_backend='cuda'))
    app.state.runtime_manager = SimpleNamespace(snapshot=lambda: SimpleNamespace(board_id='raspberry-pi-5'))
    app.state.detector = SimpleNamespace(primary=SimpleNamespace(_locator=locator))
    app.state.component_workers = [SimpleNamespace(_locator=locator, _profile=SimpleNamespace(component_id='hw-123'))]
    with TestClient(app) as client:
        result = client.get('/api/inference/status').json()
    assert result['board']['actual_backend'] == 'opencv'
    assert result['board']['requested_backend'] == 'cuda'
    assert result['board']['fallback_reason']
    assert result['components'][0]['id'] == 'hw-123'
    assert result['motion_tracking']['cuda'] is False
