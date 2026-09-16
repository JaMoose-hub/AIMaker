"""Optional Eye-trained weights, with the original webcam session preserved."""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class EyeModelLocator:
    """Switch only while workers are stopped; keep both sessions for re-entry.

    A manifest beside the original models maps their filenames to independently
    validated Eye exports. Normal camera inference always uses the exact original
    locator. No camera settings or original model files are written here.
    """

    def __init__(self, original, factory, model_path, options):
        self.original = original
        self._active = original
        self._factory = factory
        self._original_path = Path(model_path)
        self._options = dict(options)
        self._eye = None
        self._attempted = False
        self._eye_enabled = False
        self._variant_error = None

    @property
    def available(self):
        return self._active.available

    @property
    def model_path(self):
        return self._active.model_path

    def set_yolo_only(self, enabled):
        self._eye_enabled = bool(enabled)
        if enabled and not self._attempted:
            self._attempted = True
            manifest = self._original_path.parent / 'eye' / 'manifest.json'
            if manifest.is_file():
                try:
                    models = json.loads(manifest.read_text(encoding='utf-8'))['models']
                    if not isinstance(models, dict):
                        raise ValueError('Eye manifest models must be an object')
                    entry = models.get(self._original_path.name)
                    if entry:
                        path = manifest.parent / entry['file']
                        if not path.is_file():
                            raise FileNotFoundError(path)
                        options = {**self._options, 'input_size': int(entry['input_size'])}
                        candidate = self._factory(path, **options)
                        if not candidate.available:
                            candidate.close()
                            raise RuntimeError(f'Eye model could not load: {path}')
                        if self._options.get('runtime_backend') == 'cuda':
                            from app.vision.inference_status import locator_status
                            if locator_status(candidate, 'cuda')['actual_backend'] != 'cuda':
                                candidate.close()
                                raise RuntimeError(f'Eye model did not load on CUDA: {path}')
                        self._eye = candidate
                except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
                    self._variant_error = str(exc)
                    log.warning('Eye variant unavailable for %s: %s', self._original_path, exc)
        self._active = self._eye if enabled and self._eye is not None else self.original
        configure = getattr(self._active, 'set_yolo_only', None)
        if callable(configure):
            configure(bool(enabled))

    def locate(self, frame):
        return self._active.locate(frame)

    def diagnostics(self):
        from app.vision.inference_status import locator_status
        status = locator_status(self._active, self._options.get('runtime_backend', 'opencv'))
        return {**status, 'model_path': str(self.model_path),
                'model_variant': 'eye' if self._active is self._eye else 'original',
                'eye_variant_error': self._variant_error if self._eye_enabled else None}

    def close(self):
        if self._eye is not None:
            self._eye.close()
        self.original.close()
        self._eye = None
        self._active = self.original
