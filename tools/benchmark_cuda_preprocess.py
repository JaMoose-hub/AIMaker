"""Repeatable recorded-image benchmarks, not a claim of live camera FPS."""
import argparse
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.vision.cuda_preprocess import CudaPreprocessor
from app.vision.yolo_pose import _letterbox
from app.vision.pi5_pin_stability import PinImageAnchor
from app.vision.interface import PinDetection


def measure(fn, count=60):
    for _ in range(5):
        fn()
    cpu = time.process_time()
    times = []
    for _ in range(count):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return {'wall_ms_p50_p95': np.percentile(times, [50,95]).tolist(),
            'cpu_ms_per_call': (time.process_time()-cpu)*1000/count}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    frame = cv2.imread(str(args.image))
    assert frame is not None
    results = {'preprocessing': [], 'anchor_synthetic': []}
    for size in (768,960,1280):
        gpu = CudaPreprocessor(size, 0)
        def cpu():
            return cv2.dnn.blobFromImage(_letterbox(frame,size)[0], scalefactor=1/255., swapRB=True)
        expected = cpu()
        actual = gpu.prepare(frame)[0].get()
        assert np.max(np.abs(actual-expected)) < 1e-7
        for threads in (32, 2):
            cv2.setNumThreads(threads)
            results['preprocessing'].append({'size': size, 'opencv_threads': threads,
                'cpu': measure(cpu), 'cuda': measure(lambda: gpu.prepare(frame)),
                'maximum_pixel_difference': float(np.max(np.abs(actual-expected)))})
    # Same accepted feature coordinates, source-pixel units and LK thresholds
    # in both paths; only the grayscale image/pyramid extent differs.
    texture = np.random.default_rng(77).integers(30,220,(1080,1920,3),dtype=np.uint8)
    pins = [PinDetection(str(i+1),600+18*(i//2),400+16*(i%2),1.,True,'J8',i+1) for i in range(40)]
    anchor = PinImageAnchor()
    anchor.seed(texture,pins,[(570,300),(1000,300),(1000,600),(570,600)])
    original_roi, original_gray = anchor.roi, anchor.gray
    original_points = anchor.points.copy()
    for threads in (32, 2):
        cv2.setNumThreads(threads)
        for label in ('full_frame', 'roi'):
            if label == 'full_frame':
                anchor.roi = (0,0,1920,1080)
                anchor.gray = cv2.cvtColor(texture, cv2.COLOR_BGR2GRAY)
                anchor.points = original_points + np.float32(original_roi[:2])
            else:
                anchor.roi, anchor.gray, anchor.points = original_roi, original_gray, original_points
            assert anchor.stationary(texture)
            results['anchor_synthetic'].append({'opencv_threads':threads, 'extent':label,
                'gray_shape':anchor.gray.shape, **measure(lambda: anchor.stationary(texture))})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
