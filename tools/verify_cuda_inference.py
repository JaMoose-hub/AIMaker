"""Compare existing CPU/CUDA pose outputs and audit actual ONNX node providers."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.config import load_config
from app.vision.yolo_pose import OpenCvYoloPoseLocator
from app.vision.cuda_pose import CudaYoloPoseLocator


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    config = load_config()
    image = cv2.imread(str(args.image))
    assert image is not None
    targets = [('raspberry-pi-5', config.yolo_pose.model_path_for('raspberry-pi-5'), {
        'input_size': config.yolo_pose.input_size,
        'confidence_threshold': config.yolo_pose.confidence_threshold_for('raspberry-pi-5'),
        'keypoint_threshold': config.yolo_pose.keypoint_threshold,
        'keypoint_count': config.yolo_pose.keypoint_count_for('raspberry-pi-5'),
    })]
    for t in config.component_vision.components:
        profile = json.loads(t.profile_path.read_text(encoding='utf-8'))
        targets.append((t.id, t.model_path, {
            'input_size': t.input_size or config.component_vision.input_size,
            'confidence_threshold': t.confidence_threshold if t.confidence_threshold is not None else config.component_vision.confidence_threshold,
            'keypoint_threshold': t.keypoint_threshold if t.keypoint_threshold is not None else config.component_vision.keypoint_threshold,
            'keypoint_count': profile.get('keypoint_count',4),
        }))
    frames = []
    for angle in [0, 3, -3, 7, -7, 0]:
        h,w = image.shape[:2]
        matrix = cv2.getRotationMatrix2D((w/2,h/2),angle,1)
        frames.append(cv2.warpAffine(image,matrix,(w,h)))
    results = []
    for key, path, options in targets:
        cpu = OpenCvYoloPoseLocator(path, **options)
        gpu = CudaYoloPoseLocator(path, device_id=0, profile_prefix=args.out/key, **options)
        if gpu.diagnostics()['actual_backend'] != 'cuda':
            raise RuntimeError(gpu.diagnostics())
        costs = {'cpu':[], 'cuda':[]}
        errors, disagreements, detected = [], 0, 0
        for _ in range(3):
            cpu.locate(image); gpu.locate(image)
        for _ in range(2):
            for frame in frames:
                outputs = []
                for label, model in [('cpu',cpu),('cuda',gpu)]:
                    started = time.perf_counter()
                    outputs.append(model.locate(frame))
                    costs[label].append((time.perf_counter()-started)*1000)
                a,b = outputs
                disagreements += (a is None) != (b is None)
                if a is not None and b is not None:
                    detected += 1
                    errors.append(float(np.max(np.linalg.norm(a.all_points_px-b.all_points_px, axis=1))))
        profile_path = gpu._session.end_profiling()
        events = json.loads(Path(profile_path).read_text())
        operators = Counter()
        conv = Counter()
        for event in events:
            meta = event.get('args',{})
            if event.get('cat') == 'Node' and meta.get('provider'):
                operators[meta['provider']] += 1
                if 'Conv' in meta.get('op_name',''):
                    conv[meta['provider']] += 1
        result = {'id':key, 'input_size':options['input_size'],
                  'ms_p50_p95': {k:np.percentile(v,[50,95]).tolist() for k,v in costs.items()},
                  'both_detected':detected, 'presence_disagreements':disagreements,
                  'max_landmark_difference_px':max(errors,default=None),
                  'executed_node_providers':dict(operators), 'convolution_providers':dict(conv),
                  'runtime':gpu.diagnostics()}
        results.append(result)
        print(json.dumps(result),flush=True)
        assert conv.get('CUDAExecutionProvider',0)>0 and conv.get('CPUExecutionProvider',0)==0
        assert detected > 0, f'{key}: no detections to compare; use a representative image'
        assert disagreements == 0 and (not errors or max(errors)<1.)
        cpu.close(); gpu.close()
    (args.out/'summary.json').write_text(json.dumps({'results':results,
        'limits':'CPU and CUDA compare the same recorded texture, not electrical correctness or actual hand tracking. CUDA timings include profiling overhead.'},indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
