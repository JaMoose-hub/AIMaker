"""Read-only model comparison against reviewed coarse object boxes.

Not pin accuracy, a training dataset, or full acceptance. No runtime changes.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.vision.yolo_pose import create_yolo_pose_locator


def overlap(a, b):
    a, b = np.asarray(a), np.asarray(b)
    intersection = np.maximum(0, np.minimum(a[2:], b[2:]) - np.maximum(a[:2], b[:2])).prod()
    return float(intersection / max(np.maximum(0, a[2:]-a[:2]).prod() + np.maximum(0, b[2:]-b[:2]).prod() - intersection, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output already exists')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    cv2.setNumThreads(2)
    report = {'limitations': manifest['limitations'], 'models': []}
    for model in manifest['models']:
        path = ROOT / model['path']
        meta_session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        size = meta_session.get_inputs()[0].shape[-1]
        if meta_session.get_modelmeta().custom_metadata_map.get('kpt_shape') != '[4, 3]':
            raise ValueError('This probe compares four-keypoint models only')
        del meta_session
        locator = create_yolo_pose_locator(path, runtime_backend='cuda', input_size=size,
            confidence_threshold=model['confidence'], keypoint_threshold=model['keypoint'])
        cases = []
        try:
            for case in manifest['cases']:
                if model['id'] not in case['boxes']:
                    continue  # Partially hidden/unannotated is not a negative.
                image_path = ROOT / case['image']
                frame = cv2.imread(str(image_path))
                if frame is None:
                    raise ValueError(f'Unreadable source: {image_path}')
                observed = locator.locate(frame)
                expected = case['boxes'][model['id']]
                iou = overlap(observed.box_xyxy, expected) if observed is not None and expected is not None else None
                inside = int(((observed.corners_px >= expected[:2]) & (observed.corners_px <= expected[2:])).all(1).sum()) if iou is not None else None
                verdict = ('true_negative' if observed is None else 'false_positive') if expected is None else (
                    'missed' if observed is None else 'coarse_match' if iou >= .35 and inside >= 3 else 'mislocalized')
                cases.append({'image': case['image'], 'image_sha256': hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    'expected_coarse_box': expected, 'verdict': verdict, 'box_iou': iou, 'corners_inside_box': inside,
                    'observation': asdict(observed) if observed is not None else None})
            result = {'model': model, 'model_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'runtime': locator.diagnostics(), 'summary': dict(Counter(c['verdict'] for c in cases)), 'cases': cases}
            report['models'].append(result)
            print(json.dumps({'model': path.name, 'summary': result['summary']}), flush=True)
        finally:
            locator.close()
    with args.out.open('x', encoding='utf-8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2,
                  default=lambda v: v.tolist() if isinstance(v, np.ndarray) else v)


if __name__ == '__main__':
    main()
