"""Eye shares webcam weights by default; independent exports require opt-in."""
import json
from pathlib import Path
import pytest

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


def fixture(tmp_path, entry=True, available=True, use_eye_variant=None):
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
                              {'input_size': 768, 'runtime_backend': 'cuda', 'confidence_threshold': .45},
                              **({} if use_eye_variant is None else {'use_eye_variant': use_eye_variant}))
    return wrapper, original, calls


def test_eye_is_lazy_reused_and_webcam_session_is_restored(tmp_path):
    wrapper, original, calls = fixture(tmp_path, use_eye_variant=True)
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
    wrapper, original, calls = fixture(tmp_path, entry=False, use_eye_variant=True)
    wrapper.set_yolo_only(True)
    assert not calls and wrapper.locate('eye') == 'original.onnx'
    assert wrapper.diagnostics()['eye_variant_error'] is None
    wrapper.set_yolo_only(False)
    assert original.modes == [True, False]


def test_failed_candidate_reports_fallback_without_closing_original(tmp_path):
    wrapper, original, calls = fixture(tmp_path, available=False, use_eye_variant=True)
    wrapper.set_yolo_only(True)
    assert wrapper.available and wrapper.locate('eye') == 'original.onnx'
    assert calls[0][0].closed and not original.closed
    assert wrapper.diagnostics()['eye_variant_error']
    wrapper.set_yolo_only(False)
    assert wrapper.diagnostics()['eye_variant_error'] is None
    assert wrapper.locate('webcam') == 'original.onnx'


def test_cpu_variant_does_not_replace_original_cuda_model(tmp_path):
    wrapper, original, calls = fixture(tmp_path, use_eye_variant=True)
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


@pytest.mark.parametrize('invalid_manifest', [False, True])
def test_eye_defaults_to_current_webcam_session_even_with_local_variants(tmp_path, invalid_manifest):
    wrapper, original, calls = fixture(tmp_path)
    manifest = tmp_path/'eye/manifest.json'
    if invalid_manifest:
        manifest.write_text('old broken experiment', encoding='utf-8')
    before = manifest.read_bytes()
    for i in range(10):
        wrapper.set_yolo_only(True)
        assert wrapper.locate(f'eye-{i}') == 'original.onnx'
        status = wrapper.diagnostics()
        assert status['model_variant'] == 'original' and status['model_policy'] == 'shared'
        assert status['actual_backend'] == 'cuda' and status['eye_variant_error'] is None
        wrapper.set_yolo_only(False)
        assert wrapper.locate(f'webcam-{i}') == 'original.onnx'
    assert original.modes == [True, False] * 10
    assert not calls and len(original.calls) == 20
    assert manifest.read_bytes() == before
    wrapper.close()
    assert original.closed


@pytest.mark.parametrize('model_name', [
    'board-pose-pi5-guided-20260922.onnx',
    'hc-sr04-corner-pose-v3-robust.onnx',
    'mrd-tf240-8p-cs-pose.onnx',
])
def test_production_factory_keeps_current_model_when_entering_eye(tmp_path, monkeypatch, model_name):
    import app.vision.yolo_pose as module
    created = []
    def fake_locator(path, **options):
        result = Locator(path)
        created.append((result, options))
        return result
    monkeypatch.setattr(module, 'OpenCvYoloPoseLocator', fake_locator)
    eye = tmp_path/'eye'
    eye.mkdir()
    (eye/'old.onnx').write_bytes(b'old experiment')
    (eye/'manifest.json').write_text(json.dumps({'models': {
        model_name: {'file':'old.onnx', 'input_size':1280}}}), encoding='utf-8')
    wrapper = module.create_yolo_pose_locator(tmp_path/model_name, eye_variant=True,
                                             input_size=960, confidence_threshold=.45)
    wrapper.set_yolo_only(True)
    assert wrapper.locate('frame') == model_name
    assert len(created) == 1 and created[0][1]['input_size'] == 960
    assert created[0][1]['confidence_threshold'] == .45
    assert wrapper.diagnostics()['model_policy'] == 'shared'
    wrapper.close()


def test_factory_can_explicitly_opt_into_an_eye_model_experiment(tmp_path, monkeypatch):
    import app.vision.yolo_pose as module
    created = []

    def fake_locator(path, **options):
        result = Locator(path)
        created.append((result, options))
        return result

    monkeypatch.setattr(module, 'OpenCvYoloPoseLocator', fake_locator)
    eye = tmp_path / 'eye'
    eye.mkdir()
    (eye / 'experiment.onnx').write_bytes(b'experiment')
    (eye / 'manifest.json').write_text(json.dumps({'models': {
        'original.onnx': {'file': 'experiment.onnx', 'input_size': 1280}
    }}), encoding='utf-8')
    wrapper = module.create_yolo_pose_locator(tmp_path / 'original.onnx',
                                             eye_variant=True, eye_model_variant=True,
                                             input_size=960, confidence_threshold=.45)
    assert len(created) == 1
    wrapper.set_yolo_only(True)
    assert wrapper.locate('eye') == 'experiment.onnx'
    assert len(created) == 2 and created[1][1]['input_size'] == 1280
    assert created[1][1]['confidence_threshold'] == .45
    assert wrapper.diagnostics()['model_policy'] == 'eye_variant'
    wrapper.set_yolo_only(False)
    assert wrapper.locate('webcam') == 'original.onnx'
    wrapper.close()
    assert all(locator.closed for locator, _ in created)
