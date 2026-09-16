"""CUDA inference for existing ONNX pose exports, with explicit CPU fallback."""
from __future__ import annotations

import logging
import ctypes
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
import sys
import time

import cv2
import numpy as np

from app.vision.yolo_pose import (
    BOARD_KEYPOINT_COUNT, OpenCvYoloPoseLocator, _letterbox, decode_yolo_pose_output,
)
from app.vision.cuda_preprocess import CudaPreprocessor
from app.vision.eye_yolo_decode import prefilter_class_scores

log = logging.getLogger(__name__)
_extra_dlls = {}


def _preload_cudnn_tensor_ir():
    """ORT 1.24's Windows preload list predates this cuDNN 9 sub-library.

    Load only from the installed NVIDIA wheel, without changing system PATH.
    Newer ORT versions include this library in their own preload list.
    """
    if sys.platform != 'win32':
        return
    try:
        package = distribution('nvidia-cudnn-cu12')
    except PackageNotFoundError:
        return  # A system cuDNN installation can still satisfy ORT.
    path = package.locate_file('nvidia/cudnn/bin/cudnn_engines_tensor_ir64_9.dll')
    if path.is_file() and str(path) not in _extra_dlls:
        _extra_dlls[str(path)] = ctypes.CDLL(str(path))


class CudaYoloPoseLocator:
    def __init__(self, model_path: Path | str, *, device_id=0, input_size=960,
                 confidence_threshold=.45, keypoint_threshold=.35,
                 nms_iou_threshold=.45, num_classes=1, class_id=0,
                 keypoint_count=BOARD_KEYPOINT_COUNT, profile_prefix=None,
                 gpu_preprocessing=True):
        self.model_path = Path(model_path)
        self.device_id = int(device_id)
        self.input_size = int(input_size)
        self.profile_prefix = profile_prefix
        self._decode_options = dict(
            input_size=self.input_size, confidence_threshold=confidence_threshold,
            keypoint_threshold=keypoint_threshold, nms_iou_threshold=nms_iou_threshold,
            num_classes=num_classes, class_id=class_id, keypoint_count=keypoint_count,
        )
        self._session = self._input_name = self._fallback = None
        self._preprocessor = None
        self.preprocessing_fallback_reason = None
        self.gpu_preprocessing = gpu_preprocessing
        self.fallback_reason = None
        self.inference_count = 0
        self.inference_ms = 0.0
        self._yolo_only = False
        self._load()

    def _use_cpu(self, error):
        self.fallback_reason = str(error)
        self._session = self._input_name = None
        self._preprocessor = None
        log.warning('CUDA unavailable for %s; switching to OpenCV CPU: %s', self.model_path, error)
        self._fallback = OpenCvYoloPoseLocator(self.model_path, **self._decode_options)

    def _load(self):
        try:
            import onnxruntime as ort
            if 'CUDAExecutionProvider' not in ort.get_available_providers():
                raise RuntimeError('CUDAExecutionProvider unavailable; install the cuda dependency group')
            # NVIDIA pip wheels supply the runtime DLLs; no system PATH edits
            # or a machine-wide CUDA Toolkit installation are required.
            ort.preload_dlls(directory='')
            _preload_cudnn_tensor_ir()
            options = ort.SessionOptions()
            options.intra_op_num_threads = 1
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            if self.profile_prefix is not None:
                options.enable_profiling = True
                options.profile_file_prefix = str(self.profile_prefix)
            self._session = ort.InferenceSession(str(self.model_path), sess_options=options, providers=[
                ('CUDAExecutionProvider', {
                    'device_id': self.device_id,
                    'gpu_mem_limit': 1024 * 1024 * 1024,
                    'arena_extend_strategy': 'kSameAsRequested',
                    'cudnn_conv_algo_search': 'HEURISTIC',
                    'cudnn_conv_use_max_workspace': '0',
                    'do_copy_in_default_stream': '1',
                    'use_tf32': '0',
                }), 'CPUExecutionProvider',
            ])
            if 'CUDAExecutionProvider' not in self._session.get_providers():
                raise RuntimeError('CUDA session initialization fell back to CPU')
            # Do not silently change providers if an execution later fails.
            self._session.disable_fallback()
            self._input_name = self._session.get_inputs()[0].name
            # Validate DLLs and workspace allocation before declaring ready.
            # The warm-up output is discarded, never sent as a detection.
            self._session.run(None, {self._input_name: np.zeros((1,3,self.input_size,self.input_size), np.float32)})
            if self.gpu_preprocessing:
                try:
                    self._preprocessor = CudaPreprocessor(self.input_size, self.device_id)
                    # Compile and execute once at startup, not during a camera
                    # frame. This output is never published as a detection.
                    self._run_preprocessed(np.zeros((32, 32, 3), np.uint8))
                except Exception as exc:
                    self._disable_preprocessing(exc)
            log.info('CUDA ready: device=%s model=%s providers=%s', self.device_id, self.model_path, self._session.get_providers())
        except Exception as exc:
            self._use_cpu(exc)

    @property
    def available(self):
        return self._session is not None or bool(self._fallback and self._fallback.available)

    def _disable_preprocessing(self, error):
        self._preprocessor = None
        self.preprocessing_fallback_reason = str(error)
        log.warning('CUDA preprocessing unavailable for %s; retaining CUDA model with CPU input preparation: %s', self.model_path, error)

    def _run_preprocessed(self, frame):
        blob, scale, pad_x, pad_y = self._preprocessor.prepare(frame)
        binding = self._session.io_binding()
        binding.bind_input(self._input_name, 'cuda', self.device_id, np.float32,
                           tuple(blob.shape), blob.data.ptr)
        # Only the small final detections return to CPU for the existing NMS
        # and geometry gates. No full float32 input takes a CPU round trip.
        binding.bind_output(self._session.get_outputs()[0].name, 'cpu')
        self._session.run_with_iobinding(binding)
        return binding.copy_outputs_to_cpu()[0], scale, pad_x, pad_y

    def diagnostics(self):
        session = self._session
        return {
            'requested_backend': 'cuda',
            'actual_backend': 'cuda' if session is not None else 'opencv',
            'device_id': self.device_id if session is not None else None,
            'providers': session.get_providers() if session is not None else [],
            'available': self.available,
            'fallback_reason': self.fallback_reason,
            'preprocessing_backend': 'cuda' if self._preprocessor is not None else 'opencv',
            'preprocessing_fallback_reason': self.preprocessing_fallback_reason,
            'inference_count': self.inference_count,
            'mean_locate_ms': round(self.inference_ms / self.inference_count, 2) if self.inference_count else None,
        }

    def set_yolo_only(self, enabled):
        """Opt into equivalent score-first decoding while the worker is stopped."""
        self._yolo_only = bool(enabled)

    def locate(self, frame_bgr):
        return self._locate(frame_bgr)

    def locate_candidate(self, frame_bgr, confidence_threshold):
        """One forward, lower candidate gate; caller must verify image geometry."""
        return self._locate(frame_bgr, confidence_threshold)

    def _locate_fallback(self, frame_bgr, candidate_threshold):
        candidate = getattr(self._fallback, 'locate_candidate', None)
        if candidate_threshold is not None and callable(candidate):
            return candidate(frame_bgr, candidate_threshold)
        return self._fallback.locate(frame_bgr)

    def _locate(self, frame_bgr, candidate_threshold=None):
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        if self._fallback is not None:
            return self._locate_fallback(frame_bgr, candidate_threshold)
        if not self.available:
            return None
        started = time.perf_counter()
        h, w = frame_bgr.shape[:2]
        try:
            options = self._decode_options
            if candidate_threshold is not None:
                options = {**options, 'confidence_threshold': float(candidate_threshold)}
            if self._preprocessor is not None:
                try:
                    raw, scale, pad_x, pad_y = self._run_preprocessed(frame_bgr)
                except Exception as exc:
                    self._disable_preprocessing(exc)
            if self._preprocessor is None:
                image, scale, pad_x, pad_y = _letterbox(frame_bgr, self.input_size)
                blob = cv2.dnn.blobFromImage(image, scalefactor=1/255., size=(self.input_size,self.input_size), swapRB=True, crop=False)
                raw = self._session.run(None, {self._input_name: blob})[0]
            if self._yolo_only:
                raw = prefilter_class_scores(raw, **options)
            result = decode_yolo_pose_output(raw, frame_size=(w,h), scale=scale, pad_x=pad_x, pad_y=pad_y, **options)
            self.inference_count += 1
            self.inference_ms += (time.perf_counter()-started)*1000
            return result
        except Exception as exc:
            self._use_cpu(exc)
            return self._locate_fallback(frame_bgr, candidate_threshold)

    def close(self):
        if self._fallback is not None:
            self._fallback.close()
        self._session = self._input_name = self._fallback = None
        self._preprocessor = None
