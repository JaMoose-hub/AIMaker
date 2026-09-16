"""An Eye-trained export never replaces or mutates the webcam's session."""
import json
from pathlib import Path

from app.vision.eye_model import EyeModelLocator


class Locator:
    def __init__(self, path, available=True):
        self.model_path = Path(path)
        self.available = available
        self.calls = []
        self.modes = []
        self.closed = False

    def locate(self, frame):
        self.calls.append(frame)
        return self.model_path.name

    def set_yolo_only(self, enabled):
        self.modes.append(enabled)

    def close(self):
        self.closed = True

    def diagnostics(self):
        return {'actual_backend': 'cuda', 'available': self.available, 'inference_count': len(self.calls)}


def fixture(tmp_path, entry=True, available=True):
    original = Locator(tmp_path / 'original.onnx')
    calls = []

    def factory(path, **options):
        result = Locator(path, available)
        calls.append((result, options))
        return result

    directory = tmp_path / 'eye'
    directory.mkdir()
    (directory / 'trained.onnx').write_bytes(b'test candidate')
    (directory / 'manifest.json').write_text(json.dumps({'models': {
        'original.onnx': {'file': 'trained.onnx', 'input_size': 960}
    } if entry else {}}), encoding='utf-8')
    wrapper = EyeModelLocator(original, factory, original.model_path,
                              {'input_size': 768, 'runtime_backend': 'cuda', 'confidence_threshold': .45})
    return wrapper, original, calls


def test_eye_is_lazy_reused_and_webcam_session_is_restored(tmp_path):
    wrapper, original, calls = fixture(tmp_path)
    assert wrapper.locate('webcam-1') == 'original.onnx' and not calls
    wrapper.set_yolo_only(True)
    assert len(calls) == 1 and calls[0][1]['input_size'] == 960
    assert calls[0][1]['confidence_threshold'] == .45
    assert wrapper.locate('eye-1') == 'trained.onnx'
    assert wrapper.diagnostics()['model_variant'] == 'eye'
    wrapper.set_yolo_only(False)
    assert wrapper.locate('webcam-2') == 'original.onnx'
    assert wrapper.diagnostics()['model_variant'] == 'original'
    wrapper.set_yolo_only(True)
    assert wrapper.locate('eye-2') == 'trained.onnx' and len(calls) == 1
    assert original.calls == ['webcam-1', 'webcam-2']
    assert original.modes == [False]
    assert not original.closed
    wrapper.close()
    assert original.closed and calls[0][0].closed


def test_no_mapping_keeps_existing_model_and_behavior(tmp_path):
    wrapper, original, calls = fixture(tmp_path, entry=False)
    wrapper.set_yolo_only(True)
    assert not calls and wrapper.locate('eye') == 'original.onnx'
    assert wrapper.diagnostics()['eye_variant_error'] is None
    wrapper.set_yolo_only(False)
    assert original.modes == [True, False]


def test_failed_candidate_reports_fallback_without_closing_original(tmp_path):
    wrapper, original, calls = fixture(tmp_path, available=False)
    wrapper.set_yolo_only(True)
    assert wrapper.available and wrapper.locate('eye') == 'original.onnx'
    assert calls[0][0].closed and not original.closed
    assert wrapper.diagnostics()['eye_variant_error']
    wrapper.set_yolo_only(False)
    assert wrapper.diagnostics()['eye_variant_error'] is None
    assert wrapper.locate('webcam') == 'original.onnx'


def test_cpu_variant_does_not_replace_original_cuda_model(tmp_path):
    wrapper, original, calls = fixture(tmp_path)
    factory = wrapper._factory

    def cpu_factory(*args, **kwargs):
        candidate = factory(*args, **kwargs)
        candidate.diagnostics = lambda: {'actual_backend': 'opencv', 'available': True}
        return candidate

    wrapper._factory = cpu_factory
    wrapper.set_yolo_only(True)
    assert wrapper.locate('eye') == 'original.onnx' and calls[0][0].closed
    assert 'CUDA' in wrapper.diagnostics()['eye_variant_error']
    assert not original.closed
